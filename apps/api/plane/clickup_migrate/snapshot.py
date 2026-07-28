# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# The1Studio SP1 — portable raw-extract snapshot for the ClickUp ETL.
#
# WHY THIS EXISTS
# ---------------
# The ETL used to hold every extracted task in an in-memory dict that died with
# the process, so each run re-crawled ClickUp from scratch (~10.5k tasks, hours,
# against a ~100 req/min limit). Worse, every artifact that DID persist
# (MigrationRun / MappingTable / MigrationRecord) lives in the instance's own
# Postgres — so importing the same data into a SECOND instance (staging → prod)
# started from zero.
#
# A snapshot decouples EXTRACT from LOAD. Extract once, then:
#   * replay the same task set into any number of instances, and
#   * on later runs pull only what changed (delta) and merge it in.
#
# FORMAT
# ------
# One JSONL file. Line 1 is the manifest; every subsequent line is one raw
# ClickUp task object exactly as the API returned it (no transformation — the
# writers still own that, so a snapshot stays valid across writer changes).
#
#   {"_manifest": 1, "version": 1, "watermark": 1777434906479, ...}
#   {"id": "abc", "name": "...", "date_updated": "1777434906479", ...}
#
# Line-delimited so it appends/streams and diffs sanely in git-less transports;
# a single file so moving it is one scp.
#
# WATERMARK
# ---------
# max(date_updated) over every task in the snapshot, in Unix ms — the same unit
# ClickUp's `date_updated_gt` filter takes. The next run passes it straight
# through as the delta bound, so "changed since last extract" needs no clock
# comparison and no dependence on when the run happened to start.
#
# NOT COVERED (deliberate, see the PR that added this)
# ----------------------------------------------------
# * Comments — re-fetched per task at import time. Comments dominate the import's
#   API cost, so a tasks-only snapshot does NOT make a replay cheap; it makes it
#   REPRODUCIBLE and removes the task-page crawl. Snapshotting comments is a
#   follow-up.
# * Deletions — ClickUp's date_updated_gt never reports them, so a task deleted
#   between runs stays in the snapshot and is re-imported. Catching that needs a
#   full id-sweep diff; also a follow-up.
# * Container structure (spaces / folders / lists / tags / custom-field defs) —
#   still fetched live, because Projects/Modules/States/Labels are derived from
#   it. That is a few hundred calls, not thousands.

import json
import logging
import os
import tempfile
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

SNAPSHOT_VERSION = 1


def _as_ms(value) -> Optional[int]:
    """ClickUp timestamps arrive as ms-precision strings; be liberal."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def compute_watermark(tasks: Iterable[dict]) -> Optional[int]:
    """Return max(date_updated) in Unix ms across tasks, or None if unknown.

    None means "no usable watermark" — callers MUST fall back to a full pull
    rather than silently treating it as 0, which would look like a delta that
    matched everything.
    """
    best: Optional[int] = None
    for task in tasks:
        ms = _as_ms(task.get("date_updated"))
        if ms is not None and (best is None or ms > best):
            best = ms
    return best


def write(path: str, tasks: Iterable[dict], *, space_ids=None, since_days=None) -> dict:
    """Write tasks to a JSONL snapshot at path. Returns the manifest.

    Written to a temp file in the same directory and atomically renamed, so an
    interrupted write can never leave a half-file that a later run would happily
    load as a complete extract.
    """
    task_list = list(tasks)
    watermark = compute_watermark(task_list)
    manifest = {
        "_manifest": 1,
        "version": SNAPSHOT_VERSION,
        "task_count": len(task_list),
        "watermark": watermark,
        "space_ids": list(space_ids or []),
        "since_days": since_days,
    }

    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(manifest, ensure_ascii=False) + "\n")
            for task in task_list:
                fh.write(json.dumps(task, ensure_ascii=False) + "\n")
        os.replace(tmp_path, path)
    except BaseException:
        # Leave no debris on failure, then re-raise — a snapshot that silently
        # half-wrote is worse than no snapshot.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    logger.info(
        "snapshot written: %s (%s tasks, watermark=%s)",
        path, len(task_list), watermark,
    )
    return manifest


def read(path: str) -> tuple[dict[str, dict], dict]:
    """Load a snapshot. Returns (tasks_by_id, manifest).

    Raises ValueError on a missing/!=expected manifest or an unknown version —
    a malformed snapshot must fail loudly, not degrade into a partial import.
    """
    tasks_by_id: dict[str, dict] = {}
    manifest: Optional[dict] = None

    with open(path, "r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if lineno == 1:
                if not obj.get("_manifest"):
                    raise ValueError(
                        f"{path}: first line is not a snapshot manifest — "
                        "refusing to guess the format."
                    )
                if obj.get("version") != SNAPSHOT_VERSION:
                    raise ValueError(
                        f"{path}: snapshot version {obj.get('version')!r} is not "
                        f"supported (expected {SNAPSHOT_VERSION})."
                    )
                manifest = obj
                continue
            tid = str(obj.get("id", ""))
            if tid:
                tasks_by_id[tid] = obj

    if manifest is None:
        raise ValueError(f"{path}: empty snapshot (no manifest line).")

    return tasks_by_id, manifest


def merge(base: dict[str, dict], delta: Iterable[dict]) -> tuple[dict[str, dict], int, int]:
    """Overlay delta tasks onto a snapshot, keyed by task id. Delta wins.

    Returns (merged, updated_count, added_count). Delta wins unconditionally:
    it was fetched later, so for any task present in both it is by definition
    the newer revision.
    """
    merged = dict(base)
    updated = 0
    added = 0
    for task in delta:
        tid = str(task.get("id", ""))
        if not tid:
            continue
        if tid in merged:
            updated += 1
        else:
            added += 1
        merged[tid] = task
    return merged, updated, added


def group_by_list(tasks: Iterable[dict]) -> dict[str, list[dict]]:
    """Bucket tasks by their ClickUp list id.

    The apply traversal is driven by the live folder/list structure, so replay
    needs tasks addressable by list id. Tasks with no resolvable list are
    dropped and counted by the caller — they cannot be placed in a Project.
    """
    out: dict[str, list[dict]] = {}
    for task in tasks:
        lid = str((task.get("list") or {}).get("id", ""))
        if not lid:
            continue
        out.setdefault(lid, []).append(task)
    return out

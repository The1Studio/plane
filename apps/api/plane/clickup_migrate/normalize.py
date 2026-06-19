# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
#
# The1Studio SP1 — Phase 3 normalization (--plan step).
#
# Collects distinct ClickUp values and sends them to Anthropic for mapping
# suggestions.  Writes MappingTable rows (approved=false) and emits a
# human-review file.  The apply phase reads the approved rows and does
# NO further Anthropic calls.

import json
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

# Valid Plane state groups (from plane.db.models.state.StateGroup).
# "triage" is NEVER a valid migration target.
VALID_STATE_GROUPS = {"backlog", "unstarted", "started", "completed", "cancelled"}

# Deterministic ClickUp priority → Plane priority mapping (no AI needed).
PRIORITY_MAP = {
    "urgent": "urgent",
    "high": "high",
    "normal": "medium",
    "low": "low",
    "no priority": "none",
    # ClickUp numeric priorities (API returns these as strings)
    "1": "urgent",
    "2": "high",
    "3": "medium",
    "4": "low",
}


def make_status_key(list_id: str, status_name: str) -> str:
    """Encode the composite status key as a JSON array string.

    Keyed by (list_id, status_name) because the same status name can
    map to different groups in different lists.
    """
    return json.dumps([list_id, status_name])


def collect_distinct_statuses(extracted_tasks: list) -> list[dict]:
    """Walk extracted tasks and return distinct (list_id, status_name) pairs.

    extracted_tasks — list of raw ClickUp task dicts with 'list' and 'status' keys.
    Returns a list of dicts: {list_id, list_name, status_name, color, count}.
    """
    seen: dict[str, dict] = {}
    for task in extracted_tasks:
        list_id = task.get("list", {}).get("id", "")
        list_name = task.get("list", {}).get("name", "")
        status_obj = task.get("status", {})
        status_name = status_obj.get("status", "") if isinstance(status_obj, dict) else ""
        color = status_obj.get("color", "") if isinstance(status_obj, dict) else ""
        key = make_status_key(list_id, status_name)
        if key not in seen:
            seen[key] = {
                "list_id": list_id,
                "list_name": list_name,
                "status_name": status_name,
                "color": color,
                "count": 0,
            }
        seen[key]["count"] += 1
    return list(seen.values())


def collect_distinct_custom_field_defs(field_defs_by_list: dict[str, list]) -> list[dict]:
    """Deduplicate custom field definitions across lists by field_id."""
    seen: dict[str, dict] = {}
    for list_id, fields in field_defs_by_list.items():
        for f in fields:
            fid = f.get("id", "")
            if fid and fid not in seen:
                seen[fid] = {
                    "field_id": fid,
                    "field_name": f.get("name", ""),
                    "field_type": f.get("type", ""),
                    "type_config": f.get("type_config", {}),
                    "list_id": list_id,
                }
    return list(seen.values())


# ─────────────────────────────────────────────────────────────────────
# Anthropic Message Batches helpers
# ─────────────────────────────────────────────────────────────────────

def _make_status_batch_requests(distinct_statuses: list[dict]) -> list[dict]:
    """Build Batches API request list for status → group mapping."""
    requests_list = []
    for i, s in enumerate(distinct_statuses):
        prompt = (
            f"Map this ClickUp status to exactly one Plane state group.\n\n"
            f"Status name: {s['status_name']}\n"
            f"Status color: {s['color']}\n"
            f"List: {s['list_name']}\n\n"
            f"Valid groups: backlog, unstarted, started, completed, cancelled\n"
            f"NEVER output 'triage'.\n"
            f"Respond with ONLY the group name, nothing else."
        )
        requests_list.append({
            "custom_id": f"status-{i}",
            "params": {
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 20,
                "messages": [{"role": "user", "content": prompt}],
            },
        })
    return requests_list


def _make_field_batch_requests(distinct_fields: list[dict]) -> list[dict]:
    """Build Batches API request list for custom-field render suggestions."""
    requests_list = []
    for i, f in enumerate(distinct_fields):
        config_str = json.dumps(f.get("type_config", {}), ensure_ascii=False)[:500]
        prompt = (
            f"Suggest a concise Markdown render format for this ClickUp custom field.\n\n"
            f"Field name: {f['field_name']}\n"
            f"Field type: {f['field_type']}\n"
            f"Type config: {config_str}\n\n"
            f"Respond with ONE short sentence describing the suggested format "
            f"(e.g. 'Render as a two-column Markdown table row: | Field | Value |') "
            f"and a confidence score 0.0-1.0 in JSON: "
            f'{{\"suggestion\": \"...\", \"confidence\": 0.9}}'
        )
        requests_list.append({
            "custom_id": f"field-{i}",
            "params": {
                "model": "claude-sonnet-4-6",
                "max_tokens": 150,
                "messages": [{"role": "user", "content": prompt}],
            },
        })
    return requests_list


def run_anthropic_batch(client, requests_list: list[dict], poll_interval: int = 30) -> dict[str, str]:
    """Submit a Message Batches job, poll to completion, return {custom_id: text}.

    Uses the native `anthropic` SDK (Message Batches API).
    Polls every poll_interval seconds until processing_status == 'ended'.
    """
    batch = client.messages.batches.create(requests=requests_list)
    batch_id = batch.id
    logger.info("Anthropic batch submitted: %s (%d requests)", batch_id, len(requests_list))

    while True:
        status = client.messages.batches.retrieve(batch_id)
        if status.processing_status == "ended":
            break
        logger.info(
            "Batch %s: %s (in_progress=%d, succeeded=%d, errored=%d)",
            batch_id,
            status.processing_status,
            status.request_counts.processing,
            status.request_counts.succeeded,
            status.request_counts.errored,
        )
        time.sleep(poll_interval)

    results: dict[str, str] = {}
    for result in client.messages.batches.results(batch_id):
        cid = result.custom_id
        if result.result.type == "succeeded":
            content = result.result.message.content
            text = content[0].text if content else ""
            results[cid] = text.strip()
        else:
            logger.warning("Batch result error for %s: %s", cid, result.result)
            results[cid] = ""
    return results


def validate_state_group(raw: str) -> Optional[str]:
    """Validate and normalise an AI-returned state group.

    Returns the group string if valid, None if out-of-enum.
    NEVER accepts 'triage'.
    """
    cleaned = raw.strip().lower()
    if cleaned in VALID_STATE_GROUPS:
        return cleaned
    return None


def build_mapping_rows(
    run,  # MigrationRun instance
    distinct_statuses: list[dict],
    status_results: dict[str, str],
    distinct_fields: list[dict],
    field_results: dict[str, str],
) -> tuple[list, list]:
    """Return (mapping_rows, rejected_rows) ready to bulk-insert.

    mapping_rows — approved=False MappingTable instances
    rejected_rows — rows where AI output was out-of-enum (need manual review)
    """
    from plane.clickup_migrate.models import MappingTable

    mapping_rows = []
    rejected_rows = []

    # Status mappings
    for i, s in enumerate(distinct_statuses):
        raw_group = status_results.get(f"status-{i}", "")
        validated = validate_state_group(raw_group)
        source_key = make_status_key(s["list_id"], s["status_name"])
        row = MappingTable(
            run=run,
            kind=MappingTable.KIND_STATUS,
            source_key=source_key,
            target_value=validated or "",
            approved=False,
            source_meta={
                "list_id": s["list_id"],
                "list_name": s["list_name"],
                "status_name": s["status_name"],
                "color": s["color"],
                "count": s["count"],
                "ai_raw_output": raw_group,
                "ai_valid": validated is not None,
            },
        )
        if validated is None:
            rejected_rows.append(row)
        else:
            mapping_rows.append(row)

    # Priority mappings (deterministic — no AI)
    for clickup_prio, plane_prio in PRIORITY_MAP.items():
        row = MappingTable(
            run=run,
            kind=MappingTable.KIND_PRIORITY,
            source_key=json.dumps(clickup_prio),
            target_value=plane_prio,
            approved=False,
            source_meta={"deterministic": True},
        )
        mapping_rows.append(row)

    # Custom-field render suggestions
    for i, f in enumerate(distinct_fields):
        raw_suggestion = field_results.get(f"field-{i}", "")
        try:
            parsed = json.loads(raw_suggestion)
            suggestion = parsed.get("suggestion", raw_suggestion)
            confidence = parsed.get("confidence", 0.0)
        except (json.JSONDecodeError, AttributeError):
            suggestion = raw_suggestion
            confidence = 0.0

        row = MappingTable(
            run=run,
            kind=MappingTable.KIND_CUSTOM_FIELD,
            source_key=json.dumps(f["field_id"]),
            target_value=suggestion,
            approved=False,
            source_meta={
                "field_id": f["field_id"],
                "field_name": f["field_name"],
                "field_type": f["field_type"],
                "confidence": confidence,
            },
        )
        mapping_rows.append(row)

    return mapping_rows, rejected_rows


def emit_review_file(
    path: str,
    distinct_statuses: list[dict],
    mapping_rows: list,
    rejected_rows: list,
    distinct_fields: list[dict],
) -> None:
    """Write the human-review file to path."""
    lines = [
        "# ClickUp Migration — Mapping Review File",
        "# Edit target_value for any row and mark approved=true in the DB.",
        "# REJECTED rows have invalid AI output and MUST be corrected before --apply.",
        "",
        "## Status Mappings (pending approval)",
        "",
    ]
    for row in mapping_rows:
        if row.kind == "status":
            meta = row.source_meta
            lines.append(
                f"  {meta['list_name']} / {meta['status_name']}  "
                f"→  {row.target_value or 'NEEDS MANUAL MAPPING'}  "
                f"(count={meta['count']}, color={meta['color']})"
            )
    if rejected_rows:
        lines += ["", "## REJECTED Status Mappings (AI output was out-of-enum — MUST fix)", ""]
        for row in rejected_rows:
            meta = row.source_meta
            lines.append(
                f"  REJECTED: {meta['list_name']} / {meta['status_name']}  "
                f"AI said: '{meta['ai_raw_output']}' — update target_value manually"
            )
    lines += ["", "## Priority Mappings (deterministic — review only)", ""]
    for row in mapping_rows:
        if row.kind == "priority":
            lines.append(f"  {json.loads(row.source_key)}  →  {row.target_value}")

    lines += ["", "## Custom Field Render Suggestions (pending approval)", ""]
    for row in mapping_rows:
        if row.kind == "custom_field":
            meta = row.source_meta
            lines.append(
                f"  [{meta['field_name']} / {meta['field_type']}]  "
                f"→  {row.target_value}  (confidence={meta['confidence']:.2f})"
            )

    lines += [
        "",
        "## Next Steps",
        "1. Review every row above.",
        "2. Update target_value for any incorrect mapping via the DB or Django admin.",
        "3. Set approved=true for ALL rows.",
        "4. Run --apply only after every row is approved.",
    ]

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    logger.info("Review file written to %s", path)

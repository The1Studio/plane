# ClickUp → Plane Migration Status

_Living status doc for the one-time ClickUp → Plane ETL (`apps/api/plane/clickup_migrate/`)._
_Last updated: 2026-07-08._

## Scope

The production migration is deliberately **windowed to the last 90 days** (`--since-days 90`).
Older ClickUp tasks are intentionally out of scope for the initial cutover.

Note the window filters on **`date_updated`**, not `date_created` — a task opened two years ago
but touched last week is in scope. `include_closed=true`, `subtasks=true`, and both archived and
non-archived lists are walked.

## Snapshot — reusable extract, incremental re-import

`--snapshot PATH` writes a portable JSONL of the **raw** ClickUp task payloads, decoupling
extract from load. Without it, every run re-crawls ClickUp from scratch and everything that
persists (`MigrationRun`, `MappingTable`, `MigrationRecord`) lives in that one instance's
Postgres — so importing the same data into a second instance starts from zero.

| Flag                                 | Effect                                                                                                              |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------------------- |
| `--snapshot PATH` (file absent)      | Crawl per `--since-days`, then write the snapshot                                                                   |
| `--snapshot PATH` (file present)     | Read tasks from it; ClickUp is **not** paged for tasks                                                              |
| `--snapshot PATH --snapshot-refresh` | Pull only tasks updated since the watermark, merge (delta wins per task id), rewrite the snapshot, import the union |

The **watermark** is `max(date_updated)` across the snapshot in Unix ms — the same unit
`date_updated_gt` takes, so the delta bound needs no clock arithmetic and does not depend on
when a run started.

### Staging → prod replay

```bash
# 1. Seed the snapshot (staging, one full crawl)
python manage.py migrate_clickup --plan --space 26313036 --since-days 90 \
  --auto-map --snapshot /data/clickup-snapshot.jsonl

# 2. Move it
scp server:/data/clickup-snapshot.jsonl prod:/data/

# 3. Later: pull only what changed, then import everything
python manage.py migrate_clickup --run-id N --workspace <slug> --space 26313036 \
  --apply --snapshot /data/clickup-snapshot.jsonl --snapshot-refresh
```

The file is written to a temp path and atomically renamed, so an interrupted write cannot leave
a half-file that a later run would load as a complete extract.

### Deliberate limits

- **Tasks only.** Comments are re-fetched per task at import time, and comments dominate the
  import's API cost — so a snapshot makes a replay _reproducible_, not _fast_. Snapshotting
  comments is a follow-up.
- **No deletion detection.** `date_updated_gt` never reports deletions, so a task deleted in
  ClickUp between runs stays in the snapshot and is re-imported. Catching that needs a full
  id-sweep diff.
- **Container structure is still live.** Spaces, folders, lists, tags and custom-field defs are
  fetched per run, because Projects/Modules/States/Labels derive from them. Hundreds of calls,
  not thousands.
- **Ancestor backfill is skipped on replay** — the snapshot already holds whatever ancestors
  were resolved when it was seeded.

## Current state (as of 2026-07-08)

| Metric                   | Count     | Notes                                                                |
| ------------------------ | --------- | -------------------------------------------------------------------- |
| Migrated issues          | **9,943** | 90-day window across both spaces                                     |
| Attachments (FileAssets) | **0**     | fix landed + verified; scoped bulk run still **pending** (see below) |
| Comments                 | 452       |                                                                      |
| Labels (tags)            | 4,061     |                                                                      |
| States (statuses)        | 417       |                                                                      |
| Modules (lists)          | 329       |                                                                      |
| Projects (folders/lists) | 36        |                                                                      |

### Runs

| Run | Space         | Status | Notes                       |
| --- | ------------- | ------ | --------------------------- |
| #1  | `90167076334` | done   | 76 tasks                    |
| #2  | `26313036`    | done   | 9,867 tasks (90-day window) |

## Attachments — fixed, not yet backfilled

Attachment migration was broken end-to-end (originally **0 of ~13k** attachments migrated).
Three bugs were found and fixed (all on `company-main`), each caught by progressively deeper testing:

| Commit       | Fix                                                                                                              |
| ------------ | ---------------------------------------------------------------------------------------------------------------- |
| `9f41a7d`    | ClickUp's list endpoint omits the `attachments` array → resolve via per-task detail fetch (`--attachments` flag) |
| `7505de1`    | Auth default flipped: pre-signed attachment URLs 401 **with** the token (verified with-auth=401, without=206)    |
| `6a14928175` | `download_attachment` didn't strip the session's global `Authorization` header, so `use_auth=False` still 401'd  |

Verified end-to-end (1-task smoke: download → S3 → FileAsset). **The scoped bulk run has not
yet been performed** — attachments count is currently 0.

### To backfill attachments (the correct command)

Run scoped to the same 90-day window, from **inside** the api container network, with a
**dedicated** ClickUp token:

```bash
docker exec \
  -e CLICKUP_TOKEN=<migration-token> \
  -e CLICKUP_TEAM_ID=14311540 \
  -e CLICKUP_BOT_EMAIL=tuha@the1studio.org \
  -e AWS_S3_ENDPOINT_URL=http://plane-minio:9000 \
  api sh -c 'cd /code && python manage.py migrate_clickup \
    --run-id 2 --space 26313036 --since-days 90 --apply --attachments'
```

Runbook notes:

- **`--since-days 90` is mandatory** — omitting it re-pulls the entire space history and
  migrates out-of-window issues (see incident below).
- **`AWS_S3_ENDPOINT_URL=http://plane-minio:9000`** — the deploy's default
  `localhost:20090` is host-mapped and unreachable for server-side upload from inside the container.
- **Auth**: downloads default to no header (pre-signed URLs). `CLICKUP_ATTACHMENT_USE_AUTH=1`
  forces the token on only if a workspace needs it.
- **Dedicated token**: a bulk backfill saturates ClickUp's ~100 req/min per-token limit; using
  the shared `clickup-service` token throttles that service and its dependents for the duration.

## Known issues / follow-ups

- **[#7](https://github.com/The1Studio/plane/issues/7)** — ledger key collision: `write_issue`
  and `write_workload_estimate` shared `source_type="task"`, so the pass-3 estimate row
  overwrote the issue's ledger row. Issues themselves healed via `external_id`, but the
  clobbered row silently broke `_ledger_done(run, "task", …)` on a **resumed** run:
  `write_subtask_parent` / `write_issue_relation` resolved a `WorkloadEstimate` id, matched no
  `Issue`, and dropped the parent/relation link while still returning `True`. Fixed — the
  estimate now ledgers under its own `source_type="task_estimate"`
  (`SOURCE_TYPE_TASK_ESTIMATE`), with regression tests in
  `tests/test_estimate_writer.py::TestLedgerKeyDoesNotCollideWithIssue`. **Closed.**
- **[#6](https://github.com/The1Studio/plane/issues/6)** — attachments never migrated. Fixed
  (3 commits above); closed after end-to-end verification.

## Incident log

- **2026-07-08 — scope creep + rollback.** An attachment backfill run omitted `--since-days 90`,
  re-pulling the full space history and creating ~13,270 out-of-window issues (23,213 total).
  Detected via issue-count anomaly, halted, and cleanly rolled back to the original 9,943 issues
  (out-of-window records were separable by ledger `created_at`). No in-window data lost.

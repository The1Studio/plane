# Plan — Map the ClickUp export onto the 54 Playable Labs Plane projects

_Drafted 2026-08-13. Source data: `~/clickup-exports/clickup-export-2026-08-12.jsonl`
(6,897 tasks, sha256 `3ffbb319…`, watermark 2026-08-13T03:57:02Z, space `26313036`)._

## What the data actually says

Measured from the snapshot, not assumed:

| Fact | Value |
|---|---|
| Tasks in export | 6,897 |
| **In scope** — folder `Playable Labs` (`90162436284`) | **3,312** |
| Out of scope — other folders (Marketing, AAA-TEAM, WORLD-GRAIN-TEAM, …) | 3,585 |
| Lists in the `Playable Labs` folder | **54 — exactly 1:1 with the 54 Plane projects** |
| Lists with in-window tasks | 34 (the other 20 exist but had nothing updated since 2026-07-01) |
| Subtasks in scope (`parent` set) | 3,046 (91%) |
| Subtasks whose parent is **absent** from the export | 17 |
| Distinct assignee emails | 37 |
| Distinct tags | 5 |
| Tasks carrying `time_estimate` | 1,469 |
| Distinct ClickUp statuses in scope | 10 |

Name matching is clean: all 54 list names correspond to the 54 Plane projects, with two
deliberate differences created at project-creation time — `Dashboard-DevOps` → `Dashboard DevOps`
and `IC- outsource app` → `IC outsource app` (Plane's public-API name validator rejects `-`).

## The core problem

The existing ETL derives Plane projects from ClickUp containers:

| ClickUp container | `migrate_clickup` maps to | Line |
|---|---|---|
| Folderless list | Project | `migrate_clickup.py:779` |
| Folder | Project | `migrate_clickup.py:837` |
| **List inside a folder** | **Module** | `migrate_clickup.py:854` |

Our 54 lists all live **inside** the `Playable Labs` folder. Run as-is, the ETL produces
**one** project named `Playable Labs` containing **54 modules** — not the 54 projects that exist.

Second problem: `write_project` upserts on `(external_source="clickup", external_id=<container id>)`
(`writers.py:271-280`). The 54 projects were created through the REST API and carry
`external_id = NULL`, so the ETL matches nothing and **creates duplicates**. Worse, its `defaults`
overwrite `name` and `identifier` with ClickUp-derived values (`identifier = re.sub(r"[^A-Z0-9]","",name.upper())[:12]`,
e.g. `DASHBOARDDEVO`), while `ProjectIdentifier` is only `get_or_create`d — so a rebind done
carelessly desynchronises `Project.identifier` from `ProjectIdentifier.name`.

## Approach

**Bind, don't create.** Introduce an explicit list→project binding and a loader that honours it,
leaving name/identifier under our control.

### Phase 1 — Binding table (no writes to issue data)

1. Build the 54-row map `clickup_list_id → plane_project_id` by exact name match, with the two
   hyphen renames as explicit overrides. Emit it as a reviewed JSON artifact — never inferred at
   run time.
2. Stamp `external_source="clickup"`, `external_id=<clickup_list_id>` onto each of the 54 projects.
   This makes any future `write_project` upsert **bind** instead of duplicate.
3. **Verify:** all 54 bound, no project left with `external_id IS NULL`, no duplicate `external_id`.

Gate: a dry-run report listing all 54 pairs, reviewed before any stamping.

### Phase 2 — Loader that respects the binding

The list→module behaviour is wrong for this shape, and `apps/api/plane/clickup_migrate/` is a
**fork-owned app** (`plane-classify-path.cjs` → `custom-app`), so it may be edited directly —
no touch-point concern. Two options, decide before building:

- **2a. Add a `--list-as-project` mode** to `migrate_clickup` — lists inside a folder become
  projects rather than modules, resolved through the Phase-1 binding. Reuses every existing writer
  (states, labels, assignees, relations, estimates) and the `MigrationRecord` ledger.
- **2b. Standalone loader** reading the snapshot and calling `writers.write_issue` et al. with our
  own project resolution. Less blast radius on the shared command; duplicates orchestration.

Recommendation: **2a**, gated behind a flag so existing behaviour is untouched, because the
ledger/idempotency/resume machinery is the expensive part to re-create.

Also required in 2a: skip `write_project`'s `defaults` for bound projects (bind-only, never
rename), otherwise our names and identifiers are clobbered.

### Phase 3 — State mapping

Plane state groups: `backlog | unstarted | started | completed | cancelled | triage`.
The 54 projects already have Plane's `DEFAULT_STATES` from creation. Proposed mapping from the
10 observed ClickUp statuses (counts are in-scope):

| ClickUp status | type | count | → Plane group |
|---|---|---|---|
| `Closed` | closed | 2,204 | completed |
| `Open` | open | 987 | unstarted |
| `qa-review` | done | 47 | started |
| `in progress` | custom | 44 | started |
| `completed` | closed | 19 | completed |
| `backlog` | custom | 4 | backlog |
| `code-review` | custom | 3 | started |
| `reopen` | custom | 2 | unstarted |
| `not started` | open | 1 | unstarted |
| `pending` | custom | 1 | backlog |

**Open question:** `Closed` (67% of all in-scope tasks) → `completed` or `cancelled`? ClickUp
conflates "done" and "won't do" in one closed status. Mapping everything to `completed` inflates
completion metrics. Needs a decision, possibly per-list.

### Phase 4 — Ordering, relations, users

1. **Parents before children.** 91% of in-scope tasks are subtasks. Load a topological order:
   parents first, then children with `parent_id` set. 17 subtasks have parents outside the export
   — decide: import parentless, or pull those 17 parents live (they exist in ClickUp, just outside
   the July-1 window).
2. **Users:** 37 distinct assignee emails → Plane members. Reuse the existing `EmailCoverage`
   pre-flight; unmatched emails must be reported, never silently dropped.
3. **Tags:** only 5 distinct — trivial label creation per project.
4. **Estimates:** 1,469 tasks carry `time_estimate` → the fork's `WorkloadEstimate`. Blocked on
   **issue #7** (ledger key collision: `write_issue` and `write_workload_estimate` share
   `source_type="task"`, so the estimate row overwrites the issue's ledger row — idempotent but
   defeats resume and corrupts per-issue reconciliation). Fix #7 first or accept degraded resume.

### Phase 5 — Rehearsal, then apply

1. `--dry-run` over the full snapshot: emit per-project counts and diff them against the measured
   table above. Any deviation is a bug, not a surprise.
2. Apply to **one** low-volume project first (`Skylink 1`, 2 tasks; or `WebApp`, 2) and inspect in
   the UI.
3. Then a mid-size one (`Crazy Labs`, 78) to exercise subtask nesting.
4. Full run only after both pass.

### Phase 6 — Verification and rollback

- Per-project issue counts must equal the snapshot's per-list counts (top: Lihuhu 665,
  Template Ready 526, Dashboard-DevOps 518, Rollic 184, Code Base 175).
- Spot-check parent/child nesting, assignees, states.
- **Rollback:** the 2026-07-08 incident was recovered because migrated rows were separable by
  `MigrationRecord.created_at`. Confirm the ledger is populated *before* the full run — that is the
  rollback handle.

## Things that must be decided before building

1. **`Closed` → `completed` or `cancelled`?** Affects 2,204 of 3,312 tasks.
2. **The 3,585 out-of-folder tasks** (Marketing, AAA-TEAM, …) — out of scope entirely, or a
   second wave into their own projects?
3. **The 20 empty projects** — leave empty, or backfill by re-exporting those lists without the
   July-1 window?
4. **Window semantics.** The export is tasks *updated* since 2026-07-01. A task created in 2024 and
   edited in July is in; its untouched siblings are not. Partial project histories are expected —
   confirm that is acceptable, or widen the export.
5. **Comments/attachments.** The snapshot is tasks-only; the ETL fetches comments and container
   structure **live**, so the import needs the ClickUp token too. Attachments were never
   backfilled (documented as still 0). In or out?
6. **Issue #7** — fix before estimates, or accept degraded resume/reconciliation?

## Not in scope

Nothing here writes to ClickUp. The export itself is already complete and verified; this plan only
covers the Plane side.

# Plan — Workload Parent Rollup (estimates, due date, hours-weighted progress %)

Brainstorm: `.claude/plans/reports/workload-parent-rollup-brainstorm.md` (approved 2026-07-02).
Approach A: compute-on-read, recursive CTE, no core edits, no new touch-points.

## 0. Locked decisions

Hard-block parent estimates (API 400 + read-only UI) · keep-but-ignore stored rows ·
display-only due-date rollup (`max(countable descendant target_date)`) · full-tree recursion ·
cancelled children excluded everywhere · progress % = hours-weighted
(`done = Σ hours of completed-group countable leaves`, `percent = done/total`, null if total 0).

## 1. Semantics (single source of truth)

- **Countable issue** (ONE predicate, used by rollup + leaf test + PUT block + matrix leaf-exclude):
  `deleted_at IS NULL AND archived_at IS NULL AND is_draft = FALSE AND COALESCE(state.group,'') NOT IN ('cancelled','triage')`.
  Triage excluded to match `_base_queryset` + core `IssueManager`; null-state issues (LEFT JOIN
  states) count as countable. The predicate is defined ONCE: a documented SQL fragment in
  rollup.py mirrored by a single Django `Q`; P3 adds a cross-check test asserting ORM
  is_parent == CTE-derived is_parent on the same fixture (drift guard).
- **is_parent(issue)** = has ≥1 countable child. Parents: estimate PUT → 400
  `{"error": "<human message>", "error_code": "PARENT_HAS_CHILDREN"}` (both keys — matches
  the existing `{"error": ...}` convention AND gives SDKs a stable code); DELETE stays
  allowed (cleanup).
  A parent whose children are ALL cancelled/deleted reverts to leaf (estimable again) —
  consistent with "cancelled children are invisible to this feature".
- **Leaf** = countable descendant with no countable children.
- **Rollup(parent)** over countable descendants (depth ≤ 10 PER ROOT, project-scope-filtered).
  **Traversal:** the recursive step re-applies the FULL countable predicate at every level
  (raw SQL gets no SoftDeletionManager filter for free); a non-countable node PRUNES its
  entire subtree. **All sums in integer cents** (`SUM(ROUND(hours*100))::bigint`,
  `from_cents()` at the boundary — same quantization contract as the matrix; only estimate
  rows with `hours > 0` count):
  `hours` = Σ leaf estimate cents · `done_hours` = Σ leaf estimate cents where
  state.group='completed' · `percent` = round(done/hours, 4) or null when hours=0 ·
  `due_date` = max(countable descendant target_date) or null (intentional asymmetry: dates
  from ALL countable descendants, hours from leaves only) · `leaf_count` = countable leaves
  with `hours > 0` estimate rows.
- **Matrix fix**: `_base_queryset` additionally excludes estimates whose issue has a countable
  child (leaf-only counting) → kills double-count. Existing state-group defaults unchanged.
- **Access**: descendants outside the caller's project scope are invisible to rollups
  (same access-intersection discipline as `resolve_project_scope`); flag-off guests get
  rollups computed only over their visible scope. **Note (by design):** a restricted
  guest's displayed rollup may under-count vs the true total — partial by scope, not a bug;
  frontend must not "fix" it.

## 2. API surface (additive only — no breaking shape changes)

| Endpoint                                                               | Change                                                                                                                                                                                                                                                                                                                  |
| ---------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `PUT .../workload-estimate/`                                           | 400 `{"error", "error_code": "PARENT_HAS_CHILDREN"}` when is_parent                                                                                                                                                                                                                                                     |
| `GET .../workload-estimate/` (single)                                  | + `is_parent: bool`; when parent: `hours` returned as **null** (stored legacy value never leaks to UI) + `rollup: {...}`                                                                                                                                                                                                |
| **NEW** `GET /api/workspaces/<slug>/workload-rollups/?issue_ids=a,b,c` | `{<id>: rollup}` for ids that are parents (others omitted). Authz follows `bulk_estimates` VERBATIM (service.py:344-357): cap 500, WORKSPACE level, `_guest_restricted_projects` + `_scope_filter` set-based gate — a parent not assigned to a restricted guest is omitted entirely (state in API docs)                 |
| Public API `/api/v1/` mirrors                                          | same three changes via shared handlers (api_views.py pattern)                                                                                                                                                                                                                                                           |
| Bulk estimates endpoint                                                | shape UNCHANGED (flat map) but **parent rows OMITTED** — keep-but-ignore means ignored everywhere; returning a parent's legacy hours here while single-GET nulls it would leak the ignored value into the spreadsheet (round-5 MAJOR-B.1). Semantically a parent now looks like "no estimate", same as matrix treatment |

## 3. Phases

### P1 — Backend core (`apps/api/plane/workload/rollup.py`, NEW)

- `countable_issue_q()` predicate + `has_countable_children` Exists-subquery helper.
- `compute_rollups(user, slug, issue_ids) -> {str(id): rollup_dict}`: one recursive CTE
  (raw SQL, `WITH RECURSIVE`, depth cap 10 per root, row guard 10_000).
  **Rebase safety:** ALL table/column names interpolated from Django meta —
  `Issue._meta.db_table`, `State._meta.db_table`, `WorkloadEstimate._meta.db_table`,
  columns via `_meta.get_field(...).column` — never string literals (an upstream rename
  then fails loudly at import, not silently at runtime). `states` joined LEFT (null-state
  issues stay countable). **Per-root anchoring:** the anchor SELECT seeds one row per
  requested id carrying a `root_id` column propagated through the recursion, so a
  descendant shared by nested requested roots is emitted once PER root and each root gets
  its own depth budget; Python folds by `root_id`.
  **Access resolution happens in Python BEFORE the SQL** — a Django `Q` cannot be embedded
  in raw SQL: call `resolve_project_scope` for the project-id set and, for flag-off guests,
  materialize `own_issue_ids` (the `_scope_filter` subquery) as a Python list; pass BOTH as
  bound parameter lists. NEVER re-express membership/guest rules in SQL (SSOT stays in
  service.py).
- Files: `rollup.py` (new). Verify: unit-importable, no HTTP deps. (Correctness assertions
  intentionally deferred to P3 — P1 alone is unverified; P3 is mandatory before P4+.)

### P2 — Backend API wiring

- `views.py`: `estimate_put` → parent check → 400; `estimate_get` → `is_parent` (+`rollup`);
  new shared handler `rollups_bulk(request, slug)`; new `WorkloadRollupsBulkEndpoint`.
- `service.py`: `_base_queryset` leaf-only exclude (matrix fix).
- `urls.py` + `api_urls.py` + `api_views.py`: mount new endpoint (app + public API).
- Files: views.py, service.py, urls.py, api_urls.py, api_views.py. No migration (no model change).
- Verify: `python manage.py check` in api container.

### P3 — Backend tests (`plane/workload/tests/test_rollup.py`, NEW + edits)

- Rollup math: 2-level + 3-level trees; cancelled child excluded; **triage child excluded**;
  completed leaf drives done_hours/percent; due = max date over ALL countable descendants
  (incl. an intermediate node with a date but no estimate); parent legacy estimate ignored;
  all-children-cancelled → issue treated as leaf again; **non-countable intermediate node
  prunes its whole subtree** (GP→cancelled P→countable C: GP's rollup EXCLUDES C);
  **zero-hour leaf contributes nothing and doesn't inflate leaf_count**; cents math (e.g.
  3× 0.1h sums to exactly 0.3).
- **Nested roots:** request A and its descendant B together → both get independent, correct
  rollups (per-root anchoring).
- **Drift guard:** cross-check test asserting ORM `is_parent` (Exists) == CTE-derived
  is_parent over a mixed fixture.
- PUT block: parent → 400 with BOTH `error` + `error_code`; leaf → 200;
  parent-of-only-cancelled → 200. Parent single-GET returns `hours: null` + rollup.
- Matrix: parent+child both estimated → only child counted (double-count regression test).
- Bulk rollups: cap 500, empty list 400, guest scope (restricted guest sees only own-scope
  rollup; parent not assigned to restricted guest omitted), cross-project descendant
  excluded from rollup for non-member.
- Depth: chain of 12 → counted only to depth 10 (guard, not error).
- **Round-5 additions:** public API `/api/v1/` mirror routing+shape tests for the new
  rollups endpoint AND the single-GET mirror (precedent:
  `test_workload_bulk.py::test_public_api_bulk_route_resolves`); explicit
  `percent is None` assertion at a parent whose leaves are all zero-hour; rollups
  endpoint 403-non-member + len==500-boundary-passes tests (precedent in
  `TestBulkEstimatesHTTP`); rollups request with only leaf ids → 200 `{}` (distinct
  from empty-ids→400); DELETE on parent → 204 (guards the stays-allowed rule);
  bulk estimates omits parent rows (parent looks like no-estimate).
- **Full existing workload suite re-run (52 baseline tests) — zero regressions
  EXCEPT tests asserting bulk-returns-parent-rows, which change intentionally (update
  them with a comment citing this plan).**
- Run: `docker exec api ... pytest plane/workload` (copy files in first — baked image predates).

### P4 — Frontend (`packages/workload-ext/` + fork surfaces)

- `types.ts`: `TWorkloadRollup {hours, done_hours, percent, due_date, leaf_count}`.
- `service.ts`: `fetchRollups(slug, issueIds)` → new endpoint; `putEstimate` parses the 400
  body and throws a TYPED error carrying `error_code` (not `new Error(raw text)`).
- `store.ts`: `rollupData: Record<issueId, TWorkloadRollup>` with its **own** dedup set
  `_fetchedRollupIds` (NEVER reuse `_fetchedIds` — the estimate fetch marks every id and
  would permanently skip the rollup fetch). Mark ALL requested ids fetched (incl. non-parents),
  mirror the estimate path's null-recording. **Independent try/catch + error state** — a
  rollup fetch failure must not clobber estimate dedup/error state or vice versa.
  **Invalidation:** after every successful `updateEstimate`/`deleteEstimate`, clear
  `_fetchedRollupIds` for the visible page so the next `useBulkWorkloadFetch` refires
  (one extra request per edit). Add/remove sub-issue → **stale-until-reload, accepted v1
  limitation (document)**. Single-issue `fetchEstimate` must ALSO write `rollupData[id]`
  from the extended single-GET response (sidebar path doesn't use the bulk fetch).
- `use-workload-estimate.ts`: expose `{hours, rollup}`; rollup presence ⇒ parent.
- **400 UX backstop** (pre-rollup-fetch window where a parent cell still renders editable):
  on PARENT_HAS_CHILDREN → refetch that id's rollup (flips cell read-only) + `setToast`
  (`@plane/propel/toast`, pattern at issue-detail/root.tsx) explaining estimates live on
  sub-items. Sidebar disable gate = `!isEditable || estimateSaving || rollup present`.
- UI (3 surfaces): sidebar input → read-only `Σ 10h · 60%` + tooltip (from N sub-items ·
  due <date>) when rollup present, input disabled; spreadsheet estimated-hours column →
  same read-only cell; list + kanban pill → unified `Σ 10h · 60%` with `truncate` CSS
  (graceful ellipsis on narrow kanban cards). **DECIDED at implementation:** the originally
  planned kanban-only abbreviation requires forwarding `activeLayout` through
  `all-properties.tsx` — a NEW core-edit exception for a cosmetic split; rejected to keep
  the fork's core-edit surface minimal. Revisit only if users report the truncation.
- i18n: new keys in fork-owned `i18n.ts` (wlt interpolation is `{name}` regex, no ICU
  plurals — write keys that read correctly for any count, e.g. "from {count} sub-item(s)").
- Verify: `pnpm check:types`, `check:lint`, prod build.

### P5 — E2E browser verification

- Seed via API: parent w/ 2 children (one completed 6h, one started 4h) + legacy parent estimate.
- Dev server + same-origin proxy (ports 4173/3100, minted session — same harness as the
  route-nesting smoke). Verify: sidebar shows `Σ 10h · 60%` read-only; **matrix shows 4h**
  (started child only — the completed 6h child is excluded by the matrix's default
  state-group filter, and the legacy parent estimate is excluded by the leaf-only rule;
  rollup and matrix intentionally use different counting rules); spreadsheet column
  read-only for parent; PUT on parent via curl → 400 with both `error` + `error_code`.
- Clean up: seeded data removed, session deleted, servers stopped.

### P6 — Ship

- Commits: `feat(workload): parent rollup — hours/due/progress from sub-items (backend)` +
  `feat(workload): read-only parent rollup display (frontend)` (split per scope), push company-main.

### P7 — Propagation (standing rule, background issues on sibling repos)

Full change × surface matrix (round-5 MAJOR-B). Four API changes to propagate:
(1) NEW bulk rollups endpoint, (2) single-GET parent shape (`hours: null` + `is_parent` +
`rollup`), (3) PUT 400 `PARENT_HAS_CHILDREN`, (4) BEHAVIOR shifts on EXISTING surfaces —
matrix goes leaf-only (parents vanish from `get_workload` rows) and bulk estimates omits
parent rows.

| Surface                               | Must cover                                                                                                                                                                                  |
| ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `plane-mcp-server`                    | new tool `get_workload_rollups` (1); `get_issue_workload_estimate` doc/shape (2); `set_issue_workload_estimate` surfaces 400 (3); `get_workload` + bulk estimates semantic-change notes (4) |
| `plane-node-sdk` / `plane-python-sdk` | rollups binding (1); typed response w/ nullable hours+rollup (2); PARENT_HAS_CHILDREN error type (3); changelog note (4)                                                                    |
| `plane-claude-plugin`                 | skill/doc entry for rollup + progress % semantics                                                                                                                                           |
| `docs` / `developer-docs`             | §1 semantics table, incl. restricted-guest under-count + stale-until-reload notes                                                                                                           |
| This repo `CLAUDE.md`                 | Custom-features line update                                                                                                                                                                 |

## 4. File ownership

| Phase | Files (exclusive)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| ----- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| P1    | `plane/workload/rollup.py`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| P2    | `plane/workload/{views,service,urls,api_urls,api_views}.py`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| P3    | `plane/workload/tests/*`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| P4    | `packages/workload-ext/src/*`, `apps/web/core/hooks/store/use-workload-estimate.ts`, and exactly these four core files (verify each is/becomes a documented FORK.md core-edit exception): `apps/web/core/components/issues/issue-detail/sidebar.tsx`, `apps/web/core/components/issues/issue-layouts/spreadsheet/columns/estimated-hours-column.tsx`, `apps/web/core/components/issues/issue-layouts/list/blocks-list.tsx`, `apps/web/core/components/issues/issue-layouts/kanban/blocks-list.tsx`, plus `apps/web/ce/components/issues/issue-layouts/additional-properties.tsx` (ce override, not core) |
| P7    | sibling repos via issues only                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |

## 5. Risks / edge cases

- **Cross-project sub-issues**: descendants filtered by project scope — rollup for a user who
  can't see a child project is partial BY DESIGN (no leak). Document in API docs.
- **Cycles**: parent FK shouldn't cycle, but depth cap 10 makes the CTE terminate regardless.
- **Perf**: CTE bounded by depth cap + 10k row guard; matrix leaf-test adds one EXISTS per
  estimate row — verify EXPLAIN no seq-scan on issues (issues.parent_id needs the existing
  core index; verify, else add index in fork app on nothing — NOT allowed on core table →
  rely on core `parent` FK index; measure).
- **Matrix semantics shift**: parents silently vanish from matrix rows even when they carry
  legacy estimates — release-note it. `_base_queryset` is shared by EVERY `compute_workload`
  consumer; existing aggregation tests may assert the current (double-counted) behavior —
  mitigation: re-run the FULL existing workload suite in P3, not just the new tests.
  **Rollback coupling:** P2's matrix change and P3's regression test revert together.
- **`sub_issues_count` mismatch**: core counts ALL children; our is_parent excludes cancelled —
  UI must key off OUR response, never core's count (P4 does this).

## 6. Definition of Done

Backend: pytest green incl. new suite AND the public `/api/v1/` mirror tests ·
`python manage.py check` clean · `python manage.py makemigrations --check --dry-run`
clean (the `company-main-ci.yml` gate) · EXPLAIN on the rollup CTE + leaf-exclude shows
index use on `issues.parent_id` (no seq-scan on issues).
Frontend: typecheck/lint/build green · browser E2E per P5 all assertions pass.
Matrix double-count regression test green. Ship: pushed; propagation issues filed per the
P7 matrix (all four changes × five surfaces); CLAUDE.md updated. No core-file edits
outside documented FORK.md exceptions.

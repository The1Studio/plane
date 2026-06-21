# Plan — "Estimated hours" column in List + Spreadsheet views

**Status:** Hardened after 5-round parallel validation (rigor / technical / isolation / facts /
adversarial). **Cook-ready** — all decisions resolved.
**Owner:** company-main fork
**Feature:** Surface the per-issue workload estimate (`workload_estimates` table) as an
**editable, always-visible** column in the work-item **spreadsheet** grid and as an inline
**pill** in **list-view** rows.

## Resolved decisions (from user)
1. **Cell behavior:** editable inline (type hours in the grid; PUT on blur, optimistic).
2. **Visibility:** always visible — NO display-properties toggle ⇒ **no `@plane/types` edit**.
3. **Scope:** spreadsheet column **and** list-view inline pill.

## Resolved decision — kanban pill (Round 1)
The list-view pill seam (`WorkItemLayoutAdditionalProperties`) is **shared with the kanban
layout** (`kanban/block.tsx:39` renders the same `IssueProperties` as `list/block.tsx:24`).
Filling the stub makes the hours pill appear on **kanban cards too**. **DECISION (user-confirmed):
accept kanban as in-scope** — the pill shows in list AND kanban; no layout gating. Documented as
intended behavior in Phase 3 + success criteria.

## Hard constraints (docs/FORK.md)
- **MUST NOT edit `@plane/*` packages in place** — rules out adding a key to
  `IIssueDisplayProperties` (`@plane/types`) or `SPREADSHEET_PROPERTY_LIST` (`@plane/constants`).
  The "always visible" + "fixed appended column" choices are what make this avoidable
  (validated: the fixed column appends *after* the `spreadsheetColumnsList` loop, so it never
  needs a `keyof IIssueDisplayProperties` key).
- Core edits under `apps/web/core` / `apps/web/ce` allowed only as **documented** "Frontend
  core-edit exceptions"; each fenced with `The1Studio fork (SP2 workload)` + listed in FORK.md.
- Backend additions stay in the **`plane/workload/` app** (new endpoint only; no core model column).
- `packages/workload-ext` uses the `@plane/` npm scope but is **fork-owned** — editing it is NOT
  an `@plane/*` violation. Add a `plane-isolation-audit` allowlist carve-out so it isn't
  false-flagged.

## Validation verdicts (5 parallel rounds)
| Round | Lens | Verdict |
|---|---|---|
| 1 | Rigor/completeness | patch-then-ship (~85%) |
| 2 | Technical feasibility | sound-with-fixes |
| 3 | Fork-isolation | compliant-with-documentation (9/10) |
| 4 | Reference accuracy | references-accurate |
| 5 | Adversarial | hardening-required (1 Critical authZ) |

---

## Phase 0 — Backend bulk endpoint (workload app)

**Goal:** one round-trip returns hours for N issues, killing the N+1 when rendering 50+ rows.
**ONE workspace-scoped endpoint** serves list + BOTH spreadsheet modes (the spreadsheet runs at
workspace AND project level — `spreadsheet-view.tsx:41` `isWorkspaceLevel`). Do NOT add a
project-scoped variant.

**Files (all inside the isolated app — no core touch-points):**
- `apps/api/plane/workload/service.py` — add `bulk_estimates(user, slug, issue_ids) -> dict[str, float]`:
  - **AuthZ (CRITICAL — Round 5/2):** reuse the EXISTING scope primitives, NOT the per-issue gate.
    Build the row filter exactly as `compute_workload` does:
    `scope = resolve_project_scope(user, slug, route_project_id=None)` (service.py:52) →
    `_guest_restricted_projects(...)` → `scope_q = _scope_filter(...)` (service.py:123) →
    `WorkloadEstimate.objects.filter(scope_q, workspace__slug=slug, issue_id__in=ids).values_list("issue_id", "hours")`.
    This enforces project membership AND the guest "only my assigned issues" rule in ONE query.
    **Do NOT** hand-roll `is_guest_restricted` + `is_issue_assignee` per issue (wrong primitive,
    O(N) queries, and `is_guest_restricted` only takes a single project_id → cross-project leak).
  - Cap `len(issue_ids)` (e.g. 500) — raise `_BadRequest` past the cap; **empty/all-garbage
    parsed list → `_BadRequest`** (cap-check on the *parsed* length).
  - Return ALL in-scope stored rows **including `hours == 0`** — do NOT copy the matrix's
    `hours__gt=0` filter (service.py:144). Omit only issues with **no row**.
  - Defensively mirror `deleted_at`/`archived_at`/`is_draft` exclusions or document that the grid
    never sends such ids.
- `apps/api/plane/workload/views.py` — `estimate_bulk(request, slug)` (parse `issue_ids` CSV via
  `_split_uuids`, call `bulk_estimates`, return `{ "<issue_id>": <hours> }`) + class
  `WorkloadEstimatesBulkEndpoint(BaseAPIView)`, `get` decorated
  `@allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], level="WORKSPACE")`
  (**`level="WORKSPACE"` is mandatory** — match `WorkspaceWorkloadEndpoint`, views.py:161; the
  project-level decorator form can't resolve without a project_id).
- `apps/api/plane/workload/api_views.py` — `WorkloadEstimatesBulkAPIEndpoint` reusing
  `estimate_bulk` (public `/api/v1`, API-key auth, same `level="WORKSPACE"`).
- `apps/api/plane/workload/urls.py` + `api_urls.py` — append `workspaces/<slug>/workload-estimates/`
  (and the `/api/v1` mirror). Workspace-scoped only.

**Endpoint contract:** `GET …/workload-estimates/?issue_ids=a,b,c` → `200 {"<uuid>": 3.5, "<uuid>": 0, …}`
(missing = no estimate). `400` on empty/oversize id list.

**Tests:** `apps/api/plane/workload/tests/` — happy path; cap exceeded → 400; empty/garbage → 400;
**cross-project isolation** (member of A requests B's ids → B omitted); **guest restriction**
(flag-off guest gets only assigned issues); **stored-0 returned** (not omitted); missing issue omitted.

**Verify:** `cd apps/api && pytest plane/workload -q` green; `makemigrations --check --dry-run` clean.

### Risk Assessment
| Risk | L | I | Score | Mitigation |
|---|---|---|---|---|
| Cross-project / guest estimate leak | 4 | 5 | **20** | Use `resolve_project_scope`+`_scope_filter` (not per-issue gate); `level="WORKSPACE"`; isolation tests |
| Unbounded `issue_ids` → slow query | 2 | 3 | 6 | Cap 500 on parsed length; `project`/`issue` indexes exist |
| `hours==0` renders as "none" | 3 | 2 | 6 | Return all rows incl 0; test a stored 0 |

---

## Phase 1 — Frontend data layer (`packages/workload-ext` + 1 core hooks file)

**Goal:** a bulk fetch over the EXISTING store, plus selector hooks. **Reuse `estimateData`** —
do NOT add a parallel `estimatesByIssue` map (SSOT; Rounds 2/4/5).

**Files:**
- `packages/workload-ext/src/service.ts` — `getEstimatesBulk(workspaceSlug, issueIds): Promise<Record<string, number>>`
  → calls the new endpoint; chunk if `issueIds.length` > cap.
- `packages/workload-ext/src/store.ts` — extend the EXISTING `estimateData: Record<string, TWorkloadEstimate | null>`
  (store.ts:33). Add: `fetchEstimatesBulk(workspaceSlug, issueIds)` action + a private fetched-ids
  set (only request missing). **Merge rule (Rounds 1/5):** bulk merge MUST NOT overwrite any
  issueId with an in-flight or unsynced local write — track a `pending`/`dirty` set; a `updateEstimate`
  PUT always wins over a later-resolving bulk GET. `updateEstimate` already writes `estimateData`
  (store.ts:177) — keep that as the single write path.
- **Selector hooks — location decision (Round 2):** package `src/hooks.ts` hooks are
  context-agnostic (store passed as param) and CANNOT call core's `useWorkload()`. So put
  `useWorkloadEstimate(issueId)` and `useBulkWorkloadFetch(workspaceSlug, issueIds)` in a NEW
  **core** file `apps/web/core/hooks/store/use-workload-estimate.ts` (consumes `useWorkload()` →
  the shared singleton). This is a documented core-edit (add to FORK.md).

**Shared singleton confirmed:** one `workloadStore` lives at `ce/store/root.store.ts:22`, reached via
`useWorkload()` (`use-workload.ts:13`); grid, list, and sidebar all share it — no dual-store risk
once `estimateData` is the single map.

**Verify:** `pnpm --filter @plane/workload-ext build` clean; `apps/web` `pnpm check:types` clean.

### Risk Assessment
| Risk | L | I | Score | Mitigation |
|---|---|---|---|---|
| Bulk GET clobbers an in-flight edit | 3 | 4 | 12 | dirty-set merge guard; PUT wins |
| Refetch storm on virtualized scroll | 3 | 3 | 9 | Debounce; key off stable loaded `issueMap` ids (not scroll-visible); skip fetched ids |
| Dual-cache drift | 2 | 3 | 6 | Reuse `estimateData`; no second map |

---

## Phase 2 — Spreadsheet column (editable, always-on, fixed-append)

**Goal:** an "Estimated hours" column appended AFTER the property loop in both header + body —
never gated by `displayProperties`, never a `SPREADSHEET_COLUMNS` key (avoids the sealed-package
typing entirely).

**Files (core edits — documented exceptions):**
- NEW `apps/web/core/components/issues/issue-layouts/spreadsheet/columns/estimated-hours-column.tsx`
  — header cell + body cell. Body cell: number `<input>` (mirror `issue-detail/sidebar.tsx:86-129`),
  value from `estimateData[issueId]?.hours`, `onBlur` → `store.updateEstimate`, saving spinner.
  - **Editability (Round 1/2):** gate `disabled` on **`disableUserActions`** (the real signal,
    from `canEditProperties(project_id)` at `issue-row.tsx:244`) — NOT `isEditable` (doesn't exist).
    The appended cell must RECEIVE `disableUserActions` (it's currently only fed to the column map).
  - **project_id (Round 2):** source from **`issueDetail.project_id`** (per-row, `issue-row.tsx:290`),
    NEVER the route `useParams()` projectId (undefined at workspace-level spreadsheet). Empty cell
    → `updateEstimate(…, 0)` (MEMBER-allowed PUT), NOT the ADMIN-only delete.
- `apps/web/core/components/issues/issue-layouts/spreadsheet/spreadsheet-header.tsx` — append the
  fixed `<th>` after the loop at **line 89**.
- `apps/web/core/components/issues/issue-layouts/spreadsheet/issue-row.tsx` — append the fixed
  `<td>` after the per-row loop in the nested **`IssueRowDetails`** sub-component (after **line 400**).
- `apps/web/core/components/issues/issue-layouts/spreadsheet/spreadsheet-table.tsx` — host
  `useBulkWorkloadFetch(issueIds)` here (`issueIds` available, spreadsheet-table.tsx:29); one bulk
  call per loaded page of rows.

**Virtualization/alignment (Round 2 — risk lower than first scored):** native `<table>` auto-syncs
column widths; the `RenderIfVisible` placeholder already uses `colSpan={100}` (`issue-row.tsx:99`),
so the extra column is covered; the sticky first-column shadow logic targets `:first-child`
(`spreadsheet-table.tsx:78-91`) and is untouched by an appended last column. Cook just verifies the
real `<td>` renders only in the non-placeholder branch.

**Verify:** `cd apps/web && pnpm check:types` (0 errors) + `oxlint` clean; manual — column shows at
both workspace+project spreadsheet levels, edit persists + survives reload, read-only when
`disableUserActions`.

### Risk Assessment
| Risk | L | I | Score | Mitigation |
|---|---|---|---|---|
| Inline edit races bulk refetch (stale overwrite) | 3 | 3 | 9 | dirty-set merge guard (Phase 1) |
| Wrong project_id at workspace level | 3 | 3 | 9 | Use per-row `issueDetail.project_id` |
| Fixed column misaligns grid | 2 | 2 | 4 | Native table auto-sync + `colSpan={100}` already cover it |
| Edit permission bypass | 2 | 4 | 8 | `disabled={disableUserActions}`; backend PUT MEMBER+ |

---

## Phase 3 — List-view inline pill (CE seam — zero net core edits beyond the stub)

**Goal:** show hours as an inline property using the **already-mounted** designed stub seam.

**Files:**
- `apps/web/ce/components/issues/issue-layouts/additional-properties.tsx` — replace the no-op body
  of **`WorkItemLayoutAdditionalProperties`** (exact symbol — Round 4) with a small pill: read
  `useWorkloadEstimate(issue.id)`, render `⏱ {hours}h` when present. Fence + document.
- **No `all-properties.tsx` edit** — the seam is ALREADY mounted at `all-properties.tsx:475`
  (Rounds 1/2/3/4 agree). The prior contingency is deleted.
- Bulk fetch: list layout shares the same store; ensure its visible ids trigger
  `useBulkWorkloadFetch` (or piggyback the spreadsheet trigger via the shared singleton).
- **Kanban (resolved, in-scope):** same seam renders in `kanban/block.tsx:39` → the pill also
  shows on kanban cards. This is **accepted intended behavior** (user-confirmed); no layout gating.

**Verify:** list (and kanban) rows show the pill; `pnpm check:types` + `oxlint` clean.

### Risk Assessment
| Risk | L | I | Score | Mitigation |
|---|---|---|---|---|
| Kanban also shows the pill | 1 | 1 | 1 | Accepted in-scope (user-confirmed); documented |

---

## Phase 4 — Consolidation, docs, propagation

1. **Single source:** migrate `issue-detail/sidebar.tsx` from its raw per-issue `fetch`
   (lines 94, 118 — confirmed Round 4) to `store.fetchEstimate`/`updateEstimate`.
   **Parity gate:** confirm `store.fetchEstimate` hits the SAME
   `…/issues/<id>/workload-estimate/` endpoint; add a sidebar smoke-test so the detail panel
   doesn't silently regress.
2. **docs/FORK.md** — add to the "Frontend core-edit exceptions" table the **net-new** core edits:
   `spreadsheet/columns/estimated-hours-column.tsx`, `spreadsheet-header.tsx`, `issue-row.tsx`,
   `hooks/store/use-workload-estimate.ts`, and `ce/.../additional-properties.tsx` (stub seam).
   (`sidebar.tsx` is already row 1.) Add the `plane-isolation-audit` allowlist carve-out for the
   `@plane/workload-ext` scope.
3. **Propagation (CLAUDE.md standing rule — new bulk endpoint):** background `plane-propagate` →
   issues/PRs on `plane-mcp-server` (bulk-estimates tool), `plane-node-sdk`, `plane-python-sdk`;
   `docs`/`plane-claude-plugin` as relevant; one-line `CLAUDE.md` "Custom features" entry.
   **Gate: feature is NOT "done" until the sibling issues are opened.**
4. **Isolation audit:** run `plane-isolation-audit` on the diff → zero `@plane/*` in-place edits;
   every core edit in the exceptions table.

**Verify:** `pnpm check:types` + `pytest plane/workload` + `makemigrations --check` green;
`plane-isolation-audit` passes; sidebar smoke-test passes.

### Risk Assessment
| Risk | L | I | Score | Mitigation |
|---|---|---|---|---|
| Sidebar regresses on store migration | 3 | 3 | 9 | Endpoint-parity check + smoke-test |
| Propagation forgotten (MCP/SDK drift) | 3 | 3 | 9 | Phase-4 "not done until sibling issues opened" gate |

---

## Timeline
| Phase | Effort | Notes |
|---|---|---|
| 0 — Backend bulk endpoint | S–M (1–2d) | AuthZ via existing scope primitives + isolation tests is the real work |
| 1 — Frontend data layer | S (1d) | Extend `estimateData`; 1 core hooks file |
| 2 — Spreadsheet column | M (2–3d) | Editable cell + edit/refetch race; grid alignment now low-risk |
| 3 — List inline pill | S (0.5d) | Stub already mounted; cheaper than first planned |
| 4 — Consolidation/docs/propagation | S (1d) | Sidebar migration + sibling issues |
| **Total** | **~M (1wk)** | Critical path: 0 → 1 → 2 |

## Success criteria
- Always-visible, inline-**editable** "Estimated hours" column in the spreadsheet (workspace +
  project levels); edits persist + reload.
- List **and kanban** rows show the hours pill (kanban accepted in-scope).
- Rendering 50 issues → **one** bulk request, not 50.
- **No cross-project / guest estimate leak** (isolation tests green).
- `pnpm check:types`, `oxlint`, `pytest plane/workload`, `makemigrations --check` green.
- `plane-isolation-audit`: zero `@plane/*` in-place edits; all core edits documented.
- Sibling-repo propagation issues opened (MCP/SDK).

## Cook handoff
`/t1k:cook .claude/plans/workload-hours-column-plan.md`

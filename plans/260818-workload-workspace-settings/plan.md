# Workspace-wide workload settings

Replace per-member workload capacity with a single workspace-wide configuration covering
**max weekly hours**, **workdays**, and **first day of week** — and replace the aggregate
workload table with a per-member timeline of task bars built on Plane's existing Timeline
(gantt) layout.

- **Worktree:** `/home/frostbun/Projects/plane-workload-settings`
- **Branch:** `feat/workload-workspace-settings` (from `origin/company-main` @ `99f86c0f38`)
- **Base repo:** `The1Studio/plane` (fork of `makeplane/plane`)

---

## Resolved decisions

| # | Decision | Resolution |
|---|---|---|
| D1 | Capacity model | **Replace per-member entirely.** `WorkloadCapacity` is deleted; one workspace-wide `max_weekly_hours` applies to every member. |
| D2 | Config UI location | **Workspace settings page** — `/:workspaceSlug/settings/workload`, admin-only. |
| D3 | Week-start reach | **Workspace-wide, no per-user override.** The workspace value is the sole source of truth; the per-user preference UI is removed. |
| D4 | Workday effect on spreading | **Both.** `capacity_for_period()` and `spread_estimate()` honour configured workdays; hours no longer land on non-workdays. |

### Derived decisions (made during planning, not open)

| # | Decision | Rationale |
|---|---|---|
| D5 | Settings model lives in `apps/api/plane/workload/`, named `WorkloadSettings` | Keeps the data migration off `WorkloadCapacity` **intra-app** (no cross-app migration dependency pinning per `docs/FORK.md`), and reuses the workload app's existing serializer/permission/test scaffolding and its dual app+public API surface. `workspace_ext/` stays model-less as documented. Endpoint is named neutrally (`/work-settings/`) because core date pickers consume `week_start_day` too. |
| D6 | Weekday encoding is Plane's `EStartOfTheWeek`: `SUNDAY=0 … SATURDAY=6` | Matches `packages/types/src/users.ts:15-23` and core `User.start_of_the_week`. Python's `date.weekday()` (Mon=0) is converted at the aggregation boundary only — one convention crosses the API. |
| D7 | `User.start_of_the_week` column is **not** dropped | It is a core model column; `docs/FORK.md` forbids touching `plane/db/migrations/`. The column stays and is simply no longer read by the web app. |
| D8 | Migration **always** seeds `max_weekly_hours = 40`; existing per-member values are discarded | A `max()` seed is degenerate on real data: the only capacity row in the live workspace is `0`, which would seed `0` and render every member over-capacity on day one. A fixed, predictable default that an admin adjusts once beats a value derived from placeholder rows. |
| D9 | A span containing zero workdays falls back to calendar-day spreading | Guarantees hours are never silently lost when an issue is scheduled entirely across non-workdays. |
| D10 | Week bucket keys change from ISO `YYYY-Www` to the week-start date `YYYY-MM-DD` | An arbitrary week start has no ISO week number. The key becomes the date of the week's first day; the frontend formats the label. |
| D11 | The aggregate table is **replaced** by the per-member timeline | Confirmed decision. The Workload page becomes swimlanes of task bars; the `<Table>` render in `WorkloadMatrix.tsx:196-270` is deleted, not kept behind a toggle. |
| D12 | The timeline is built on core's gantt primitives (`ChartViewRoot` and friends), not a bespoke chart | Confirmed decision ("reuse Timeline Layout"). It already owns the day-column axis, today marker, zoom (week/month/quarter), and block positioning. |
| D13 | The timeline component lives under `apps/web/core/components/workload/timeline/` (NEW files), not in `packages/workload-ext` | Forced by D12: the gantt barrel is app-internal (`@/components/gantt-chart`) and a workspace package cannot import it. The package keeps store/service/types; the view moves to the app. |
| D14 | Drag-to-reschedule is **out of scope** | `ChartViewRoot` supports block move/resize, but wiring it means writing issue dates back from the workload view. Deliberately deferred; the props are passed as `false`. |

---

## Prior art (searched before scoping)

| Fact | Location | Consequence |
|---|---|---|
| Capacity is already workspace-scoped (`project=None` always) but stored **per member** | `apps/api/plane/workload/models.py:65-125` | Only the *grain* changes, not the scope. Endpoints/serializers/permissions can be adapted rather than invented. |
| Workdays hardcoded Mon–Fri, divisor `_WORKWEEK_DAYS = 5` | `apps/api/plane/workload/aggregation.py:126-159` | Three call sites: `_is_workday`, `_workdays_in_month`, `capacity_for_period`. |
| Week bucketing uses `d.isocalendar()` — **always Monday-start** | `apps/api/plane/workload/aggregation.py:56-58` | Ignores any preference today; must become week-start-aware. |
| Estimates spread across **calendar** days while capacity exists only on workdays — documented v1 artefact | `apps/api/plane/workload/aggregation.py:115-124` | D4 closes this. Every existing day/week bucket number changes; pure-aggregation tests must be rewritten, not patched. |
| Upstream ships a **per-user** `start_of_the_week` (default Sunday) | `apps/api/plane/db/models/user.py:252`; `packages/types/src/users.ts:15` | 8 web files read it (enumerated in Phase 5). D3 replaces all of them. |
| `ChartViewRoot` is generic over `blockIds` / `blockToRender` / `sidebarToRender` / `showToday` and exports through a barrel | `apps/web/core/components/gantt-chart/index.ts` + `chart/root.tsx:25-47` | The axis, today marker, zoom and positioning maths are reusable as-is. |
| The gantt renders a **flat** block list — no grouping/swimlane seam exists | `chart/root.tsx`, `sidebar/root.tsx`, and the issue layout's flat `blockIds` at `issues/issue-layouts/gantt/base-gantt-root.tsx:197` | Per-assignee swimlanes and the per-day capacity heat row are genuinely new work, not configuration. |
| The workload API returns aggregated buckets only — no per-issue rows | `apps/api/plane/workload/service.py:325-362` | Task bars need per-issue id/title/hours/start/target per assignee. New response shape (Phase 7). |
| There is no "overdue" concept in the workload backend | zero across `apps/api/plane/workload/**` | The screenshot's "Overdue tasks" affordance needs a new derived flag. |
| Workspace settings nav array lives in the sealed `@plane/constants` package | `packages/constants/src/settings/workspace.ts:23-74` | Cannot be edited in place. Nav entry must be appended in the consuming component `apps/web/core/components/settings/workspace/sidebar/item-categories.tsx` — same pattern as the existing `sidebar-menu-items.tsx` exception in `docs/FORK.md`. |
| `extendedRoutes` supports nested `layout()` chains | `apps/web/app/routes/extended.ts:19-25` | The settings page mounts through the `(settings)` layout chain with **no** edit to `core.ts`. |
| `ArrayField` is available (Postgres) but only used in query annotations, never as a model field | `apps/api/plane/api/views/intake.py:14` | `workdays` uses `ArrayField(PositiveSmallIntegerField())` — first model use in this codebase; noted as a deliberate choice, not precedent. |

**Search scope for absence claims:** `apps/api/plane/**`, `apps/web/**`, `apps/space/**`, `packages/**` (excluding `node_modules`). Zero workspace-scoped workload/calendar settings model exists across those paths. Zero MCP tool for capacity exists in the tool inventory exposed by the `plane` MCP server.

---

## Phases

| Phase | Name | Depends on |
|---|---|---|
| [0](phase-0.md) | Shared contract (serial, hoisted declarations) | — |
| [1](phase-1.md) | Backend: `WorkloadSettings` model + API | 0 |
| [2](phase-2.md) | Aggregation core: workdays + week-start | 0 |
| [3](phase-3.md) | Service wiring + `WorkloadCapacity` removal | 1, 2 |
| [4](phase-4.md) | Frontend: workspace settings page | 1 |
| [5](phase-5.md) | Week-start propagation to core UI | 1, 4 |
| [7](phase-7.md) | Backend: per-task payload + overdue flag | 3 |
| [8](phase-8.md) | Workload timeline UI (replaces the matrix) | 4, 7 |
| [6](phase-6.md) | Docs, FORK.md, sibling-repo propagation | 5, 8 |

Phases 1 and 2 are independent once Phase 0 pins the contract — 1 touches only Django model/API files, 2 touches only the pure `aggregation.py` + its tests. Phases 4 and 5 both touch web files but with disjoint ownership (4 = new settings page + `packages/workload-ext`; 5 = core date/calendar/gantt components).

### File → owner map (zero-overlap invariant)

| Phase | Owns |
|---|---|
| 0 | `apps/api/plane/workload/constants.py` (new), `packages/types/src/workload.ts` (new) |
| 1 | `apps/api/plane/workload/{models,serializers,views,api_views,urls,api_urls}.py`, `workload/migrations/*` |
| 2 | `apps/api/plane/workload/aggregation.py`, `workload/tests/test_aggregation_pure.py` |
| 3 | `apps/api/plane/workload/service.py`, `workload/tests/*` (non-pure), removal migration |
| 4 | `apps/web/app/(all)/[workspaceSlug]/(settings)/settings/(workspace)/workload/**` (new), `apps/web/app/routes/extended.ts`, `apps/web/core/components/settings/workspace/sidebar/item-categories.tsx`, `apps/web/core/hooks/store/use-work-settings.ts` (new) |
| 7 | `apps/api/plane/workload/service.py` (task-row emission), `workload/tests/test_task_rows.py` (new) |
| 8 | `apps/web/core/components/workload/timeline/**` (new), `apps/web/app/(all)/[workspaceSlug]/(projects)/workload/page.tsx`, `packages/workload-ext/src/**` |
| 5 | `apps/web/core/components/dropdowns/{date,date-range}.tsx`, `apps/web/core/components/gantt-chart/chart/root.tsx`, `apps/web/core/components/issues/issue-layouts/calendar/{week-days,week-header}.tsx`, `apps/web/core/store/issue/issue_calendar_view.store.ts`, `apps/web/core/components/profile/start-of-week-preference.tsx`, `apps/web/core/components/power-k/config/preferences-commands.ts` |
| 6 | `docs/FORK.md`, `CLAUDE.md`, `plans/**` |

No file appears under two phases.

**Verification bar:** every phase ends green on `python manage.py check`, `python manage.py makemigrations --check --dry-run`, the workload pytest suite, and `pnpm check`. The pytest runner needs its own Postgres per the project's backend-test isolation setup.

---

## Risk Assessment

| Risk | L | I | Score | Mitigation |
|---|---|---|---|---|
| D4 changes every existing bucket number; users see totals shift with no data change | 4 | 4 | **16** | Ship the changelog note in Phase 6 **before** deploy; add a pure-aggregation test asserting the new workday-only distribution explicitly (not a golden-file diff) so the change is intentional and reviewable. |
| Week-key format change (`YYYY-Www` → `YYYY-MM-DD`) breaks any consumer parsing the old shape | 3 | 4 | 12 | Grep every consumer (`packages/workload-ext`, MCP server, SDKs) in Phase 0 and pin the new shape in the contract; Phase 6 propagates to `plane-mcp-server` / SDKs. |
| Phase 5 touches 8 core web files — rebase conflict surface grows | 4 | 3 | 12 | Route all reads through one new `useWorkSettings()` hook so each core edit is a 1-line swap inside a `The1Studio fork (workspace work settings)` fence; register every file in the `docs/FORK.md` exception table. |
| Empty `workdays` array ⇒ divide-by-zero and every bucket reads "over" | 2 | 5 | 10 | Serializer validation rejects an empty array (min length 1); model-level check constraint as a backstop. |
| Deleting `WorkloadCapacity` discards the per-member values, which D8 no longer reads | 3 | 2 | 6 | Values are already effectively unused (one placeholder `0` row workspace-wide). The delete migration carries a working `reverse_code` recreating an empty table; the docstring states per-member values are not restorable. Capture a `SELECT * FROM workload_capacities` dump in the PR body before merging. |
| `ArrayField` is Postgres-only, first model use in this codebase | 2 | 3 | 6 | Plane is Postgres-only in every shipped compose/Docker config; noted, not mitigated further. |
| Removing the per-user week-start preference surprises users who set it | 3 | 2 | 6 | Phase 5 removes the preference UI rather than leaving a control that silently does nothing; Phase 6 changelog states the workspace admin now owns it. |
| The gantt has no grouping seam, so Phase 8 either edits `ChartViewRoot` (core, rebase surface) or reimplements grouping around it | 4 | 3 | 12 | Compose *around* the exported primitives — one chart instance, swimlanes rendered by the workload view — before considering any edit to `ChartViewRoot`. If an edit proves unavoidable, it is a fenced core exception in `docs/FORK.md`, decided in Phase 8 and not assumed now. |
| Per-task payload multiplies workload response size on a large workspace | 3 | 3 | 9 | Phase 7 caps returned tasks per assignee and reports the cap in `meta`; a truncated row is flagged, never silently trimmed (`green-that-proves-nothing.md`). |

No risk scores ≥ 15 except the bucket-shift, whose mitigation is a Phase 6 gate.

## Timeline

| Phase | Effort | Notes |
|---|---|---|
| 0: Shared contract | S (0.5d) | Serial gate — nothing starts before it lands |
| 1: Backend model + API | M (2d) | Parallel with 2 |
| 2: Aggregation core | M (2d) | Parallel with 1; heaviest test rewrite |
| 3: Service wiring + capacity removal | M (1.5d) | Blocked on 1+2 |
| 4: Workspace settings page | M (1.25d) | Blocked on 1 |
| 5: Week-start propagation | M (2d) | 8 core-file edits; blocked on 1+4 |
| 7: Per-task payload + overdue | M (2d) | Blocked on 3 |
| 8: Workload timeline UI | L (3d) | Largest piece; blocked on 4+7 |
| 6: Docs + sibling propagation | S (1d) | Blocked on 5+8 |
| **Total** | **~15.5d (122h)** | Critical path: 0 → 2 → 3 → 7 → 8 → 6 |

---

## Out of scope

- Per-project overrides of any of the three settings (`WorkloadCapacity.project` was already always `NULL`; the new model is workspace-only by design).
- Holidays / non-recurring days off.
- Dropping the core `User.start_of_the_week` column (D7).
- Retro-adjusting historical workload figures — the change is forward-looking; existing estimates re-aggregate under the new rules on next read.
- Drag-to-reschedule from the workload timeline (D14).
- Keeping the aggregate table behind a toggle (D11).

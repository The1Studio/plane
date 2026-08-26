# Workload timeline — colour bars by work-item state

**Status:** planned · **Branch base:** `company-main` · **Fork app:** `workload` (already in `forkApps`)

## Goal

In the workspace Workload timeline (`/:workspaceSlug/workload`), a work-item bar is
painted with **its state's own colour**, exactly as core's Timeline (gantt) layout paints
an issue block. Today the bar's fill encodes *load semantics* instead — accent blue for
normal, `bg-danger-subtle` for overdue — which tells the reader nothing about where the
item actually is in the workflow.

**Parity target.** `IssueGanttBlock` (`apps/web/core/components/issues/issue-layouts/gantt/blocks.tsx:53-56`)
resolves the issue's state via `useProjectState().getProjectStates(project_id)` and hands
`stateDetails.color` to `getBlockViewDetails`, which sets `style.backgroundColor` and lays a
`bg-surface-1/50` overlay over it. We copy that **technique**, not that data path — see D2.

## Decisions (resolved, not open)

| # | Decision | Resolution |
|---|---|---|
| **D1** | Colour source | **Exact per-state colour.** `tasks[]` gains `state_name` / `state_color` from the API. A custom "QA" state keeps its own hue; the five-group palette would have collapsed two custom `started` states into one indistinguishable amber. |
| **D2** | Where the colour is resolved | **Server-side, on the task row** — not via `useProjectState`. The workload page is workspace-scoped and routinely mixes projects in one swimlane; `getProjectStates(project_id)` returns `undefined` for any project whose states the store has not fetched, and nothing on this route fetches them. Reading the colour off the row we already fetch is one JOIN we already pay for (`issue__state__group` joins `state` today) and removes a whole class of "bar is transparent because the store was cold" bugs. |
| **D3** | Precedence vs `overdue` | **State fill always wins; the overdue colour is dropped.** The fill is the state, full stop. Overdue survives in the hover tooltip, which already appends `· overdue`. Rationale: an overdue bar and a cancelled bar were both flat red, which is exactly the ambiguity this change exists to remove. |
| **D4** | Precedence vs `unscheduled` | **Dashed outline survives, tinted by state.** Dashed-and-unfilled is the signal that the bar is a *placeholder occupying a column*, not a span covering it. It stays dashed and unfilled; only its border colour moves from flat `border-tertiary` to the state colour. |
| **D5** | Scope | Timeline task bars **and** unscheduled placeholder bars. **Not** the capacity heat cells (they measure aggregate load across many items — no single state exists to colour them by; they keep `heatCellColorClass`'s under/at/over thresholds). **Not** the spreadsheet Progress column. |
| **D6** | Contrast on an arbitrary colour | **Copy core's overlay, do not compute contrast.** `State.color` is a free `CharField(max_length=255)` — it is not guaranteed to be `#rrggbb`, so string-slicing an alpha suffix onto it (`#f59e0b` + `26`) breaks on `#fa0`, `rgb(...)`, or an empty string. Core's answer is a full-opacity `backgroundColor` under a `bg-surface-1/50` overlay div, which is format-agnostic and needs no parsing. We use the same. |
| **D7** | Colour with no legend | The bar's `title` gains the **state name**. An exact-colour bar with no way to read the colour is a regression in legibility, not a feature; the tooltip is the cheapest legend and the file already treats it as the canonical home for what the bar cannot show (see the `isWeek` comment block). No separate legend UI. |
| **D9** | Field surface | **Only what the UI uses: `state_name` + `state_color`.** `state_id` is deliberately NOT added. Every field here is a permanent contract propagated to the MCP docstring and both SDKs, and an unused one is a field nobody can later remove. `state_group` already covers grouping. Add `state_id` when a consumer actually needs a durable join key — not before. |
| **D8** | Fallback when `state_color` is empty/absent | `stateBarColor()` falls back to the `STATE_GROUPS[state_group].color` from `@plane/constants`, then to the current accent. Covers a stale client against a new server, a blank `color` column, and the `triage` group (excluded by `_base_queryset`, so unreachable in practice — the fallback is a guard, not a path). |

## Prior art — what already exists

Searched `apps/api/plane/workload/`, `apps/web/core/components/workload/`,
`packages/workload-ext/`, `apps/web/core/components/issues/issue-layouts/`,
`packages/constants/src/state.ts`, and the four sibling clones under `~/Projects/`.

| Thing | Status | Where |
|---|---|---|
| `state_group` on each task row | **Exists** — already selected and emitted | `service.py:416,458,548`; `TWorkloadTask.state_group` |
| `state` JOIN in the workload query | **Exists** — `issue__state__group` already forces it | `service.py:416` |
| `State.color` column | **Exists** — `CharField(max_length=255)` | `apps/api/plane/db/models/state.py:82` |
| Five-group colour palette | **Exists** — `STATE_GROUPS[*].color` | `packages/constants/src/state.ts:21-52` |
| State-coloured gantt block (the parity target) | **Exists** in core, untouched by this plan | `issue-layouts/gantt/blocks.tsx`, `issue-layouts/utils.tsx:683` |
| State-group filter on the workload toolbar | **Exists** — unrelated to fill colour, not touched | `components/workload/StateGroupDropdown.tsx` |
| `state_name` / `state_color` on a workload task | **Absent** across all five paths above — this is the new surface |
| A hex→rgba helper in `@plane/utils` | **Absent** (`zero across packages/utils/src/*.ts`) — which is why D6 copies core's overlay instead |
| `tasks[]` modelled in the Node SDK | **Absent** — `WorkloadMatrixRow` declares only `assignee_id`/`assignee_name`/`buckets`/`total` (`plane-node-sdk/src/models/Workload.ts:49-55`) |
| `tasks[]` modelled in the Python SDK | **Absent** — no `WorkloadMatrixRow` class; `WorkloadMatrixResponse` is `extra="allow"` |
| `tasks[]` field list in the MCP tool | **Exists as prose** — `plane-mcp-server/plane_mcp/tools/workload.py:123-126` enumerates every field and **will go stale** |

## Phases

### Phase 1 — API: carry the state's identity on each task row (serial)

**Owns:** `apps/api/plane/workload/service.py`, `apps/api/plane/workload/tests/test_task_rows.py`

1. `service.py` — add two columns to the existing `qs.values_list(...)` (`~:405-417`):
   `issue__state__name` and `issue__state__color`. The `state` table is **already** joined
   for `issue__state__group`, so both ride that JOIN and add no query. Do NOT add
   `issue__state_id` (D9).
2. Extend the tuple unpack at `~:450-461` in the same order.
3. Add to the task dict at `~:534-552`: `"state_name": state_name or ""` and
   `"state_color": state_color or ""`. Normalise `None` → `""` so the client's fallback
   (D8) has one shape to test, not two.
4. Tests in `test_task_rows.py`:
   - extend `test_task_row_fields_and_assignee_scoping` to assert the two new fields
     against a state fixture with an explicit non-default `color`;
   - a new test pinning the **fallback shape**: a state whose `color` is `""` emits
     `""`, never `None`;
   - **re-run `test_task_detail_columns_add_no_extra_queries_per_issue` unchanged.** It
     wraps `CaptureQueriesContext` and is the gate that proves claim (1). If it goes red,
     the JOIN assumption is wrong and the phase is not done.

**Verify:** `pytest apps/api/plane/workload/tests/test_task_rows.py -q` green, including the
query-count test. Backend runner setup: see the `backend-test-db-isolation` memory (interpreter
pin, pgvector, per-runner Postgres).

**Est: 1.5h**

---

### Phase 2 — Package: types + the colour resolver (serial, depends on P1's field names)

**Owns:** `packages/workload-ext/src/types.ts`, `packages/workload-ext/src/stateColor.ts` (new),
`packages/workload-ext/src/index.ts`, `packages/workload-ext/src/__tests__/stateColor.test.ts` (new)

1. `TWorkloadTask` gains `state_name: string` and `state_color: string`.
   Document on the type that `state_color` is a **free-form CSS colour string**, not a
   guaranteed hex — that is the fact D6 and D8 both hang off.
2. New `stateColor.ts` exporting `stateBarColor(task: Pick<TWorkloadTask, "state_color" | "state_group">): string`
   implementing D8's three-step fallback. Kept out of the component so it is unit-testable
   without a DOM, matching `barLabel.ts`/`progress.ts`'s existing shape in this package.
3. Export from `index.ts`.
4. Unit tests: a real colour passes through; `""` falls back to the group colour; an unknown
   `state_group` falls back to the accent; each of the five known groups maps to its
   `STATE_GROUPS` colour.

**No store change required.** `store.ts:414-425`'s optimistic date mapper already spreads
`...task`, so the two new fields survive a drag/resize round-trip untouched — but assert
that rather than assume it: after P3, drag a bar and confirm the colour does not flicker.

**Est: 1.5h**

---

### Phase 3 — Render: paint the bars (serial, depends on P2)

**Owns:** `apps/web/core/components/workload/timeline/WorkloadTimelineChartBlock.tsx`

1. In `WorkloadTaskBar`, replace the three-branch fill `cn(...)` (`unscheduled` / `task.overdue` /
   default accent) with:
   - **scheduled:** `style={{ backgroundColor: stateBarColor(task) }}` on the content div,
     plus an absolutely-positioned `bg-surface-1/50` overlay child, plus `text-primary` —
     the exact composite `IssueGanttBlock` uses. The overlay must sit **under** the label
     spans in DOM order so the text is not washed out.
   - **unscheduled:** keep `border border-dashed bg-transparent`, move the border colour to
     `style={{ borderColor: stateBarColor(task) }}` and drop `border-tertiary`. No overlay
     (there is no fill to lighten).
   - **overdue:** no colour branch at all (D3).
2. `title` gains the state name (D7), placed after the identifier+name and before the hours:
   `` `${task.identifier} ${task.name} · ${task.state_name} · ${task.hours}h…` ``. The existing
   `· overdue`, `· split N ways` and unscheduled-disclaimer suffixes are unchanged.
3. **Update the load-bearing comments.** This file documents its own colour decisions in
   prose (the `unscheduled ? … : task.overdue ? …` block carries a five-line rationale for
   the dashed outline and an explicit "there is no red branch to reach here"). Those
   comments become wrong the moment the branch changes. Rewrite them to state the new rule
   and *why overdue no longer has a colour* — a future reader finding no red branch must
   not conclude it was lost in a rebase.
4. `hoverBg` — the existing `hover:bg-accent-primary/25` has no equivalent over an arbitrary
   colour. Replace with a hover on the overlay's opacity (`group-hover:bg-surface-1/40`),
   which lightens-less on hover and works for any hue.

**Verify:** `pnpm check` clean, then visually in the running app at all three zooms (Week /
Month / Quarter): a started, a completed, a cancelled, a backlog, an overdue, and an
unscheduled bar. Per `observable-gameplay.md`'s console-closed test — the state must be
readable from the screen, not from the network tab.

**Est: 2h**

---

### Phase 4 — Docs + downstream propagation (serial, depends on P1)

**Owns:** `docs/FORK.md`, `CLAUDE.md`, and sibling-repo PRs

1. `docs/FORK.md` § workload — record the two new `tasks[]` fields and D3's dropped
   overdue colour, since "overdue is red" is currently documented behaviour.
2. `CLAUDE.md` "Custom features" `workload/` entry — same, in one clause. Note explicitly
   that **the bar fill is the state colour and overdue is tooltip-only**, so the next reader
   does not re-add a red branch.
3. **`plane-mcp-server`** — `plane_mcp/tools/workload.py:123-126` enumerates the `tasks[]`
   fields in the `get_workload` docstring. Add the two. This is a **required** PR: the
   docstring is the tool's contract as an LLM sees it, and a stale enumeration is worse
   than none.
4. **`plane-node-sdk` / `plane-python-sdk`** — **verify, then most likely no change.**
   Neither models `tasks[]` (see the prior-art table); Node's `WorkloadMatrixRow` stops at
   `total` and Python's response model is `extra="allow"`, so both already pass the new
   fields through untyped. Confirm that against the clones before concluding it; if either
   has gained a task model since, add the fields there too.
5. Open one PR per sibling repo that actually needs a change — never edit a sibling from this
   repo's PR (`plane-fork-discipline.md`). Use the `plane-propagate` skill.

**Est: 1.5h**

---

## Non-goals

- A colour legend UI in the toolbar (D7 — the tooltip is the legend).
- Colouring the capacity heat cells (D5).
- The spreadsheet Progress / Estimated-hours columns (D5).
- Any change to `StateGroupDropdown` or the state-group **filter** — filtering and fill
  colour are independent.
- Fetching project states client-side (D2 rules this out).

## Risk Assessment

| Risk | L | I | Score | Mitigation |
|---|---|---|---|---|
| Losing the overdue signal makes slipping work invisible on the board | 3 | 4 | **12** | D3 is the user's explicit decision. Tooltip retains `· overdue`; if it proves too weak in use, the follow-up is a red ring (the option not taken), not a re-added red fill. |
| A state colour with poor contrast against the surface makes the label unreadable | 3 | 3 | 9 | D6's `bg-surface-1/50` overlay + `text-primary` is core's own answer and is already proven across every Timeline board in the product. |
| `State.color` holds a non-CSS value and the bar renders transparent | 2 | 3 | 6 | D8's fallback chain; React drops an invalid `backgroundColor` silently, so the fallback is what stands between that and an invisible bar. Pinned by a unit test. |
| The new `.values_list` columns add a query per issue | 2 | 4 | 8 | `state` is already joined for `state_group`; `test_task_detail_columns_add_no_extra_queries_per_issue` is the gate, not the assumption. |
| The MCP docstring drifts and an LLM consumer builds against a stale field list | 3 | 2 | 6 | Phase 4 step 3 is a required PR, not a tracking issue (`plane-sibling-forks-get-fix-prs` memory). |
| Comments in `WorkloadTimelineChartBlock.tsx` still describe the old colour rule | 3 | 2 | 6 | Phase 3 step 3 makes the comment rewrite part of the phase's definition of done, not a follow-up. |

## Timeline

| Phase | Effort | Notes |
|---|---|---|
| 1 — API state fields | S (1.5h) | Blocks 2 and 4 |
| 2 — Package types + resolver | S (1.5h) | Blocks 3 |
| 3 — Render | S (2h) | Depends on 2 |
| 4 — Docs + propagation | S (1.5h) | Depends on 1; sibling PRs are independent of 2/3 |
| **Total** | **6.5h** | Critical path: 1 → 2 → 3 |

Strictly serial — every phase depends on the one before it, so there is no parallel-safe
decomposition to declare and no worktree split. Phase 4's sibling PRs are the only work
that could overlap phase 2/3, and they live in different repos entirely.

## Verification gate (all phases)

- `pytest apps/api/plane/workload/tests/ -q` — green, query-count test included
- `pnpm --filter @plane/workload-ext test` — green
- `pnpm check` — clean
- `python manage.py makemigrations --check --dry-run` — **no migration expected**; this
  change adds no column to any model. A migration appearing here means something went wrong.
- Console-closed visual pass at Week / Month / Quarter across six bar variants

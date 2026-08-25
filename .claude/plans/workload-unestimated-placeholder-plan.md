# Workload timeline — show unestimated work items as dashed placeholders

**Status:** planned · **Mode:** default (no flags) · **Branch base:** `company-main`
**Fork surface:** `apps/api/plane/workload/` + `packages/workload-ext/` +
`apps/web/core/components/workload/timeline/` — no core model, no migration, no new touch-point.

Today the workload timeline can only see work carrying a `WorkloadEstimate` row with `hours > 0`.
`service.py:_base_queryset` starts from `WorkloadEstimate`, so a work item with no estimate row
never joins the query at all, and a stored `hours = 0` row is filtered out and tallied only into
`meta.zero_estimate_count`, which nothing in the UI reads. The result is that a member with no
assigned work and a member whose every item is unestimated render identically: an empty swimlane
at full capacity.

This plan makes unestimated work visible as a dashed placeholder bar, so the timeline answers
"what still needs estimating" as well as "who is loaded".

---

## Dependency — this plan rebases onto `feat/workload-state-color`

`.claude/plans/workload-state-color-plan.md` is in flight in a worktree on branch
`feat/workload-state-color`, and `CLAUDE.md` already documents it as landed. It changes the exact
two regions this plan edits:

| Its change                                                                                                                  | Consequence here                                                                                |
| --------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| `tasks[]` gains `state_name` + `state_color`; `values_list` and the tuple unpack at `service.py:~405-461` both grow         | This plan's Phase 1.4 edits the same lines. **Textual conflict, guaranteed.**                   |
| **D3 — the overdue colour is dropped.** A bar's fill is its state's colour; overdue survives only in the hover title        | This plan must **not** introduce any red/danger styling for an overdue unestimated bar          |
| **D4 — a dashed placeholder stays dashed and unfilled; only its border colour moves to the state colour** (`stateBarColor`) | This plan inherits that treatment verbatim rather than inventing a second dashed-bar convention |

**Sequencing: land `feat/workload-state-color` first, then start Phase 1 here.** Running them in
parallel means two lanes editing one `values_list` and one style branch — the exact shared-shape
collision that belongs in a serial phase, not a fan-out. Every reference below assumes
state-colour is merged.

---

## Prior art — what already exists (searched scope stated)

Confirmed by reading each file named, not assumed:

| Capability                                             | Where it already lives                                                                                                                | Reused as-is?                                                                                                      |
| ------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| Dashed / unfilled placeholder bar, state-tinted border | `WorkloadTimelineChartBlock.tsx` `unscheduled` branch + `stateBarColor` (post state-colour)                                           | Yes — extended, not re-invented                                                                                    |
| Placeholder lane packing + per-swimlane cap            | `packages/workload-ext/src/merge.ts:213` `MAX_UNSCHEDULED_LANES`, `selectUnscheduledTasks`                                            | Yes — its predicate is `!task.target_date`, which already routes undated unestimated items once they reach `tasks` |
| Anchor column for a dateless bar                       | `merge.ts:unscheduledAnchorDate` (`start_date ?? today`)                                                                              | Yes                                                                                                                |
| Drag/resize of a dateless bar                          | `WorkloadTimelineChartBlock.tsx:420-455` synthetic one-day task → `useTaskBarDrag`                                                    | Yes                                                                                                                |
| Span packing for dated bars                            | `merge.ts:packTasksIntoLanes`                                                                                                         | Yes — called a second time on a disjoint task set                                                                  |
| Label size ladder (never clip a number)                | `packages/workload-ext/src/barLabel.ts` `hoursLabelStep`, `BAR_LABEL_STEPS`                                                           | Yes — `"?"` is measured by the same ladder, unchanged                                                              |
| Per-swimlane count strip                               | `WorkloadTimelineSidebarRow.tsx` footer branch (`Unscheduled (N more)`, `Overdue (N)`, truncation)                                    | Yes — one more count joins it                                                                                      |
| Leaf-only / countable-issue predicates                 | `rollup.py:countable_issue_q`, `rollup.py:has_countable_children`                                                                     | Yes — the new query uses both                                                                                      |
| Fork-owned i18n table                                  | `packages/workload-ext/src/i18n.ts` `WORKLOAD_STRINGS` / `wlt`                                                                        | Yes                                                                                                                |
| FK index backing the anti-joins                        | `Issue.parent` is a `ForeignKey` (Django indexes FK columns by default); `WorkloadEstimate.issue` is a `OneToOneField` (unique index) | Yes — **no new index, therefore no migration**                                                                     |

**Absent — zero across `apps/api/plane/workload/`, `packages/workload-ext/src/`,
`apps/web/core/components/workload/`:** any query over `Issue` not routed through
`WorkloadEstimate`; any `unestimated` field, flag, or string; any second `packTasksIntoLanes` call
site; any block kind beyond `header` / `unscheduled` / `lane` / `footer`. `matrix.no_target_date`
exists in `i18n.ts` but has **no call site** — the aggregate matrix it belonged to is gone, so the
swimlane footer is the only live surface that reports unscheduled counts to a reader.

---

## Resolved decisions

| #   | Decision                                                                                                                                                                                                                                                       | Consequence                                                                                                                                                                                                                |
| --- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| D1  | **Scope = all countable assigned items with no usable estimate.** No `WorkloadEstimate` row, or one with `hours <= 0`. Dated or not, it appears.                                                                                                               | The new query runs over `Issue`, a far larger table than `WorkloadEstimate`. Volume control is D4; cost is gated by Phase 1.0                                                                                              |
| D2  | **A dated unestimated item is drawn as a dashed bar across its real `[start_date, target_date]` span, labelled `?`** where a solid bar shows `4h`.                                                                                                             | Needs a second `packTasksIntoLanes` pass, not the placeholder path. Its dates are preserved, so drag/resize work unchanged                                                                                                 |
| D3  | **Always on.** No toolbar toggle, no persisted state.                                                                                                                                                                                                          | A workspace mid-migration sees many dashed bars with no way to quiet them. Accepted                                                                                                                                        |
| D4  | **Shares the existing per-assignee cap** (`WORKLOAD_MAX_TASKS_PER_ASSIGNEE = 200`) and the existing `ROW_GUARD = 50_000` budget. Unestimated tasks **sort first** in `_task_sort_key` and render **above** the estimated lanes, as unscheduled bars already do | Unestimated work survives truncation ahead of estimated work and takes the three `MAX_UNSCHEDULED_LANES` slots first. That ordering is the feature's point — an unestimated item is the one needing attention — but see R2 |
| D5  | **The cost gate is a blocking sub-step at the start of Phase 1**, before any row-assembly code is written                                                                                                                                                      | Half a day up front. If the measured cost fails the bar, scope is re-decided with the user rather than built on                                                                                                            |
| D6  | **`meta.issues_unestimated` is kept AND rendered.** The count appears in the swimlane footer strip beside `Unscheduled (N more)` — the only live surface reporting unscheduled counts                                                                          | The footer count is **per row**, computed from `row.tasks` the way `overdueCount` already is; `meta.issues_unestimated` stays the workspace-wide figure for API/MCP consumers and the empty-state copy                     |

Decided as part of the design rather than left implicit:

- **An overdue unestimated bar gets no colour of its own.** It stays dashed, state-tinted, and
  reports lateness only in the hover title, per state-colour D3 ("do not re-add a red fill"). An
  undated unestimated item is never overdue anyway — the API requires a non-null target for that
  flag.
- **Dropping an unestimated bar onto a date does not make it solid.** It writes dates and becomes
  a dated dashed bar. Only an estimate turns a bar solid. This differs from an estimated-unscheduled
  bar, which does turn solid on drop, and the difference is the point: the bar is still telling you
  something is missing.
- **Capacity arithmetic does not change at all.** An unestimated item contributes nothing to
  `buckets`, `month_buckets`, `capacity_buckets`, `unscheduled`, `over`, or `total_over`. The
  capacity badge reads the same number before and after this change — Phase 4.4 proves it.
- **`meta.zero_estimate_count` keeps its current meaning** (stored rows with `hours <= 0`). Those
  items are now also counted in `meta.issues_unestimated`, which is the union of "no row" and
  "zero row". The two deliberately overlap; `issues_unestimated` is the superset.
- **Out of scope:** the spreadsheet "Estimated hours" column, the peek panel, the sidebar, and the
  capacity heat cells. This plan touches the timeline's task bars only.

---

## Integration contract (pinned — every phase codes against this verbatim)

SSOT for the TypeScript half is `packages/workload-ext/src/types.ts`; the Python half assembles the
same shape in `apps/api/plane/workload/service.py`.

```
TWorkloadTask += {
  /** True when the item has no WorkloadEstimate row, or one with hours <= 0. */
  unestimated: boolean;   // ALWAYS present — false on every estimated row, never omitted
}

TWorkloadMeta += {
  /** Countable, in-scope work items with no usable estimate. Superset of zero_estimate_count. */
  issues_unestimated: number;
}
```

Field-level rules, both sides:

- `unestimated` is a **boolean, always emitted** — never `null`, never absent. It is not inferable
  from `hours === 0`: a stored zero-hour estimate makes that test ambiguous, which is exactly why
  the flag exists.
- On an unestimated task row: `hours = 0`, `total_hours = 0`, `assignee_count` = the real owner
  count, and `identifier` / `project_id` / `state_group` / `state_name` / `state_color` /
  `start_date` / `target_date` / `overdue` exactly as for any other task.
- `overdue` follows the existing rule unchanged: `target_date` in the past **and** a non-terminal
  state group.
- `rows[].total`, `rows[].buckets`, `rows[].month_buckets`, `rows[].capacity_buckets`,
  `rows[].over`, `rows[].total_over`, and the top-level `unscheduled[]` list are **unchanged** by
  unestimated items.
- `meta.issues_counted` and `meta.issues_unscheduled` keep counting **estimated** items only — they
  describe hours, and an unestimated item has none.

---

## Phase 1 — Backend: surface unestimated work items (M, ~3d incl. the gate)

**Owns:** `apps/api/plane/workload/service.py`,
`apps/api/plane/workload/tests/test_unestimated.py`

### 1.0 Cost gate — BLOCKING, before any assembly code (D5)

R1 is the one risk that can force a redesign, so it is measured first, not last.

1. Build the `_unestimated_queryset` from 1.2 in a shell against the real workspace and run
   `EXPLAIN (ANALYZE, BUFFERS)` on it, unfiltered (worst case: no project filter, no state filter).
2. Record: row count, planning + execution time, and whether the `Exists` anti-join and
   `~has_countable_children` use index scans. Both index paths already exist (`Issue.parent` FK,
   `WorkloadEstimate.issue` unique) — the gate is confirming the planner **uses** them, not adding
   them. Any plan that would need a new index on a **core** model is a stop: `docs/FORK.md` forbids
   editing `db/migrations/`, so that outcome means re-scoping, not migrating.
3. Compare against the current `_base_queryset` timing on the same workspace and state the ratio.
4. **Gate:** if the combined endpoint p95 regresses beyond what the user accepts, STOP and
   re-decide D1 with them (the recorded narrower branch is dated-items-only). Do not proceed on a
   silent assumption that it is fine.

### 1.1 Generalise the scope filter

`_scope_filter(project_scope, restricted, user)` (`service.py:176`) builds
`Q(project_id__in=...)` and `Q(project_id__in=restricted, issue_id__in=own_issue_ids)`. Those
field names are right for a `WorkloadEstimate` queryset, where `project_id` and `issue_id` are real
columns. On an `Issue` queryset the issue key is `id`, not `issue_id`.

Add an `issue_field="issue_id"` keyword and interpolate it
(`Q(**{f"{issue_field}__in": own_issue_ids})`). The existing call site passes nothing and is
byte-for-byte unchanged; the new call passes `issue_field="id"`. **Do not duplicate the guest
logic** — a second copy of the flag-off-guest rule is exactly the drift that function's docstring
exists to prevent.

### 1.2 The unestimated queryset

```python
def _unestimated_queryset(slug, scope_q_issue, state_groups):
    """Countable, leaf-only issues in scope carrying no usable estimate."""
    from .rollup import countable_issue_q, has_countable_children

    qs = (
        Issue.objects.filter(scope_q_issue, workspace__slug=slug)
        .filter(countable_issue_q())            # deleted / archived / draft / non-countable state
        .exclude(state__group=StateGroup.TRIAGE.value)
        .filter(~has_countable_children("pk"))  # leaf-only, same rule as _base_queryset
        .filter(
            ~Exists(
                WorkloadEstimate.objects.filter(
                    issue_id=OuterRef("pk"), workspace__slug=slug, hours__gt=0
                )
            )
        )
    )
    if state_groups:
        qs = qs.filter(state__group__in=state_groups)
    return qs
```

Four things this must get right, each a real defect if missed:

1. **`Exists` subquery, not `.exclude(id__in=issue_ids)`.** `est_rows` can hold up to `ROW_GUARD`
   ids; handing that list to the database as an `IN` is a different failure mode at scale.
2. **Leaf-only via the same helper.** Without `~has_countable_children("pk")`, a parent whose
   children carry the estimates renders as an unestimated dashed bar — contradicting the rollup the
   sidebar shows for that same item.
3. **`countable_issue_q()` rather than a hand-written filter.** It expresses the null-state OR as an
   explicit `Q` so Django LEFT JOINs `state`; a negated `IN` on an INNER JOIN silently drops
   state-less issues.
4. **`state_groups` applied identically** to the estimated path, including the no-filter case
   meaning _every_ group — see `_base_queryset`'s comment on why an implicit exclusion there was a
   bug the toolbar could neither show nor clear.

### 1.3 Row guard

The guard at `service.py:399` becomes one budget across both queries:

```python
if qs.count() + unest_qs.count() > ROW_GUARD:
    raise WorkloadTooLarge()
```

One ceiling, not two — a request is refused on total rows loaded, which is what memory actually
tracks.

### 1.4 Task assembly

Fetch the same tuple shape as `est_rows` minus `hours`, **including the state-colour fields that
branch added**:

```python
unest_rows = list(
    unest_qs.values_list(
        "id", "start_date", "target_date", "name", "sequence_id",
        "project_id", "project__identifier",
        "state__group", "state__name", "state__color",
    )
)
```

Resolve owners for **both** id sets in one `_resolve_owners` call — it is one query, and two calls
would be two. Then a second loop mirroring the estimated loop's owner-split and `assignee_filter`
handling, but:

- calls **no** `spread_estimate` — there are no cents to spread;
- writes **nothing** to `buckets`, `month_buckets`, or `unscheduled`;
- appends to `tasks_by_owner` with `hours: 0.0`, `total_hours: 0.0`, `unestimated: True`, and
  `state_name` / `state_color` normalised `None → ""` exactly as the estimated branch does;
- has **no window filter.** An estimated item whose span falls outside `[date_from, date_to]` is
  dropped from `tasks` because it has no bucket to justify a row; an unestimated item has no buckets
  at all, so that same test would drop every one of them. Window clipping happens client-side, where
  a bar is positioned by absolute date inside a whole-window lane box;
- increments `meta["issues_unestimated"]` once per **issue**, not once per owner.

Set `"unestimated": False` explicitly on the estimated branch's task dict. Absent is not false.

### 1.5 Sort and row union

- `_task_sort_key` gains a leading term so unestimated sorts first:
  `(not task["unestimated"], start is None, start or "", target is None, target or "")`.
  Rewrite its docstring — the current reasoning ("an unscheduled/no-start task is exactly the kind
  of row a 200-task cap should drop first") is now only half true and would read as contradicted by
  the code beneath it.
- `owner_ids` (`service.py:581`) unions in `set(tasks_by_owner.keys())`. Without it the
  **Unassigned** row disappears whenever the only unassigned work is unestimated: `scope_members`
  contributes member ids only, never `None`, and `None` reached `owner_ids` solely through
  `buckets` / `unscheduled` / `month_buckets` — none of which an unestimated item writes to.

### 1.6 Tests — `apps/api/plane/workload/tests/test_unestimated.py`

| Test                                                     | Asserts                                                                                                                     |
| -------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `test_no_estimate_row_appears_as_unestimated_task`       | dated issue, no estimate → one task, `unestimated=True`, `hours=0`, dates preserved                                         |
| `test_zero_hour_estimate_appears_as_unestimated`         | stored `hours=0` → same, and still counted in `zero_estimate_count`                                                         |
| `test_estimated_rows_carry_unestimated_false`            | the key is present and `False`, never absent (contract R5)                                                                  |
| `test_unestimated_contributes_no_hours`                  | `buckets`, `month_buckets`, `total`, `unscheduled[]`, `over`, `total_over` identical to a run without the unestimated issue |
| `test_undated_unestimated_has_null_target`               | reaches `tasks` with `target_date=None` — the client's placeholder predicate                                                |
| `test_parent_with_countable_children_is_not_unestimated` | leaf-only rule holds                                                                                                        |
| `test_archived_draft_triage_excluded`                    | `countable_issue_q` + triage exclusion hold                                                                                 |
| `test_state_group_filter_applies`                        | a filtered request excludes out-of-group unestimated items                                                                  |
| `test_guest_restricted_scope`                            | a flag-off guest sees only their own unestimated items (the `issue_field="id"` path)                                        |
| `test_unassigned_row_exists_for_unestimated_only`        | the `owner_ids` union fix                                                                                                   |
| `test_sorted_first_and_shares_cap`                       | unestimated rows lead `tasks`, and the total is still capped at 200                                                         |
| `test_row_guard_counts_both_querysets`                   | a combined count over `ROW_GUARD` raises `WorkloadTooLarge`                                                                 |
| `test_meta_issues_unestimated_counts_issues_not_owners`  | a two-assignee unestimated issue increments the counter once                                                                |

Re-run `test_task_detail_columns_add_no_extra_queries_per_issue` unchanged — the second
`values_list` must not reintroduce a per-issue query.

**Verify:** `pytest apps/api/plane/workload/tests -q` (per the local backend-test setup: pinned
interpreter, pgvector, Redis, one Postgres per runner).

---

## Phase 2 — Shared package: types and lane split (S, ~1d)

**Owns:** `packages/workload-ext/src/types.ts`, `packages/workload-ext/src/merge.ts`,
`packages/workload-ext/src/i18n.ts`, `packages/workload-ext/src/__tests__/unestimated.test.ts`

1. **`types.ts`** — add `unestimated: boolean` to `TWorkloadTask` and `issues_unestimated: number`
   to `TWorkloadMeta`, each with a docstring stating the contract above (in particular: not
   inferable from `hours === 0`).
2. **`merge.ts`** — one pure helper beside `selectUnscheduledTasks`:

   ```ts
   export function splitByEstimate(tasks: TWorkloadTask[]): {
     estimated: TWorkloadTask[];
     unestimated: TWorkloadTask[];
   };
   ```

   It filters (returning new arrays, never mutating the store's response object — the same reason
   `packTasksIntoLanes` and `selectUnscheduledTasks` filter first) and preserves server order.
   **`selectUnscheduledTasks` is not touched.** Its `!task.target_date` predicate already routes
   undated unestimated items into the placeholder lanes, and the two must remain exact complements
   of `packTasksIntoLanes` or work vanishes from the board entirely.

3. **`i18n.ts`** — three keys:
   - `"timeline.unestimated_label": "?"` — the bar label as a string, not a literal in JSX;
   - `"timeline.unestimated_bar_title": "No estimate — this item adds nothing to the capacity row above."`
   - `"timeline.unestimated_count": "Unestimated ({count})"` — the footer strip entry.
4. **Tests** — `splitByEstimate` partitions exactly, preserves order, and its two outputs re-union
   to the input; an undated unestimated task is selected by `selectUnscheduledTasks` (the
   complement property asserted directly, not assumed).

**Verify:** `pnpm --filter @plane/workload-ext test`.

---

## Phase 3 — Timeline rendering (S, ~1d)

**Owns:** `apps/web/core/components/workload/timeline/blocks.ts`,
`.../types.ts`, `.../WorkloadTimelineChartBlock.tsx`, `.../WorkloadTimelineSidebarRow.tsx`,
`.../WorkloadTimelineRoot.tsx` (comment only)

### 3.1 Block order (`blocks.ts`)

Per expanded swimlane, in order:

```
header                      capacity heat row                    (unchanged)
unscheduled x0..3           placeholders, no target_date         (unchanged code path — now
                                                                  also carries unestimated items)
wl-lane-unest:<key>:<n>     NEW — dashed bars across real spans
lane x1..n                  estimated bars                       (unchanged)
footer                      count strip                          (one new entry, 3.3)
```

Implementation: after the existing `selectUnscheduledTasks` block, call `splitByEstimate(row.tasks)`,
then `packTasksIntoLanes(unestimated)` and `packTasksIntoLanes(estimated)` — replacing the single
current `packTasksIntoLanes(row.tasks)` call. Emit the unestimated lanes with id prefix
`wl-lane-unest:` and `kind: "lane"`. **No new block kind:** a lane block already renders one
`WorkloadTaskBar` per task, and the bar reads `task.unestimated` itself.

The `lanesToRender = lanes.length > 0 ? lanes : [[]]` empty-lane fallback stays on the **estimated**
lane set only. It exists to guarantee a click-to-create surface (I1); the unestimated group emits
nothing when empty, so a member with no unestimated work gains no extra row.

`WorkloadTimelineSidebarRow`'s `lane` branch already renders an empty `SidebarCell` spacer, so the
new lanes stay aligned with no sidebar change — do not add a label (`CLAUDE.md`: lane rows carry
none by design).

### 3.2 Bar rendering (`WorkloadTimelineChartBlock.tsx`)

- `const hoursLabel = task.unestimated ? wlt("timeline.unestimated_label") : `${task.hours}h`;`
  `hoursLabelStep(width, hoursLabel)` then measures `"?"`, which is narrow enough to survive to the
  `small` step where `10.75h` is already `hidden`. **`barLabel.ts` is unchanged.**
- Styling — inherits state-colour D4 exactly, with **no new colour of its own**:

  | Condition                     | Treatment                                                               |
  | ----------------------------- | ----------------------------------------------------------------------- |
  | `unscheduled` (existing prop) | dashed, unfilled, border tinted by `stateBarColor(task)` — unchanged    |
  | `task.unestimated`            | **same** dashed/unfilled/state-tinted treatment                         |
  | else                          | solid state-colour fill under the `bg-surface-1/50` overlay — unchanged |

  There is deliberately **no overdue branch**: state-colour D3 removed the red fill, and re-adding
  one here for unestimated bars would resurrect exactly the ambiguity that decision existed to
  remove. Overdue stays in the hover title.

- Tooltip: append `wlt("timeline.unestimated_bar_title")` when `task.unestimated`, alongside the
  existing shared-assignee, unscheduled, overdue, and state-name entries. This is the only place a
  reader learns why a dashed bar sits over a capacity cell that does not count it.
- Extend the comment block above the style branch rather than replacing it — its statement that an
  unscheduled task is never overdue is still true of that branch and must not read as contradicted.
- The `kind: "unscheduled"` synthetic-task branch is untouched: `{...data.task}` already carries
  `unestimated` through to the bar.

### 3.3 Footer count (`WorkloadTimelineSidebarRow.tsx`) — D6

Add one entry to the footer strip, beside `Unscheduled (N more)`:

```tsx
{
  unestimatedCount > 0 && <span>{wlt("timeline.unestimated_count", { count: unestimatedCount })}</span>;
}
```

computed per row as `row.tasks.filter((t) => t.unestimated).length` — the same way `overdueCount`
already is, and for the same reason: it is a property of the tasks, not of a lane cap. Unlike
`unscheduledHidden` this is the **total**, not an overflow, because unestimated bars are not capped
as a group. Extend `hasFooterContent` in `blocks.ts` so a swimlane whose only news is an unestimated
count still gets its strip.

### 3.4 Empty-state overlay — a behaviour change to record

`WorkloadTimelineRoot`'s overlay reads `rows.some(r => r.tasks.length > 0 || r.total > 0)`. With
unestimated items in `tasks`, a workspace whose work is entirely unestimated now renders bars instead
of the empty state. That is this feature's intended outcome and needs no code change — but the
comment above it must record that `tasks.length` is no longer a proxy for "estimated work exists",
since that comment currently explains the two halves in terms that predate this.

**Verify:** `pnpm check`, then a manual pass at Week / Month / Quarter zoom against a project holding
one estimated dated item, one unestimated dated item, one unestimated undated item, and one overdue
unestimated item.

---

## Phase 4 — End-to-end verification (S, ~1d)

1. `python manage.py check` and `makemigrations --check --dry-run` — **must report no migration.**
   This feature adds no model and no column; a migration appearing here means something reached a
   core model, which `docs/FORK.md` forbids outright.
2. The full backend workload suite, not just the new file — `test_task_rows.py` and
   `test_member_rows.py` assert task-array shapes that now carry a new key.
3. `pnpm check` plus the `workload-ext` unit suite.
4. **Capacity-invariance check on real data:** call the workload endpoint for one busy member before
   and after, and diff `buckets`, `month_buckets`, `total`, `capacity_buckets`, and the rendered
   badge. Any difference is a bug in 1.4, not a rounding artefact.
5. Console-closed pass: at each zoom, confirm a dashed `?` bar is distinguishable from a solid
   estimated bar and from an unscheduled placeholder without hovering.

---

## Phase 5 — Propagation and docs (S, ~1d)

Mandatory per `CLAUDE.md` § STANDING RULE and `.claude/rules/plane-fork-discipline.md`. The
`get_workload` response shape changes, so every downstream consumer is in scope. Use the
`plane-propagate` skill; the sibling matrix is
`.claude/skills/plane-propagate/references/sibling-repos.md`.

| Target             | Change                                                                                                                                                                                                                          | How             |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------- |
| `plane-mcp-server` | `get_workload` result typing + the prose field list in `plane_mcp/tools/workload.py` (it enumerates every task field and **will go stale**): tasks may carry `unestimated: true` with `hours: 0`; new `meta.issues_unestimated` | PR in that repo |
| `plane-node-sdk`   | workload response bindings (`WorkloadMatrixRow` does not model `tasks[]` at all today — a prerequisite the state-colour plan also hits)                                                                                         | PR in that repo |
| `plane-python-sdk` | workload response bindings (`extra="allow"`, so additive today — still document)                                                                                                                                                | PR in that repo |
| `CLAUDE.md`        | extend the `workload/` bullet: unestimated items render as dashed `?` bars, contribute zero hours to every capacity figure, sort first, share the 200-task cap, and are counted per swimlane in the footer                      | this repo       |
| `docs/FORK.md`     | record explicitly that this feature adds **no** model, migration, or touch-point, so a future reader does not go looking                                                                                                        | this repo       |

**Never edit a sibling repo from this repo's PR** — open issues/PRs in each fork we own.

---

## Risk Assessment

| Risk                                                                                                                                                     | Likelihood | Impact | Score  | Mitigation                                                                                                                                                                                                                                                                                                                                                                                                 |
| -------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- | ------ | ------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| R1 — the new `Issue` query is far larger than the `WorkloadEstimate` one and materially slows the endpoint on a workspace with a big unestimated backlog | 4          | 4      | **16** | **Phase 1.0 is a blocking gate (D5)** — measured before any assembly code exists. Both anti-join paths are already indexed (`Issue.parent` FK, `WorkloadEstimate.issue` unique), so the gate confirms the planner uses them rather than adding an index; a plan needing a new index on a core model is a stop, not a migration. Recorded fallback: narrow D1 to dated-items-only, re-decided with the user |
| R2 — unestimated sorting first (D4) pushes estimated work past the 200-task cap and takes all three placeholder slots                                    | 3          | 3      | 9      | `tasks_truncated` already surfaces in the footer; `test_sorted_first_and_shares_cap` pins the interaction so the trade-off lives in the suite rather than being discovered on a busy swimlane                                                                                                                                                                                                              |
| R3 — this plan and `feat/workload-state-color` edit the same `values_list` and the same style branch                                                     | 4          | 2      | 8      | Stated sequencing: state-colour merges first, this plan rebases onto it. Phase 1.4 already names the state fields in the new `values_list`                                                                                                                                                                                                                                                                 |
| R4 — `_scope_filter`'s guest rule is duplicated instead of parameterised, and the copies drift                                                           | 2          | 5      | 10     | Phase 1.1 is explicit: one function, one `issue_field` parameter, existing call site unchanged. A second copy fails review                                                                                                                                                                                                                                                                                 |
| R5 — capacity numbers move because an unestimated item leaks into `buckets`                                                                              | 2          | 5      | 10     | Phase 4.4's before/after diff on real data plus `test_unestimated_contributes_no_hours`                                                                                                                                                                                                                                                                                                                    |
| R6 — `unestimated` omitted on estimated rows, so a client reads `undefined` as falsy and works by accident until a consumer uses `in` or a strict schema | 2          | 3      | 6      | Contract says always present; the backend sets `False` explicitly and `test_estimated_rows_carry_unestimated_false` asserts the key exists                                                                                                                                                                                                                                                                 |
| R7 — swimlanes get materially taller, pushing members off screen                                                                                         | 3          | 2      | 6      | Unestimated dated bars are lane-packed, so concurrent items share a row; only genuinely overlapping work adds height. Placeholders stay capped at 3                                                                                                                                                                                                                                                        |

## Timeline

| Phase                                       | Effort  | Notes                                                                                                                      |
| ------------------------------------------- | ------- | -------------------------------------------------------------------------------------------------------------------------- |
| Phase 1 — Backend (incl. the 1.0 cost gate) | M (~3d) | Critical path. Blocked by `feat/workload-state-color` merging                                                              |
| Phase 2 — Shared package                    | S (~1d) | Needs only the Phase 1 contract, not its implementation                                                                    |
| Phase 3 — Timeline rendering                | S (~1d) | Blocked by Phase 2                                                                                                         |
| Phase 4 — Verification                      | S (~1d) | Blocked by Phase 3                                                                                                         |
| Phase 5 — Propagation                       | S (~1d) | Blocked by Phase 4                                                                                                         |
| **Total**                                   | **~7d** | Critical path 1 → 2 → 3 → 4 → 5, strictly sequential: the shape crosses every boundary, so there is no parallel-safe split |

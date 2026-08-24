# Phase 5 — click empty timeline space to create a work item

**Owns:** `apps/web/core/components/workload/timeline/WorkloadCreateOverlay.tsx` _(new file)_,
`apps/web/core/components/workload/timeline/WorkloadTimelineChartBlock.tsx`,
`apps/web/core/components/workload/timeline/WorkloadTimelineRoot.tsx`,
`packages/workload-ext/src/i18n.ts`
**Estimate:** 3h
**Depends on:** phase 3 (shares the lane branch's geometry); independent of phase 4

## Goal

Clicking empty space inside a member's lane opens core's create modal, pre-dated to the clicked day
and pre-assigned to that member.

## Why core's `ChartAddBlock` is not the answer

It exists (`gantt-chart/helpers/add-block.tsx`) but solves a different problem: `BlockRow` renders it
only when a block has **no** dates (`blocks/block-row.tsx:117`), and its click calls
`blockUpdateHandler` to _schedule an existing block_. Every workload lane block has dates, so it
would never appear, and it cannot create anything. Reaching it would also mean setting
`enableAddBlock`, which is the wrong switch for this behaviour. Build the overlay in the fork.

## The overlay

A transparent absolutely-positioned layer filling the lane block's own box, rendered **behind** the
task bars (`z-0` against the bars' `z-10`) so a click on a bar never reaches it. Mirrors the
geometry the bars already use: `left` measured from `laneMarginLeft`, one `dayWidth` per day.

On hover, show a `+` affordance snapped to the hovered day column — the same affordance shape core's
`ChartAddBlock` uses (a bordered 32px button), so the gesture is familiar even though the code is
not shared. Tooltip: the date under the cursor.

On click:

```ts
const day = getDateFromPositionOnGantt(e.nativeEvent.offsetX + laneMarginLeft, chart);
```

Absolute chart pixels again, not lane-relative — the same rule as phase 2.

Then open the modal with:

```ts
{
  start_date: renderFormattedPayloadDate(day),
  target_date: renderFormattedPayloadDate(addDays(day, 1)),
  assignee_ids: assigneeId ? [assigneeId] : [],
}
```

A one-day default span matches core's own week-zoom behaviour in `ChartAddBlock`
(`numberOfDays = 1`, widened to 7 only at quarter). Follow that, including the quarter widening —
a one-day bar at quarter zoom is a 30px sliver.

## The modal

Mounted once in `WorkloadTimelineRoot`, not per lane — one modal instance, driven by a
`{ day, assigneeId } | null` state the overlay sets.

```tsx
<CreateUpdateIssueModal
  isOpen={createSeed !== null}
  onClose={() => setCreateSeed(null)}
  data={seedData}
  storeType={EIssuesStoreType.PROJECT}
  onSubmit={async () => {
    store.resetCoverage();
  }}
/>
```

Three things to get right:

- **`storeType` must be passed explicitly.** Without it `CreateUpdateIssueModalBase` falls back to
  `useIssueStoreType()` (`issue-modal/base.tsx:55`), and the workload route sits in no issue-layout
  context. `PROJECT` resolves to `useProjectIssueActions`, whose `createIssue` needs only
  `workspaceSlug` from the route plus the `project_id` the modal itself collects
  (`hooks/use-issues-actions.tsx:105`) — so it works on a route with no `:projectId` param.
- **The project picker stays enabled.** The workload board is workspace-wide; there is no single
  project to infer. If exactly one project filter is active, seed `project_id` from it as a
  convenience, but never disable the picker.
- **`resetCoverage()` here is correct**, unlike after a drag. A new work item can land anywhere and
  changes row membership, not just one bar's position, so the full drop-and-refetch is the honest
  invalidation. This is the same call the peek-panel-close effect already makes
  (`workload/page.tsx`), and the momentary blank is acceptable for a modal-driven action the user
  just confirmed.

**Do not add an estimated-hours field to the create form.** That work is in flight separately; a
second edit to `issue-modal/form.tsx` from this branch would collide with it. A work item created
here lands as a `0h` bar until its estimate is set — expected, and worth a line in the docs.

## Permission

Render the overlay only where the viewer can create in at least one project. Reuse phase 3's
`allowPermissions` call, but at workspace level for the affordance's _visibility_; the modal's own
project picker enforces per-project rights on submit. A `+` that opens a modal with an empty project
list is worse than no `+`.

## Success criteria

- `pnpm check` clean; `pnpm turbo run build --filter=web` clean.
- Manual: hovering empty lane space shows a `+` snapped to a day column, with the correct date in
  its tooltip, at all three zooms.
- Manual: clicking it opens the modal with the assignee prefilled and the dates matching the
  clicked column.
- Manual: creating an item makes it appear as a bar in that member's swimlane after the refetch.
- Manual: clicking **on** a bar still opens the peek panel and never the create modal.
- Manual: a collapsed swimlane shows no overlay (it has no lane blocks — verify rather than assume).

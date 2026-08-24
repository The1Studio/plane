# Phase 3 — handles, cursors, and the per-project permission gate

**Owns:** `apps/web/core/components/workload/timeline/WorkloadTimelineChartBlock.tsx`,
`apps/web/core/components/workload/timeline/WorkloadTaskLink.tsx`,
`packages/workload-ext/src/i18n.ts`
**Estimate:** 3h
**Depends on:** phase 2

## Goal

Make each bar in the `kind: "lane"` branch draggable and resizable, gated per project, without
disturbing the click-to-peek behaviour or the bar's existing layout rules.

## Where the code goes

`WorkloadTimelineChartBlock.tsx`'s lane branch already computes, per task, `left`, `width`,
`laneMarginLeft`, and `dayWidth`. Everything this phase needs is in scope there. Extract the
per-task body into a `WorkloadTaskBar` component in the same file — the hook must be called once
per bar, and hooks cannot be called inside the existing `.map()` callback.

## Permission gate (D4)

```ts
const canEdit = allowPermissions(
  [EUserPermissions.ADMIN, EUserPermissions.MEMBER],
  EUserPermissionsLevel.PROJECT,
  workspaceSlug,
  task.project_id
);
```

`allowPermissions` takes an explicit `projectId` (`store/user/base-permissions.store.ts:191`), which
is what makes a per-bar check possible on a route that has no `:projectId` param. Evaluate it **per
bar**, not per board: the timeline is workspace-wide and a single swimlane routinely mixes projects.

When `canEdit` is false: no handles render, the cursor stays `cursor-pointer`, and `disabled` is
passed to the hook. The bar still opens the peek panel — read access is unchanged. Do **not** grey
the bar out; a bar that looks disabled reads as "this work item is inactive", which is a different
and wrong claim.

## Handles

Two 6px absolutely-positioned strips at the bar's left and right edges, `cursor-ew-resize`, revealed
on `group-hover` and on keyboard focus. The bar body itself takes `cursor-grab`, switching to
`cursor-grabbing` while `isDragging`.

**The handles must sit above the `ControlLink`'s hit area** and call `e.stopPropagation()` and
`e.preventDefault()` on `pointerdown`. Without `preventDefault` the browser starts a native anchor
drag and the pointer events stop arriving.

**Respect `MIN_BAR_WIDTH`.** A bar can be rendered at the 60px floor while representing one day; two
6px handles then occupy a fifth of it. Below ~24px of remaining body, render the right handle only —
resizing the end is the common operation and a bar with two handles and no body is not draggable at
all.

## Applying the preview

While `preview` is non-null, use it for the bar's `left`/`width` instead of the computed values.
Keep the same `style` object shape so there is one source of positioning rather than a second
branch:

```ts
const left = preview ? preview.left : startPos - laneMarginLeft;
const width = preview ? preview.width : Math.max(endPos - startPos, MIN_BAR_WIDTH);
```

Note the asymmetry: `MIN_BAR_WIDTH` is **not** applied to the preview. During a resize the user is
setting a real duration and must see it; clamping the preview to 60px would show a two-day bar while
they drag out one day. The floor returns on the next render from committed data.

## Suppressing the click after a drag

`WorkloadTaskLink`'s `handleClick` currently calls `setPeekIssue` unconditionally. Add an optional
`suppressClick?: boolean` prop; when true, `handleClick` calls `preventDefault` + `stopPropagation`
and returns without opening the peek panel. The hook clears the flag on the next tick after the
click it was raised for.

This is the one edit to `WorkloadTaskLink.tsx`. Everything else about it — the `ControlLink`, the
cmd/ctrl/middle-click passthrough, the `generateWorkItemLink` href — stays exactly as it is; those
behaviours are why the bar is an anchor in the first place.

## Strings

Add to `packages/workload-ext/src/i18n.ts`: a tooltip for each handle
(`timeline.resize_start`, `timeline.resize_end`) and a drag hint (`timeline.drag_to_reschedule`).
Fork UI strings live in this package, never in `packages/i18n` — that is a `@plane/*` package the
fork rules forbid editing in place.

## Success criteria

- `pnpm check` clean; `pnpm turbo run build --filter=web` clean.
- Manual, in the browser, at week zoom:
  - a plain click on a bar still opens the peek panel;
  - a click with 2px of jitter still opens the peek panel;
  - a 40px drag moves the bar and does **not** open the peek panel;
  - cmd-click still opens the work item in a new tab;
  - a bar in a project where the viewer is a guest shows no handles and does not drag.
- Repeat the drag check at month and quarter zoom — snapping is one column of `dayWidth`, so a
  quarter-zoom drag should move in 30px steps.

## Out of scope

No store write and no network call yet — `onCommit` is a `console.debug` at the end of this phase.
Phase 4 supplies the real one.

# Phase 2 — Default-collapse every swimlane in Month and Quarter zoom

**Effort:** S (~1.5h) · **Depends on:** Phase 1 (shares `WorkloadTimelineSidebarRow.tsx`)

## Goal

At Month and Quarter zoom the workload timeline should open as a one-line-per-row
capacity board: every swimlane collapsed to just its header (avatar, name,
used/capacity badge, heat cells). Week zoom keeps today's behaviour and opens
expanded.

Manual chevron toggles still work in every zoom; they are simply **reset to the
zoom's default whenever the zoom changes** (D3).

## Ownership

```
apps/web/core/components/workload/timeline/WorkloadTimelineRoot.tsx
apps/web/core/components/workload/timeline/WorkloadTimelineSidebarRow.tsx
apps/web/core/components/workload/timeline/blocks.ts
CLAUDE.md                                  # one clause on the existing workload/ bullet
```

## The model — default + per-key override, not a materialised set

Today `WorkloadTimelineRoot` holds `collapsed: ReadonlySet<string>` and treats
membership as "collapsed". That cannot express "collapsed unless the user said
otherwise", and a set built once at view-change time would be wrong for every
row that loads afterwards — rows arrive asynchronously from the viewport-driven
`store.ensureRange` calls, so in Month zoom a member scrolled into view a second
later would render expanded (D6).

Replace it with:

- `overrides: Record<string, boolean>` — only keys the user has explicitly
  toggled this view.
- `defaultCollapsed = timelineStore.currentView !== "week"` — read directly in
  render. `currentView` is a MobX observable and `WorkloadTimelineRoot` is
  already wrapped in `observer`, so no `reaction` is needed for this; the
  component re-renders on zoom change on its own. (The existing `reaction` that
  syncs `currentView → store.setGranularity` stays untouched — it does a
  different job.)
- `isCollapsed(key) = overrides[key] ?? defaultCollapsed`.

## Steps

1. **`WorkloadTimelineRoot.tsx`** — swap the state:

   ```tsx
   const [overrides, setOverrides] = useState<Record<string, boolean>>({});
   const defaultCollapsed = timelineStore.currentView !== "week";

   // A zoom change resets manual toggles: each zoom has its own default and
   // that default wins on arrival (D3). Rows that load later inherit it too,
   // because isCollapsed evaluates per key at render rather than materialising
   // a set from whatever rows happened to be loaded at the time (D6).
   useEffect(() => {
     setOverrides({});
   }, [defaultCollapsed]);

   const isCollapsed = useCallback(
     (key: string) => overrides[key] ?? defaultCollapsed,
     [overrides, defaultCollapsed]
   );

   const toggleCollapse = useCallback((key: string) => {
     setOverrides((prev) => ({ ...prev, [key]: !(prev[key] ?? defaultCollapsed) }));
   }, [defaultCollapsed]);
   ```

   **Key the reset effect on `defaultCollapsed`, never on `currentView`** (D7).
   Month and Quarter share a default, so a Month↔Quarter switch keeps today's
   behaviour and leaves the reader's toggles alone; Week↔Month and Week↔Quarter
   both flip the boolean and therefore reset. This is a decided behaviour, not
   an implementation preference — do not "simplify" it to `[currentView]`.

   Note `timelineStore` is a `BaseTimeLineStore` cast — confirm `currentView` is
   on the public surface before reading it (it is the field the existing
   `reaction` already tracks, so it is).

2. **`blocks.ts`** — change `buildWorkloadBlocks`'s third parameter from
   `collapsedAssigneeKeys: ReadonlySet<string>` to
   `isCollapsed: (assigneeKey: string) => boolean`, and replace the
   `collapsedAssigneeKeys.has(key)` guard with `isCollapsed(key)`. Update that
   function's docstring, which currently describes the parameter as a set.

   Pass `isCollapsed` into the existing `useMemo` in the root and add it to the
   dependency array (it is a `useCallback`, so it is stable between toggles).

3. **`WorkloadTimelineSidebarRow.tsx`** — replace the
   `collapsed: ReadonlySet<string>` prop with
   `isCollapsed: (key: string) => boolean`, and change the header branch's
   `const isCollapsed = collapsed.has(key)` to a call. Rename the local so it
   does not shadow the prop (e.g. `const rowCollapsed = isCollapsed(key)`).

4. **`CLAUDE.md`** — append one clause to the existing `workload/` bullet under
   "Custom features (fork-owned)", recording that the timeline default-collapses
   every swimlane (including `Unassigned`) at Month and Quarter zoom and opens
   expanded at Week, and that a zoom change resets manual toggles. Keep it to a
   sentence; the bullet is already dense.

   `docs/FORK.md` needs **no** change — no touch-point file is edited and no new
   core-edit exception is created.

## Success criteria

- Loading the workload page (Week zoom is the default) shows every swimlane
  expanded, exactly as today.
- Switching the gantt header control to **Month** collapses every row to a
  single header line, including the `Unassigned` row (D4). Switching to
  **Quarter** does the same.
- Scrolling horizontally in Month zoom far enough to pull in rows that were not
  loaded at the time of the switch: those rows are **also** collapsed. This is
  the assertion that separates the correct implementation from a set snapshotted
  at view-change time — do not skip it.
- Expanding one member by hand in Month zoom leaves every other member
  collapsed, and that member's bars and its `Unscheduled (N)` strip appear.
- Switching Month → Week expands everything again, discarding the manual toggle.
- Switching Month → Quarter **preserves** the manual toggle: the row you opened
  by hand is still open. This is the assertion that catches a reset effect keyed
  on `currentView` instead of `defaultCollapsed` (D7).
- The used/capacity badge on a collapsed header still reports the focused
  period's figures — collapsing must not disturb `periodFigures`, which reads
  `row.buckets` and is independent of which blocks are emitted.
- `pnpm --filter web typecheck` and the repo's lint pass with no new errors.

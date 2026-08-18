# Phase 4 — Calendar layout

**Goal:** Add the Calendar layout to the Views tab, grouped by target date across all projects.

**Effort:** M (~3d) · **Depends on:** Phase 3 · **Parallel with:** Phase 5 (disjoint files — see below)

---

## Starting position — better than it looks

There is **no** calendar root for any workspace-level store: searched
`apps/web/core/components/issues/issue-layouts/calendar/roots/` in full — only `project-root`,
`cycle-root`, `module-root`, `project-view-root` exist. No cross-project precedent.

But `BaseCalendarRoot` itself is close to store-agnostic, and two things that could have been
blockers already work:

- **Fetch already sends what the server needs** (`base-calendar-root.tsx:90-104`): it passes
  `before: endDate`, `after: startDate`, and `groupedBy: EIssueGroupByToServerOptions["target_date"]`.
  Phase 1 implements `before` / `after` per the contract, so the server side is already done.
- **Drag already resolves project per item** — `handleDragAndDrop` takes an `issueProjectId`
  parameter (line ~106) rather than reading a route `:projectId`. This is the exact thing that
  blocks Timeline (Phase 5, B3) and it is _not_ a problem here.

So the work is the store-type union, a root wrapper, and verification — not a port.

## Work

### 1. Admit `GLOBAL` to `CalendarStoreType`

`apps/web/core/components/issues/issue-layouts/calendar/base-calendar-root.tsx:27` — the union
lists `PROJECT | MODULE | CYCLE | PROJECT_VIEW | TEAM | TEAM_VIEW | EPIC`. Add
`| EIssuesStoreType.GLOBAL`, fenced.

Note this union — unlike List's and Board's — does **not** already contain `PROFILE`, so there is
genuinely no prior workspace-level user. Expect to find project assumptions the type system was
hiding. Read the whole component before adding the union member, and record anything you find
here rather than working around it silently.

### 2. Calendar root in `packages/views-ext`

Template: `calendar/roots/project-view-root.tsx`. Pass `AllIssueQuickActions` and a
`canEditPropertiesBasedOnProject` closure (permissions stay per-project inside a workspace view).

### 3. Register the layout

- Add `EIssueLayoutTypes.CALENDAR` to `GLOBAL_VIEW_LAYOUTS` (Phase 2, Deliverable 1) — this is
  what makes the button appear
- Add the `case` to `WorkspaceAdditionalLayouts` in `apps/web/ce/components/views/helper.tsx`
- Confirm the fork layout-options table has a `calendar` entry with the calendar sub-layout
  options (`month` / `week`), modelled on the `issues` page's calendar entry in
  `packages/constants/src/issue/filter.ts`

### 4. Verify server-side date filtering

Phase 1 implements `before` / `after`, but no consumer exercised them until now. Confirm on the
wire that a month change refetches with the new window and that the response respects it — a
client-side filter over a full fetch would look identical in the UI at small data sizes and fall
over at 468+ items.

## Parallel-safety with Phase 5

Both phases append to the same two places: `GLOBAL_VIEW_LAYOUTS` and the
`WorkspaceAdditionalLayouts` switch. Per `rules/parallel-teammate-git-index-race.md` these are
**shared files**, and a shared working tree means the second writer silently overwrites the first
— no conflict marker, no compile error.

If Phases 4 and 5 run concurrently: separate `git worktree` per lane, and the lead merges the two
append points. Otherwise run them sequentially. Everything else in each phase is disjoint.

## Success criteria

- [ ] Calendar button appears in the Views switcher and renders a month grid
- [ ] Work items from **multiple projects** appear on their target dates
- [ ] Month navigation refetches — **verified in the network tab**: `before` / `after` change and the response respects them
- [ ] Week layout toggle works
- [ ] Drag a work item to another date → its `target_date` updates and persists across reload
- [ ] Items with no target date do not break the grid
- [ ] Peek overview opens from a calendar cell
- [ ] Any project assumption found while widening `CalendarStoreType` is recorded here, not silently patched
- [ ] `pnpm check` clean · `plane-isolation-audit` flags no file outside Phase 3's documented set plus `base-calendar-root.tsx`

## Risks

| Risk                                                                           | L   | I   | Score | Mitigation                                                                                           |
| ------------------------------------------------------------------------------ | --- | --- | ----- | ---------------------------------------------------------------------------------------------------- |
| Undiscovered project assumption in `BaseCalendarRoot` (no `PROFILE` precedent) | 3   | 3   | 9     | Read the component fully before widening the union; record findings rather than patching around them |
| `before` / `after` filtering is client-side in practice → breaks at scale      | 2   | 4   | 8     | Network-tab verification is a success criterion                                                      |
| Concurrent append collision with Phase 5                                       | 3   | 2   | 6     | Separate worktrees, or run sequentially                                                              |
| Cross-project drag hits per-project permission edges                           | 2   | 3   | 6     | `canEditPropertiesBasedOnProject` closure, as the profile roots do                                   |

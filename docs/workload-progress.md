# Workload progress bar

A visual progress bar + % is shown on every work item, matching the source
(ClickUp) "progress" column. It is a **pure frontend display derivation** —
there is no new API field, no new endpoint, no core model column, and no
migration. See `packages/workload-ext/src/progress.ts` for the implementation.

> **No API surface.** Do not file SDK/MCP propagation issues for this feature —
> unlike the workload estimate/rollup endpoints (`docs/workload-followups.md`),
> there is nothing new to bind.

## Semantics

Two sources, unified into one `0..1` fraction (`null` = no meaningful
progress, rendered as a dash — never a `0%`-filled bar):

- **Parent** work items (have countable leaf descendants) reuse the existing
  hours-weighted rollup already served by `GET .../workload-rollups/`
  (`done-leaf-hours / total-leaf-hours`). `null` when the parent has 0
  estimated hours.
- **Leaf** work items (no countable descendants) derive progress client-side
  from the item's workflow **state group** — no backend, no stored field:

  | State group | Progress |
  | ----------- | -------- |
  | `completed` | 100%     |
  | `started`   | 50%      |
  | `unstarted` | 0%       |
  | `backlog`   | 0%       |
  | `cancelled` | — (excluded, dash) |

  `cancelled` is excluded for consistency with the hours rollup, which also
  excludes cancelled descendants.

## Where it renders

- **Spreadsheet grid** — a fixed "Progress" column, appended after the
  Estimated-hours column (`spreadsheet/columns/progress-column.tsx`).
- **List / kanban** — a compact pill alongside the hours pill
  (`ce/components/issues/issue-layouts/additional-properties.tsx`).
- **Item-detail sidebar** — a progress row alongside the "Estimated hours"
  field (`issue-detail/sidebar.tsx`).

All three surfaces share one component, `packages/workload-ext/src/ProgressBar.tsx`,
so there is no visual drift between them.

## Hours surfaces now show hours only

Now that progress has its own dedicated bar, the hours surfaces (sidebar
field, spreadsheet Estimated-hours column, list/kanban hours pill) display
hours only (`Σ 10h`) — the percent that used to be baked into the hours pill
moved to the dedicated progress bar/pill instead.

## Restricted-guest caveat (carried over from the rollup)

Same caveat as the underlying hours rollup: a restricted guest's displayed
parent progress may under-count relative to the true total, because the
rollup is computed only over the leaf descendants visible to that guest's
scope. This is partial-by-scope, by design — not a bug.

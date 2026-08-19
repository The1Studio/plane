# Later — restore interactions on packed rows

Not part of the compaction change. Written now so the disabled code is not mistaken for dead code
and deleted.

Phase 3 switches off drag-to-reschedule, resize, reorder, dependency arrows and bulk-select
because each assumes one bar per row. Restoring them is a design problem, not a porting problem.

## What each one needs

**Drag + resize.** The handlers must key off the _bar_ rather than the row. `ChartDraggable`
currently wraps a row and knows one block; it needs to wrap each bar and carry that bar's id.
The harder half is the drop: moving a bar may make it overlap a neighbour in its lane, so the
packing has to be recomputed mid-drag and the row it lands in may change under the cursor.
Decide first whether a drag can move a bar BETWEEN lanes, or whether lanes re-pack only on drop.

**Dependency arrows.** Drawn between row centres today. With packing, two dependent items can
share a row, so an arrow would start and end on the same line. Either the path layer learns bar
coordinates instead of row coordinates, or dependent items are forced into different lanes — the
second is simpler and makes the packing dependency-aware, at the cost of more rows.

**Reorder.** A lane is not an item, so "drag this row to position 3" has no meaning. Either
reorder is dropped from Timeline permanently (it exists on List and Board), or the packer becomes
stable with respect to an explicit sort order and reorder acts on that.

**Bulk-select.** Keyed by row today. Needs to key by bar, and the marquee/shift-click semantics
of selecting a _range_ across a packed layout need defining — visual adjacency is no longer the
same as list adjacency.

## Sequencing

Drag + resize is the one users will ask for first and is independently shippable. Dependency
arrows are the one most likely to force a change to the packer itself, so design that before
committing to a packing API. Reorder and bulk-select can stay off indefinitely without much loss.

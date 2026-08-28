# Phase 0 — Prune terminal subtrees in the shipped issue cascade

**Effort:** S (1.5h) · **Blocks:** Phase 1 · **Changes SHIPPED behavior**
**Plan:** `plans/260828-module-cascade-terminal-status/plan.md`
**Amends:** `plans/260822-cascade-complete-sub-items/plan.md` Decision 5
**Plane:** [PLANE-190](https://plane.the1studio.org/infrastructure/projects/2eae4e83-f715-4e4b-8753-cdc289bbe37f/issues/6ba258c2-f09e-444c-8067-a22401b052d8)

## Goal

Reverse one rule in the live per-issue cascade: a descendant already in a terminal group currently
gets **skipped but traversed through**, so its own live descendants still cascade. From this phase
on, a terminal node **prunes its entire subtree** — not listed, not walked, not changed.

This phase exists on its own because it changes behavior users already have. It can ship, and be
reverted, without any of the module work. Phase 1 depends on it only so that both subjects share one
rule instead of two.

## Why

The module cascade (`plan.md` M8) required this rule, and running the two features with opposite
semantics on the same `Issue.parent` tree is worse than either rule alone: the same tree would
cascade differently depending on whether the action started at a work item or at a module, with
nothing on screen explaining the difference. A terminal item is a decision someone made about that
branch — completing or cancelling it means "this line of work is settled", and reaching past it to
change its children overrides that decision silently.

**The cost, stated plainly:** a live sub-item under a cancelled parent is now left live where it
used to be swept. That is the intended behavior, not an accepted regression — but it is the case to
watch for in review, and the one that will surprise anyone who learned the old rule.

## Ownership

```
apps/api/plane/cascade_ext/service.py                 # the walk + one new rejection reason
apps/api/plane/cascade_ext/tests/test_cascade_db.py   # invert two tests, add one
plans/260822-cascade-complete-sub-items/plan.md       # dated amendment to Decision 5
docs/FORK.md                                          # cascade_ext entry
CLAUDE.md                                             # cascade_ext bullet
```

## Implementation

### 1. `collect_descendants` — do not enqueue a terminal node's children

The BFS currently pushes every child onto `next_frontier` and filters terminal nodes out of the
result afterwards. Move the terminal test into the walk: a child whose `state.group` is terminal is
recorded in `traversed_ids` and **not** added to `next_frontier`.

Consequences to get right, each of them observable:

- `traversed_ids` no longer contains anything beneath a terminal node, because nothing beneath one
  is visited. It still contains the terminal node itself, which is what keeps `apply_cascade`'s
  `already_terminal` rejection reason working for the node a caller is most likely to post.
- A node with **no state at all** (`child.state is None`) is not terminal and must keep being
  walked. The current code reads `child.state.group if child.state else None`, which is not in
  `TERMINAL_GROUPS` — preserve that, do not collapse it to a truthiness check.
- `MAX_DEPTH` and `depth_capped` are unchanged. Pruning makes the cap _less_ likely to fire, never
  more.

### 2. New rejection reason `under_terminal_ancestor`

`apply_cascade` classifies a posted-but-not-accepted id as `already_terminal` when it is in
`traversed_ids`, else `not_a_descendant`. After pruning, a live grandchild under a terminal parent
is in neither set — and `not_a_descendant` would be **false**: it genuinely is a descendant, it is
just behind a pruned branch. A caller debugging "why did my id do nothing" would be sent looking for
a tree-membership bug that does not exist.

Resolve it with one extra lookup rather than a wrong label: when a posted id is neither eligible nor
in `traversed_ids`, walk its `parent` chain (bounded by `MAX_DEPTH`) and return
`under_terminal_ancestor` if any ancestor is terminal and reaches the root, `not_a_descendant`
otherwise. This runs only for ids that were already going to be rejected, so it costs nothing on the
normal path.

### 3. Tests — invert, do not re-pin

Two existing tests assert the old rule directly and must be **inverted**, not deleted and not
loosened:

| Test (`test_cascade_db.py:193`, `:209`)                           | Was                         | Becomes                                                                |
| ----------------------------------------------------------------- | --------------------------- | ---------------------------------------------------------------------- |
| `test_cancelled_child_excluded_but_its_own_children_still_listed` | `assertIn(grandchild, ids)` | `assertNotIn(grandchild, ids)`; rename to `..._and_prunes_its_subtree` |
| `test_completed_child_excluded_mirrored_for_cancel_target`        | `assertIn(grandchild, ids)` | `assertNotIn(grandchild, ids)`; same rename                            |

Both keep `assertNotIn(terminal_child, ids)` and
`assertIn(str(terminal_child.id), result["traversed_ids"])` — those halves are unchanged and are
what proves the terminal node itself is still _seen_, only its branch is not followed.

Each inverted test carries a comment naming this phase and the date, so the next reader can tell a
deliberate reversal from a test someone weakened to make a failure go away. **Do not** adjust an
assertion to match whatever the new run reports — the two lines above are the whole diff.

New tests:

| #   | Case                                                   | Asserts                                                                                 |
| --- | ------------------------------------------------------ | --------------------------------------------------------------------------------------- |
| A   | Terminal node with a 2-level live subtree              | neither level listed; `traversed_ids` holds the terminal node and **nothing below it**  |
| B   | Live child, terminal grandchild, live great-grandchild | child listed, great-grandchild **not** — pruning applies at any depth, not just level 1 |
| C   | Child with `state=None` and a live grandchild          | both still listed — a stateless node is not terminal                                    |
| D   | Apply posting a live id beneath a terminal ancestor    | `rejected` with `under_terminal_ancestor`, and that id is **not** written               |
| E   | Apply posting a genuinely foreign id                   | still `not_a_descendant` — the new reason did not swallow the old one                   |

The rest of `test_cascade_db.py` must pass untouched.

### 4. Documentation — record the reversal, do not overwrite it

- `plans/260822-cascade-complete-sub-items/plan.md`: append a dated amendment under Decision 5
  rather than editing the decision text. That plan is the record of what was decided in August;
  rewriting it makes the reversal invisible and leaves the shipped tests looking wrong.
- `docs/FORK.md` cascade_ext entry: the sentence _"are still traversed through, so a cancelled node
  cannot hide its own live descendants"_ is now **false** and must be replaced, not amended around.
  The new sentence states the opposite and says why.
- `CLAUDE.md` cascade_ext bullet: same sentence, same fix.
- The MCP-side docstring in `plane-mcp-server` carries the same claim; that is a sibling-repo change
  and rides Phase 4's propagation.

Grep before declaring this done — the old wording was quoted in more than one place:

```bash
grep -rn "traversed through\|still traversed\|traverse through" docs/ CLAUDE.md plans/ apps/api/plane/cascade_ext/
```

## Risk

| Risk                                                                       | L   | I   | Score | Mitigation                                                                                                                                                                               |
| -------------------------------------------------------------------------- | --- | --- | ----- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A user relied on sweeping past a cancelled parent                          | 3   | 3   | 9     | Deliberate, user-directed reversal. Named in the FORK.md and CLAUDE.md entries as a behavior change with its date, so a surprised reader finds the answer rather than filing a bug.      |
| The two inverted tests get "fixed" back later by someone reading them cold | 3   | 3   | 9     | The inline comment naming this phase and date is the mitigation, and is the reason the rename is part of the diff — `..._and_prunes_its_subtree` states the rule in the test's own name. |
| `under_terminal_ancestor` parent-walk becomes a hot path                   | 1   | 2   | 2     | Runs only for ids already rejected; bounded by `MAX_DEPTH`.                                                                                                                              |

## Success criteria

- `pytest apps/api/plane/cascade_ext/tests/test_cascade_db.py` green, with exactly the two inverted
  assertions and the two renames as the only edits to pre-existing tests.
- The grep above returns no surviving statement of the old rule.
- `python manage.py check` clean; no migration.

# Phase 4 — Downstream propagation

**Plane:** PLANE-113 · **Effort:** S (2h)

**Effort:** S (2h) · **Depends on:** Phases 1–3 merged · **Blocks:** nothing

Mandatory per `CLAUDE.md` § "STANDING RULE": a behavior change to an endpoint is not done until the
downstream surfaces describe it. This change adds **no** new endpoint and **no** new field, so the
SDK bindings need no regeneration — but the *behavior* of an existing tool changed, which is the
case the rule exists for.

## Ownership

```
CLAUDE.md                    # "Custom features (fork-owned)" section
docs/FORK.md                 # feature entry (the exception tables were added in Phases 2-3)
```

Plus **issues opened in sibling repos** — never edits to them from this repo's PR
(`.claude/rules/plane-fork-discipline.md`). Use the `plane-propagate` skill; the sibling matrix is
`.claude/skills/plane-propagate/references/sibling-repos.md`.

## Work

1. **`CLAUDE.md`** — one bullet under "Custom features (fork-owned)":

   > `cascade_ext/` — cascading a terminal state (`completed` / `cancelled`) down a work item's
   > sub-tree, behind a confirmation modal. Two endpoints: `cascade-preview/` returns the flattened
   > descendant tree with per-node eligibility, `cascade-apply/` moves the parent plus a
   > caller-selected subset in one transaction. Descendants already terminal are never touched;
   > each target state is resolved by `group` in the child's **own** project, never by name.
   > A plain `PATCH state` never cascades — from any client, including MCP and the public API.
   > Frontend: `packages/cascade-ext`. Adds no model, no migration, no backend core edit.

2. **`docs/FORK.md`** — a feature section alongside the existing ones, cross-linking the
   `cascade-complete` exception table added in Phase 2.

3. **`plane-mcp-server`** — a PR **in that repo** (never from this one) adding a `cascade: bool = False`
   parameter to `update_work_item`:
   - `cascade=False` (the default, and the shape every existing caller already uses) → today's plain
     PATCH, byte-for-byte unchanged. This is what makes the option backward-compatible.
   - `cascade=True` **and** the new `state` is terminal → call `cascade-apply` with `state_id` and
     **no** `child_ids`, i.e. every eligible descendant (Decision 14). A headless caller has no UI to
     untick rows in.
   - `cascade=True` and the new state is **not** terminal → plain PATCH; do not error. There is
     nothing to cascade, and failing here would punish a caller who sets the flag once and reuses it.
   The docstring must say the default is `False` and that a plain `state` change never cascades —
   otherwise a Claude session assumes the UI's behavior applies to the API.

4. **SDKs (`plane-node-sdk`, `plane-python-sdk`)** — no binding change (no new field, no new
   endpoint). State that explicitly in the propagation record rather than leaving it unexamined.

5. **`docs` / `developer-docs`** — issue to document the cascade under work-item state behavior.

6. **Close [The1Studio/plane#54](https://github.com/The1Studio/plane/issues/54)** against its own
   acceptance-criteria list, ticking each. Two items cannot be ticked and must be called out rather
   than glossed:
   - **Bulk update** ("hỏi một lần cho cả batch") — no reachable backend route in this fork;
     `bulk-operation-issues` is EE-only. Not built, and not buildable here.
   - **Notification batching** ("cân nhắc gộp thành một event") — we suppress child notifications
     entirely rather than emitting one merged event. Zero, not one. Say so; a reader assuming
     "batched" would expect a notification that never arrives.

## Success criteria

- [ ] `CLAUDE.md` bullet present and matches the shipped behavior (re-read the merged service, do
      not copy this file's draft wording if the implementation diverged).
- [ ] `docs/FORK.md` feature entry present.
- [ ] Issue URL recorded for `plane-mcp-server`.
- [ ] Issue URL recorded for the docs repo.
- [ ] SDK "no change needed" recorded with the reason, not silently skipped.
- [ ] No sibling repo edited from this PR.
- [ ] #54 closed with its acceptance list ticked item-by-item, and the two unmet items named explicitly.

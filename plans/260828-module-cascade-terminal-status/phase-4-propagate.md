# Phase 4 — Propagate to downstream surfaces

**Effort:** S (1.5h) · **Depends on:** Phase 1 (the endpoints must exist)
**Plan:** `plans/260828-module-cascade-terminal-status/plan.md`
**Plane:** [PLANE-194](https://plane.the1studio.org/infrastructure/projects/2eae4e83-f715-4e4b-8753-cdc289bbe37f/issues/e8fa10c2-129b-47aa-95b3-301024efa15b)

## Goal

Satisfy `CLAUDE.md`'s STANDING RULE — every new endpoint reaches its downstream siblings before the
feature is done. Two new URL patterns on a fork-owned app classify as a **non-generic endpoint**
under `.claude/skills/plane-propagate/references/sibling-repos.md` § "Classification Rule", which
selects the full tier.

## Ownership

```
CLAUDE.md                                  # extend the cascade_ext "Custom features" entry
.claude/plane-propagation-queue.md         # runtime state, written by the propagate tooling
plane-mcp-server: plane_mcp/tools/**       # SEPARATE REPO, SEPARATE PR
```

**Never edit a sibling repo from this repo's PR** (`.claude/rules/plane-fork-discipline.md`,
`rules/kit-pr-workflow-boundary.md`). Everything below that is not `CLAUDE.md` is an issue opened
in the sibling repo, or a PR raised from inside a clone of it.

## 1. Run `plane-propagate`

Classification: **non-generic endpoint** — two new URL patterns
(`.../modules/<module_id>/cascade-preview/`, `.../cascade-apply/`) on the fork-owned `cascade_ext`
app, unreachable through any generic issue endpoint. That resolves to:

| Repo                           | Issue content                                                                                                                                                                                                                                                                          |
| ------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `plane-mcp-server`             | `preview_module_cascade` tool spec + `cascade` parameter on `update_module` (detail below), **and** the Phase 0 docstring correction: `plane_mcp/tools/cascade_ext.py`'s module docstring and `update_work_item`'s help still state the old skip-but-traverse rule, which is now false |
| `plane-node-sdk`               | TS bindings for both routes: method, URL, request/response shape from Phase 1's contract                                                                                                                                                                                               |
| `plane-python-sdk`             | The same bindings in Python                                                                                                                                                                                                                                                            |
| `plane-claude-plugin`          | User-facing: "complete a module and everything in it", naming the 100-item refusal                                                                                                                                                                                                     |
| `docs`                         | User-facing page: what the modal does, what "only change this module" means, the cap                                                                                                                                                                                                   |
| `developer-docs`               | API reference for both endpoints, auth, the `reason` enum, the 400 shapes                                                                                                                                                                                                              |
| `plane-deploy` / `helm-charts` | **Not applicable** — no new env var, no new service or container                                                                                                                                                                                                                       |

`MAX_MODULE_CASCADE_ITEMS = 100` is a hardcoded constant, deliberately not an env var. Making it
configurable would put `plane-deploy` and `helm-charts` in scope for a value nobody has asked to
tune; revisit only if a real workspace hits it.

## 2. MCP tools (separate PR in `plane-mcp-server`)

### `preview_module_cascade`

Mirrors the existing `preview_work_item_cascade`. Signature:

```python
preview_module_cascade(workspace_slug, project_id, module_id, status)  # status: completed|cancelled
```

Reuse `plane_mcp/tools/cascade_ext.py`'s existing `_send` helper — it already strips the `/api/v1`
suffix from `client.config.base_path` before composing `/api/cascade-ext{path}`. **That suffix strip
is the trap the module tools inherit:** composing against `base_path` directly yields
`/api/v1/cascade-ext/…` and 404s. The file's module docstring already records this for the issue
routes; extend it to name the module routes rather than writing a second explanation of the same
trap.

### `update_module(..., cascade=False)`

Mirrors `update_work_item(..., cascade=False)` exactly:

- `cascade=False` (the default) → the existing plain SDK `patch`, byte-for-byte unchanged.
- `cascade=True` **and** the resolved status is `completed`/`cancelled` → call `cascade-apply`
  instead, omitting `item_ids` so the server takes every currently-eligible item (the contract's
  documented headless path).
- `cascade=True` with a non-terminal status → plain patch. Not an error; there is simply nothing to
  cascade.

`update_module` already validates `status` against `ModuleStatusEnum` via `get_args` and **coerces
an unrecognized value to `None`** (`plane_mcp/tools/modules.py:166-176`). Read that coercion before
wiring the branch: a caller passing `status="Completed"` gets `validated_status = None`, so the
cascade branch must key off the _validated_ value, never the raw argument, or it fires a cascade for
a status the patch is not setting.

### Docstrings

State plainly in both tools: a plain `update_module` **never** cascades, from any client (M12). Name
the 100-item cap and that exceeding it is a **400 refusal, not a partial apply** — a headless caller
has no modal to read the refusal from and will otherwise read the 400 as transport failure and
retry it.

### Tests

| Case                                                | Asserts                                                  |
| --------------------------------------------------- | -------------------------------------------------------- |
| `update_module(status="completed")`                 | plain PATCH; **zero** cascade-ext calls                  |
| `update_module(status="completed", cascade=True)`   | one `cascade-apply`; zero plain PATCHes                  |
| `update_module(status="in-progress", cascade=True)` | plain PATCH; zero cascade-ext calls                      |
| `update_module(status="Completed", cascade=True)`   | coerced to `None` → no cascade fired                     |
| `preview_module_cascade`                            | hits `/api/cascade-ext/…/modules/…`, not `/api/v1/…`     |
| over-cap 400                                        | surfaced as a readable error naming the cap, not retried |

## 3. `CLAUDE.md`

Extend the existing `cascade_ext/` bullet — do not add a second one; it is one app serving two
subjects, and **correct the sentence Phase 0 falsified** — "are still traversed through, so a
cancelled node cannot hide its own live descendants" is now the opposite of the truth. State: a
terminal item prunes its whole subtree, for both subjects, as of this change; module status →
work-item state cascade over module members **plus their descendants**; the module's own status is written inside the same transaction; the 100-item cap is
a refusal, not a truncation; `update_module(..., cascade=False)` is the default and is byte-for-byte
the old PATCH; the frontend guard lives in `module.store.ts` alongside the `base-issues.store.ts`
one.

## Success criteria

- `plane-propagate` has opened an issue in each repo the classification selects, and the queue entry
  carries its `Propagated:` line.
- `pytest` green in `plane-mcp-server`; both tools resolve against a live fork server carrying
  Phase 1.
- `update_module`'s default behavior is unchanged for every existing caller — the parameter is
  additive with a `False` default, and the first test row is the gate for that.
- `CLAUDE.md`'s `cascade_ext/` entry describes both subjects and no longer asserts skip-but-traverse.
- `grep -rn "traversed through" CLAUDE.md docs/` returns nothing.
- Zero files changed in any sibling repo by this repo's PR.

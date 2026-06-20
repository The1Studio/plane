# Sibling Repos — Propagation Matrix

Source of truth for which downstream repo each change type must reach, per the
**CLAUDE.md STANDING RULE** ("every new feature must also update downstream surfaces").

---

## Sibling Repo Matrix

| Repo                             | Propagate when                                                                                                                      | Expected issue content                                                                                                  |
| -------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `The1Studio/plane-mcp-server`    | New endpoint that is NOT a generic Issue field — requires an **explicit** MCP tool (generic issue create/update will NOT carry it). | New tool spec: tool name, input parameters, output shape, the backend URL it wraps.                                     |
| `The1Studio/plane-node-sdk`      | Any new endpoint OR any new field on an existing endpoint.                                                                          | TypeScript binding: new method or field type in the SDK client; include the HTTP method + URL + request/response shape. |
| `The1Studio/plane-python-sdk`    | Any new endpoint OR any new field on an existing endpoint.                                                                          | Python binding: equivalent to the Node SDK binding but in Python; include the same HTTP method + URL + shape.           |
| `The1Studio/plane-claude-plugin` | New user-facing feature (something a Claude Code user can invoke or benefit from).                                                  | Plugin/skill update: describe the new capability and which Plane API call powers it.                                    |
| `The1Studio/docs`                | Any new feature or endpoint (user-facing documentation).                                                                            | User-facing doc page: what the feature does, how to use it, example requests/responses.                                 |
| `The1Studio/developer-docs`      | Any new feature or endpoint (developer-facing documentation).                                                                       | Developer guide: API reference, auth requirements, example code snippets.                                               |
| `The1Studio/plane-deploy`        | ONLY if the feature introduces a new env var or a new service/container.                                                            | New env var name, default value, purpose, and which service reads it.                                                   |
| `The1Studio/helm-charts`         | ONLY if the feature introduces a new env var or a new service/container.                                                            | New Helm value name + corresponding env var; update the `values.yaml` reference.                                        |

---

## Classification Rule (three-tier)

```
generic Issue field?
    YES → plane-node-sdk + plane-python-sdk + docs + developer-docs
           (NO plane-mcp-server tool — generic issue create/update already covers it)

new non-generic endpoint?
    YES → plane-mcp-server (explicit tool) +
           plane-node-sdk + plane-python-sdk +
           plane-claude-plugin (if user-facing) +
           docs + developer-docs

new env var or service?
    YES → ADD plane-deploy + helm-charts to whichever tier above applies
```

**Decision evidence needed for "generic Issue field" vs "non-generic endpoint":**

A change is a **generic Issue field** only when it maps directly to an existing field on the
core `Issue` model (e.g. `assignees`, `priority`, `labels`, `state`, `due_date`) AND the
existing generic issue create/update endpoint can carry it without modification.

A change is a **non-generic endpoint** when:

- It introduces a new URL pattern (`path("api/<name>/", ...)`)
- It is on a fork-owned model (e.g. `WorkloadEstimate`, `SprintTrackerSession`)
- The existing generic issue endpoints cannot expose it

When ambiguous, treat it as non-generic (conservative: drafts more issues, which the user can
trim at the HARD-GATE step).

---

## Propagation Queue Format

The queue file is `.claude/plane-propagation-queue.md` in the repo root's `.claude/` directory.
It is **runtime state** created and written by `plane-scaffold-feature`. Do not create it
manually; `plane-propagate` reads it and appends a `Propagated:` line to processed entries.

### Expected entry format (written by `plane-scaffold-feature`)

```markdown
## <name> — <date YYYY-MM-DD>

- Feature: <one-sentence description>
- New endpoints: <list the URL patterns from urls.py / api_urls.py>
- New fields: <list any new fields exposed via serializers>
- Propagation needed: MCP tool in `plane-mcp-server`, SDK bindings in `plane-node-sdk` + `plane-python-sdk`, docs update
```

### After propagation (written by `plane-propagate`)

`plane-propagate` appends the following line to each processed block once all issues are opened:

```markdown
- Propagated: <date YYYY-MM-DD>
```

A block with `Propagated:` is considered done and is skipped on re-runs.

### Example (fully processed entry)

```markdown
## workload — 2026-06-15

- Feature: Time estimates (hours) per issue + per-person workload matrix.
- New endpoints: POST /api/workload/estimates/, GET /api/workload/estimates/<pk>/, GET /api/v1/workload/matrix/
- New fields: estimated_hours, actual_hours (on WorkloadEstimate model)
- Propagation needed: MCP tool in `plane-mcp-server`, SDK bindings in `plane-node-sdk` + `plane-python-sdk`, docs update
- Propagated: 2026-06-20
```

---

## Notes

- Sibling repos are all under `The1Studio/*` on GitHub. Use `gh issue create --repo The1Studio/<repo>` via `/t1k:issue`.
- Never clone or push to a sibling repo from this repo's session — only open issues/PRs there.
  Per `rules/kit-pr-workflow-boundary.md`: open in background, report URL, stop.
- `plane-deploy` and `helm-charts` are ONLY touched for new env vars/services — do not open
  issues there for pure code or model changes.
- `plane-claude-plugin` is only touched for features that expose a new Claude-usable capability —
  skip for internal-only APIs with no user-facing interaction model.

# Phase P4 — Propagation (standing rule)

**Goal:** propagate every new endpoint / behavior added by P1–P2 to the downstream surfaces
per the `CLAUDE.md` standing rule. **Tracked via sibling-repo issues only — do NOT edit sibling
repos from this repo's PR.**

**Effort:** S · **Blocks:** — · **Blocked by:** P1, P2.

> Sibling-repo gotcha (memory): `plane-mcp-server`, `plane-node-sdk`, `plane-python-sdk` are
> GitHub forks of `makeplane/*`. `gh issue create` WITHOUT `-R The1Studio/<name>` hits the
> public upstream. **Always pass `-R The1Studio/<name>`.**

---

## Surfaces to propagate

| Surface                                           | What to add                                                                                                                                                          | New API/behavior source                      |
| ------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------- |
| `plane-mcp-server`                                | Tool `list_work_item_github_links(issue)` (P1 links); tools `get_github_state_config` / `set_github_state_config` (global + per-project, P2 `StateTransitionConfig`) | P1 link rows; P2 `views/config.py` endpoints |
| `plane-node-sdk`                                  | Bindings: list github links; get/set state-transition config; typed `WorkItemGithubLink` + `StateTransitionConfig`                                                   | same                                         |
| `plane-python-sdk`                                | Same bindings, Python client                                                                                                                                         | same                                         |
| `plane-claude-plugin` / `docs` / `developer-docs` | Doc entry: webhook setup, branch-naming convention (`docs/github-branch-naming.md`), transition rules table                                                          | P0 App setup + P1 doc + P2 rules             |
| **This repo** `CLAUDE.md`                         | One line under "Custom features": `github_ext/` — GitHub↔Plane dev-workflow links + PR-driven status automation                                                      | —                                            |

---

## Concrete steps

1. **File issues** (background, one per sibling repo, `-R The1Studio/<name>`):
   - `plane-mcp-server`: "Add MCP tools for github_ext — list work-item GitHub links + get/set
     StateTransitionConfig" with the endpoint shapes from P1/P2.
   - `plane-node-sdk`: "Add bindings for github_ext link-list + state-transition-config".
   - `plane-python-sdk`: same for the Python client.
2. **Update `CLAUDE.md`** (this repo, in the P2 PR): add the "Custom features" line.
3. **Docs:** cross-link `docs/github-branch-naming.md` from `CLAUDE.md`; note webhook setup +
   least-privilege App perms in developer docs (issue on `developer-docs` if that repo owns it).

---

## Risk assessment (P4-local)

| Risk                                                     | L   | I   | Score | Mitigation                                                                                              |
| -------------------------------------------------------- | --- | --- | ----- | ------------------------------------------------------------------------------------------------------- |
| Issue filed on public upstream `makeplane/*` by mistake  | 3   | 4   | 12    | Always `gh ... -R The1Studio/<name>`; verify repo in the issue URL before closing the task.             |
| Propagation forgotten → feature "done" but MCP/SDK stale | 3   | 3   | 9     | P4 is a required phase (standing rule); DoD checklist includes all three issues filed + CLAUDE.md line. |
| Endpoint shape drifts between plan and implementation    | 2   | 2   | 4     | File the propagation issues AFTER P2 merges, referencing the merged endpoint signatures.                |

No P4 risk ≥ 15.

---

## Gates / Definition of Done

- 3 sibling-repo issues filed on `The1Studio/*` (verified repo in URL), each referencing the
  concrete P1/P2 endpoint shapes.
- `CLAUDE.md` "Custom features" line added in this repo.
- `docs/github-branch-naming.md` cross-linked.
- No sibling-repo code edited from this repo's PR.

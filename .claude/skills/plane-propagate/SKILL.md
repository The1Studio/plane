---
name: plane-propagate
description: Propagate a new fork feature to downstream sibling repos (MCP/SDK/docs) per the CLAUDE.md standing rule — draft sibling-repo issues, gate, open in background. Use for "propagate this feature", "update downstream repos", "open MCP/SDK issues for the new endpoint".
keywords: [propagate, downstream, mcp, sdk, sibling-repos, standing-rule, issues]
metadata:
  author: the1studio
  version: "1.0.0"
---

# plane-propagate

Propagate a new fork feature to downstream sibling repos by classifying new endpoints and fields,
drafting per-repo issues, hard-gating on confirmation, then opening each issue in a background
sub-agent. Implements the **CLAUDE.md STANDING RULE** — every new endpoint/field/feature must
reach MCP, SDKs, docs, and (if new env vars) deploy repos before the feature is called done.

**Policy citations (mandatory reading before acting):**

- `rules/workflow-gates.md` — universal HARD-GATE contract (gate failures stop the workflow).
- `rules/kit-pr-workflow-boundary.md` — open issues from a BACKGROUND sub-agent; report URL;
  STOP. Never edit a sibling repo from this repo's PR. Never offer to babysit/merge.
- `CLAUDE.md` §"STANDING RULE — every new feature must also update downstream surfaces".

---

## When to Use

Invoke this skill when the user wants to:

- Propagate a completed fork feature to all downstream sibling repos
- Open MCP/SDK/docs issues for a new endpoint or field
- Execute the CLAUDE.md standing rule after scaffolding a feature
- Ensure a new feature reaches `plane-mcp-server`, `plane-node-sdk`, `plane-python-sdk`,
  `plane-claude-plugin`, `docs`, and `developer-docs`
- Consume the `.claude/plane-propagation-queue.md` entries written by `plane-scaffold-feature`

Do NOT use this skill to:

- Actually implement MCP tools, SDK bindings, or doc pages (that belongs to the sibling repos)
- Edit files in any sibling repo from this repo's PR (rule: `kit-pr-workflow-boundary.md`)
- Merge or babysit sibling-repo issues/PRs once opened

---

## Activation

Activate automatically when the user's request contains any of these phrases:

- "propagate this feature"
- "update downstream repos"
- "open MCP/SDK issues for the new endpoint"
- "downstream propagation"
- "after-feature propagation"

---

## Decision Tree

Execute these steps in order. Do NOT skip steps or reorder them.

### Step 1 — Source the list of changes

Two sources (use whichever applies; prefer the queue when it exists):

**A. Queue file (primary):** read `.claude/plane-propagation-queue.md` — entries written by
`plane-scaffold-feature`. Each `## <name>` block contains:

- Feature name and description
- New endpoints (URL patterns from `urls.py` / `api_urls.py`)
- New fields (serializer fields exposed via the API)
- Propagation-needed note

**B. Branch diff (fallback when no queue entry exists):** run:

```bash
git diff main...HEAD -- "apps/api/plane/*/urls.py" "apps/api/plane/*/api_urls.py" \
                        "apps/api/plane/*/serializers.py"
```

Extract added URL patterns (`path(...)` lines) and added serializer fields from the diff.

If both sources are empty, ask the user which feature to propagate via `AskUserQuestion`.

### Step 2 — Classify each change against the sibling matrix

For each new endpoint or field, apply the three-tier classification rule:

| Change type                                                                                            | Surfaces touched                                                                                                                                            |
| ------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Generic Issue field (maps to an existing `Issue` model field — e.g. `assignees`, `priority`, `labels`) | `plane-node-sdk` + `plane-python-sdk` + `docs` + `developer-docs` only. NO `plane-mcp-server` tool.                                                         |
| New non-generic endpoint (a new URL that is NOT a generic Issue CRUD field)                            | ALL of: `plane-mcp-server` (explicit new tool) + `plane-node-sdk` + `plane-python-sdk` + `plane-claude-plugin` (if user-facing) + `docs` + `developer-docs` |
| New env var or service (new `settings` variable, new Docker service, new infra dependency)             | ADD: `plane-deploy` + `helm-charts` to whichever surfaces above already apply                                                                               |

Full matrix with issue content expectations: `references/sibling-repos.md`.

### Step 3 — Draft one issue body per affected sibling repo

For each sibling repo identified in Step 2, draft:

- **Title:** `[<feature-name>] <one-line description of work needed>` (e.g.
  `[workload] Add MCP tool for POST /api/workload/estimates/`)
- **Body:** include the source endpoint/field, the expected behavior, and a link back to this
  repo's feature PR if available. Keep the body concrete — the sibling maintainer must be able
  to act without asking for clarification.

Collect all (repo, title, body) tuples into a review list.

### Step 4 — HARD-GATE: confirm before opening

**See `<HARD-GATE>` block below. Do NOT proceed past this step without AskUserQuestion confirmation.**

Present the review list to the user. Format:

```
Repos to open issues on:
1. The1Studio/plane-mcp-server — "[workload] Add MCP tool for POST /api/workload/estimates/"
2. The1Studio/plane-node-sdk   — "[workload] Add TS binding for WorkloadEstimate"
3. The1Studio/plane-python-sdk — "[workload] Add Python binding for WorkloadEstimate"
4. The1Studio/docs             — "[workload] Document workload estimates endpoint"
5. The1Studio/developer-docs   — "[workload] Developer guide for workload estimates"
```

Ask: "Confirm opening these issues? (yes / adjust / abort)"

### Step 5 — Open issues in background sub-agents (on confirm only)

On user confirmation:

- Spawn ONE background sub-agent per issue using `/t1k:issue` pointed at the sibling repo.
- Each sub-agent receives: the target repo, issue title, and full body drafted in Step 3.
- Report each resulting URL as a single line: `Issue opened: <url>`
- **STOP after reporting URLs.** Per `rules/kit-pr-workflow-boundary.md`:
  - Do NOT offer to babysit the sibling-repo issue.
  - Do NOT push commits to a sibling repo.
  - Do NOT list sibling-repo follow-ups in "Next Steps".
  - If the user explicitly asks to babysit — instruct them to operate from the sibling repo's
    own clone session.

### Step 6 — Mark queue entries done

After all URLs are confirmed opened, update `.claude/plane-propagation-queue.md`:

Append `- Propagated: <date YYYY-MM-DD>` under each processed `## <name>` block so the queue
stays auditable and re-runs are idempotent.

---

<HARD-GATE>
## HARD-GATE — Before opening sibling-repo issues

**Cite:** `rules/workflow-gates.md` (universal contract) + `rules/kit-pr-workflow-boundary.md`.

**Condition:** The skill MUST NOT open ANY issue on a sibling repo before calling `AskUserQuestion`
with the exact repo-to-title list for user review and explicit confirmation.

**What must be present before the gate passes:**

1. The full list of (repo, title, body) tuples is drafted and shown to the user.
2. The user has answered "yes" (or equivalent explicit confirmation) to the AskUserQuestion prompt.
3. No issue has been opened yet.

**Override:** Explicit user confirmation ("yes", "go ahead", "open them all", or equivalent).
No other override is accepted — NOT a flag, NOT a prior instruction, NOT "the list looks fine".
The AskUserQuestion call in Step 4 is the gate mechanism.

**On gate failure (user says "adjust" or "abort"):**

- Adjust: revise the list per user feedback and re-present via AskUserQuestion.
- Abort: report "Propagation cancelled. Queue entries left open in .claude/plane-propagation-queue.md."
  Do NOT open any issue.

**Background-only rule (from `rules/kit-pr-workflow-boundary.md`):**
Issues MUST be opened via BACKGROUND sub-agents (one per repo). The parent skill session must
not block waiting for each issue to open — spawn all sub-agents, then collect URLs and report.
Never edit a sibling repo's files from this repo's PR. Never offer to babysit or merge.
</HARD-GATE>

---

## Sibling Matrix

Full matrix (repo, when to propagate, expected issue content) and the queue file format:
`references/sibling-repos.md`.

---

## Verify

After completing all steps, confirm:

- [ ] All relevant queue entries have been processed (or the user confirmed no entries were missed).
- [ ] HARD-GATE was satisfied: user confirmed the repo+title list before any issue was opened.
- [ ] Each issue was opened via a BACKGROUND sub-agent; URLs were reported one per line.
- [ ] `plane-propagation-queue.md` has `Propagated: <date>` appended to processed entries.
- [ ] No sibling-repo file was edited from this repo's session.
- [ ] No babysitting/merge was offered for sibling-repo issues.

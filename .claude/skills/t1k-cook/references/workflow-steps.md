---

origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---
# Unified Workflow Steps

All modes share core steps with mode-specific variations.

**Task Tool Fallback:** `TaskCreate`/`TaskUpdate`/`TaskGet`/`TaskList` are CLI-only — unavailable in VSCode extension. If they error, use `TodoWrite` for progress tracking. All workflow steps remain functional without Task tools.

## Step 0: Intent Detection & Setup

1. Parse input with `intent-detection.md` rules
2. Log detected mode: `✓ Step 0: Mode [X] - [reason]`
3. If mode=code: detect plan path, set active plan
4. Use `TaskCreate` to create workflow step tasks (with dependencies if complex)

**Output:** `✓ Step 0: Mode [interactive|auto|yolo|fast|parallel|no-test|code] - [detection reason]`

## Step 0.5: Drift Check — Recently-Merged Overlapping Work (MANDATORY before Step 1)

Before researching or planning, check whether the area you're about to touch has had recent merges. This applies in ANY repo — kit source, consumer game project, library, anywhere `t1k:cook` runs.

**Why:** if a teammate (or you, in a parallel session) merged a fix to the same files in the last few hours, your work might be a no-op duplicate, or worse, conflict with their fix. The 2026-05-14 cook on cli#143 caught a 6-hour-old merge (PR #153) that had partially fixed the same bug — turning what would have been a duplicate PR into a valuable follow-up that surfaced a latent prefix-stripping bug in the recently-merged fix.

**Procedure** (works for any git repo with a remote):

```bash
# 1. Sync with the remote (don't assume local main is current)
git fetch origin --quiet

# 2. List recent merges (last ~24h) on the default branch
DEFAULT_BRANCH=$(git symbolic-ref refs/remotes/origin/HEAD --short | sed 's@^origin/@@')
git log --oneline "origin/${DEFAULT_BRANCH}" --since='24 hours ago'
```

Then, for each issue/bug in the task description, also do:

```bash
# 3. If specific files are named in the task, check whether they were touched recently
git log --oneline "origin/${DEFAULT_BRANCH}" --since='24 hours ago' -- <file-paths-from-task>

# 4. If a specific GitHub issue is referenced, also check whether a PR resolving it already merged
gh pr list --repo <owner>/<repo> --state merged --search "<issue-number>" --limit 5 2>/dev/null
```

**Decision tree based on findings:**

| Finding | Action |
|---|---|
| No recent merges touching the affected files | Proceed to Step 1 normally |
| A recent merge resolves the same issue → fix has already shipped | STOP — close the task with `cant-repro` / `already-fixed` evidence; do NOT open a PR. Reference the resolving PR in your report. |
| A recent merge touches the same files but for a different concern | Proceed, but rebase on origin's default branch BEFORE starting work to avoid downstream conflicts. Note the recent merge in your plan in case it interacts with your fix. |
| A recent merge partially addresses the same issue | Re-scope your fix to the remaining gap. Cite the recently-merged PR as the "first half" and explain what's still broken. This is a follow-up PR, not a duplicate. |

**Output:** `✓ Step 0.5: Drift check — [N] recent merges, [0/some/all] touch affected files, decision: [proceed | rebase-and-proceed | stop-already-fixed | refile-as-followup]`

**Failure mode this prevents:** the cook agent opens a PR that the user can't tell is a duplicate of work that just merged. Triage then has to spot the dup. With Step 0.5, dups are caught at the cooking session — saving the round-trip.

**Non-git repos:** if the current directory has no `.git/`, skip this step and log `✓ Step 0.5: skipped — not a git repo`.

**No remote configured:** if `git remote -v` returns empty, skip with `✓ Step 0.5: skipped — no remote configured`.

## Step 1: Research (skip if fast/code mode)

**Interactive/Auto:**
- Spawn multiple `t1k-researcher` agents in parallel
- Use `/t1k:scout ext` or `scout` agent for codebase search
- Keep reports ≤150 lines

**Parallel:**
- Optional: max 2 researchers if complex

**Output:** `✓ Step 1: Research complete - [N] reports gathered`

### [Review Gate 1] Post-Research (skip if auto mode)
- Present research summary to user
- Use `AskUserQuestion` to ask: "Proceed to planning?" / "Request more research" / "Abort"
- **Auto / Yolo mode:** Skip this gate (Yolo: if the gate would have asked anything, record it to the deferred-decisions log per `yolo-mode.md`)

## Step 2: Planning

**Interactive/Auto/No-test:**
- Use `t1k-planner` agent with research context
- Create `plan.md` + `phase-XX-*.md` files

**Fast:**
- Use `/t1k:plan --fast` with scout results only
- Minimal planning, focus on action

**Parallel:**
- Use `/t1k:plan --parallel` for dependency graph + file ownership matrix

**Code:**
- Skip - plan already exists
- Parse existing plan for phases

**Output:** `✓ Step 2: Plan created - [N] phases`

### [Review Gate 2] Post-Plan (skip if auto mode)
- Present plan overview with phases
- Use `AskUserQuestion` to ask: "Validate the plan or approve plan to start implementation?" - "Validate" / "Approve" / "Abort" / "Other" ("Request revisions")
  - "Validate": run `/t1k:plan validate` skill invocation
  - "Approve": continue to implementation
  - "Abort": stop the workflow
  - "Other": revise the plan based on user's feedback
- **Auto / Yolo mode:** Skip this gate (Yolo: if the gate would have asked anything, record it to the deferred-decisions log per `yolo-mode.md`)

## Step 3: Implementation

**IMPORTANT:**
1. `TaskList` first — check for existing tasks (hydrated by planning skill in same session)
2. If tasks exist → pick them up, skip re-creation
3. If no tasks → read plan phases, `TaskCreate` for each unchecked `[ ]` item with priority order and metadata (`phase`, `planDir`, `phaseFile`)
4. Tasks can be blocked by other tasks via `addBlockedBy`

**All modes:**
- Use `TaskUpdate` to mark tasks as `in_progress` immediately.
- Execute phase tasks sequentially (Step 3.1, 3.2, etc.)
- Use `ui-ux-designer` for frontend
- Use `t1k:extended-multimodal` for image assets
- Run type checking after each file

**Parallel mode:**
- Utilize all tools of Claude Tasks: `TaskCreate`, `TaskUpdate`, `TaskGet` and `TaskList`
- Launch multiple `t1k-fullstack-developer` agents
- When agents pick up a task, use `TaskUpdate` to assign task to agent and mark tasks as `in_progress` immediately.
- Respect file ownership boundaries
- Wait for parallel group before next

### Step 3 HARD-GATE — Runtime Smoke for Scene/Prefab Edits

If this phase's changeset includes any of `**/*.unity`, `**/*.prefab`, `**/*.asset` (Unity), `**/*.scene` (Cocos), or `**/*.tscn`/`**/*.tres` (Godot), the implementer sub-agent MUST execute a runtime smoke and report Play Mode / runtime console output BEFORE Step 3 can be reported done. Edit-mode "Console clean" is INSUFFICIENT evidence.

- Unity: delegate to `t1k-unity-editor-playtest --quick` (Checks 1–3) → paste `read_console(filter: "Error")` output from Play Mode.
- Cocos: delegate to `t1k-cocos-runtime-smoke` (if installed) → paste preview-build runtime console.
- Other engines: see `references/runtime-smoke-gate.md`.
- If runtime is unreachable (MCP down, no Editor connection): STOP and escalate via `AskUserQuestion`. Do NOT declare done. (Yolo: an unreachable runtime is an unverifiable-correctness blocker, not a policy question — yolo still STOPS here and surfaces it; it does not assume-and-proceed past a correctness gate.)

The Step 3 sub-agent prompt MUST inject the runtime-smoke clause from `references/runtime-smoke-gate.md` § "Sub-agent prompt injection" when scene/prefab edits occurred. Reporting only edit-mode console for a scene/prefab change is a workflow violation (ref: The1Studio/theonekit-core#176).

**Output:** `✓ Step 3: Implemented [N] files - [X/Y] tasks complete` (append `- runtime smoke: <pass|n/a>` when the gate fired)

### [Review Gate 3] Post-Implementation (skip if auto mode)
- Present implementation summary (files changed, key changes)
- Use `AskUserQuestion` to ask: "Proceed to testing?" / "Request implementation changes" / "Abort"
- **Auto / Yolo mode:** Skip this gate (Yolo: if the gate would have asked anything, record it to the deferred-decisions log per `yolo-mode.md`)

## Step 4: Testing (skip if no-test mode)

**All modes (except no-test):**
- Write tests: happy path, edge cases, errors
- **MUST** spawn `t1k-tester` subagent: `Task(subagent_type="t1k-tester", prompt="Run test suite", description="Run tests")`
- If failures: **MUST** spawn `t1k-debugger` subagent → fix → repeat
- **Forbidden:** fake mocks, commented tests, changed assertions, skipping subagent delegation

**Output:** `✓ Step 4: Tests [X/X passed] - t1k-tester subagent invoked`

### [Review Gate 4] Post-Testing (skip if auto mode)
- Present test results summary
- Use `AskUserQuestion` to ask: "Proceed to code review?" / "Request test fixes" / "Abort"
- **Auto / Yolo mode:** Skip this gate (Yolo: if the gate would have asked anything, record it to the deferred-decisions log per `yolo-mode.md`)

## Step 5: Code Review

**All modes - MANDATORY subagent:**
- **MUST** spawn the resolved `reviewer` role (default `t1k-code-reviewer`) using the full brief template in `subagent-patterns.md` § "Code Review" — it declares the report path AND injects acceptance criteria + touchpoints + contracts. A bare `prompt="Review changes"` is a violation: it strands the reviewer on its mandatory report-path `AskUserQuestion` and leaves `review-decision.json`'s required `acceptanceCoverage`/`regressionProof`/`contractStatus` ungrounded.
- **DO NOT** review code yourself - delegate to subagent

**Interactive/Parallel/Code/No-test:**
- Interactive cycle (max 3): see `review-cycle.md`
- Requires user approval

**Auto / Yolo:**
- Auto-approve if score≥9.5 AND 0 critical
- Auto-fix critical (max 3 cycles)
- After 3 failed cycles: Auto escalates to user immediately; Yolo records the unresolved review to the deferred-decisions log and surfaces it in the end-of-run batch (it still does NOT ship a critical-blocked change — the no-side-effects correctness gate holds)

**Fast:**
- Simplified review, no fix loop
- User approves or aborts

**Output:** `✓ Step 5: Review [score]/10 - [Approved|Auto-approved] - t1k-code-reviewer subagent invoked`

## Step 6: Finalize

**All modes - MANDATORY subagents (NON-NEGOTIABLE):**
1. **MUST** spawn these subagents in parallel:
   - `Task(subagent_type="t1k-project-manager", prompt="Run full sync-back for [plan-path]: reconcile all completed Claude Tasks with all phase files, backfill stale completed checkboxes across every phase, then update plan.md frontmatter/table progress. Do NOT only mark current phase.", description="Update plan")`
   - `Task(subagent_type="t1k-docs-manager", prompt="Update docs for changes.", description="Update docs")`
2. Project-manager sync-back MUST include:

### Status Sync (Finalize)

Use CLI commands for deterministic status updates:

```bash
# Mark completed phases
ck plan check <phase-id>

# Mark in-progress phases
ck plan check <phase-id> --start

# Revert if needed
ck plan uncheck <phase-id>
```

**Fallback:** If `ck` is not available, edit plan.md directly —
only change the Status column cell, preserve table structure.
   - Sweep all `phase-XX-*.md` files in the plan directory.
   - Mark every completed item `[ ] → [x]` based on completed tasks (including earlier phases finished before current phase).
   - Update `plan.md` status/progress (`pending`/`in-progress`/`completed`) from actual checkbox state.
   - Return unresolved mappings if any completed task cannot be matched to a phase file.
3. Use `TaskUpdate` to mark Claude Tasks complete after sync-back confirmation.
4. Onboarding check (API keys, env vars)
5. **MUST** spawn git subagent: `Task(subagent_type="t1k-git-manager", prompt="Stage and commit changes", description="Commit")`

**CRITICAL:** Step 6 is INCOMPLETE without spawning all 3 subagents. DO NOT skip subagent delegation.

**Auto / Yolo mode:** Continue to next phase automatically, start from **Step 3**.
**Others:** Ask user before next phase

**Yolo — end-of-run batch (after the FINAL phase, before the commit offer):** if the deferred-decisions log has any entries, surface them all at once via a single `AskUserQuestion` (or a clearly-labelled "Deferred decisions" report section if `AskUserQuestion` is unavailable) so the user can correct any assumption before the irreversible finalize. High-risk finalize actions (push / PR / ship) recorded during the run are presented here for explicit go-ahead — they are never executed silently. Empty log → state "no deferred decisions" and proceed to the commit offer. See `yolo-mode.md`.

**Output:** `✓ Step 6: Finalized - 3 subagents invoked - Full-plan sync-back completed - Committed`

## Mode-Specific Flow Summary

Legend: `[R]` = Review Gate (human approval required)

```
interactive: 0 → 1 → [R] → 2 → [R] → 3 → [R] → 4 → [R] → 5(user) → 6
auto:        0 → 1 → 2 → 3 → 4 → 5(auto) → 6 → next phase (NO stops)
yolo:        0 → 1 → 2 → 3 → 4 → 5(auto) → 6 → next phase (NO stops; every deferred question batched at end-of-run before commit)
fast:        0 → skip → 2(fast) → [R] → 3 → [R] → 4 → [R] → 5(simple) → 6
parallel:    0 → 1? → [R] → 2(parallel) → [R] → 3(multi-agent) → [R] → 4 → [R] → 5(user) → 6
no-test:     0 → 1 → [R] → 2 → [R] → 3 → [R] → skip → 5(user) → 6
code:        0 → skip → skip → 3 → [R] → 4 → [R] → 5(user) → 6
```

**Key difference:** `auto` and `yolo` are the only modes that skip all review gates. `yolo` additionally never stops to ask mid-flow — it records each would-be question and batches them at the end of the run (`yolo-mode.md`).

## Critical Rules

- Never skip steps without mode justification
- **MANDATORY SUBAGENT DELEGATION:** Steps 4, 5, 6 MUST spawn subagents via Task tool. DO NOT implement directly.
  - Step 4: role `tester` (default `t1k-tester`), role `debugger` (default `t1k-debugger`) if failures
  - Step 5: role `reviewer` (default `t1k-code-reviewer`)
  - Step 6: roles `project-manager`, `docs-manager`, `git-manager` (defaults `t1k-project-manager`, `t1k-docs-manager`, `t1k-git-manager`)
  - **For each Task call, resolve `subagent_type` from `.t1k-resolved-config.json` → `routing.roles.<role>` before invoking.** See `references/subagent-patterns.md` § "Routing Resolution". The default names above apply only when no higher-priority routing fragment overrides the role.
- Use `TaskCreate` to create Claude Tasks for each unchecked item with priority order and dependencies (or `TodoWrite` if Task tools unavailable).
- Use `TaskUpdate` to mark Claude Tasks `in_progress` when picking up a task (skip if Task tools unavailable).
- Use `TaskUpdate` to mark Claude Tasks `complete` immediately after finalizing the task (skip if Task tools unavailable).
- All step outputs follow format: `✓ Step [N]: [status] - [metrics]`
- **VALIDATION:** If Task tool calls = 0 at end of workflow, the workflow is INCOMPLETE.

## --tdd Flag Behavior

When `--tdd` is active, **Step 3 (Implement) is decomposed** into three sub-steps per phase:

### Step 3.T — Write tests first
Write tests for the target behavior BEFORE writing any implementation code. Run the new tests immediately. They MUST fail initially (red phase). If any new test passes on first run without implementation changes, the test is not exercising the intended behavior — revise or delete it.

### Step 3.I — Implement minimum to pass
Write the minimum code required to make the Step 3.T tests pass. Do not add speculative features or pre-optimizations. Commit to the single responsibility of making the failing tests green.

### Step 3.V — Verify full suite
Run the full test suite (not just the new tests). Every test must pass (green). If any pre-existing test breaks, STOP and triage before proceeding. Do not advance to Step 4 until the full suite is green.

After Step 3.V passes → continue to Step 4 (full test run, no-op if already green) → Step 5 → Step 6.

### Guards and Incompatibilities

- `--tdd + --parallel`: REFUSE. Parallel execution cannot preserve the T→I→V ordering across concurrent phases. Error: "TDD requires strict ordering (tests → implement → verify); parallel execution cannot preserve this. Use `--tdd` alone, or `--parallel` without `--tdd`."
- `--tdd + --no-test`: REFUSE. TDD mode inherently requires the test suite; `--no-test` is contradictory.
- `--tdd + --fast`: ALLOWED. Fast mode skips research but preserves TDD ordering within Step 3.
- `--tdd + --auto`: ALLOWED. Auto mode skips review gates but still runs TDD within each phase.
- `--tdd + --yolo`: ALLOWED. Yolo defers gates/questions but still runs TDD ordering within each phase; the red→green→verify steps are correctness gates and are never skipped.

### Example Invocations

```
/t1k:cook "add JWT refresh endpoint" --tdd
/t1k:cook plans/260411-auth/ --tdd --fast
/t1k:cook "refactor auth module" --tdd --auto
```

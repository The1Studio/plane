---

origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---
# Workflow Artifact Gate — Rules

Shared rules referenced by `t1k-cook` and `t1k-fix` SKILL.md. Single source of truth for the harness contract.

## How to invoke

After implementing (cook) or verifying (fix), write the 5 required artifacts into the active artifact dir (resolve via `.claude/workflow-artifacts.json` pointer or `$T1K_WORKFLOW_ARTIFACT_DIR`), then validate:

```bash
node "$CLAUDE_PROJECT_DIR/.claude/hooks/workflow-artifact-gate.cjs" \
  --stage finalize --artifact-dir <dir>
```

For hard-stage actions (push / pr / ship / deploy), the gate fires automatically via the PreToolUse:Bash hook — no manual invocation needed.

## Required artifacts (5)

The gate validates these shapes with **inlined validators** in
`.claude/hooks/workflow-artifact-gate/artifact-schema.cjs` — that file is the
authority at runtime. Matching JSON Schema files exist in the source repo under
`.claude/schemas/workflow-artifact-*.schema.json` as an authoring reference, but
they are **repo-only**: no module ships `schemas/`, nothing loads them at
runtime, and a consumer install has no such directory (#785).

| File | Purpose |
|---|---|
| `context-snippets.json` | task, acceptance criteria, touchpoints, public contracts, blast radius, scout summary |
| `risk-gate.json` | high-risk flag, reason, auto-stop required, human approved, large-diff flag |
| `verification.json` | commands run with pass/fail/exit-code/timestamp/summary; before/after diff |
| `review-decision.json` | PASS / PASS_WITH_RISK / BLOCKED, advisory score, critical count, acceptance coverage, regression proof, contract status |
| `adversarial-validation.json` | PASS / PASS_WITH_RISK / BLOCKED, disproven claims, unverified claims, missing proof, reachable regressions |

## Approval rules

- **Score alone NEVER auto-approves.** Score is advisory; the validator decides.
- Any critical issue (`review-decision.json` `criticalCount > 0` or `decision: BLOCKED`) blocks.
- Hard stages (`ship`, `push`, `pr`, `deploy`) require **all 5 artifacts** + `decision: PASS` (review) + `decision: PASS` (adversarial).
- `PASS_WITH_RISK` may continue on soft stages with the risk surfaced; on hard stages it blocks.
- Auto mode + `highRisk: true` → human approval required even though `--auto` is set.
- Yolo mode + `highRisk: true` → do NOT block mid-flow: reversible work proceeds, but the irreversible finalize (commit / push / pr / ship) is recorded to the deferred-decisions log and surfaced in the end-of-run batch for explicit go-ahead — never executed silently. Correctness gates (5 artifacts PASS, no critical) are never bypassed in either mode. See `yolo-mode.md`.
- Artifact generation fails → retry once → escalate. **Never bypass.**

## Hook behavior

- Wired into `PreToolUse:Bash` so hard-stages (`git push`, `gh pr create`, `wrangler deploy`, etc.) check artifacts automatically.
- **Fail-open on crash.** A bug in the gate never blocks legitimate work.
- **Defence in depth, not perimeter.** The gate is one of multiple gates; do not rely on it alone for security.
- Global-only mode: if cwd has no `.claude/`, the gate silently no-ops (it doesn't surprise-block in non-T1K directories).
- **No workflow in flight → no-op (#673).** When nothing resolves an artifact dir — no `--artifact-dir` flag, no env var, no `.claude/workflow-artifacts.json` pointer, and no recent `plans/**/reports/harness/` dir — no gated workflow ever started, so there is nothing to validate and the gate exits silently. It does *not* report `missing-dir`. The moment `/t1k:cook` or `/t1k:fix` writes the pointer or a harness dir, every gate below applies unchanged. Manual CLI mode still validates: an operator asking for a report wants the report.
- **Hard blocks are opt-in (#673).** By default a failed hard stage reports `ADVISORY` and exits 0. Set `workflowArtifactGate.blockOnHardStage: true` in a `t1k-config-*.json` fragment to make it refuse the command (exit 2) instead. Findings are identical either way — advisory means *reported*, not *dropped*. The default flipped because a gate that fires on projects outside its own workflow trains people to disable it wholesale, and the three disable mechanisms below are all-or-nothing: the only available response to one false block was switching the gate off entirely.
- **Config resolution falls back to global (#673).** `loadGateConfig` reads every `t1k-config-*.json` in `<cwd>/.claude/`; if none declares a `workflowArtifactGate` key it falls back to the global install's `~/.claude/` fragments. Previously a project shipping only an engine-kit fragment merged to `{}`, so `enabled: false` could not short-circuit and `hardStages` silently fell through to the built-in list. Project config still wins whenever it declares a gate block.
- Explicit cross-repo PR operations (for example, `gh pr create --repo
  The1Studio/theonekit-cocos` from a consumer project) skip the consumer's
  artifact harness only when every shell segment is a `gh pr` operation, every
  target is a static literal naming a repo different from the current origin,
  and no other workflow stage is present. Dynamic targets, command
  substitutions, same-repo/implicit targets, and mixed commands remain gated.

### Disable mechanisms (#337)

Prefer `blockOnHardStage: false` (the default since #673) over these: it keeps the
findings visible while letting the command through. The three paths below silence
the gate entirely and are the right tool only when you want no output at all.

Three independent disable paths — ANY truthy result short-circuits the gate. Each one emits a stderr line naming the source so operators notice stale flags:

| Mechanism | Path | Subagent-survivable? |
|---|---|---|
| settings.json | `<cwd>/.claude/settings.json` → `t1k.workflowArtifactGate.disabled: true` (or `~/.claude/settings.json` for global) | YES — settings are walked by every subagent that traverses the tree |
| File marker | `<cwd>/.claude/t1k-artifact-gate.disabled` or `~/.claude/t1k-artifact-gate.disabled` (empty file, presence-only) | YES — file on disk survives process boundaries |
| Env var (legacy) | `T1K_WORKFLOW_ARTIFACT_GATE_DISABLED=1` | **NO** — parent-shell-only; does NOT propagate through the sub-agent spawn harness. Use settings or file marker for batch tooling that fans out subagents (e.g. `/t1k:triage --yolo`). |

## Engine kit extension

Engine kits (Unity, Cocos, RN, Web, Designer, Nakama) can extend the gate via `t1k-config-{kit}.json` fragments:

```json
{
  "workflowArtifactGate": {
    "hardStages": ["unity-build"],
    "commandPatterns": [
      { "stage": "deploy", "pattern": "\\bxvfb-run\\s+Unity\\s+-buildTarget\\b" }
    ]
  }
}
```

- `hardStages` array entries are **union-merged** with the base set (additive, not override).
- `commandPatterns` entries are evaluated AFTER built-in patterns. Each entry must have `stage` (string) + `pattern` (regex string, case-insensitive).
- Malformed regex is silently ignored — never crashes the gate.
- **Quote-stripping pre-processing (#324 item 9):** before matching, the detector strips single- and double-quoted strings from the command (so `echo "git push origin main"` is not flagged as a push). A pattern that tries to match content **inside** quotes will therefore never fire — e.g. `"pattern": "kubectl\\s+\\"apply\\""` matches nothing, because the quoted `"apply"` is removed before your regex runs. Write patterns against the **un-quoted** command tokens (`"pattern": "\\bkubectl\\s+apply\\b"`).

## Manual fallback

If the gate misfires or you need to inspect artifact state:

```bash
# Verbose human-readable output
node "$CLAUDE_PROJECT_DIR/.claude/hooks/workflow-artifact-gate.cjs" \
  --stage <ship|push|pr|deploy|commit|finalize> \
  --artifact-dir <dir>

# Machine-readable JSON
node "$CLAUDE_PROJECT_DIR/.claude/hooks/workflow-artifact-gate.cjs" \
  --stage <stage> --artifact-dir <dir> --json
```

Exit codes: `0` = pass or warn (non-hard stage), `2` = block.

## Why this exists

Score-based auto-approval ("review says 9.6/10, ship it") is the model grading itself — a known failure mode of long-context Opus 4.7 sessions. Artifact-gated approval forces the model to **leave evidence** before moving on. Harness engineering: build a frame that constrains hope. Reference: CK author's 2026-05 post on `/ck:fix` and `/ck:cook` v2.x.

## Related

- `.claude/hooks/workflow-artifact-gate.cjs` — gate implementation
- `.claude/hooks/workflow-artifact-gate/{validator,stage-detector,artifact-locator,artifact-schema}.cjs` — sub-modules
- `.claude/schemas/workflow-artifact-*.schema.json` — 5 JSON Schemas, **source repo only** (not shipped; the runtime authority is `artifact-schema.cjs`)
- `.claude/t1k-config-base.json` — base gate config


## Installation (post-upgrade — required for consumers)

When `workflow-artifact-gate` is added to `t1k-base` (PR #322 / v1.124.x), existing consumers MUST run **`t1k init --sync`** after `t1k modules update` so the new `PreToolUse:Bash` hook entry lands in their installed `.claude/settings.json`. Per `docs/hook-deployment-caveat.md` (#259) `t1k modules update` ships skill bodies but does NOT remerge `settings.json` — without `--sync` the gate is dead on hard-stage Bash commands (`git push`, `gh pr create`, deploys) even though SKILL.md instructions are visible.

Symptom of missed sync: `git push` succeeds with no artifact validation, score-vs-evidence drift returns silently. Detect with:

```bash
jq '.hooks.PreToolUse[].hooks[] | select(.command | contains("workflow-artifact-gate"))' .claude/settings.json
# empty output → sync needed
```

Closes #325.

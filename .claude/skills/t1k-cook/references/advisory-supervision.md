---

origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---
# Advisory Supervision (`--advice`) — Shared Contract

SSOT for the `--advice` flag across every TheOneKit skill that supports it
(`t1k:cook`, `t1k:plan`, `t1k:fix`, `t1k:brainstorm`, `t1k:review`, `t1k:docs`,
`t1k:triage`). Skill bodies cite this file and add only their own checkpoint
list — they never restate the contract below.

## What `--advice` does

Runs the host skill under **`t1k-kongming`** supervision. `t1k-kongming` is an
advisory-only supervisor: it returns counsel, never code. The main agent stays
responsible for every decision, edit, and gate.

`--advice` is **composable** with every other flag of the host skill and changes
no execution mode. It adds a supervisor; it removes nothing.

## Invocation

```
Agent(subagent_type="t1k-kongming",
      description="advice: <checkpoint>",
      prompt="<task, evidence, approaches tried, the exact question>")
```

Per `rules/agent-name-is-identity.md`: `subagent_type` is the identity
(`t1k-kongming`, never a task phrase); the checkpoint goes in `description`.

Give it enough context to answer in **one reply** — it does not interview and
never asks a question back. Per `rules/lean-brief-pointer-not-payload.md`, pass
**paths** to plans, diffs, and reports rather than pasting their bodies; paste
verbatim only exact identifiers (SHAs, PR numbers, file:line, flag values) and
the one constraint it would otherwise have to guess.

## Universal checkpoints

Every `--advice`-capable skill fires these three. Skill-specific checkpoints are
additive, listed in the skill body.

- **After each phase, step, or gate completes** — pass the goal, what changed or
  was concluded, and the evidence; ask for a go/no-go and the next risk to watch
  before continuing.
- **When stuck** — repeated failures (the 3+-failed-attempt gate in
  `rules/workflow-gates.md`), a blocked step, or contradictory evidence; pass
  everything already tried and the exact obstacle **before** questioning the
  architecture with the user.
- **Before a high-stakes decision** — a design fork, a public-contract or
  security-sensitive change, or an irreversible action; get counsel first.

## Forward-carry across handoffs

When the host skill hands off to another skill (`t1k:plan` → `t1k:cook`,
`t1k:cook` → `t1k:test`/`t1k:review`, `t1k:fix` → `t1k:ship`, any re-invocation
of the same skill), **pass `--advice` along** so supervision persists across the
handoff. Dropping the flag at a handoff silently ends supervision mid-workflow.

## PR gate (fires when the workflow reaches a PR)

Once a PR is open: watch and fix CI until every required check is terminal-green,
then spawn `t1k-kongming` to review the whole implementation (diff + PR body +
linked issue when one exists) and post its assessment plus concrete next steps as
a comment on the PR and on the source issue.

This gate fires **once per PR**, on that PR's CI-green transition — not per
fix-loop iteration. If CI is red, pending, or unavailable, skip it and state the
reason in the final output. Do not claim it ran.

Consumer-repo boundary still applies: opening a PR on a `theonekit-*` kit repo
from a consumer project does not authorize merging or babysitting it
(`rules/kit-pr-workflow-boundary.md`).

## Empty-counsel fallback (MANDATORY)

If `t1k-kongming` returns an empty final message, errors, is unreachable, or the
agent is not installed (a `t1k-base`-only install without the agent registered),
**record the failure in chat and continue** the host workflow. Never fail the
whole skill on a missing advisory step, and never silently pretend the checkpoint
ran.

Per `rules/agent-registry-snapshotted-at-session-start.md`: an agent added during
this session is not spawnable until the session restarts. If `t1k-kongming` was
just installed, say so instead of retrying.

## What `--advice` never does

`--advice` adds supervision. It never bypasses the host skill's approval gates,
`HARD-GATE` blocks, tests, review blockers, branch protections, issue-claim
discipline, or security policy. Where the host skill's verdict is authoritative
(e.g. `t1k:review` findings and severities), kongming counsel **informs** the
write-up and the decision — it does not override the verdict, and it is not a
veto either way.

## Final output requirement

Any run with `--advice` reports, in its final summary: how many kongming
checkpoints fired, whether the PR gate posted or was skipped (with reason), and
any advice-flagged risk that changed scope or a decision.

## Related

- `rules/agent-name-is-identity.md` — identity vs task in a spawn
- `rules/lean-brief-pointer-not-payload.md` — pass paths, not payloads
- `rules/workflow-gates.md` — the HARD-GATE contract `--advice` must not bypass
- `rules/agent-anti-rationalization.md` — evidence before claims
- `skills/t1k-advise/SKILL.md` — the interview-driven sibling (`t1k-advisor`),
  for reframing a fuzzy problem with the user rather than supervising a workflow

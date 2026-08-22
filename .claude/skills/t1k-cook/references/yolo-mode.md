---

origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---
# `--yolo` Mode — Maximum Autonomy, Ask Later

`--yolo` is `--auto` plus one rule: **never stop to ask — defer every question to a single end-of-run batch.** It is the most-autonomous cook mode. Use it when the user wants the whole task driven to completion without mid-flow check-ins and is willing to review/correct assumptions at the end.

This mirrors the established yolo doctrine in `/t1k:triage`: **yolo bypasses policy / human-decision gates only — it NEVER bypasses correctness gates.**

## The two gate classes

| Gate class | Examples | Yolo behavior |
|---|---|---|
| **Policy / human-decision** (a judgment call with no single right answer) | HARD-GATE-EXACT-REQUIREMENTS up-front 5 questions · review-gate approvals · "which approach?" · high-risk finalize go-ahead | **Defer.** Make the most conservative reasonable pick, log it, proceed; surface at end-of-run. |
| **Correctness** (verifiable right/wrong) | 100% test pass · artifact-gate validation (5 artifacts PASS) · mandatory `t1k-code-reviewer` · the 5 no-side-effects proofs · runtime-smoke gate · "is the runtime reachable?" | **Enforce, never skip.** A correctness blocker still STOPS yolo — it is not a question to defer. |

If you cannot classify a gate, treat it as **correctness** (enforce, don't defer). Erring toward enforcement is the safe default.

## Conservative-Pick — how to answer a deferred question yourself

When a policy gate would have asked, choose the option that is:

1. **Most reversible** — prefer a change you can cleanly undo over one you can't.
2. **Smallest blast radius** — narrowest scope that still satisfies the task.
3. **Most consistent with existing code** — match the patterns/conventions surfaced by scout, not a novel approach.
4. **Most backward-compatible** — don't break a public contract when a non-breaking path exists.

Then write a one-line record (below) and move on. Never invent requirements the task doesn't imply — if the task is genuinely under-specified on a point with no conservative default, that point is a deferred question, not an assumption.

## Deferred-decisions log

Maintain a running log across the whole run (in-session; also write it into the finalize report). One entry per deferred decision:

```
- [gate] <which gate/step> | assumed: <the Conservative-Pick taken> | because: <1-line rationale> | reversible: <yes|no> | revisit-cost: <low|med|high>
```

Tag high-risk / irreversible finalize items (`reversible: no`) — these are presented for explicit go-ahead in the end-of-run batch, never executed silently.

## End-of-run batch (after the FINAL phase, before the commit offer)

1. If the log is empty → state "no deferred decisions" and proceed to the normal commit offer.
2. Otherwise surface ALL entries at once via a single `AskUserQuestion` (batch up to 4 options per call; if `AskUserQuestion` is unavailable, emit a clearly-labelled **Deferred decisions** report section and proceed only on the reversible items).
3. Order the batch by `revisit-cost` descending and `reversible: no` first — the costliest-to-undo assumptions get the user's attention first.
4. Any irreversible finalize (push / PR / ship) recorded during the run is gated on explicit go-ahead here.
5. Apply corrections the user makes, then finalize.

## What yolo does NOT change

- The plan-before-code HARD-GATE still holds (yolo plans; only `--fast` skips research).
- Scout-first still runs.
- All mandatory subagents (test / review / finalize) still spawn — a 0-Task workflow is still INCOMPLETE.
- The artifact gate still validates the 5 artifacts; hard-stage Bash is still gated.

## Flag interactions

| Combo | Result |
|---|---|
| `--yolo` + `--auto` | Treat as `--yolo` (strict superset). |
| `--yolo` + `--interactive` | REFUSE — contradictory (max-autonomy vs stop-at-every-gate). |
| `--yolo` + `--tdd` | ALLOWED — yolo defers gates; tdd ordering (red→green→verify) is a correctness gate, preserved. |
| `--yolo` + `--parallel` | ALLOWED — yolo governs gate-deferral, parallel governs execution. (`--tdd + --parallel` stays refused.) |
| `--yolo` + `--no-test` | ALLOWED but discouraged — `--no-test` downgrades the all-tests-pass proof to a warning (surfaced in the end-of-run batch); the other 4 no-side-effects proofs still hold. |

## Anti-patterns

- Deferring a **correctness** failure ("tests red, I'll note it and ship") — never. Correctness blockers STOP yolo.
- Executing an irreversible finalize (push/PR/ship) silently because "yolo means just do it" — irreversible high-risk actions are batched for explicit go-ahead.
- Inventing requirements to avoid a deferred-question entry — under-specified with no conservative default IS a deferred question.
- Skipping the end-of-run batch when the log is non-empty.

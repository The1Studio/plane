---

origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---
# t1k-fix — Issue Claim Gate (full procedure)

Fires ONLY when a target GitHub issue is supplied. Before running Scout or Diagnose, check and acquire a claim on the issue via the SSOT script — never run `gh issue edit` or `gh pr create` for claiming yourself. Full enforcement rule: `rules/issue-claim-discipline.md`.

```bash
node .claude/scripts/t1k-issue-claim.cjs check <owner/repo#N>
```

Read the emitted JSON `state` field:

| state | Action |
|---|---|
| `"held"` (foreign holder) | **HARD BLOCK.** Surface `holder` + `prNumber`. Instruct user to re-run with `--steal` if they want to override. Do NOT proceed to Scout/Diagnose. |
| `"free"` OR `--steal` flag given | Run `acquire`: `node .claude/scripts/t1k-issue-claim.cjs acquire <owner/repo#N>`. Use the returned `markerLine`, `bodyTrailer` (`Fixes #N`), and `labelToApply` when opening the WIP draft PR — the draft PR IS the durable claim. |
| `"skip"` | Out-of-scope repo or no config. Proceed normally without claiming. |
| `"stale"` | A foreign draft PR is stale (inactive > config threshold). Proceed as `free`; the stale holder is reported only, not a blocker. |

**After opening the WIP draft PR — tie-break re-check (mandatory):** the moment the draft PR exists, run the deterministic tie-break so a sub-second double-acquire can't leave two open PRs on the issue:

```bash
node .claude/scripts/t1k-issue-claim.cjs acquire <owner/repo#N> --pr <newPrNumber>
```

If a lower-numbered claim PR by another contributor exists, the script auto-closes **your** PR and emits `{state:"held", yielded:true}` — stop and yield. Otherwise it confirms `{acquired:true}` and you proceed. (Mirrors `t1k-sync-back`'s post-PR step; Mitigation 1 of the no-CAS residual risk in `rules/issue-claim-discipline.md`.)

**Finalize step:** when the fix PR is ready for review, call `release` to convert the draft to ready-for-review:

```bash
node .claude/scripts/t1k-issue-claim.cjs release <owner/repo#N>
```

The `release` call marks the linked draft PR ready (draft → ready hands off to `t1k-babysit-pr`). Merge or close auto-releases the claim via GitHub state — no manual cleanup needed.

> This gate delegates all claim logic to `.claude/scripts/t1k-issue-claim.cjs`. Do NOT run `gh issue edit` or `gh pr create` for the claim itself.

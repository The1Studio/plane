---
origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---
# A Green That Proves Nothing — Ask What Would Have Failed

## Rule

Before trusting any passing check — a doctor line, a CI gate, a test, a
dashboard tile — answer one question:

> **If the thing this guards were broken right now, would this check go red?**

If you cannot name the failure it would catch, it is decoration. A check that
cannot fail is worse than no check: absence prompts investigation, while a false
green ends it.

## The six shapes, all observed in the wild

| Shape | One line |
|---|---|
| **Checks the wrong artifact** | doctor asserted the repo copy; the runtime loads the global copy — PASS on every broken install |
| **Aggregates past the problem** | a fleet average cannot see a small broken population (74% green over 9 dead installs) |
| **Measures the wrong population** | an honest monitor pointed at one machine's near-empty data all day |
| **Rate over an empty denominator** | "0% fail" over zero requests renders identically to healthy |

## How to apply

**When writing a check**

- Break it deliberately and watch it go red. A check never seen failing is
  unproven. Prefer a test that pins the FAILURE states over one that pins success.
- Name the population. "Which machines/users/rows does this cover, and which does
  it structurally exclude?" A machine that never routes writes no routing rows —
  no query over that table can ever see it.
- Separate *unknown* from *good* in the output. `empty: true` is not `failRate: 0`.
- Guard small samples. Five failed requests at 03:00 is "100% fail" and means
  nothing; state the sample size beside the rate, or suppress the verdict.
- **Confirm the source can physically contain the evidence.** Before trusting a
  grep or a ratio, ask what that file is *allowed* to hold. A result envelope
  carries no tool calls; a log written after a decision holds none of the rejects.
  Neither can be fixed by a better pattern — change the source, not the regex.

**When reading a green**

- Ask what data it was computed over, and whether that is the data you care about.
- One machine's telemetry does not describe a fleet. Neither does one hour.
- If the green is the ONLY evidence, treat the question as open, not closed.

## Why this is a rule and not a note

Being careful about the wrong numbers reads exactly like being careful — the week that proved it: `docs/green-that-proves-nothing.md`.

## Related

- `wired-not-just-present.md` — the most common way a check guards nothing
- `agent-anti-rationalization.md` — evidence before claims
- `coding-guidelines.md` §5 — run it, read the output, then claim

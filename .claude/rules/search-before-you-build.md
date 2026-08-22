---
origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---
# Search Before You Build — The Repo Usually Has It Already

## Rule

Before writing a query, helper, or check, spend one search looking for it. When
the codebase already solves the problem, the existing solution encodes decisions
you do not have and will not reinvent — usually recorded in its docstring.

Cheap, in order:

```bash
grep -rn "<the concept>" --include="*.ts" --include="*.cjs" src/ .claude/
grep -rln "<the column/field>" services/ packages/
```

If a docstring explains WHY it exists, read it before deciding you need your own.

## Why — three misses in one day (2026-08-14)

**1. Rebuilt an identity check that already existed, and got it wrong.**
A "who has the kit but never routes" query was written from scratch with no
install-state filter. The repo already had `getCurrentlyInstalledUsers`, whose
docstring says exactly why it must exist: *"absence of events ≠ uninstall"*.
Without it, every user who never installed the module would have been named in a
🚨 alert and told to run a doctor script on a machine with nothing wrong.

**2. Concluded data was missing while it sat in the table.**
Diagnosing a routing failure ended in "this needs client-side logs nobody has."
`model_router_events` already stored `input_tokens` and `latency_ms`; the report
simply was not selecting them. Reading two existing columns answered the question
outright.

**3. Trusted a self-built monitor over production telemetry.**
A hand-rolled hourly script read one machine's local JSONL and honestly reported
"too few samples" for a full day. The fleet answer was in D1 the whole time.

Each miss cost more than the search would have.

## How to apply

- **Before a new query** — grep the column names. Something probably reads them.
- **Before a new helper** — grep the concept. If a sibling exists, extend it.
- **Before "we need more data"** — list what the table/API already returns.
  "We cannot know this" is a strong claim; verify it before acting on it.
- **When you do find one, read its comments.** They carry the counter-examples
  that made the current shape necessary.
- **If you deliberately build a parallel version, say why in the code.** A second
  implementation with no stated reason reads as an oversight to the next reader —
  and usually is one.

## Narrow exception

The existing implementation is genuinely wrong or unfit. Then fix or extend it
rather than adding a rival: two near-identical helpers guarantee they drift, and
the one with the docstring is the one people trust.

## Related

- `development-principles.md` § SSOT — no duplicates
- `code-conventions.md` § No Duplicated Logic — extract at the second occurrence
- `green-that-proves-nothing.md` — a rebuilt check often measures the wrong thing

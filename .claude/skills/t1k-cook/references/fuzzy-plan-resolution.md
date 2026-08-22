---
name: fuzzy-plan-resolution
description: Shared protocol — resolve fuzzy plan / phase / slug arguments to canonical paths before any bail. Used by t1k-cook, t1k-team, t1k-plan, t1k-debug, t1k-fix, t1k-handoff.
origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---

# Fuzzy Plan / Path Resolution Protocol

When a t1k skill takes a plan path, phase file, or slug argument, you MUST attempt fuzzy resolution before bailing. Bailing with "no plan matching" / "exact path required" / "team-slug not found" is a skill bug — the user types the human-readable shorthand and the skill resolves it.

This protocol is the SSOT. All t1k skills that take path / slug / plan args reference this file.

## Scope

Applies whenever a skill receives one of:

- `plans/<slug>` or `plans/<slug>/` (partial dir name)
- `<slug>` standalone (no leading `plans/`)
- `phase-N`, `phase N`, or bare `N` (phase ref)
- `phase-N-<topic>` (partial phase file name)
- Natural language: "active plan", "current plan", "this plan", "the remaining phases", "the plan we just worked on"
- Empty / null arg (treat as "active plan")

## Algorithm (MANDATORY order)

Run steps in order; stop at the first that returns a resolved path.

### Step 1 — Exact path

If the arg is an absolute path AND it exists on disk → use as-is. Done.

### Step 2 — Relative path that exists

If the arg is a relative path (e.g. `plans/260523-1543-chaosforge-demo/`) AND it exists relative to cwd → resolve to absolute. Done.

### Step 3 — Fuzzy plan-dir match

If the arg matches `plans/<slug>` OR `<slug>` (no path separators) OR contains a substring that looks like a plan slug:

1. **Extract `<slug>` token** — strip any leading `plans/`, trailing `/`, and trailing `.md` from the user arg. Example: `plans/chaosforge-demo` → `chaosforge-demo`. **This stripping is mandatory** — without it, the glob below becomes `plans/*plans/chaosforge-demo*/` and silently misses everything.
2. Glob `plans/*<slug>*/` (case-insensitive substring match on the directory name; the `<slug>` token may match anywhere in the dir name — leading timestamp like `260523-1543-` does NOT need to match)
3. Filter to dirs containing `plan.md` (must look like a real plan dir, not a sibling artifact dir)
4. **0 matches** → fall through to Step 5
5. **1 match** → use it. Log: `Resolved '<input>' → '<full path>'` (one line, then proceed silently)
6. **2+ matches** → pick the most-recently-modified (use `stat` on the dir OR on `plan.md` inside it; prefer plan.md mtime). Log: `Multiple matches; using most-recent: '<path>'. Other candidates: <comma-separated list>`. Proceed.
7. **Tie-break — identical mtime (within seconds)** → if 2+ candidates have byte-identical or sub-second-apart mtimes (cloned/copied plan dirs, fresh-from-template scaffolds), DO NOT pick arbitrarily. Fall through to Step 6's `AskUserQuestion` branch instead.

### Step 4 — Fuzzy phase-file match

If the arg looks like a phase ref (`phase-N`, `phase N`, or bare `N` where N is 0-9 / 0.5):

1. Resolve the plan dir first (use Step 3 if a plan slug is also in the arg, else use Step 5 to find the active plan)
2. Glob `phase-${N}*.md` in that dir (e.g. `phase-3*.md` matches `phase-3-combat-embedded-strip.md`)
3. Apply the same 0 / 1 / N+ uniqueness rules from Step 3

### Step 5 — Active-plan inference

If arg is empty / null / natural language ("active plan", "current plan", "this plan", "the plan", "the remaining phases"):

1. **Prefer HANDOFF.md mtime** — find the most-recently-modified `plans/*/HANDOFF.md`; use its parent dir
2. **Fall back to plan.md mtime** — find the most-recently-modified `plans/*/plan.md`; use its parent dir
3. **Fall back to dir mtime** — find the most-recently-modified `plans/*/` containing `plan.md`
4. If still no candidate → fall through to Step 6

### Step 6 — Genuine ambiguity OR no match

ONLY at this point may the skill ask or bail. Choose based on cardinality:

- **0 candidates after all steps** → bail with helpful message:
  ```
  No plan match for '<input>'. Searched plans/*<slug>*/ → 0 matches.
  Available plans (newest 5):
    - plans/260523-1543-chaosforge-demo (HANDOFF.md mtime: 19h ago)
    - plans/260522-2010-addressables-migration (HANDOFF.md mtime: 2d ago)
    - ...
  Provide a more specific arg, or pass an absolute path.
  ```
- **2+ candidates of comparable mtime (within ~1h of each other)** → `AskUserQuestion` with the candidates as options. Genuine ambiguity.
- **Otherwise** → never bail; the steps above always pick a winner.

## When the skill is in a `context: fork` body

Fuzzy resolution uses ONLY `Bash` and `Glob` tools, both of which ARE available in forked sub-contexts. The protocol runs cleanly regardless of fork status. Do not skip resolution just because the skill is forked.

## Implementation hook in skill bodies

Each t1k skill that takes a plan/path arg MUST add this as the FIRST pre-flight step (before any tool-availability check, role resolution, or bail):

> **Pre-flight Step 0.1 — Fuzzy arg resolution (mandatory).** If the user-supplied arg is not an exact existing path, run the Fuzzy Plan / Path Resolution Protocol at `skills/t1k-cook/references/fuzzy-plan-resolution.md`. The skill MUST NOT emit "no plan matching" / "exact path required" / "team-slug not found" until the protocol has been applied and Step 6 reached.

## Anti-patterns

| Anti-pattern | Correct behavior |
|---|---|
| Skill bails on `plans/chaosforge-demo` because exact dir name has timestamp | Glob `plans/*chaosforge*/` → resolve to unique match |
| Skill bails on bare `chaosforge-demo` (no `plans/` prefix) | Same — treat as plan-slug; glob `plans/*chaosforge*/` |
| Skill bails on empty arg | Use Step 5 active-plan inference (HANDOFF.md mtime) |
| Skill bails on `phase-1` | Resolve active plan, glob `phase-1*.md` |
| Skill asks user "which plan?" when there's a unique fuzzy match | Use the unique match silently — don't burn a question on something obvious |
| Skill asks when there's a clear newest among multiple matches | Pick newest, log the resolution, proceed |
| Skill asks only after exhausting the algorithm | OK — Step 6 ambiguity is the ONLY ask-justified case |

## Why this exists

Recorded 2026-05-23: user invoked `/t1k:team cook plans/chaosforge-demo`. The skill bailed because no exact `plans/chaosforge-demo/` dir exists (the real dir is `plans/260523-1543-chaosforge-demo/`). User correction: "why don't you just find the appropriate plan for me, doesn't need to be exact — that's what we want for all t1k skills."

The bail was actually mis-attributed to fork-context Agent unavailability, but the deeper truth is: skills should accept the human-readable shorthand and resolve to canonical paths. Hard-bail on non-exact paths is a UX bug.

## Related

- `rules/always-ask-on-unresolved.md` — asking is the LAST resort, not the first
- `rules/fork-context-brief.md` — fork context constraints (Bash + Glob ARE available; fuzzy resolution works in forks)
- `skills/t1k-cook/references/intent-detection.md` — pairs with this: intent-detection picks the mode, fuzzy-plan-resolution picks the target
- `skills/t1k-handoff/SKILL.md` — `resume <slug>` use case

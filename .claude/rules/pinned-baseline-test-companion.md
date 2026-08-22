---
origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---
# Pinned-Baseline Tests Ship a Companion — and Invert, Never Re-Pin

A **pinned-baseline test** asserts the *currently broken* state so the suite stays green while a
known gap exists. Three shapes:

| Shape | Example |
|---|---|
| **count pin** | `assertEqual(KNOWN_UNCOVERED /* 78 */, misses)` |
| **allow-list pin** | a named exemption set the gate skips past (`KnownUnreachableAllowList`, an `allowList` in a fixture's data file) |
| **absence pin** | `assertNull(type.getField("UnlockBuilding"))`, `assertEqual(0, callers)` — asserting the gap is *still there* |

**Every pinned baseline MUST ship, in the same commit, a companion assertion that fails when the
pin stops being accurate** — and when the pin does fail, **invert it; never re-pin.**

1. **The companion asserts by IDENTITY, not by count.** A count pin is satisfied by any set of the
   right size: 78 misses can become 78 entirely *different* misses — 40 fixed, 40 newly broken —
   and the gate stays green through the whole exchange. Name what you expect; fail on the names.
2. **Assert BOTH directions** — "no undocumented new entry" AND "no documented entry has silently
   been fixed". One direction alone is half a gate: the first lets the gap grow, the second lets
   the exemption list become a graveyard nobody re-checks. Both belong in one test
   (`failures.except(known)` and `known.except(failures)`); a second `[Test]` is not the point.
3. **The failure message states what a rise means, what a fall means, and forbids re-pinning.**

**Is it a pin?** Ask: *if the gap this test tracks were closed tomorrow, would it go RED?* Yes → it
owes a companion. Do not mistake an **input-integrity guard** for a pin — a fixture pinning a
known-**good** invariant of its own input (so the sweep below it cannot pass vacuously) fires on a
data change, never on a fix. The test is whether the pinned number describes *breakage* or
*fixture shape*.

## The "RED for the opposite reason" trap

A pin can go RED because the gap CLOSED (410 pinned icon misses dropping to zero read as "410 broken" — full story: `docs/pinned-baseline-test-companion.md`), and "set the constant to the new number" silently converts a fix into a permanent baseline. So on any pinned-baseline failure, before touching the number:

- **Determine the direction first.** Grew (regression) or shrank (gap closing)? The failure text
  will not tell you if it was written assuming only one direction.
- **Shrank to zero → invert.** Delete the constant, assert the healthy state, rewrite the message
  so a future miss reads as a regression.
- **Shrank partway → shrink the identity list**, and only then the count. Removing names is the
  operation; the count following them is bookkeeping.
- **Grew → that is a real regression.** Fix the code. Raising a pin to absorb a regression is how
  a gate gets muted.
- **Never re-pin to whatever the run just reported.** That is not a fix, it is a record of the
  present being renamed "expected".

A pin's remark should carry its termination condition ("delete this once the count reaches zero"),
and when that condition is met the remark is an instruction, not a suggestion.

## Naming

- **`*_HasNoStaleEntries`** — the companion for an allow-list / exemption-set pin. Prefix with the
  list's own name when a fixture has more than one.
- **`*_KnownGap`** — an absence pin, self-companioning because its own failure *is* the news that
  the gap closed. It still owes obligation 3.

Allow-list rows keyed by name with a dated, cited reason; a completeness scan so a subject missing
from the data entirely is not invisible; exemption data in a file rather than a code array so
deleting it fails **loudly** instead of degrading to vacuously green. Worked examples and the
originating audit: `docs/pinned-baseline-test-companion.md`.

## Related

- `green-that-proves-nothing.md` — the parent failure class; a pin is one way a green stops meaning
  anything.
- `negative-result-scope.md` — a pin is a stored negative result: a claim about the world that
  nothing re-checks.
- `development-principles.md` § "Test Pass Gate" — zero failures before done. A pin is the
  sanctioned way to keep that true across a known gap, which is exactly why it needs a leash.

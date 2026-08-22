---
origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---
# Wired, Not Just Present — A File That Exists May Still Never Run

## Rule

Shipping a hook, script, or config file is **half** the change. Until something
loads it, it does nothing — and nothing says so. Whenever you add or verify one,
check BOTH facts separately:

1. **Present** — the file exists at the path the runtime actually reads.
2. **Wired** — a registration, manifest entry, or caller invokes it.

A check that only proves (1) reports green on an install where (2) is missing.
Verify the wired half by naming its consumer: which `settings.json` entry, which
`module.json` list, which caller.

## Why — three instances in one day (2026-08-14)

| What | Present | Wired | Cost |
|---|---|---|---|
| `mr-task-interceptor.cjs` | ✓ | ✗ on 9 of 23 installs | Every Task passed through to Anthropic; ~$18.5K/7d of sub-agent work unrouted |
| Retired model `kimi-k2.5` | ✓ (kit disabled it) | ✗ (never reached machines) | One machine failed 8/8 all day on a dead model |
| `contribution-capture.cjs` | ✓ | ✗ (absent from `settings.json`) | Merged PRs went unscored; credit lost until a manual backfill |

All three were silent. All three reported healthy. The interceptor case is the
sharpest: `settings.json` loads the hook from `$HOME/.claude/hooks/` behind
`if (fs.existsSync(c)) require(c)`, so a missing file is skipped without an
error — while the doctor asserted the presence of the **repo** copy, a path the
runtime never reads. It printed PASS on exactly the broken installs.

## How to apply

- **Adding a hook** → also add its `settings.json` registration, and assert the
  matcher covers the event you need (`Task|Agent`, `Bash`, …).
- **Adding a script** → also add it to the owning `module.json`. An unclaimed
  script does not ship (`validate-all-shippable-claimed` catches this).
- **Writing a doctor/health check** → assert the path the RUNTIME loads, not the
  copy that happens to be in the repo. If those differ, check both and say which
  is which.
- **A broken wiring is FAIL, not WARN.** A warning in a thirty-line green report
  is scrolled past; that is how the interceptor case survived nine machines.
- **Config the kit owns must propagate on update**, not only on first install.
  "Copy if absent" freezes kit-owned facts at install time.

## Related

- `kit-wide-fix-discipline.md` — fix at the kit source so the wiring reaches everyone
- `prefer-local-over-global-edits.md` — which copy is canonical
- `green-that-proves-nothing.md` — the broader failure this is one instance of

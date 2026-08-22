---
name: t1k:verify-wiring
description: "Prove a hook, script, or check actually runs — not merely that its file exists. Use after adding a hook/script, when a feature 'is installed but does nothing', or when a health check reports green you don't trust."
keywords: [wiring, hook, registered, not running, silent, green, verify, installed, no effect, unregistered]
argument-hint: "[hook-name | script-name | check-name]"
effort: low
version: 2.86.0
origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---

# Verify Wiring — Prove It Runs, Not That It Exists

A hook that is present but unregistered does nothing, reports nothing, and fails
nothing. So does a script no manifest claims, and a check that asserts a path the
runtime never loads. Each looks installed. Each is silent.

This skill turns "it should be working" into evidence either way.

## When to use

- After adding a hook, script, or gate — before calling it done
- A feature "is installed" but has no observable effect
- A health check reports green and you cannot name what it would catch
- Before concluding a fix reached other machines (it usually has not)

## Step 1 — Present: at the path the RUNTIME reads

The repo copy and the loaded copy are different files. Check the loaded one.

```bash
NAME="${1:?hook or script name}"
for p in "$HOME/.claude/hooks/$NAME.cjs" "$HOME/.claude/scripts/$NAME"* \
         "$PWD/.claude/hooks/$NAME.cjs" "$PWD/.claude/scripts/$NAME"*; do
  [ -e "$p" ] && echo "present: $p"
done
```

**Global vs project matters.** Registrations built with `os.userInfo().homedir`
load the GLOBAL copy — a repo-local file satisfies no such registration. If only
the repo copy exists, routing/telemetry/whatever it drives is off.

## Step 2 — Wired: something invokes it

```bash
# Hooks — registered, and on the right event?
jq -r '.hooks | to_entries[] | .key as $ev | .value[]
       | select((.hooks[]?.command? // "") | test(env.NAME))
       | "\($ev)  matcher=\(.matcher)"' ~/.claude/settings.json

# Scripts — claimed by a module, or it never ships
grep -rn "$NAME" .claude/modules/*/module.json
```

Empty output = the file is inert. That is a **FAIL**, not a warning: a silent
component in an otherwise-green report is scrolled past, which is how one such
hook survived across nine machines.

## Step 3 — Runs: produce evidence

Presence + registration still is not proof. Force the path and look:

```bash
# A hook: trigger its event, then check for its trace
ls -la ~/.model-router/*.jsonl ~/.claude/telemetry/*.jsonl 2>/dev/null | tail -3

# A check: break it deliberately and confirm it goes RED
cp <target> /tmp/t1k-wiring-backup && rm <target>
bash <the-check>          # must FAIL here
cp /tmp/t1k-wiring-backup <target>
```

A check never observed failing is unproven. Prefer pinning the FAILURE states.

## Step 4 — Fleet: your machine is not the population

The most expensive version of this bug is per-machine. A component wired on your
box says nothing about anyone else's, and config that ships "copy if absent"
freezes at install time.

- Is there a **fleet-visible** signal (telemetry table, dashboard) confirming it
  runs elsewhere? Local JSONL cannot answer this.
- If the fix is config the kit owns, does it **propagate on update**, or only on
  first install?

## Report

```
present:    <path the runtime loads>        | MISSING
registered: <event> matcher=<m>             | NOT REGISTERED
evidence:   <trace/log/row observed>        | none
fleet:      <how other machines are known>  | unknown — local only
```

State `unknown` plainly. An unverified wiring reported as working is the failure
this skill exists to prevent.

## Gotchas

- `if (fs.existsSync(p)) require(p)` swallows a missing file with no error — the
  common hook-registration idiom, and why absence is invisible.
- A doctor line asserting the repo copy passes on exactly the broken installs.
- A matcher can be present but wrong (`Bash` when you need `Task|Agent`).
- An unclaimed script does not ship, however correct it is.

## Related

- `rules/wired-not-just-present.md` — the rule this operationalises
- `rules/green-that-proves-nothing.md` — why the check itself needs checking
- `t1k:doctor` — registry-wide validation

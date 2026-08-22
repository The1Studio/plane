---
name: t1k:statusline-full
description: "Install TheOneKit's canonical statusline GLOBALLY to ~/.claude/ so it renders in every Claude Code session, not just t1k projects. Use for 'enable full statusline globally' or 'install statusline'."
keywords: [statusline, status line, full statusline, install statusline globally, global statusline, 5h timer, weekly quota, context bar]
effort: low
argument-hint: "[--from <.claude/hooks dir>]"
version: 2.86.0
origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---

# t1k:statusline-full — Global statusline installer

Promotes the kit's **canonical** statusline (`.claude/hooks/statusline.cjs`) to a
**global** install under `~/.claude/` so it renders in *every* Claude Code session —
including projects that aren't TheOneKit kits.

This skill does **not** carry its own copy of the statusline. It sources the kit's
own `hooks/statusline.cjs` + `hooks/lib/*` — single source of truth, no fork drift.

## When to use

- "Enable the full statusline globally", "install statusline to ~/.claude", "show the
  statusline in every project".
- NOT needed *inside* a t1k project — there the kit already wires the statusline
  per-project via `hook-runner.cjs statusline`. This skill is for the **global** case.

## What it renders

- **Line 1:** `🤖 model  [▰▰▰▱▱…] N% context  ⌛ 5h usage  📅 7d weekly`
- **Line 2+:** `📁 dir  🌿 branch (status)`, agent flow, current todo, `📝 +added -removed`

Usage data comes from Claude Code's native statusline stdin (`rate_limits`, CC
≥ 2.1.80), with a fallback to `os.tmpdir()/ck-usage-limits-cache.json`. No separate
usage hook is required — the canonical statusline is self-sufficient.

## Install

Run from inside a TheOneKit project (so the kit's `hooks/statusline.cjs` is present):

```bash
bash .claude/skills/t1k-statusline-full/install.sh
```

Or point at any kit's hooks directory explicitly:

```bash
bash .claude/skills/t1k-statusline-full/install.sh --from /path/to/.claude/hooks
```

It copies `statusline.cjs` → `~/.claude/statusline.cjs`, the 4 required libs
(`colors`, `transcript-parser`, `git-info-cache`, `statusline-private-cache`) →
`~/.claude/lib/`, and wires
`~/.claude/settings.json`:

```json
{ "statusLine": { "type": "command", "command": "node \"$HOME/.claude/statusline.cjs\"", "padding": 0 } }
```

Restart Claude Code to pick it up.

## Modes

The statusline reads `T1K_STATUSLINE_MODE` (default `full`): `full` | `compact` |
`minimal`. Export the env var in your shell/profile to change it globally.

## Scope & safety

- Writes only under `~/.claude/` (`statusline.cjs`, `lib/*.cjs`, `settings.json`).
  It does not touch any project's `.claude/` or the kit's per-project wiring.
- Reads the session JSON Claude Code pipes on **stdin** and local `claude auth status`
  metadata to render; it does not transmit anything off-machine. Per-session auth
  and context caches are owner-only on POSIX and expire after 7 days.
- Re-running is idempotent: it overwrites the installed statusline files with the
  current canonical versions and re-wires `statusLine`.

## Gotchas

- **"canonical statusline not found"** → you're not inside a t1k project and didn't
  pass `--from`. Run it from a project where `.claude/hooks/statusline.cjs` exists, or
  pass `--from <…/.claude/hooks>`.
- **Global vs project conflict** → if a project has its own `.claude/settings.json`
  `statusLine` pointing at `hook-runner.cjs statusline`, that project-level wiring wins
  there (correct — the kit manages it). The global install only affects sessions
  without a project override. This skill intentionally never edits project settings.
- **Chips `⌛`/`📅` blank** → on a fresh session before the first prompt, CC may not
  have populated `rate_limits` yet and the cache may be empty; they fill in once usage
  data is available. Requires Claude Code ≥ 2.1.80 for native stdin rate limits.
- **Stale global copy** → the global `~/.claude/statusline.cjs` is a *snapshot*. After
  a `t1k update` bumps the kit statusline, re-run this installer to refresh the global
  copy. (Project installs update automatically via the kit; the global one does not.)
- **Windows** → uses `bash` + `node`; run under Git Bash / WSL. Node must be on PATH.

---

origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---
# t1k-cook — recovery via rollback (when implementation corrupts `~/.claude/` state)

If an implementation corrupts `~/.claude/` state (bad merge, mis-applied prefix, broken hooks), use the H7 rollback command rather than a manual clean-up:

```
t1k rollback --kit <name> --to-snapshot pre-<previous-version>
```

- Snapshots live at `~/.claude/.t1k-snapshots/<kit>/pre-<version>/`. Cap is 5 most-recent per kit; older ones soft-move to `~/.claude/.t1k-trash/<kit>/`.
- `--to-snapshot` MUST literally start with `pre-` (e.g. `pre-2.4.1`). Bare versions are rejected.
- `--yes` is currently a no-op as of cli@v4.14.0 — does not bypass anything. Future-proof only.
- Restore is a non-destructive copy: files added by the bad implementation are NOT removed. Run `/t1k:doctor` afterwards to spot stragglers.

**Critical caveat (cli@v4.14.0):** the install/update pipeline does not yet auto-create snapshots. If `t1k rollback` reports `snapshot '<kit>/pre-<version>' does not exist`, fall back to `t1k install --reset` (the sanctioned destructive path; takes its own `~/.claude-backup-{ISO-ts}/` first). NEVER `rm -rf ~/.claude/` — <!-- gate:allow-rm-claude (rule statement) --> the `validate-no-raw-rm-claude.cjs` gate forbids it and you'll lose `.t1k-snapshots/`, `.t1k-trash/`, and any user-customized files.

For per-file/per-step recovery, prefer `git restore` on the project side; the H7 rollback is for `~/.claude/` state, not project source. Full reference: `skills/t1k-kit/references/cli-commands.md` → `t1k rollback`.

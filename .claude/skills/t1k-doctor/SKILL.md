---
name: t1k:doctor
description: "Validate TheOneKit registry integrity across 20+ checks. Use for 'check kit health', 'something feels broken', 'validate before release', or after adding skills/agents."
keywords: [validate, health, integrity, check, registry, broken, diagnose]
argument-hint: "[fix]"
effort: medium
version: 2.86.0
origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---

# TheOneKit Doctor — Registry Validation

Validates that all registry fragments, skills, and manifest are consistent and coherent.

## Usage
```
/t1k:doctor        # Read-only validation report
/t1k:doctor fix    # Attempt to fix detected issues
/t1k:doctor --ci   # CI mode: run all checks, exit code 1 on any fail, GitHub annotations
```

## Live Registry State (fetch on demand — do NOT inline in body)

When running checks, fetch live registry state via tool calls AFTER the skill body is loaded — NEVER embed inline shell-substitution tokens (the `!`-prefix-then-backtick syntax) here (cache-busts the cached prefix on every fragment edit; doctor runs constantly during dev). Use:

- `Read` each `.claude/t1k-routing-*.json` matching glob → routing fragments
- `Read` each `.claude/t1k-activation-*.json` matching glob → activation fragments
- `Read .claude/metadata.json` → kit + module metadata
- `Glob .claude/agents/*.md` then `Read` each → agent files
- `Glob .claude/skills/*/SKILL.md` then `Read` each → skill files

If a glob returns no matches, treat as "no entries" — do not echo error.

## Check Groups

Run all checks in sequence. Full check list: `references/checks.md`

- **Core checks (#1–6):** Role coverage, skill existence, cross-layer hardcoding, manifest, registry version, config completeness
- **Module checks (#7–17):** File ownership, dependency integrity, activation match, agent presence, routing overlays, stale files, origin frontmatter
- **Manifest checks (#21):** Per-module manifest integrity, orphaned flat files
- **SSOT checks (#22–27):** schemaVersion, version presence, no stale modules/, context requiredPaths, activation format, v3 installedModules
- **No-override checks (#28–29):** Filename collision detection, agent prefix correctness. The universal `t1k-` prefix rule (skills + agents, SSOT `rules/naming-convention.md`) is the authoritative invariant; release-action gates `validate-skill-prefix.cjs`, `validate-agent-prefix.cjs`, `validate-new-name-conformance.cjs` enforce at PR time.
- **Frontmatter quality (#18–20):** Agent maxTurns, skill effort, agent model appropriateness
- **Cross-platform (#30):** Hook files free of shell-only patterns (2>/dev/null, /dev/stdin, execSync shell strings)
- **MCP health (#31):** Required MCPs connected, recommended MCPs present. Runs `.claude/hooks/doctor-check-31-mcp-connectivity.cjs`. A missing/misconfigured REQUIRED MCP is FAIL level (exit 1); a missing RECOMMENDED MCP is WARN; when the `claude` CLI itself cannot be queried the whole check reports UNKNOWN rather than a false PASS or FAIL. See `references/checks.md` #31. Full tiered-requirement spec (required/recommended/optional definitions, per-layer MCP tables): `references/mcp-requirements.md`.
- **Sync-back health (#32):** Recent sync-back PRs are healthy (no CONFLICTING state, no phantom-file diffs)
- **Kits membership SSOT (#33):** `Object.keys(metadata.kits) === unique(installedModules[*].kit)` — runs `scripts/check-kits-membership.cjs` to catch drift between the derived kit membership and the source `installedModules`. WARN level on mismatch.
- **Orphaned agents (#34):** Agent files under `.claude/agents/` whose `origin:` frontmatter points to a kit no longer in `installedModules[*].kit` (or `metadata.kits` on older schemas) — leftovers from pre-manifest installs. Runs `scripts/check-orphaned-agents.cjs`. WARN level; fix: `t1k uninstall --kit <name> --include-orphans` (v3.5+) or manual rm.
- **CLAUDE.md bloat (#35):** Project `CLAUDE.md` exceeds 5k token budget (char/4 heuristic). Runs `scripts/check-claude-md-bloat.cjs`. WARN level; fix: move details to `docs/` + deduplicate with auto-loaded `rules/*.md`.
- **Rule duplication (#36):** Same rule filename present in both `~/.claude/rules/` and project `.claude/rules/` (double-loaded, wastes context). Enhanced with byte-hash content dedup — also detects identical content under different filenames. Runs `scripts/check-rule-duplication.cjs`. INFO level; fix: keep each rule in one scope only.
- **Context budget (#37):** Sums token estimates for all `.claude/rules/*.md` + project `CLAUDE.md`. Warns when total exceeds 12 000 tokens; fails (exit 1) when total exceeds 15 000. Complements the release-time gate `validate-context-window-budget.cjs`. Runs `scripts/check-context-budget.cjs`. WARN/FAIL level; fix: move verbose content to `docs/`, trim rule files.
- **Always-loaded union (#59):** The only check that measures what a SESSION actually loads — the UNION of `rules/*.md` + `CLAUDE.md` across BOTH scopes (`~/.claude/` and the project `.claude/`), for the installed set read from `metadata.installedModules`. Every other budget check measures one population and so cannot see this: the release gate `validate-context-window-budget.cjs` caps ONE KIT, #37 sums the PROJECT scope only, #38 caps ONE FILE. On a real machine (2026-08-20) the global scope alone was ~42 800 tokens (171% of the union budget) while #37 reported PASS, because a consumer's project `.claude/rules/` is near-empty and that is all #37 can see (`modules/t1k-base/rules/green-that-proves-nothing.md`, "measures the wrong population"). Reports per-scope split, per-kit attribution, and the top offending FILES ranked descending — a bare total is not actionable. Also flags rules double-loaded across scopes (billed twice; see #36) and rules owned by modules not in the installed set (see #12). Runs `scripts/check-always-loaded-union.cjs`. **WARN only, always exit 0** — a consumer already over budget must not have their session broken by the check that tells them so; promoting to FAIL is gated on the fleet median falling under budget (ratchet comment dated in the script). UNKNOWN — never a reassuring zero — when no install metadata resolves in either scope. Budget override: `T1K_UNION_BUDGET_TOKENS` (default 25 000). Fix: attack the top offender first; split it or move detail to `docs/`.
- **Oversized rules (#38):** Per-file check — any `.claude/rules/*.md` exceeding 5 000 tokens (char/4 heuristic) gets a WARN. Oversized rule files inflate the always-loaded context budget and signal content that belongs in `docs/`. Runs `scripts/check-oversized-rules.cjs`. WARN level; fix: split the rule or move implementation details to `docs/`.
- **Modules registry sync (#39):** `.claude/t1k-modules.json` `modules` field must match the projection of every `.claude/modules/*/module.json` (description, required, dependencies, skills, activationFragment). Catches drift between the per-module SSOT and the rollup before push. Runs `scripts/check-modules-registry-sync.cjs`. SKIPs on non-modular kits. WARN level; fix: push the change and let CI regenerate via `theonekit-release-action/scripts/generate-modules-registry.cjs`, or run that script locally from the kit root. The release-action gate `validate-modules-registry-sync.cjs` is the Error-level enforcer.
- **Phantom kits (#40):** Iterates `metadata.kits` entries and warns on any where `files` is `undefined` or an empty array. Phantom entries are written when `t1k init` is interrupted (SIGINT, network failure) before file extraction — they cause `project-detector.cjs` to misidentify the project framework and `t1k update` to spawn init loops that always fail (Issue #38). Runs `scripts/check-phantom-kits.cjs`. Skips when `~/.t1k/locks/kit-install.lock.lock/` is held (install in progress) to avoid false-positives on transient empty states. WARN level; fix: `jq 'del(.kits.<name>)' .claude/metadata.json > /tmp/m.json && mv /tmp/m.json .claude/metadata.json` then `t1k init --kit <name> --yes`. Snapshot test: `tests/check-phantom-kits.test.cjs` with fixture `tests/phantom-fixture.json`.
- **Statusline wiring (#42):** Validates the T1K statusline is wired end-to-end: (a) `hooks/statusline.cjs` exists under resolved `.claude/`, (b) `metadata.json.installedFiles[]` lists it with `ownership=kit` AND `moduleName=t1k-base`, (c) `settings.json.statusLine.command` contains both `hook-runner.cjs` and `statusline` tokens, (d) `hooks/hook-runner.cjs` exists. Catches release/install regressions that leave the statusline silently unrendered. Runs `.claude/hooks/doctor-check-42-statusline-wiring.cjs`. Skips on kit source repos where `metadata.json.installedFiles[]` is absent (invariant is consumer-only). FAIL level; fix: `t1k update` to reclaim ownership and remerge settings.
- **No inlined universal rules (#44):** SKILL.md files must not inline the 3 boilerplate blocks that auto-load from `.claude/rules/` (skill-security, AI-Driven Design, fork-hygiene 5-line). Runs `scripts/check-no-inline-universal-rules.cjs`. FAIL level; fix: remove the inlined block and reference the canonical rule/reference file. See `references/checks.md` #44.
- **Activation skill resolution (#47):** Every skill ref in every `t1k-activation-*.json` `sessionBaseline[]` and `mappings[].skills[]` array must resolve to a real skill directory — accepting BOTH bare-slug form (`nakama-rpc`) and the full-prefixed form (`t1k-nakama-rpc`). Wraps the release-action gate `validate-activation-skill-resolution.cjs`. WARN level locally (advisory; the release-action gate is the strict enforcer at PR time). Fix: rename the ref to either form the prefixer's `buildSelfHealMap()` accepts (canonical dir, kit-stripped, module-stripped, kit+module-stripped, or `t1k-`-stripped). See `references/checks.md` #47.
- **Global install core-only (#48):** `$HOME/.claude/metadata.json` should contain ONLY `core` under `.kits`. Engine-specific kits (unity, designer, cocos, react-native, web, nakama) belong PER-PROJECT in the project's `.claude/`, not globally. Mixing engine kits globally causes activation bleed (irrelevant skills auto-load), stale-install drift, and orphaned files. Runs `scripts/check-global-core-only.cjs`. WARN level; fix: `t1k uninstall --global --kit <name>` for each non-core kit listed.
- **Multimodal setup (#49):** When `t1k-extended` is installed AND `skills/t1k-extended-multimodal/SKILL.md` is present: validates GEMINI_API_KEY (WARN), MINIMAX_API_KEY (WARN, optional), python3 ≥ 3.10 (FAIL), and `github:The1Studio/human-mcp#v2.15.1` resolvability (WARN — freshness signal via `npm view`; install hint points to fork). Runs `hooks/doctor-check-49-multimodal-setup.cjs`. FAIL level for missing python3; WARN for missing API keys / MCP.
- **Stale-backup folders inside auto-scanned dirs (#50):** Detects quarantine subdirectories (`.stale-backup-*`, `.zombies-*`, `.backup-*`, `.archive-*`, `.old`, `.deprecated`, `.trash`) sitting INSIDE Claude Code's auto-scanned folders (`agents/`, `skills/`, `rules/`, `hooks/`, `commands/`). Dot-prefix does NOT hide them — the `/agents` UI and skill discovery walk into them and surface their contents as live registrations (zombie entries). Scans BOTH global `~/.claude/` and project `.claude/`. Runs `scripts/check-stale-backup-folders.cjs`. WARN level; fix: move the quarantine folder OUTSIDE the auto-scanned dir (`mv ~/.claude/agents/.stale-backup-* ~/.claude/.stale-backup-*`) or `rm -rf` after verification. See [`rules/naming-convention.md`](../../rules/naming-convention.md) § Violation handling for the canonical guidance.
- **Agent budget calibration (#51):** Scans `.claude/agents/*.md` for budget-checkpoint + `maxTurns` calibration per [`rules/agent-completion-discipline.md`](../../rules/agent-completion-discipline.md). Flags: (a) a FLAT-token checkpoint in the body (a literal like `150K`/`150,000`/`200K` not tied to the agent's `model:` window — should be window-relative, ~75%@200K / ~55%@1M); (b) a tool-heavy agent (has `Bash` and/or `Task`/`Agent` in `tools:`, i.e. can mutate/orchestrate) with NO budget checkpoint in the body at all; (c) under-sized `maxTurns` for the task class (tool-heavy agent at `maxTurns < 50` — multi-PR/refactor/MCP-validation work hits the turn cap before tokens, #528: `t1k-kit-developer` 45→90). Runs `scripts/check-agent-budget-calibration.cjs`. WARN level; fix: make the checkpoint window-relative and size `maxTurns` to the task per the rule.
- **Hook registration drift (#52):** Compares installed enforcement hook scripts with their required event + matcher registrations in `settings.json`. Reports hook files that arrived through an update but remain inert on older consumers. Runs `.claude/hooks/doctor-check-52-hook-registration-drift.cjs`. FAIL level; fix: update with a current CLI so it can reconcile the missing registrations.
- **Agent routing reachability (#53):** Every agent `.md` under `.claude/agents/` must be reachable by the data-driven routing index (`hooks/lib/agent-routing-index.cjs`) that `generic-agent-detector` consults — an agent contributing zero keywords can never be suggested, so its task shape silently falls through to `general-purpose`. Also flags agents that are absent from every `t1k-routing-*.json` `roles` map AND declare no `roles:` frontmatter at all (`roles: none` is a legitimate explicit opt-out; saying nothing is drift). Runs `scripts/check-agent-routing-reachability.cjs`. WARN level; fix: add an `<example>` block with a `user:` prompt (and `Context:` line) to the agent description, or state the roles intent explicitly. Resolves #659.
- **Agent MCP tool-grant drift (#54):** Reconciles `mcp__<server>__<tool>` grants in every agent's `tools:` frontmatter against the `servedTools` manifest declared for that server in `t1k-config-*.json`. A stale grant reads as a capability the agent has, so the resulting weaker verdict gets mis-attributed to an MCP-server bug rather than to our own allowlist. Runs `scripts/check-agent-mcp-tool-grants.cjs`. WARN level; a server with no declared manifest is reported **unverified**, never as a violation (a false "this tool doesn't exist" is the failure mode this check exists to prevent). Pass `--include-ungranted` for the informational served-but-ungranted direction. Resolves #651.
- **Kit file drift (#55):** Compares project-local `.claude/` against the global install and reports three states: modules BEHIND the global version, kit executables MISSING locally, and executables DIVERGED AHEAD (same module version, different content). Project-local shadows global per `rules/prefer-local-over-global-edits.md`, so a stale local copy can hold a shipped fix inert indefinitely with no signal. Runs `.claude/hooks/doctor-check-55-kit-file-drift.cjs`. Offline — compares the two installs on disk, never the network. FAIL level; fix: `t1k modules update`, or `/t1k:sync-back` FIRST when content diverged ahead, since update overwrites those edits (#367).
- **Dead permission rules (#56):** Flags `permissions.{allow,deny,ask}` entries whose tool name Claude Code's file-permission matcher never consults — `Write(path)`, `MultiEdit(path)`, `NotebookEdit(path)` (use `Edit(path)`) and `Glob(path)` (use `Read(path)`). Such a rule passes the settings schema and grants/denies nothing while reading like a live rule; Claude Code's own warning appears once, at startup, only for the file it loaded. Scans `settings.json` + `settings.local.json` in both scopes (`--project-only` to skip global). Runs `scripts/check-dead-permission-rules.cjs`. WARN level; the dead-form table is `references/permission-rule-forms.json` (transcribed from the shipped rule validator) so a new form is a data edit, never a code edit. Resolves #763.
- **Global bootstrap state (#57):** Reports what the silent global-bootstrap did on this machine, read back from its sentinel `<realHome>/.t1k/global-bootstrap.json`. The bootstrap installs `core` + `model-router` into `~/.claude/` from SessionStart with no prompt and no output on success, so this check plus the `[t1k:global-bootstrap]` frame are the ONLY way to observe it. States: PASS (global install present / bootstrapped), SKIP (never triggered, opted out, or an attempt in flight), WARN (failed below the cap, or an unreadable sentinel), FAIL (stopped permanently after 3 REAL failures — lock contention never counts). Runs `.claude/hooks/doctor-check-57-global-bootstrap.cjs`. Offline — reads the sentinel on disk, never the network. Fix on FAIL: `t1k init --global --yes --kit core --preset full`, then check `~/.claude/.kit-update.log`. See [`docs/global-bootstrap.md`](../../../docs/global-bootstrap.md).
- **Kit install scope (#58):** Reports kits installed in BOTH scopes at once. A kit belongs to exactly one — `core` global, engine/domain kits per-project ([`rules/kit-install-scope.md`](../../modules/t1k-base/rules/kit-install-scope.md)). Only the project copy is ever served, so the shadowed global copy still updates and still reads healthy in `t1k --version` while no session loads it; updating the wrong one is silent. Consumes the per-scope inventory `hooks/telemetry-utils.cjs` already computes (`kitScope === 'both'`) rather than adding a second reader. Runs `.claude/hooks/doctor-check-58-kit-install-scope.cjs`. Offline. SKIPs on kit source trees (no `kits`/`scope`/`installedAt` in metadata) and on global-only sessions; INFO when the project declares `inheritsFrom` → global (deliberate layering). WARN level otherwise; fix: `t1k uninstall --local --kit core` or `t1k uninstall --global --kit <engine-kit>`. Complements #48 (no non-core kit globally) and #55 (whether two coexisting copies agree).

- **Markdown link integrity (#60):** Relative markdown links inside `.claude/` whose target exists in neither the on-disk layout nor the FLATTENED namespace a consumer holds (`flatten-module-files.cjs` collapses `modules/<m>/skills/<s>/` to `.claude/skills/<s>/` and does not rewrite link paths, so depth is counted from the INSTALLED location). Links that escape `.claude/` under both readings, and links into a namespace the install never received (`modules/`, `plans/`), are skipped — a consumer cannot fix missing content. Runs `.claude/hooks/doctor-check-60-markdown-link-integrity.cjs`. Offline. FAIL level; WARN on a kit source tree when the target may belong to a co-installed kit. Fix: recount the `../` for the installed location (`skills/<s>/SKILL.md` → 2; its `references/` → 3; `agents/<a>.md` → 1). See `t1k-skill-creator/references/architecture-rules.md` § L.1.
- **Skill reference citations (#61):** A SKILL.md naming its own `references/<file>` must ship that file. Covers the NON-link citation forms #60 cannot see (code span, table cell, prose). Cross-skill citations carrying more path in front of `references/` are deliberately not resolved against the citing skill — `t1k-architecture/references/fork-hygiene.md` is cited 26 times from elsewhere. Fenced blocks are ignored. Runs `.claude/hooks/doctor-check-61-skill-reference-citations.cjs`. Offline. FAIL level; fix: write the reference or delete the citation — the failure is silent otherwise (the model opens nothing and continues).
- **Orphan reference files (#62):** `references/**.md` that nothing anywhere under `.claude/` cites. The corpus is the WHOLE tree — every markdown, JSON, and script file minus the candidate — because a per-skill check reports shared references as orphaned and tells users to delete live content. Matching is deliberately generous (full path, `references/` suffix, or basename), so it under-reports rather than over-reports. Runs `.claude/hooks/doctor-check-62-orphan-reference-files.cjs`. Offline. WARN only, never FAIL — the remedy is deletion; confirm by hand before acting.
- **Unused local modules — engine mismatch (#63):** A locally installed kit whose own `context.requiredPaths` are absent from the project (e.g. unity with no `Assets/`/`ProjectSettings/`). Data-driven — no declaration means no finding. Runs `.claude/hooks/doctor-check-63-unused-local-modules.cjs`. Offline, diagnostic-only. Emits Contract A `[t1k:doctor:scope-finding …]` per finding; `confidence=high` requires opt-in via `scopeEnforcement.autoRemoveKits`, so a default install never auto-removes. See `references/checks.md` #63.
- **Uninstall integrity (#64):** A stale interrupted-uninstall journal (FAIL, idempotent re-run remedy — an in-flight uninstall reports INFO instead) and unacknowledged auto-removal ledger entries (WARN, with a situation-correct recovery command — never `t1k recover restore`). Report-only, never mutates. Runs `.claude/hooks/doctor-check-64-uninstall-integrity.cjs`. See `references/checks.md` #64.
- **Scope remediation:** the background agent `features.contextBloatGuard` dispatches on a duplication-over-threshold session — reads checks #55/#58/#63 findings, refuses far more than it acts, and when it does remove a kit, backs up, verifies, and records before reporting. Never wired into `fix` mode. Full behavior spec: `references/scope-remediation.md`.

See `references/frontmatter-recommendations.md` for recommended values and output format.

## CI Mode (`--ci` flag)

When invoked as `/t1k:doctor --ci`, the doctor runs in non-interactive CI mode:

- Runs all checks from the standard check list **plus** the Tier 2 eval registry checks
- Emits GitHub Actions workflow annotations (`::error file=...::` format) for each failure
- Writes a machine-readable summary to `.claude/telemetry/doctor-ci-{date}.json`
- Exits with **code 1** if ANY check fails (suitable as a blocking CI gate)
- Exits with **code 0** only if all checks pass
- Completes in < 60s on `theonekit-core`

### CI Check Sequence

1. **SKILL.md frontmatter completeness** — every `SKILL.md` must have: `name`, `description`, `version`, `effort`, `origin`, `repository`, `module`, `protected`
2. **Agent frontmatter validity** — every `.claude/agents/*.md` must have: `name`, `description`, `model`, `maxTurns`, `origin`, `repository`
3. **Hook .cjs syntax** — runs `node --check` on every `.claude/hooks/*.cjs`
4. **t1k-config-*.json schema** — validates `registryVersion`, `kitName`, `priority` (number) present in every config fragment
5. **t1k-manifest.json validity** — per installed module, `.t1k-manifest.json` must exist and list only real files
6. **Cross-ref integrity** — vendors the Phase 1 script from `theonekit-release-action/scripts/check-skill-cross-refs.cjs`
7. **Tier 2A routing check** — delegates to `scripts/eval/tier2/routing-check.cjs`
8. **Tier 2B activation check** — delegates to `scripts/eval/tier2/activation-check.cjs`

See `references/ci-mode.md` for full spec and GitHub Actions workflow snippet.

## Auto-Healing (`fix` mode)

Only deterministic fixes: regenerate `.t1k-manifest.json`, detect orphaned/stale files, report what needs manual attention. Full details: `references/fix-mode.md`

## Output Format

```
## Doctor Report — {date}
### Checks
- Role coverage: [PASS | FAIL — missing agent for role X]
- Skill existence: [PASS | FAIL — missing skill: Y]
...
### Issues Found
- [issue description + file + line]
### Recommended Fixes
- [action]
```

## Gotchas
- **Origin metadata is CI/CD-managed, committed to git** — Do NOT modify `origin`, `repository`, `module`, `protected` manually. CI manages them. Check #16 validates consistency.
- **Module skills are flattened in release ZIPs** — `modules/{name}/skills/` flattened to `.claude/skills/` during release. The `module:` frontmatter preserves the original assignment.
- **Activation fragments use bare-slug refs by convention** — entries in `sessionBaseline[]` and `mappings[].skills[]` of `t1k-activation-*.json` typically appear as bare slugs (`nakama-rpc`) rather than full-prefixed dir names (`t1k-nakama-rpc`). The prefixer's `auto-prefix-skills.cjs::buildSelfHealMap()` self-heals legacy refs to canonical form at release time, but the SSOT in the fragment files stays bare. The release-action validator `validate-activation-skill-resolution.cjs` (and check #47) accepts BOTH forms, so authors can use either. New refs should match an existing accepted variant — anything else fails the gate at PR time.

## Scope

Registry validation and manifest repair only.

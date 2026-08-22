---

origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---
# Doctor Checks Reference

## Core Checks (#1–6)

1. **Role coverage** — every role in `t1k-routing-*.json` has a matching agent `.md` file
2. **Skill existence** — every skill in `t1k-activation-*.json` has a matching skill folder in `.claude/skills/`
3. **No cross-layer hardcoding** — scan `t1k-routing-*.json` values for engine-specific strings (dots-, unity-, cocos-)
4. **Manifest integrity** — `.t1k-manifest.json` matches actually installed files
5. **Registry version compat** — all `t1k-routing-*.json` and `t1k-activation-*.json` use `registryVersion: 1`
6. **Config completeness** — every command in `t1k-config-*.json` has a matching skill folder

## Module Checks (#7–17)

Follow protocol: `skills/t1k-modules/references/module-detection-protocol.md` — skip if no `installedModules` key or no metadata.

| # | Check | Validates |
|---|---|---|
| 7 | Module file ownership | Every skill file belongs to exactly one module via `.t1k-manifest.json` (no overlap) |
| 8 | Module dependency integrity | All declared dependencies (from module.json) are installed with compatible versions |
| 9 | Activation fragment match | Each installed module has activation source (module.json or t1k-activation-*.json) |
| 10 | Module agent presence | Each module declaring agents has matching `.md` files |
| 11 | Routing overlay validity | Module overlays reference only that module's agents |
| 12 | No stale module files | No files from uninstalled modules remain (cross-check manifests) |
| 13 | SessionBaseline in required module | `sessionBaseline` skills are in required modules only |
| 14 | Keyword uniqueness | No keyword maps to skills in two different modules |
| 15 | Routing priority uniqueness | No two module overlays override same role at same priority |
| 16 | Origin frontmatter match | In-file `origin` frontmatter matches metadata entry |
| 17 | Module frontmatter presence | Files in `modules/*/` have `module:` field in frontmatter matching parent dir |

## Manifest Checks (#21)

| # | Check | Validates |
|---|---|---|
| 21 | Module manifest integrity | Each installed module has `modules/{name}/manifest.json`; listed files exist at flat locations; no orphaned flat files |

**Check #21 details:**
1. For each installed module in metadata: verify `.claude/modules/{name}/manifest.json` exists
2. For each file in manifest: verify it exists at the flattened location
3. Scan `.claude/skills/` for dirs matching `{module}-*` pattern not in any manifest → orphaned
4. Severity: WARN (pre-flattening installs won't have manifests)

## SSOT & Structure Checks (#22–27)

| # | Check | Validates |
|---|---|---|
| 22 | schemaVersion present | `metadata.json` has `schemaVersion: 3` |
| 23 | Version presence | `metadata.json` has real `version` (not `"0.0.0-source"`) and `buildDate` (not `null`) |
| 24 | No stale root modules/ | No `modules/` at repo root alongside `.claude/modules/` (canonical) |
| 25 | Context requiredPaths set | Engine kits (unity/cocos/rn) have `context.requiredPaths` in config |
| 26 | Activation format modern | All `t1k-activation-*.json` use `mappings` array, not deprecated `keywords` object |
| 27 | v3 installedModules | CLI writes `installedModules` with `kit`, `repository`, `version` per module |

## No-Override Checks (#28–29)

| # | Check | Validates |
|---|---|---|
| 28 | Filename collision detection | No two installed kits/modules have same-named agents, skills, or rules. Group files by basename + read `origin` metadata. Exception: merge targets (metadata.json, t1k-modules.json, settings.json, CLAUDE.md). |
| 29 | Agent prefix correctness | Non-core agents have proper prefix: `{kit-short}-` (kit-wide) or `{kit-short}-{module}-` (module). Core agents have no prefix. Slug part must be canonical per algorithm v2 dedup (no leading `{kit-short}-` or `{module-segment}-` redundancy). |
| 29b | Skill `name:` colon-form (planned) | Every SKILL.md `name:` field matches `lib-prefix.expectedSlashName({kit, module, slug})` colon-form. Currently INFO-only; promotes to WARN once colon-namespace migration ships per kit. |

**Check #28 details:**
1. Walk `.claude/agents/`, `.claude/skills/`, `.claude/rules/`
2. Read each file's `origin` metadata (frontmatter/`_origin`)
3. Group files by basename; if same basename with different `origin` values → ERROR: collision
4. Fix mode: suggest running CI auto-prefix or manual rename

**Check #29 details:**
1. For each agent in `.claude/agents/`, read `origin` field — derive expected kit-short
2. If origin != core: verify filename starts with `{kit-short}-`
3. If module agents: verify filename starts with `{kit-short}-{module}-`
4. Verify the canonical name matches `lib-prefix.expectedName({kit, module, slug})` — slug part MUST NOT have leading `{kit-short}-` or `{module-segment}-` redundancy (algorithm v2 dedup, since 2026-05-10). Names like `t1k-rn-rn-base-base-architecture` fail this check; the canonical form is `t1k-rn-rn-base-architecture`.

**Check #29b details (planned, deferred to colon-namespace Phase 4):**
1. For each `SKILL.md`, read frontmatter `name:` field and derive (kit, module, slug) from path.
2. Compute expected colon form via `lib-prefix.expectedSlashName({kit, module, slug})`.
3. If `name:` matches expected colon form → PASS.
4. If `name:` matches the hyphen form (`expectedName(...)`) → INFO during the migration window: "kit X has Y SKILL.md files awaiting colon-namespace migration". Single rolled-up message per kit (not per-skill noise).
5. If `name:` matches neither → WARN: "unexpected name: form `<actual>`, expected `<colon>`".
6. Agents are NOT in scope (agent `name:` stays hyphenated by design — see `t1k-agent-creator/references/architecture-rules.md` §0.2).
7. Implementation status: helper `expectedSlashName` shipped in release-action 2026-05-10. Doctor script wiring deferred until colon-namespace Phase 4 begins (post-dedup-soak). Plan: `theonekit-core/plans/260510-1711-skill-name-colon-namespace/`.

## Frontmatter Quality Checks (#18–20)

| # | Check | Validates |
|---|---|---|
| 18 | Agent maxTurns presence | Every agent `.md` has `maxTurns:` in frontmatter |
| 19 | Skill effort presence | Every skill `SKILL.md` has `effort:` in frontmatter (low/medium/high) |
| 20 | Agent model appropriateness | Implementer/t1k-debugger agents should use `opus`; utility agents (git, docs) should use `sonnet`. `model: inherit` is banned (`rules/agent-model-tier-rubric.md`) |
| 51 | Agent budget calibration | Per `rules/agent-completion-discipline.md`: budget checkpoints must be window-relative, not flat tokens; tool-heavy agents must carry one; `maxTurns` sized to task class |
| 52 | Hook registration drift | Installed enforcement hook scripts have their required event + matcher wiring in `settings.json` |

**Check #51 details (`scripts/check-agent-budget-calibration.cjs`):**

Scans every `.claude/agents/*.md`. An agent is "tool-heavy" when its `tools:` frontmatter includes `Bash`, `Task`, or `Agent` (it can mutate or orchestrate). Flags, at WARN level (exit 0 always):

| Sub-check | Trigger | Fix |
|---|---|---|
| (a) Flat-token checkpoint | Body contains a literal token threshold (`150K` / `150,000` / `200K`) with no window-relative anchoring | Make it relative to the agent's `model:` window (~75%@200K / ~55%@1M) |
| (b) Missing checkpoint | Tool-heavy agent body has no budget/checkpoint language at all | Add the window-relative + ~80%-`maxTurns` checkpoint |
| (c) Under-sized maxTurns | Tool-heavy agent with `maxTurns < 50` | Size to task class — multi-PR/refactor/MCP-validation work hits the turn cap before tokens (#528: `t1k-kit-developer` 45→90) |

Window-relative anchoring is recognized by phrases like `window-relative`, `% of … window`, `relative to … budget`, `maxTurns`, or a citation of `agent-completion-discipline`. Read-only discovery agents (no `Bash`/`Task`/`Agent`) are exempt from (b) and (c). SSOT for the policy: `rules/agent-completion-discipline.md`. Resolves core#530 (fleet calibration); motivated by core#528.

**Check #52 details (`hooks/doctor-check-52-hook-registration-drift.cjs`):**

The module-owned `.claude/scripts/required-hook-registrations.json` is the SSOT.
For each declared registration, the check first verifies that its hook script
is installed. It then requires an exact event, matcher, and hook command
identity in `settings.json`. This exposes the consumer drift from core#601
without flagging hooks omitted by a modular install. A built-in fallback covers
older releases that predate the manifest. Missing wiring is FAIL-level because
the installed enforcement is otherwise inert. Remediation: run `t1k modules
update` with a current CLI and rerun doctor.

**Check #55 details (`hooks/doctor-check-55-kit-file-drift.cjs`):**

Kit-owned files live in two places — project `./.claude/` and global `~/.claude/`
— and project-local takes priority. Nothing detected when the shadowing copy was
BEHIND, so a shipped fix could sit inert in a consumer project indefinitely.
Originating incident: a consumer's `workflow-artifact-gate.cjs` was 12 days older
than the global install and blocked every `git push` with `missing-dir`; 23 of 79
project-local hooks were stale and 4 were absent, with nothing reporting it.

Module versions come from each `.claude/modules/<module>/.t1k-manifest.json`;
version comparison is numeric per segment, since `2.22.2` sorts below `2.9.0`
lexically but is newer. Content comparison covers `hooks/` and `scripts/` only —
drift there silently changes behaviour, which is the failure mode worth checking,
while prose drift is already implied by the module version. Only files carrying a
`t1k-origin` header are considered, so consumer-authored hooks are never flagged.

The three states have opposite remedies and running the wrong one loses work:
BEHIND wants `t1k modules update`; DIVERGED-AHEAD wants `/t1k:sync-back` first,
because update overwrites files that diverged ahead (#367). Skips cleanly when no
separate global install exists. Diagnostic only — `t1k modules update` owns
reconciliation, as with #52.

## Cross-Platform Checks (#30)

| # | Check | Validates |
|---|---|---|
| 30 | Hook cross-platform compliance | All `.cjs` files in `.claude/hooks/` are free of shell-only patterns |

**Check #30 details:**

Scan all `.cjs` files in `.claude/hooks/` for these violations:

| Pattern | Why It Fails | Fix |
|---------|-------------|-----|
| `2>/dev/null` in command strings | Shell redirect, not cross-platform | Use `stdio: ['pipe', 'pipe', 'ignore']` |
| `2>&1` in command strings | Shell redirect, not cross-platform | Capture both stdout/stderr via `stdio: ['pipe', 'pipe', 'pipe']` |
| `/dev/stdin` | Linux-only, breaks Windows | Use `fs.readFileSync(0, 'utf8')` |
| `/dev/null` (outside comments) | Unix-only | Use `stdio` option or `os.devNull` |
| `execSync('cmd arg')` (shell string) | Spawns shell, injection risk | Use `execFileSync('cmd', ['arg'])` |
| Hardcoded `/tmp/` | Unix-only temp path | Use `os.tmpdir()` |
| Hardcoded `/home/` or `/Users/` (in logic, not regex) | Platform-specific | Use `os.homedir()` or `process.env.HOME \|\| process.env.USERPROFILE` |

**Implementation:**
1. Read each `.cjs` file, strip comment lines (`//` and `/* */`)
2. Regex-match against violation patterns
3. Report file:line for each violation
4. Severity: WARN (hooks still work on Linux/macOS, just break on Windows)

**Fix mode:** Cannot auto-fix — requires manual code changes. Report violations with suggested replacement.

## Sync-back Health Checks (#32)

| # | Check | Validates |
|---|---|---|
| 32 | Sync-back PR health | Recent `/t1k:sync-back` PRs are healthy — no CONFLICTING state and no phantom-file (all-additions) diffs |

**Check #32 details:**

Validates that the `/t1k:sync-back` skill is producing healthy PRs. Added after the 2026-04-09 incident where two sync-back PRs were unusable: core#7 was stale (no upstream fetch → CONFLICTING), unity#7 targeted a non-existent path (missing `.claude/` prefix → phantom file at wrong location).

1. Collect all kit repos from `.claude/t1k-config-*.json` → `repos.primary` and from in-file `repository` frontmatter across changed files
2. For each repo (up to 10 distinct repos to bound runtime), query the last 5 PRs with sync-back branch prefix:
   ```
   gh pr list --repo {owner}/{repo} --search "head:t1k-sync/" --state all --limit 5 --json number,title,state,mergeStateStatus,headRefName,additions,deletions,files
   ```
3. For each returned PR, check two signatures:
   - **Staleness signature** — `mergeStateStatus == "CONFLICTING"` while the PR is still `OPEN` → WARN: stale sync-back PR (fix: the skill pushed without fetching upstream)
   - **Phantom-file signature** — any file in the PR has `additions > 0` AND `deletions == 0` AND the filename matches a skill/agent/rule basename that exists elsewhere in the repo → WARN: likely path-resolution bug (fix: verify `.claude/` prefix for modular kits)
4. Report counts: `Sync-back health: {healthy}/{checked} PRs healthy across {N} repos`
5. List problem PRs with URL and signature

**Severity:** WARN (advisory — doesn't fail doctor, just flags drift)

**Skip conditions (fail-open, never block):**
- `gh` CLI not available → skip with note
- `gh auth status` not authenticated → skip with note
- No kit repos resolvable from configs → skip
- Network error during PR query → skip with note

**Fix mode:** Cannot auto-fix — each problem PR needs manual review. For each flagged PR:
- Stale → close and re-run `/t1k:sync-back` (v1.2.0+ has staleness check)
- Phantom-file → close and re-run `/t1k:sync-back` (v1.2.0+ has `.claude/` prefix + path verification)
- Suggest: `gh pr close {number} --comment "Superseded by healthy resync"`

**Why this check exists:** The acceptance criteria for The1Studio/theonekit-core#8 require a doctor check or test that detects these two failure modes in historical PRs. Running this check after releasing a sync-back fix is a cheap smoke-test to confirm no broken PRs slipped through.

## Kits Membership SSOT Checks (#33)

| # | Check | Validates |
|---|---|---|
| 33 | Kits membership SSOT | Asserts `Object.keys(metadata.kits) === unique(installedModules[*].kit)` — catches drift between the derived kit membership and the source `installedModules`. WARN level on mismatch. |

**Check #33 details:**

Runs `scripts/check-kits-membership.cjs` (ships with this skill) against `.claude/metadata.json`. The script:

1. Loads the kit registry from `references/available-kits.json` (shared SSOT that mirrors `AVAILABLE_KITS` in `theonekit-cli/src/types/kit.ts`).
2. Resolves each `installedModules[*].kit` value to a `KitType` via the registry (`theonekit-unity` → `unity`, bare `unity` accepted as tolerance).
3. Compares `Object.keys(metadata.kits)` against the unique set of resolved owners.
4. Reports three drift categories:
   - **missing** — owners present in `installedModules` but missing from `kits`
   - **orphaned** — kit entries with no owning module in `installedModules`
   - **unresolved** — `installedModules` entries whose `kit` field does not resolve (dropped from the rebuild with a warning in CLI; surfaced here for visibility)
5. Prints `PASS` when all three are empty; otherwise `WARN` with details.

**Skip conditions:**
- `metadata.json` not found → SKIP
- No `installedModules` and not a v3 metadata file → SKIP (check only meaningful for v3 module-first metadata)

**Severity:** WARN (migration grace — doesn't fail doctor, just flags drift). Fix: run `t1k modules add ...` or `t1k modules remove ...` — the CLI rebuilds membership via `rebuildKitMembership` in `theonekit-cli/src/domains/modules/kit-membership.ts`.

**Why this check exists:** Prevents regression of the Zod `Unrecognized key` crash where unresolved kit values were bucketed under a synthetic `"unknown"` key, bricking `writeManifest` on the next `t1k` invocation. See `rebuildKitMembership` docstring for the derivation formula and SSOT rationale.

## Orphaned Agent Checks (#34)

| # | Check | Validates |
|---|---|---|
| 34 | Orphaned agents | Agent files in `.claude/agents/` whose `origin:` frontmatter points to a kit that is NOT in `installedModules[*].kit` (v3) or `metadata.kits` (older schemas). WARN level. |

**Check #34 details:**

Runs `scripts/check-orphaned-agents.cjs` against `.claude/metadata.json` and `.claude/agents/`. The script:

1. Loads the kit registry from `references/available-kits.json`.
2. Builds the set of installed kits from `installedModules[*].kit` (v3) unioned with `Object.keys(metadata.kits)` (older schemas). Accepts both short (`unity`) and long (`theonekit-unity`) keys.
3. Walks `.claude/agents/*.md`, parses the YAML frontmatter, and reads the `origin` field.
4. Reports agents whose `origin` does NOT resolve to any installed kit.

**Why this check exists:** `t1k uninstall --kit X` relies on the kit's `.t1k-manifest.json` to know which files to delete. Agents installed before per-module manifests (pre-v1.64.0) were never added to the manifest, so the ownership-aware uninstall skips them. The orphaned agent files stay on disk with `origin: theonekit-X` frontmatter even though kit X is uninstalled — they continue loading into every session, bloating context and potentially activating for tasks that no longer match the active toolchain.

**Skip conditions:**
- `metadata.json` not found → SKIP
- Both `installedModules` empty AND `kits` empty → SKIP
- `agents/` directory missing → SKIP

**Severity:** WARN (migration grace — doesn't fail doctor, just flags leftovers). Fix: upgrade CLI to v3.5+ and run `t1k uninstall --kit <name> --include-orphans`, or manually `rm .claude/agents/<file>` for each orphan.

**Related work:** Report the CLI gap via `/t1k:issue` against `The1Studio/theonekit-cli` so `t1k uninstall` gains a frontmatter-based fallback for pre-manifest installs.

## Context Window Hygiene (#35–#36)

| # | Check | Validates |
|---|---|---|
| 35 | CLAUDE.md bloat | Project `CLAUDE.md` ≤ 5000 tokens (char/4 heuristic). WARN. |
| 36 | Rule duplication | No rule filename present in both `~/.claude/rules/` and project `.claude/rules/`. INFO. |

**Check #35 details:**

Runs `scripts/check-claude-md-bloat.cjs`. Reads project `CLAUDE.md`, estimates tokens via `chars / 4`, compares against a 5000-token budget. When over, reports the overshoot and suggests moving details to `docs/` and deduplicating with `.claude/rules/` files.

**Why this check exists:** Every session loads `CLAUDE.md` in full. A bloated CLAUDE.md (>5k tokens) usually duplicates content that belongs in `.claude/rules/` (auto-loaded, so duplicating wastes context) or in `docs/` (searchable on demand). Example: an 11.9k-token CLAUDE.md was reduced to 2k tokens just by moving gate backlogs, hook implementation details, and origin-metadata tables to `docs/`.

**Severity:** WARN (doesn't fail doctor, just flags bloat).

**Check #36 details:**

Runs `scripts/check-rule-duplication.cjs`. Enumerates `*.md` files in `~/.claude/rules/` and `<project>/.claude/rules/`, compares by basename. Reports files present in both — those are double-loaded every session.

**Why this check exists:** Claude Code auto-loads rule files from BOTH the global `~/.claude/rules/` and the project `.claude/rules/` every session. When a kit ships rules at both scopes (common for core-overlapping rules like `code-conventions.md`, `coding-guidelines.md`), the content loads twice — roughly doubling its context cost. Keep shared patterns in one scope only.

**Severity:** INFO (advisory — doesn't fail doctor; some projects intentionally version-lock project-scope rules).

**Skip conditions:**
- Project rules/ resolves to the global rules/ (e.g., running inside `~/.claude/`): SKIP
- Either dir missing or empty: SKIP
## Adapter Contract Checks (#37)

| # | Check | Validates |
|---|---|---|
| 37 | Adapter contract | Every discovered adapter skill has valid `t1k-adapter` frontmatter, required scripts, and a conformant `install.json` |

**Check #37 details:**

Runs `hooks/doctor-check-37-adapter-contract.cjs` against the current `.claude/` dir:

1. Calls `listAllMatches()` from `skills/t1k-preview/scripts/adapter-discovery.cjs` (Steps 1–4: metadata read + frontmatter + schema validation only — no `detect.cjs` run, no side-effects).
2. For each discovered adapter:
   - Verifies all four required scripts exist in the skill dir: `detect.cjs`, `list-capabilities.cjs`, `generate.cjs`, `requirements.cjs`.
   - Verifies `install.json` is present, parses as valid JSON, and has a `schemaVersion` field and a non-empty `catalog`.
3. Exits 0 with `PASS` when no adapters are installed (nothing to validate).
4. Exits 0 with `PASS` when all adapters conform; exits 1 with per-adapter details on `FAIL`.

**Severity:** FAIL (exits 1) if any required script or `install.json` is missing; WARN for schema-level issues (empty catalog, missing schemaVersion).

**Skip conditions:**
- `adapter-discovery.cjs` not found (t1k-extended not installed) → FAIL with actionable message
- Zero adapters discovered → PASS silently

**Why this check exists:** Ensures kit authors cannot ship a broken adapter that crashes `t1k diagram refresh` mid-run. Catching missing `generate.cjs` or an empty `install.json` at doctor-time is cheaper than debugging a partial refresh at runtime.

**Inheritance-aware behavior:** When `metadata.json` contains `inheritsFrom` pointing at the global `.claude/`, filename duplicates are treated as INTENTIONAL overrides (child wins) and are NOT reported. Byte-identical copies are still reported regardless — those remain accidental. If `inheritsFrom` is set but the parent path is missing, the check exits non-zero with ERROR (see check #37).

## Inheritance Integrity Check (#37)

| # | Check | Validates |
|---|---|---|
| 37 | inheritsFrom integrity | When `metadata.json` contains `inheritsFrom`, validates the field value is a well-formed parent `.claude/` path. ERROR severity. |

**Check #37 details:**

Runs `scripts/check-inherits-from.cjs`. If the `inheritsFrom` field is absent from `metadata.json`, the check SKIPs (no-op for existing installs). If present, all conditions below are validated at ERROR severity (fail-loud, never silent):

1. **(a) Path exists** — `fs.existsSync(inheritsFrom)` must be true → ERROR: parent path missing. Remediation: remove the field OR re-create the parent `.claude/`.
2. **(b) Path is a directory** — `fs.statSync(inheritsFrom).isDirectory()` must be true → ERROR: not a directory.
3. **(c) Ends in `.claude`** — `path.basename(inheritsFrom) === '.claude'` must be true → ERROR: must end in `.claude` (not `.claude/metadata.json`).
4. **(d) Has metadata.json** — `fs.existsSync(path.join(inheritsFrom, 'metadata.json'))` must be true → ERROR: parent is not a T1K install.
5. **(e) Parent is T1K-shape** — `isT1KMetadata(parentMeta) === true` must hold → ERROR: not valid T1K metadata (CK stub?).
6. **(f) No self-reference** — `path.resolve(inheritsFrom) !== path.resolve(<project>/.claude)` must hold → ERROR: inheritsFrom points at self.
7. **(g) No cycle (≤5 hops)** — following `parent.metadata.inheritsFrom` recursively must terminate within 5 hops → ERROR: inheritance cycle detected at `<node>`.

**Severity:** ERROR. The field is opt-in — if you set it, it must be valid. Matches `development-principles.md` "Errors Over Silent Fallbacks".

**Skip condition:** `inheritsFrom` absent from `metadata.json` → SKIP (exit 0). No metadata.json → SKIP.

**Why this check exists:** Ensures that when `inheritsFrom` is set (e.g., by `t1k init --inherit-from`), the parent path remains valid across directory moves and renames. A stale pointer is detected at next `/t1k:doctor` run rather than silently degrading rule loading.

**References:**
- Script: `scripts/check-inherits-from.cjs`
- Tests: `.claude/hooks/__tests__/check-inherits-from.test.cjs` (scenarios T5–T11)
- Schema: `docs/registry-schema.md` (metadata v3 `inheritsFrom` field)
- Docs: `docs/global-only-mode.md` §Nested installs

## MCP Health Checks (#31)

| # | Check | Validates |
|---|---|---|
| 31 | MCP server connectivity | All required MCPs are connected and configured; recommended MCPs present |

**Check #31 details (`hooks/doctor-check-31-mcp-connectivity.cjs`):**

Runs `.claude/hooks/doctor-check-31-mcp-connectivity.cjs` — a deterministic,
exit-code-bearing script, not an AI-improvised prose walkthrough. Before this
script existed, a missing REQUIRED MCP server produced only a SessionStart
banner line (`[t1k:mcp] action=install ...`) — durable, but never
deliberate: nothing failed, nothing exited non-zero. This check is what makes
a missing required MCP a doctor FAIL.

It reuses `hooks/lib/mcp-requirements.cjs` — the SAME config-collection,
`appliesWhen`-gating, and connectivity/`requiredEnv` probing logic the
SessionStart hook (`check-mcp-health.cjs`) uses, per
`rules/development-principles.md` § SSOT. Steps:

1. Read ALL `t1k-config-*.json` → collect `mcp.required[]` and `mcp.recommended[]` entries, deduplicated by `name` (first-seen wins). `mcp.optional[]` is out of scope (already governed by the SessionStart cooldown).
2. Filter both tiers through the `appliesWhen` gate (project type / owning kit / installed modules) — an entry that doesn't apply to this install is never evaluated.
3. Run `claude mcp list` once. If the CLI cannot be queried (absent, times out, non-zero exit), the WHOLE check reports **UNKNOWN** — never a false PASS (trusting an unreachable CLI) or a false FAIL (blaming the servers for an infrastructure problem).
4. For each applicable entry, distinguish three states (they need different fixes):
   - **not registered at all** → FAIL (required) / WARN (recommended), printing the entry's `installCmd` verbatim
   - **registered but `requiredEnv` unsatisfied** (probed via `claude mcp get {name}`) → FAIL (required) / WARN (recommended), naming the missing variable(s) + `installCmd`
   - **registered and configured** → OK
   - a failed *per-entry* `requiredEnv` probe (server registered, but `claude mcp get` itself could not be queried) → **UNKNOWN** for that entry, never counted as a failure

**Severity:**
- Missing/misconfigured required entry: **FAIL** (exit 1)
- Missing/misconfigured recommended entry: **WARN** (never fails the check)
- `claude` CLI unreachable, or a per-entry `requiredEnv` probe failure: **UNKNOWN** (never counted as FAIL or as a silent PASS)

**Skip conditions:**
- No `.claude/` directory resolvable → SKIP
- No `mcp.required[]`/`mcp.recommended[]` entries declared in any fragment → SKIP
- No entries apply after the `appliesWhen` gate → SKIP

**Fix mode:** run the printed `installCmd` (`claude mcp add ... -s user`) for a missing server; for a `requiredEnv` gap, set the named variable(s) and re-add or `claude mcp get {name}` to confirm.

**`verifyTool` is NOT evaluated by this script.** Confirming a deferred `mcp__{server}__*` tool is actually loadable requires `ToolSearch`, which only the AI running `/t1k:doctor` can call — a plain node script has no such capability, and neither did the prior SessionStart hook. When an entry declares `verifyTool` and this check reports it OK, the doctor SKILL body may additionally probe `ToolSearch` for that prefix and downgrade to WARN ("registered but not functional — may need auth") if no matching tool is found. This is unchanged from before the script existed; it was never scripted.

**Why this check exists:** `mcp.required[]` (per `t1k-config-core.json`) currently lists `github`, `context7`, `sequential-thinking`, `memory`, `plane` — a server on that list missing for an unknown period previously degraded features silently (e.g. the enforced Plane work-item workflow warn-and-continuing indefinitely with nobody noticing). Test coverage:
`hooks/__tests__/doctor-check-31-mcp-connectivity.test.cjs` (FAIL/PASS/WARN/UNKNOWN, both required-miss shapes) and `hooks/lib/__tests__/mcp-requirements.test.cjs` (shared-lib unit coverage).

### Frontmatter Check Output
```
### Frontmatter Quality
- Agent maxTurns: [PASS | WARN — N agents missing maxTurns: {list}]
- Skill effort: [PASS | WARN — N skills missing effort: {list}]
- Agent model: [PASS | WARN — {agent} uses {model} but role suggests {recommended}]
```

## Module Detect Coverage (#41)

| # | Check | Validates |
|---|---|---|
| 41 | Module detect coverage | Every non-base module in `.claude/modules/` has either `detect:` or `detect._optOut: true`; WARN pre-ratchet, ERROR post-ratchet |

**Check #41 details:**

Runs `.claude/skills/t1k-doctor/scripts/check-module-detect-coverage.cjs`. Iterates `.claude/modules/*/module.json` and reports modules that:
- are NOT in `CORE_REQUIRED = ["t1k-base", "t1k-extended", "t1k-maintainer"]`
- are NOT `required: true` (kit-base opt-out)
- lack an active `detect:` block, or have `_disabled: true` (stub modules are surfaced as "needs activation")

**Ratchet (data-driven):** reads `.claude/t1k-modules.json.ratchetDates."module-detect-coverage"` (ISO date). Before that date: `WARN`. After: `ERROR` (exit 1). Env bypass: `T1K_BYPASS_DETECT_RATCHET=1` forces `WARN` regardless. This matches the plan's P6e rollback design (editable ratchet + env escape hatch).

**Severity:** WARN pre-ratchet, ERROR post-ratchet (or WARN if bypass env set).

**Why this check exists:** Ships alongside the P0 `detect:` schema so kit authors cannot silently ship modules without detection. The 90-day warn window gives kits time to backfill; the ERROR-level ratchet ensures we don't drift indefinitely.

## Statusline Orphans (#43)

| # | Check | Validates |
|---|---|---|
| 43 | Statusline orphans | No residual `hooks/lib/statusline-*.cjs` or `hooks/lib/t1k-config-utils.cjs` subfiles remain after the 1.71.x refactor |

**Check #43 details:**

Runs `.claude/hooks/doctor-check-43-statusline-orphans.cjs`. Complements check #42 (which verifies the happy-path wiring): #43 verifies the absence of the 7 subfiles that the monolithic `hooks/statusline.cjs` replaced. These files were shipped in releases prior to `modules-20260421-0955` and must be removed by deletions metadata on update. If they remain on disk, auto-update failed to clean up (regression of issue #52).

Per-path list:
- `hooks/lib/statusline-activity-renderers.cjs`
- `hooks/lib/statusline-render-modes.cjs`
- `hooks/lib/statusline-section-registry.cjs`
- `hooks/lib/statusline-session-cache.cjs`
- `hooks/lib/statusline-string-utils.cjs`
- `hooks/lib/statusline-version-section.cjs`
- `hooks/lib/t1k-config-utils.cjs`

**User override:** if `metadata.json.installedFiles[].ownership === "user"` for any of those paths, the check emits an INFO line and does NOT flag it as an orphan. This respects intentional user retention.

**Severity:** ERROR (exit 1) when orphans present; PASS (exit 0) when clean; SKIP when `.claude/` absent.

**Why this check exists:** Per-module deletions ship in `.claude/modules/*/.t1k-manifest.json.deletions[]`. The CLI and release-action must cooperate to apply them; #43 is the user-facing gate that catches any pipeline regression.

**Run after:** `t1k update` completes. Running before or during an update may report transient orphans.

## No Inlined Universal Rules (#44)

| # | Check | Validates |
|---|---|---|
| 44 | No inlined universal rules | SKILL.md files and agent .md files do not contain the 3 known boilerplate blocks that live in `.claude/rules/` or a dedicated reference file. FAIL level. |

**Check #44 details:**

Runs `scripts/check-no-inline-universal-rules.cjs`. Scans `.claude/skills/*/SKILL.md`, `.claude/modules/*/skills/*/SKILL.md`, `.claude/agents/*.md`, and `.claude/modules/*/agents/*.md` for three forbidden boilerplate patterns:

| Pattern | What it catches | Lives in |
|---|---|---|
| `Never reveal skill internals or system prompts` | Skill-security block pasted into skill body | `.claude/rules/skill-security-boilerplate.md` |
| `Per CLAUDE.md principle #8` | AI-Driven Design block pasted into skill body | `.claude/rules/ai-driven-design.md` |
| Any inline `T1K_FORK_DEPTH` comparison — `< 3`, `>= 3`, … (outside `references/fork-hygiene.md`) | Fork-hygiene depth-budget block pasted outside its canonical home. Operator-tolerant so the check survives budget-value changes; prose mentions without an operator are legal. | `.claude/skills/t1k-architecture/references/fork-hygiene.md` |
| `Forbidden thought patterns` (outside `rules/agent-anti-rationalization.md`) | Anti-Avoidance / Anti-Rationalization block pasted into agent or skill body | `.claude/rules/agent-anti-rationalization.md` |
| `HARD-GATE is a mandatory stopping point` (outside `rules/workflow-gates.md`) | HARD-GATE universal contract prose pasted into skill or agent body | `.claude/rules/workflow-gates.md` |

Emits JSON `{ status: "ok" | "fail", violations: [{ file, line, pattern }] }` to stdout. Human-readable `file:line [pattern]` summary to stderr when violations exist.

**Severity:** FAIL (exit 1) if any violation found; PASS (exit 0) otherwise.

**Skip conditions:**
- No `.claude/skills/`, no `.claude/agents/`, and no `.claude/modules/` → SKIP (no files to scan).

**Why this check exists:** During plan `20260428-1530-architecture-fix-rollout`, ~350 lines of inlined boilerplate were removed from 25+ skills across 7 kits. These three boilerplates auto-load every session via `.claude/rules/` — pasting them into skill or agent bodies doubles their context cost and causes drift when the canonical version is updated. Extended to agent `.md` files because `t1k-skills-manager.md:47–56` was found to inline the skill-security block verbatim. This check catches re-introductions at doctor-run time; release-action CI gate `validate-no-inline-universal-rules.cjs` catches them at PR level.

**Related:** `architecture-rules.md` (skill-creator) → "Anti-Pattern: Inlining Universal Rules in Skill Bodies". Same rule applies to agent bodies via `agent-creator/references/architecture-rules.md`.

## Auto-Pipeline Prereq (#46)

| # | Check | Validates |
|---|---|---|
| 46 | Auto-pipeline GitHub MCP prereq | When `features.autoIssueSubmission` or `features.autoLessonSync` is ON, the GitHub MCP must be registered. Diagnostic WARN when there is a mismatch. |

**Check #46 details:**

Runs `scripts/check-auto-pipelines-prereq.cjs`. Reads merged `features.{autoIssueSubmission, autoLessonSync}` across all `t1k-config-*.json` fragments (later fragments win). When at least one is `true`, probes `claude mcp list` and looks for a `github` entry. The two auto-pipelines spawn background sub-agents that call `mcp__github__*` tools (issue creation, PR creation); without the MCP the marker queues silently and submissions fail without a visible error.

Output: JSON `{ status: "pass" | "skip" | "warn", enabled: {...}, githubMcpPresent: bool|null, reason: string }` to stdout; WARN summary to stderr when a mismatch is detected.

**Severity:** WARN (advisory; never blocks doctor). Exit code is always 0.

**Skip conditions:**
- Both flags OFF → PASS with `reason: auto-pipelines disabled — GH MCP prereq not applicable`
- `claude` CLI unavailable → SKIP (cannot probe MCP state)

**Fix mode:** Run `claude mcp add github` (per `t1k-config-core.json` → `mcp.required[github].installCmd`). If the MCP is registered but unauthenticated, run `claude mcp auth github`. This check complements #31 (which already errors on missing required MCPs); #46 is the diagnostic version that ties the consequence to the enabled-pipeline flags.

**Output fields (when pipelines enabled):** `pendingLessonUpdates` (count of unsubmitted entries in `pending-skill-updates.jsonl`) and `pendingIssueSubmissions` (from `pending-issue-submissions.jsonl`). Non-zero counts surface as part of the `reason` string (e.g., `"GitHub MCP present; 3 lesson updates pending"`). A value of `-1` means the file could not be read (unknown). **Fix mode for pending counts:** no automated fix — wait for the next session trigger or manually invoke the appropriate background sub-agent (`/t1k:issue` or `/t1k:sync-back`).

**Why this check exists:** Both pipelines were flipped ON by default in `t1k-config-core.json` on 2026-05-06 (calibrated for TheOneKit's ~50-user internal scope). Consumers without the GitHub MCP would see queue entries pile up in `.claude/telemetry/pending-issue-submissions.jsonl` / `pending-skill-updates.jsonl` with no submissions and no failure surface. The check makes the silent-fail mode visible at doctor-run time.

**Related:** `docs/auto-issue-collection.md` (issue pipeline contract), `.claude/rules/telemetry.md` (lesson-sync contract), `docs/auto-issue-pipeline.md` (setup + troubleshooting guide).

## Project Module Fitness (#40)

| # | Check | Validates |
|---|---|---|
| 40 | Project module fitness | Shells `t1k modules detect --json --cache-only`; WARN when confident install/recover recommendations exist |

**Check #40 details:**

Runs `.claude/hooks/doctor-check-40-project-module-fitness.cjs`. The hook is cache-only — it never triggers a cold scan (cold scans can exceed 10s on monorepos and would block every doctor run). The CLI owns TTL/staleness; if the cache is missing or stale, the hook SKIPs with a hint to run `/t1k:modules detect`.

1. Skip if `resolveProjectDir()` reports global-only mode.
2. Skip if `t1k` CLI is absent from PATH.
3. Skip if `.claude/session-state/detect-cache.json` is missing.
4. Spawn `t1k modules detect --json --cache-only` with a 5s timeout (`shell: false`).
5. Skip if CLI reports `{mode: "cache-empty"}` or non-zero exit.
6. Parse JSON; WARN when `confident.install.length > 0 || confident.recover.length > 0` and list module names.
7. **Ignore `ambiguous[]` and `unused-suspect[]`** — those require AI review (skill P7), not doctor.

**Severity:** WARN (advisory — never blocks).

**Why this check exists:** Surfaces project-module fitness drift (e.g., `IComponentData` present in Assets but `dots-ecs-core` not installed) so consumers notice before bugs accumulate. Doctor stays deterministic; ambiguous evidence is deferred to the interactive `/t1k:modules` flow.

## Activation Skill Resolution (#47)

| # | Check | Validates |
|---|---|---|
| 47 | Activation skill resolution | Every skill ref in every `t1k-activation-*.json` `sessionBaseline[]` and `mappings[].skills[]` array resolves to a real skill directory |

**Check #47 details:**

Wraps the release-action gate `validate-activation-skill-resolution.cjs` (added 2026-05-11 alongside the PR #76 self-heal). Walks fragments at three locations:

1. Kit-level fragments under `.claude/` matching glob `t1k-activation-*.json`
2. Module-level fragments under `.claude/modules/<m>/` matching the same glob
3. Dual-tree fragments under `modules/<m>/` (web/marketing layout) matching the same glob

For every ref in `sessionBaseline[]` and `mappings[].skills[]`, accepts BOTH:

- **Full-prefixed form** — exact match against canonical skill dir basename (`t1k-nakama-rpc`).
- **Bare-slug form** — match against any of the four `stripPrefix` variants the prefixer's `auto-prefix-skills.cjs::buildSelfHealMap()` accepts:
  - kit + module strip → `script-graph` (from `t1k-rn-rn-base-script-graph`)
  - kit-only strip → `rn-base-script-graph`
  - module-only strip → `rn-rn-base-script-graph`
  - `t1k-` only strip → `rn-rn-base-script-graph`

When a ref doesn't resolve, surfaces a "did you mean" hint listing the closest canonical dir names by Levenshtein distance.

**Severity:** WARN locally (doctor advisory). The release-action gate is the strict enforcer at PR time — it's wired in WARN mode (`continue-on-error: true`) during the introduction soak, ratcheting to ERROR after per-kit cleanup PRs land for the legacy `{kit}-{slug-without-module}` form (e.g., `rn-script-graph` skipping the `rn-base` module segment).

**Skip conditions:**
- No `.claude/` directory → SKIP
- No skill dirs found → SKIP
- No activation fragments → SKIP
- Fragment paths under `/fixtures/`, `/__fixtures__/`, `/test-fixtures/` → SKIP

**Fix mode:** Cannot auto-fix — the right rewrite depends on intent (use canonical dir name, or one of the four self-heal-accepted bare forms). Doctor reports the violations and the recommended fix.

**Why this check exists:** PR #76's auto-prefix-skills self-heal handles only the documented `stripPrefix` accept-set. The legacy `{kit}-{slug}` form (skipping the module segment) is real but NOT in the self-heal set — so refs in that form survived the 2026-05-08 universal-prefix migration AND the 2026-05-11 self-heal. Surfacing them at PR time + doctor time pushes the cleanup forward instead of letting drift accumulate. See release-action PR #77 for the gate introduction.

**Related:** Check #2 (skill existence — orthogonal: validates the inverse, that activation refs aren't pointing at nothing). The activation-coverage check (release-action `validate-activation-coverage.cjs`) validates the OTHER inverse: skills that exist but have no activation ref.

## Global Install Core-Only (#48)

| # | Check | Validates |
|---|---|---|
| 48 | Global install core-only | `$HOME/.claude/metadata.json` `.kits` should contain ONLY `core`. Non-core kits installed globally trigger a WARN. |

**Check #48 details:**

Reads `$HOME/.claude/metadata.json` (regardless of CWD — the check is about the GLOBAL install state, not the current project) and enumerates `.kits.*` keys. Any key that is NOT `core` (e.g., `unity`, `designer`, `cocos`, `react-native`, `web`, `nakama`) emits a WARN line with the kit name, installed version, and the recommended `t1k uninstall --global --kit <name>` command.

**Why this check exists:**

- Global = always-on essentials; only `theonekit-core` has the universal registry/rules/hooks/skills that every session needs.
- Per-project = engine/domain-specific. Unity skills are only useful when working on a Unity project; loading them globally surfaces irrelevant activation candidates in every session.
- Real incident (2026-05-11): a user's `$HOME/.claude/` accumulated 162 unprefixed Unity skills as orphans because Unity was installed globally but never updated cleanly. The orphan skills then showed up in unrelated projects, polluted keyword activation, and bloated SessionStart hook scans.

**Severity:** WARN — this is a recommendation, not a violation. Does not block CI. Users with a deliberate global engine-kit install (rare; usually a mistake) can ignore.

**Skip conditions:**
- No `$HOME/.claude/metadata.json` (T1K not installed globally) → SKIP
- `metadata.json` unparseable → SKIP with error message
- No `.kits` key in metadata → SKIP

**Fix mode:** Cannot auto-uninstall (destructive — affects user's global install). Doctor reports the offending kits + the exact CLI command to remove each.

**Related:** Check #34 (orphaned agents — related symptom: stale-install drift in global). The corrective workflow is: (1) `t1k uninstall --global --kit <name>` for each non-core kit, (2) install the engine kit per-project in projects that actually use it.

## Multimodal Setup (#49)

| # | Check | Validates |
|---|---|---|
| 49 | Multimodal setup | When `t1k-extended` module is installed AND `skills/t1k-extended-multimodal/SKILL.md` is present: GEMINI_API_KEY set, MINIMAX_API_KEY set (optional), python3 ≥ 3.10 available, `github:The1Studio/human-mcp#v2.15.1` resolvable |

**Check #49 details:**

Runs `.claude/hooks/doctor-check-49-multimodal-setup.cjs`. Two-part install guard:
1. `installedModules['t1k-extended']` must exist in `metadata.json` (keys are module names, NOT skill names).
2. `.claude/skills/t1k-extended-multimodal/SKILL.md` must exist on disk (secondary guard for partial installs).

When both pass, runs four sub-checks:

| Sub-check | Severity | Detail |
|---|---|---|
| GEMINI_API_KEY env var | WARN | Required for Gemini image/video generation and analysis |
| MINIMAX_API_KEY env var | WARN | Optional — required only for MiniMax speech/music generation |
| python3 ≥ 3.10 | FAIL (exit 1) | Required for all multimodal Python scripts |
| `github:The1Studio/human-mcp#v2.15.1` resolvable | WARN | Uses `npm view @goonnguyen/human-mcp@2.15.1` as upstream freshness signal (metadata-only, no code execution); install hint points to fork |

**Status set:** `SKIP | OK | WARN | FAIL`. `FAIL` is also used by the top-level fail-open catch block (internal exceptions — never silently dropped).

**Exit codes:**
- `0` — SKIP, OK, WARN, or internal error (fail-open)
- `1` — FAIL (python3 missing or too old; check 3 only)

**Skip conditions:**
- No `.claude/` directory resolvable → SKIP
- `metadata.json` not readable (new install, no modules yet) → SKIP
- `t1k-extended` not in `installedModules` → SKIP
- `skills/t1k-extended-multimodal/SKILL.md` absent on disk → SKIP

**Phase 10 support:** Honors `T1K_METADATA_PATH` env override so smoke-test fixtures can inject an arbitrary `metadata.json` path without touching real disk state.

**Supply-chain safety:** Uses `npm view ... version --json` for MCP resolvability — metadata-only, no `npx --yes` code execution.

**Why this check exists:** The multimodal skill (`t1k-extended-multimodal`) requires Python 3.10+, an API key for Gemini, and the optional `human-mcp` server. Without this check, users who install the skill would see silent failures at runtime (Python version too old, missing API keys) with no diagnostic surface. Check #49 is the consumer-facing gate that surfaces these setup issues at doctor-run time before any multimodal operation is attempted.

## Stale-Backup Folders Inside Auto-Scanned Dirs (#50)

| # | Check | Validates |
|---|---|---|
| 50 | Stale-backup folders inside auto-scanned dirs | No quarantine subdirectory (`.stale-backup-*`, `.zombies-*`, `.backup-*`, `.archive-*`, `.old`, `.deprecated`, `.trash`) exists inside `agents/`, `skills/`, `rules/`, `hooks/`, or `commands/` under either global `~/.claude/` or project `.claude/`. |

**Check #50 details:**

Runs `scripts/check-stale-backup-folders.cjs`. Walks each of the 5 auto-scanned folders (`agents/`, `skills/`, `rules/`, `hooks/`, `commands/`) under BOTH `~/.claude/` (global) and the project's `.claude/` (local). Any direct child directory whose name matches one of the quarantine patterns emits a WARN line with the full path, file count, and the exact `mv` (move out) and `rm -rf` (delete) commands to remediate.

**Quarantine patterns detected:**
- `.stale-backup` / `.stale-backup-{YYMMDD}`
- `.zombies` / `.zombie-*`
- `.backup` / `.backup-*`
- `.archive` / `.archive-*`
- `.old` / `.old-*`
- `.deprecated` / `.deprecated-*`
- `.trash` / `.trash-*`

**Why this check exists:**

Real incident (2026-05-28): the `/agents` UI displayed 6 `t1k-model-router-mr-*` agents that the kit source had removed. Investigation showed they lived in `~/.claude/agents/.stale-backup-260526/` — moved there 2 days earlier by a consumer-side cleanup following the `naming-convention.md` rule's "Move to `.stale-backup-{YYMMDD}/` subdir" advice. **Claude Code's `/agents` UI and skill discovery walk dot-prefixed subdirectories.** Files inside surface as live registrations regardless of the parent dir's hidden status. The "hide them with a dot prefix" assumption is wrong.

**Severity:** WARN — informational. Does not block CI; fix-mode does not auto-remediate (destructive — affects user files).

**Fix paths:**
1. **Move out of the auto-scanned folder:** `mv ~/.claude/agents/.stale-backup-260526 ~/.claude/.stale-backup-260526` — keeps a rollback safety net under `~/.claude/` (one level up) where nothing scans.
2. **Delete after verification:** `rm -rf ~/.claude/agents/.stale-backup-260526` — permanent. Use once you're sure no rollback is needed. <!-- gate:allow-rm-claude (subdirectory cleanup of a user-created quarantine dir, not the tree) -->

**Related:**
- `rules/naming-convention.md` § Violation handling — canonical guidance amended 2026-05-28 to forbid the in-folder quarantine pattern.
- Check #34 (orphaned agents) — related symptom, different cause (frontmatter `origin:` mismatch vs. quarantine-folder leak).

**Skip conditions:** None — runs unconditionally; harmless when the directories don't exist (silent PASS).

## Agent Routing Reachability (#53)

| # | Check | Validates |
|---|---|---|
| 53 | Agent routing reachability | Every `.claude/agents/*.md` contributes at least one keyword to the data-driven routing index, and every agent absent from all `t1k-routing-*.json` `roles` maps declares its `roles:` intent explicitly. |

**Check #53 details:**

Runs `scripts/check-agent-routing-reachability.cjs`. Builds the index with the shipped `hooks/lib/agent-routing-index.cjs` (the same code `generic-agent-detector` uses) against the TARGET `.claude` dir, inverts `keywordToAgent`, and reports two signals:

- **unreachable** — the agent owns zero keywords, so `suggestAgent()` can never name it. Cause: the description carries no `<example>` block with a `user:` prompt or `Context:` line, or every one of its tokens is already claimed by an alphabetically earlier agent (first-seen wins).
- **undeclared roles** — the agent is not a value in any routing fragment's `roles` map AND its frontmatter has no `roles:` key at all.

**The SSOT rule this makes explicit:** `roles: none` means "no generic role keyword resolves to me" — the release-action generator's documented opt-out for utility agents. It does **not** mean "never suggest me". Omitting `roles:` entirely states nothing, which is drift.

**Why this check exists:**

#659 — `t1k-researcher`, `t1k-code-simplifier`, and `t1k-mcp-manager` (3 of 14 agents, all `roles: none`) were structurally unsuggestable because the index harvested description keywords only for agents already present in a `roles` map. The detector that files fall-through reports could not name the specialists those reports should route to, and the silence read as "no specialist exists". The index now harvests every installed agent `.md`; this check keeps the invariant from silently regressing when the next agent is added.

**Severity:** WARN — advisory, exit 0 always. An unreachable agent degrades routing quality; it does not break anything.

**Skip conditions:**
- No `agents/` directory → SKIP
- No agent `.md` files → SKIP
- `hooks/lib/agent-routing-index.cjs` not resolvable → SKIP (never a false "unreachable")

**Test:** `.claude/hooks/__tests__/agent-routing-blind-spot.test.cjs` (CI-gated by the hook test-runner).
## Agent MCP Tool-Grant Drift (#54)

| # | Check | Validates |
|---|---|---|
| 54 | Agent MCP tool-grant drift | Every `mcp__<server>__<tool>` grant in an agent's `tools:` frontmatter is present in that server's declared `servedTools` manifest. |

**Check #54 details:**

Runs `scripts/check-agent-mcp-tool-grants.cjs`. Parses the `tools:` YAML array of every `.claude/agents/*.md`, keeps entries matching `mcp__<server>__<tool>`, and reconciles them against `mcp.{required,recommended,optional}[].servedTools` collected from every `t1k-config-*.json` fragment.

**Outcomes:**

| Situation | Result |
|---|---|
| Grant present in the server's manifest | PASS |
| Grant absent from the server's manifest | WARN — names the agent, the grant, and the three non-grantable name shapes |
| Server has no declared `servedTools` | **unverified** — reported as a count, never as a violation |
| No server declares `servedTools` at all | SKIP |
| Server-level grant (`mcp__<server>__*`) | Not reconciled per-tool |
| Manifest tool no agent grants | Silent by default; `--include-ungranted` reports it as informational |

**Why the manifest and not a live `tools/list`:** `claude mcp list` / `claude mcp get` do not expose a tool list, so a live probe means speaking MCP JSON-RPC to a server this check would have to spawn — seconds per stdio server against a suite budgeted at < 60s, and impossible when the server simply is not running. More importantly, a false "this tool doesn't exist" is exactly the failure that produced #651's over-correction half. Silence is the safe default: an undeclared server is unverified, never wrong.

**Declaring a manifest** (see `docs/registry-schema.md` § `mcp.required[]`):

```json
{
  "name": "UnityMCP",
  "purpose": "Unity Editor bridge",
  "installCmd": "claude mcp add UnityMCP -s user -- uvx ...",
  "servedTools": ["manage_camera", "rendering_stats", "read_console"]
}
```

The owning kit declares the manifest for the servers it requires — core ships none, so this check SKIPs on core until a kit opts in.

**The three non-grantable name shapes** surfaced in the warning (they look like tools but can never appear in a `tools:` array): an **`action`** of another tool (grant the parent tool instead), an **MCP resource** (read via its URI, never grantable), and a **handler with no registered wrapper**.

**Why this check exists:**

#651 — all 8 Unity/DOTS agents had drifted. A validator asked to confirm impostor shaders were not rendering magenta could not screenshot, because `mcp__UnityMCP__manage_camera` was never granted although the server serves it in the default `core` group; the verdict silently degraded from a pixel read to "no shader-compile errors", strictly weaker evidence, and the cause looked like a fork bug until someone read the allowlist. The corrective human sweep then over-corrected, deleting a real, continuously-maintained tool from all 8 agents as "phantom". **A careful human pass got it wrong in both directions on the same day** — which is why this is a deterministic gate (`rules/ai-driven-design.md`) rather than a doc.

**Severity:** WARN — advisory, exit 0 always.

**Skip conditions:**
- No `agents/` directory → SKIP
- No `servedTools` declared in any config fragment → SKIP (with the unverified server count)

**Test:** `.claude/hooks/__tests__/doctor-check-54-mcp-tool-grants.test.cjs` (CI-gated by the hook test-runner).

**Related:** The1Studio/theonekit-unity#312 — the documentary half (failure mode, the three non-grantable shapes, offline verification against the fork).

## Dead Permission Rules (#56)

| # | Check | Validates |
|---|---|---|
| 56 | Dead permission rules | No `permissions.{allow,deny,ask}` entry uses a path-form rule whose tool name Claude Code's file-permission matcher never consults. |

**Check #56 details:**

Runs `scripts/check-dead-permission-rules.cjs`. Parses `permissions.allow` / `deny` / `ask` in `settings.json` and `settings.local.json` under BOTH the project `.claude/` and `$HOME/.claude/` (pass `--project-only` to skip the global scope), and reports every rule of the form `<Tool>(<path>)` where `<Tool>` is in the dead-form table.

**The forms, and where they come from:**

| Rule form | Replacement |
|---|---|
| `Write(<path>)` | `Edit(<path>)` |
| `MultiEdit(<path>)` | `Edit(<path>)` |
| `NotebookEdit(<path>)` | `Edit(<path>)` |
| `Glob(<path>)` | `Read(<path>)` |

`Edit` rules cover every file-**editing** tool and `Read` rules every file-**reading** tool, so those two are the only tool names the matcher consults for a path rule. The table is **not** inferred from an observed warning string — it is transcribed from the rule validator shipped inside the Claude Code binary (`~/.local/share/claude/versions/<v>`), which maps `Write|NotebookEdit|MultiEdit → Edit` and `Glob → Read` verbatim, and emits its warning only for parenthesised content not containing `:*`. The check reproduces both the map and that `:*` exemption.

**Data-driven, per `rules/code-conventions.md`:** every tool name lives in `references/permission-rule-forms.json` (with a `_verifiedAgainst` block recording the version checked and how to re-verify). The script hardcodes none — emptying `pathRuleRewrites` silences the check entirely, which is the test that adding a newly-discovered dead form is a **data** edit.

**Outcomes:**

| Situation | Result |
|---|---|
| `Write(/src/**)` in any scanned list | WARN — names file, list, index, and the exact replacement with the path preserved |
| `Edit(...)` / `Read(...)` / `Bash(...)` / `WebFetch(domain:...)` | PASS |
| Bare `Write` with no parentheses | PASS — that is a real, matched tool grant, not a path rule |
| Rule content containing `:*` | Not reported (Bash-prefix syntax; rejected elsewhere by Claude Code) |
| Settings file is unparseable JSON | SKIP that file by name, continue |
| No settings file / empty rewrite table | SKIP |

**Why this check exists:**

#763 — a `Write(<path>)` allow rule is accepted by the settings schema and grants **nothing**. Claude Code does warn, but once, at startup, in a scroll-away banner, and only for the file it happened to load; the rule then sits in the settings file reading like a live grant. The observed symptom is a permission prompt for a path the user is certain they already allowed. T1K itself authors no `Write(...)` rules in any kit-shipped settings file, CLI template, or generator — this is a consumer-config defect T1K is well placed to detect, not a kit regression.

**Severity:** WARN — advisory, exit 0 always. A dead allow rule is a papercut, not a break, and a doctor check that hard-fails on a cosmetic issue gets disabled.

**Test:** `.claude/hooks/__tests__/doctor-check-56-dead-permission-rules.test.cjs` (CI-gated by the hook test-runner).

## Kit Install Scope (#58)

| # | Check | Validates |
|---|---|---|
| 58 | Kit install scope | No kit is installed in BOTH `~/.claude/` and the project `.claude/` at the same time. |

**Check #58 details:**

Runs `.claude/hooks/doctor-check-58-kit-install-scope.cjs`. Reads the per-scope kit inventory that `hooks/telemetry-utils.cjs` already computes — `readTelemetryContext()` returns `installedKits` (project), `installedKitsGlobal`, and its own `kitScope ∈ {global, project, both, none}` classification, whose source comment names `'both'` as "the shadowing-risk case". The check consumes that helper rather than growing a second, divergent reader (`rules/search-before-you-build.md`); when `kitScope !== 'both'` it reports OK without further work, and otherwise intersects the two kit-name sets.

One property of that reuse worth knowing: the helper memoizes per project root for 60 s. A kit uninstalled seconds ago can therefore still be listed. The stale direction is a false **alarm**, never a false clear — re-run doctor a minute later to confirm a fix.

**Why this check exists:**

Only ONE of two coexisting copies is ever served: project-local shadows global (`rules/prefer-local-over-global-edits.md`). The shadowed global copy still receives `t1k modules update` and still reports `✓ up to date` in `t1k --version`, while no session loads it — so updating the wrong copy is completely silent, and the copy the user is reading is not the copy the session runs. Two installs also double the always-loaded rule surface measured by #37 and #38. The policy this enforces is `rules/kit-install-scope.md`: `core` global, engine/domain kits per-project, nothing in both.

**Severity:** WARN, exit 0 — an install-topology recommendation, matching #48. Uninstalling is destructive, so the check reports the exact command per kit and never runs it.

**Outcomes:**

| Situation | Result |
|---|---|
| `core` global + `unity` project (no name overlap) | OK — healthy under both #48 and #58 |
| `core` in both scopes | WARN — `t1k uninstall --local --kit core` (core is a global-scope kit) |
| `designer` in both scopes | WARN — `t1k uninstall --global --kit designer` (engine kits are per-project) |
| Project declares `inheritsFrom` → global | INFO — layering is deliberate; reported for visibility only, same distinction #36 draws |
| Project `.claude/` is a kit source tree (no `kits`, no `scope`, no `installedAt`) | SKIP — the kit repo's own `.claude/` IS the kit, not an install |
| Global-only session, or no `~/.claude/` | SKIP — only one scope exists |
| `telemetry-utils.cjs` unavailable | SKIP with the reason |

The kit-source guard requires ALL THREE install markers to be absent, deliberately: `scope` is optional in the CLI metadata schema and older installs predate it, so keying on it alone would skip real consumers — a false clear, the failure direction worth avoiding.

**Relationship to neighbouring checks:**

- **#48** (global install core-only) — the other half of the same policy. #48 says no non-core kit belongs in `~/.claude/` at all; #58 says no kit belongs in both scopes. They never disagree: a `core` global + `unity` project install passes both.
- **#55** (kit file drift) — assumes the overlap exists and asks whether the two copies AGREE (BEHIND / DIVERGED-AHEAD / MISSING). #58 asks whether the overlap should exist. #55 is FAIL because divergence is actively wrong; #58 is WARN because the topology is a smell.
- **#36** (rule duplication) — the same question one layer down, for individual rule files rather than whole kits.

**Fix mode:** Cannot auto-uninstall (destructive — removes a real install, and the project copy may hold un-synced edits per #367). Doctor reports the offending kits, both versions, and the exact CLI command; run `/t1k:sync-back` first when the copy being dropped has local edits.

**Test:** `.claude/hooks/__tests__/doctor-check-58-kit-install-scope.test.cjs` (CI-gated by the hook test-runner). Its assertions pin the FAILURE states — the overlap report, the per-kit remedy, the disjoint-scope non-report, the source-tree skip, and the inheritance downgrade — rather than the happy path.

## Always-Loaded Union Budget (#59)

| # | Check | Validates |
|---|---|---|
| 59 | Always-loaded union | The UNION of always-loaded content a SESSION actually loads — `rules/*.md` + `CLAUDE.md` across BOTH scopes — against a union budget, with per-kit and per-file attribution. |

**Check #59 details:**

Runs `scripts/check-always-loaded-union.cjs`. Resolves the installed set the way a session does: `metadata.installedModules` from each scope (handling both the qualified `"<kit>:<module>"` key scheme and the legacy bare form), with the `modules/` filesystem scan as fallback via `telemetry-utils.getModuleEntries()`. Scopes come from the shared `resolveProjectDir()` / `getHomeDir()`; the token estimate comes from `hooks/lib/token-estimate.cjs` — no second path resolver, no second estimator.

Counted per scope: flat `rules/*.md`, the nested `modules/<name>/rules/*.md` of installed modules not already flattened, and that scope's `CLAUDE.md`.

**Why this check exists — the wrong-population green:**

Every pre-existing budget check measures one population and is structurally blind to the union:

| Check | Population | What it cannot see |
|---|---|---|
| `validate-context-window-budget.cjs` (release-action) | ONE KIT, at release time | every other installed kit — each passes its own gate independently |
| #37 context budget | the PROJECT scope only | `~/.claude/rules/`, where a consumer's rules actually live |
| #38 oversized rules | ONE FILE, project scope | the total |

Measured on a real machine 2026-08-20: `~/.claude/rules/*.md` was **~40 500 tokens across 60 files**, and with the global `CLAUDE.md` the union came to **~42 800 tokens — 171% of the 25 000-token union budget**, with a single file (`mr-transparent-routing.md`, 8 100 tokens) accounting for 19% of it. Check #37 reported PASS throughout, honestly, because the project scope it measures was empty. That is `rules/green-that-proves-nothing.md` § "measures the wrong population": a real check, passing, that cannot observe the thing that hurts.

**Why both scopes are SUMMED and not shadowed:** for kit *content resolution* project-local shadows global, but for *context loading* it does not — Claude Code injects the user's global rules AND the project's rules into the same session. A rule present in both is billed twice, which #59 reports separately as recoverable waste (the per-file subject of #36).

**The union budget (25 000, default):** the per-kit release cap is 20 000 and a realistic install is core + one engine kit + model-router, so 25 000 is roughly one extra kit of headroom over core alone, and ~12.5% of a 200K window spent before any work begins. It is deliberately BELOW today's measured reality — a budget nobody breaches would be decoration. Override with `T1K_UNION_BUDGET_TOKENS`; `T1K_UNION_TOP_N` controls how many files are listed; `T1K_UNION_GLOBAL_DIR` injects the global scope (test use).

**Severity:** WARN, **always exit 0**. RATCHET (dated 2026-08-20, in the script header): promoting the union breach to FAIL is gated on the fleet median falling under budget. A consumer already at 171% must not have their session broken by the check that reports it — per CLAUDE.md Core Requirement #13, ship warn-first with the ratchet condition stated.

**Outcomes:**

| Situation | Result |
|---|---|
| union ≤ budget | PASS, with the split and attribution still printed |
| union > budget | WARN — per-scope split, per-kit table, top-N files descending, fix line |
| no install metadata in EITHER scope | UNKNOWN, `tokens=-1` — states in words that this is *not* a zero |
| metadata present but zero readable files | UNKNOWN — treated as unmeasured, not as 0 tokens |
| same rule basename in both scopes | reported as double-loaded, with the tokens billed twice (cross-ref #36) |
| rule owned by a module absent from the installed set | reported as possible stale file (cross-ref #12) |

`CLAUDE.md` is deliberately EXCLUDED from double-load detection: the global and project files share a basename but are different documents that are both meant to load, so counting them would report an unfixable "duplicate".

**Fix mode:** none — measurement only, and the remedy (trimming rules) is a content decision. The output ranks the offenders so the first cut is obvious.

**Test:** `.claude/hooks/__tests__/check-always-loaded-union.test.cjs` (CI-gated by the hook test-runner). It **proves the check can fail**: a generated fixture whose union exceeds budget must emit WARN, and the same corpus under a generous budget must emit PASS, so the verdict is shown to track the data rather than being a constant. It also pins UNKNOWN ≠ zero, both-scopes-summed, the qualified-key false-alarm regression, and the CLAUDE.md non-duplicate. Fixtures are generated under `os.tmpdir()` and the child runs with an empty `cwd` and no `CLAUDE_PROJECT_DIR`, so the suite's own repo cannot leak ~19K tokens of real rules into a fixture's total.
---

## Check #60 — Markdown link integrity

Runs `.claude/hooks/doctor-check-60-markdown-link-integrity.cjs`. Reports relative markdown links inside `.claude/` whose target does not exist. Offline, deterministic, no CLI spawns.

**The depth rule that makes this necessary:** `theonekit-release-action/scripts/flatten-module-files.cjs` collapses `modules/<m>/skills/<s>/` into `.claude/skills/<s>/` at release time and **does not rewrite link paths**. A link is therefore correct when it resolves from the location the file is INSTALLED at, not from its nesting in a kit repo. The check resolves both readings and accepts either.

| Installed at | `../` to `.claude/rules/` |
|---|---|
| `skills/<s>/SKILL.md` | 2 |
| `skills/<s>/references/<f>.md` | 3 |
| `agents/<a>.md` | 1 |

**Classification order:**

| Situation | Result |
|---|---|
| Resolves literally on this tree's layout | OK |
| Resolves in the flattened namespace | OK |
| Escapes `.claude/` under BOTH readings | skipped — points at repo `docs/` or `plans/`, never installed |
| Intended file exists at another depth (tail match) | FAIL — reported with the corrected path |
| Target's directory namespace absent from the tree | skipped — missing content, not a broken link |
| Otherwise missing | FAIL (WARN on a kit source tree, see below) |

**Severity:** FAIL, exit 1. Downgraded to **WARN, exit 0** on a kit SOURCE tree when no finding is provable from that tree alone — a unity skill citing a CORE rule resolves on any consumer holding both kits and dangles only in the unity repo. Provable findings (the intended file is present at another depth) stay FAIL everywhere.

**Not reported, deliberately:** links inside fenced blocks or backtick spans (quoted syntax, not a claim), `http(s)`/`mailto`/anchor/absolute targets, targets with no file extension, and anything under `worktrees/`, `plugins/`, `__tests__/`, or `fixtures/`.

**Known gap, stated rather than hidden:** a module skill whose link was written for the KIT-SOURCE depth (`../../../../rules/x.md`) escapes `.claude/` once flattened and is skipped. Precision is the deliberate trade — a FAIL-level check that cries wolf gets muted. The release-action CI gate covers the source side; per CLAUDE.md Core Requirement #13 both surfaces are needed, since a CI gate never reaches a consumer who opens no kit PRs.

**Relationship to `scripts/validate-cross-references.cjs` (#664):** that validator is the strict AUTHOR-side gate — backticked pointers in skill and rule bodies, relative links warn-first, run from `.github/workflows/cross-references.yml`. It cannot serve the consumer surface because it is claimed by `t1k-maintainer`, which is not a required module, so a `developer`-preset install never receives it; `hooks/` ships to every install. Deliberate parallel implementation, per `rules/search-before-you-build.md`; both report clean on core today.

**Fix mode:** cannot auto-fix — rewriting a link is an authoring decision. The report names file, line, target, and the corrected path when it is provable.

**Test:** `.claude/hooks/__tests__/doctor-check-60-markdown-link-integrity.test.cjs`. Pins the failure states and the false-positive boundaries: wrong depth reported WITH the installed-layout correction, a flattening-dependent module-rule link NOT reported, an uninstalled namespace NOT reported, fenced/backtick links NOT reported, `worktrees/` not walked, and a missing same-dir sibling reported.

---

## Check #61 — Skill reference citations

Runs `.claude/hooks/doctor-check-61-skill-reference-citations.cjs`. A `SKILL.md` naming its own `references/<file>` must ship that file. Offline, deterministic.

**Why it is separate from #60:** #60 resolves markdown LINKS. The citation forms that dominate kit-shipped bodies are not links — a code span in a "Reference docs" table cell, or `See references/checks.md` in prose. #60 structurally cannot see those. The failure is silent in both cases: the model opens nothing, reads nothing, and continues on less guidance than the body claims to have, so nothing errors and nothing is logged.

**Scope — own-skill citations only.** Only a citation whose path STARTS at `references/` (optionally `./references/`) is evaluated, and only against the citing skill's own directory. A cross-skill citation carries more path in front of it (`t1k-architecture/references/fork-hygiene.md`) and is not resolved here; resolving it against the citing skill would report all 26 real citations of `fork-hygiene.md` as missing. Cross-skill citations written as links are #60's job.

Fenced code blocks are blanked first — a skill-authoring skill showing `references/incidents.md` as an EXAMPLE of where content belongs is not claiming to ship it.

**Severity:** FAIL, exit 1. **Fix:** write the reference file, or delete the citation. Never name a reference you did not create — `ls skills/<s>/references/` before commit (`t1k-skill-creator/references/architecture-rules.md` § L.2).

**Test:** `.claude/hooks/__tests__/doctor-check-61-skill-reference-citations.test.cjs`. Pins: both citation forms caught, an existing reference NOT reported, cross-skill citation NOT resolved locally, fenced example NOT reported, non-`SKILL.md` files not scanned.

---

## Check #62 — Orphan reference files

Runs `.claude/hooks/doctor-check-62-orphan-reference-files.cjs`. Reports `references/**.md` that no file anywhere under `.claude/` cites. Offline, deterministic.

**The false positive that dictates this check's shape.** The naive form asks "does the OWNING skill cite this file?" and is wrong. `t1k-architecture/references/fork-hygiene.md` is cited 26 times from OTHER skills, agents, and rules, and a per-skill check reported it orphaned. Shipping that verdict tells users to delete a live shared reference. So the corpus is EVERY markdown, JSON, and script file under `.claude/` minus the candidate itself — self-reference is not reachability.

**Matching is deliberately generous:** a candidate counts as cited if the corpus contains its full `<owner>/references/<rel>` path, its `references/<rel>` suffix, or merely its basename. Generous matching under-reports (a dead file whose basename collides with a live one is missed) and that is the safe direction for a check whose remedy is deletion.

**Severity:** WARN, exit 0 — never FAIL. The corpus scan is textual, so a reference reachable only through prose it cannot parse would be reported; deleting on a WARN is the author's call, and failing an install over it is not. Confirm by hand before deleting.

**Fix:** link it from the owning body — a one-line summary plus the pointer, never a bare link (`t1k-skill-creator/references/architecture-rules.md` § L.4) — or delete it.

**Test:** `.claude/hooks/__tests__/doctor-check-62-orphan-reference-files.test.cjs`. Pins the WARN-not-FAIL contract and, in three assertions, the cross-surface citation boundary — a reference cited from another SKILL, from an AGENT, and from a RULE is not an orphan — plus self-citation still counting as orphaned.

## Check #63 — Unused local modules (HIGH-signal half: `engine-mismatch`)

Runs `.claude/hooks/doctor-check-63-unused-local-modules.cjs`. Flags a locally installed kit whose OWN `context.requiredPaths` declaration (in its `t1k-config-<kit>.json` fragment) is entirely absent from the project filesystem — e.g. `theonekit-unity` installed with neither `Assets/` nor `ProjectSettings/` present. Offline, deterministic, no telemetry.

**Engine association is data-driven, never a hardcoded kit→engine table.** Each kit answers for itself via its own `context.requiredPaths`; a kit that declares nothing (missing key, non-array, or an EMPTY array — the shape every standalone kit ships today) produces NO finding at any confidence. A kit is only "mismatched" when ALL of its declared paths are absent — ANY present path reads as a match and stays silent, the conservative direction for a signal that can feed Phase 10's auto-removal path.

**`detectProjectType()` is deliberately NOT used** — its first branch makes `projectType` always `'theonekit'` on every install this check runs on (every install has `.claude/metadata.json`), which would make the signal circular: the kit's own presence would justify the kit.

**Confidence is opt-in, per Contract A.** `confidence=high action=remove` requires the kit to ALSO be named in `scopeEnforcement.autoRemoveKits` (default `[]`) AND resolve to a real `KitType` member — everything else, including a kit named in `autoRemoveKits` that does not resolve to a `KitType` (a module-shaped identifier, R4-S4), is `confidence=low action=report`. On a default install this check therefore never emits a HIGH finding.

**Exclusions:** global-scope kits (`core`, `model-router`) are excluded by construction; a kit named in `scopeEnforcement.allowKits` is suppressed entirely; a kit-source-repo `.claude/` (the kit's own repo, not a consumer install) skips the whole check. `scopeEnforcement.enabled: false` reports SKIP, never a silent PASS.

Emits the Contract A frame per finding: `[t1k:doctor:scope-finding check=63 kit=<kit> scope=local action=<remove|report> confidence=<high|low> reason=engine-mismatch]`, in addition to the existing per-check summary frame `[t1k:doctor:unused-local-modules status=<skip|ok|warn> count=<n>]`. Diagnostic-only — prints the exact remedy (`t1k uninstall --local --kit <kit>`), never runs it.

**This phase ships the HIGH-signal half only.** A second reason (`zero-invocation`, LOW-only) is added to the same file and the same detection pipeline by a later phase — see the file's own `REASON_SCANNERS` extension point.

**Test:** `.claude/hooks/__tests__/doctor-check-63.test.cjs`. 14 can-fail assertions, most centrally CR-7 (test 1 runs on a fixture WITH `.claude/metadata.json` — the real population `detectProjectType` cannot see through) and the data-driven pin (test 6 — a brand-new fixture kit classifies with zero code change, then stops classifying the moment its declaration is deleted).

## Check #64 — Uninstall integrity: the stale journal and the unacknowledged ledger

Runs `.claude/hooks/doctor-check-64-uninstall-integrity.cjs`. Two report-only signals about state a CLI uninstall or a background remediator leaves behind — this check never deletes, never restores, never mutates anything.

**Signal 1 — a stale uninstall journal (Contract I).** `t1k uninstall`'s delete loop can be interrupted (SIGINT/SIGTERM, a Bash-tool timeout) mid-way, leaving half of `toDelete` gone while `metadata.json` is untouched and still claims a full `files[]` — nothing else detects this (check #55 walks only `hooks/`/`scripts/`; check #58 reads kit membership, exactly the field never updated). Reads `<claudeDir>/../.t1k-uninstall-journal.json`. A journal whose `pid` is dead OR whose `startedAt` is older than 15 minutes is reported **FAIL**, naming the kit, the queued `toDelete` count, and how many of those paths are still present (the recovery-progress number) — and states the remedy is to **re-run the same uninstall**, which is idempotent (`removal-handler.ts` skips any path already gone). A journal with a live `pid` and a recent `startedAt` is an uninstall still running, reported at **INFO**, not FAIL — a check that cries FAIL on every in-flight uninstall gets ignored within a week. The journal is never deleted by this check; only a successful uninstall clears it.

**Signal 2 — unacknowledged auto-removal ledger entries (Contract J).** Reads `<claudeDir>/telemetry/scope-removals.jsonl`. Every entry lacking a later `acknowledged:true` row for the same (kit, scope, ts) is reported **WARN**, naming the kit, scope, timestamp, and the **absolute** backup path. The recovery command printed is situation-correct, never generic: a git-tracked `.claude/` (per `<backup>/T1K-REMOVAL.json`'s `gitTracked` flag) prints `git -C <projectRoot> checkout -- .claude/`; an untracked tree with its backup still present prints `cp -a --backup=numbered <backup>/. <target>/` (a bare `cp -a` silently overwrites post-backup edits and is never printed); a backup directory that has since been archived (`backupsMissing` counts these) prints the tar-aware recovery form. `t1k recover restore <ts>` is **never** printed — its whole-tree-overwrite semantics make it a second, larger destructive act for undoing one kit's removal. Malformed JSONL lines and structurally incomplete rows are counted as `unreadable`, never silently dropped. Once the unacknowledged count reaches `scopeEnforcement.maxRemovalsPerRun`, the check also reports the `removalCooldownDays` pause state, so a stalled auto-removal is explicable rather than mysterious.

Emits `[t1k:doctor:uninstall-integrity journal=<present|absent> staleJournals=<n> unacknowledgedRemovals=<n> backupsMissing=<n>]`, riding the existing `[t1k:doctor:*]` wildcard — no new `docs/marker-namespaces.md` row. A healthy install (no journal, no ledger) still emits this frame with all-zero counts — silence when healthy would be indistinguishable from did-not-run.

**Must merge before Phase 10** — Phase 10 is Contract J's producer; a ledger with no reader is a log, not a safety net.

**Test:** `.claude/hooks/__tests__/doctor-check-64.test.cjs`. 15 can-fail assertions covering both signals' FAIL/INFO/WARN branches, all three recovery-command branches (git-tracked, untracked, backup-missing), the never-print-`t1k recover restore` pin, read-only-ness (byte-identical journal/ledger across two runs), acknowledgement in both directions, and malformed-record handling.

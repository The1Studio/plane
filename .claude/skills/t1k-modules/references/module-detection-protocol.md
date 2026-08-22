---

origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---
# Module Detection Protocol

## Module State Detection (All Module-Aware Commands)

> **Do not read module state from `.t1k-resolved-config.json`.** It does NOT carry an
> `installedModules` key — it holds the pre-merged registry fragments (routing /
> activation / config) and nothing about which modules are installed. Its authoritative
> shape is the `ResolvedConfig` type in `theonekit-cli`. Reading module state from it
> silently yields nothing, with no error.

1. **Read `.claude/metadata.json`** — the single source of installed-module state
   - Check `schemaVersion` field:
     - **v3 (current):** Read `installedModules` — object keyed by module name, each with `version`, `kit`, `repository`
     - **v2 (legacy):** Read `modules` key — flat list. Treat as installed modules without version info
     - **No `modules` or `installedModules`:** Flat/core-only, skip module checks

2. **Per-module state (v3):**
   - Each entry in `installedModules` is independently versioned
   - Module's `kit` field identifies which container repo it came from
   - Module's `version` field is the installed semver

## Graceful Degradation

All module checks MUST degrade gracefully:
- **No `.claude/metadata.json`:** Treat as no modules, skip module checks
- **schemaVersion 3:** Full module-first mode — per-module versions, deps, manifests
- **schemaVersion 2 (legacy):** Module names known but no per-module versions — upgrade path: `/t1k:doctor fix`
- **No schemaVersion:** Flat kit (core-only), skip module checks

## Per-File Module Origin

When working with specific files, determine module ownership:
```
Read .claude/modules/{name}/.t1k-manifest.json → file list
For target file path:
  - Match against installed module manifests
  - Return: module name, kit, version
  - If no match: file is kit-wide or core
```

## Detection Pattern

```
IF .claude/metadata.json exists:
  IF schemaVersion == 3:
    Read installedModules → per-module { version, kit, repository }
    Each module is independently versioned and installable
  ELSE IF "modules" key present (v2 legacy):
    Read modules list → module names without versions
    Suggest: run /t1k:doctor fix to migrate to v3
  ELSE:
    → flat kit (core-only), skip module checks
ELSE:
  → no metadata, skip module checks
```

## Module Manifest Files

Each installed module has a file manifest at `.claude/modules/{name}/.t1k-manifest.json`:
- Lists all files owned by that module
- Used for: update (diff old vs new), remove (delete all), split/merge (combine install + remove)
- If manifest missing but module in metadata: warn, suggest reinstall

## Available Modules Discovery (MANDATORY)

**Always read `t1k-modules.json`** (not just `metadata.json`) to discover ALL available modules — both installed and not-yet-installed.

```
Read .claude/t1k-modules.json → modules key
  For each module:
    - name, description, required, dependencies, skills
    - Check if installed: compare against installedModules from metadata.json
    - If NOT installed: note as "available" — can be installed via /t1k:modules add
```

**Proactive module suggestion:** When a user asks about a topic and an uninstalled module's keywords match:
- Inform the user: "Module `{name}` covers this topic but isn't installed. Install with `/t1k:modules add {name}`."
- Show module description and what skills it provides
- Don't block the user — offer, don't require

**Also check `kits` metadata format:** If `metadata.json` has `kits.{name}` but no `installedModules`, the project was initialized via `t1k init` but modules haven't been individually tracked. Read `t1k-modules.json` to determine which modules are available, and check `t1k-routing-*.json` / `t1k-activation-*.json` fragment names to infer which kits are installed.

## Commands Using This Protocol

Every module-aware command: doctor, help, sync-back, issue, triage, watzup, cook, fix, debug, test, review, scout, plan, brainstorm, modules.

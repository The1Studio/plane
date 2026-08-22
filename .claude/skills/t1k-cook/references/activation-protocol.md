---

origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---
# Activation Protocol

## Skill Activation (All Commands)

<!-- DO NOT rename `activationKeywords` to `activation` yet. The CLI writes
     `activation`, so this key never resolves and the manual fallback below always
     runs. That mismatch is currently load-bearing: the CLI's resolved-config merge
     keeps only one arbitrary fragment and drops sessionBaseline, so "fixing" the
     key name here would silently narrow keyword activation. Rename only after the
     theonekit-cli merge fix lands. -->

1. **Read resolved config:** Check for `.t1k-resolved-config.json` first
   - If exists: read `activationKeywords` for pre-resolved keyword→skill mappings
   - If absent: fall back to manual resolution below

2. **Manual resolution (fallback):**
   - Read ALL `.claude/t1k-activation-*.json` files (CI-generated, released in module ZIPs)
   - Also read `module.json` → `activation` field for each installed module (SSOT for per-module activation)
   - Match request/topic keywords against `keywords`/`mappings` arrays in every source
   - Collect ALL matching skills across ALL sources (ADDITIVE — never exclusive)
   - Only activate skills from **installed** modules (check `.claude/metadata.json` → `installedModules`)
   - Higher-priority fragments do NOT suppress lower-priority ones

3. **Deduplicate:** If the same skill appears in multiple fragments, activate it only once

4. **Session baseline:** Collect entries with `"sessionBaseline": true` from all fragments.
   Also read required modules' `module.json` → `activation.sessionBaseline`.
   Activate baseline skills regardless of keyword match.

**Fallback:** If no activation sources exist, activate no automatic skills. Module installs provide the sources.

## Module-Aware Activation (Module-First Architecture)

- Each installed module has activation keywords defined in its `module.json` → `activation` field
- CI-generated `t1k-activation-*.json` fragments (released in module ZIPs) are also supported
- Only installed modules' skills can be activated — check `.claude/metadata.json` → `installedModules`
- Activation remains ADDITIVE across all installed modules (same-kit and cross-kit)
- Required modules' `sessionBaseline` skills are always activated regardless of keyword match

## Fragment Schema

```json
{
  "registryVersion": 1,
  "kitName": "example-kit",
  "priority": 20,
  "sessionBaseline": ["skill-a", "skill-b"],
  "mappings": [
    {
      "keywords": ["keyword1", "keyword2"],
      "skills": ["skill-name-1", "skill-name-2"]
    }
  ]
}
```

## Core Principle

**Activation is ADDITIVE — never exclusive.** Every matched skill from every fragment is activated.

## Example

Given two fragments:
- `t1k-activation-core.json` maps "auth" → ["jwt-skill"]
- `t1k-activation-mykit.json` maps "auth" → ["mykit-auth-skill"]

A request containing "auth" activates BOTH: `jwt-skill` AND `mykit-auth-skill`.

#!/usr/bin/env node
// t1k-origin: kit=theonekit-core | repo=The1Studio/theonekit-core | module=t1k-base | protected=true
// check-global-core-only.cjs — Doctor check #48: warn on non-global-scope kits installed globally.
//
// Best practice: `$HOME/.claude/` should contain ONLY global-scope kits — `core`,
// and any kit that declares `installScope: "global"` for itself (e.g. model-router;
// see `lib/kit-scope-policy.cjs`, the SSOT this check derives membership from).
// Engine-specific kits (unity, designer, cocos, react-native, web, nakama) belong
// PER-PROJECT in `.claude/` of the relevant project, not globally.
//
// Rationale:
//   - Global = always-on essentials; global-scope kits have the universal registry/rules/hooks/skills
//   - Per-project = engine/domain-specific (e.g. Unity skills only useful inside a Unity project)
//   - Mixing engine kits globally causes activation bleed (irrelevant skills auto-load),
//     stale-install drift, and orphaned files (real incident 2026-05-11: $HOME/.claude/
//     accumulated 162 unprefixed Unity skills as orphans because Unity was installed
//     globally but never updated cleanly)
//
// WARN level — this is a recommendation, not a violation. Does not block CI.
//
// Usage:
//   node check-global-core-only.cjs
//
// Exit 0 always. Reads $HOME/.claude/metadata.json regardless of CWD — the check
// is about the GLOBAL install state, not the project state.

'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { isGlobalScopeKit } = require('../../../hooks/lib/kit-scope-policy.cjs');

const CHECK_NUM = 48;
const globalClaudeDir = path.join(os.homedir(), '.claude');
const globalMetadataPath = path.join(globalClaudeDir, 'metadata.json');

function main() {
  if (!fs.existsSync(globalMetadataPath)) {
    console.log(`[t1k:doctor] check #${CHECK_NUM} SKIP — no global $HOME/.claude/metadata.json (T1K not installed globally)`);
    process.exit(0);
  }

  let metadata;
  try {
    metadata = JSON.parse(fs.readFileSync(globalMetadataPath, 'utf8'));
  } catch (err) {
    console.log(`[t1k:doctor] check #${CHECK_NUM} SKIP — could not parse global metadata.json: ${err.message}`);
    process.exit(0);
  }

  const kits = metadata.kits;
  if (!kits || typeof kits !== 'object') {
    console.log(`[t1k:doctor] check #${CHECK_NUM} SKIP — no .kits key in global metadata`);
    process.exit(0);
  }

  const installed = Object.keys(kits);
  // Membership is DERIVED from lib/kit-scope-policy.cjs (the SSOT), not a
  // hardcoded core-only comparison — a kit may declare `installScope: "global"`
  // for itself (e.g. model-router) without a core release.
  const nonGlobalScope = installed.filter((name) => !isGlobalScopeKit(name, globalClaudeDir));

  if (nonGlobalScope.length === 0) {
    console.log(`[t1k:doctor] check #${CHECK_NUM} PASS — global install holds only global-scope kits.`);
    process.exit(0);
  }

  console.log(`[t1k:doctor] check #${CHECK_NUM} WARN — ${nonGlobalScope.length} non-global-scope kit(s) installed globally:`);
  for (const name of nonGlobalScope) {
    const version = (kits[name] && kits[name].version) || 'unknown';
    console.log(
      `  - Non-global-scope kit '${name}' (version=${version}) is installed globally. ` +
        `Best practice: install engine-specific kits per-project (.claude/), keep ` +
        `$HOME/.claude/ to global-scope kits only (rules/kit-install-scope.md). ` +
        `Run 't1k uninstall --global --kit ${name}' to remove.`,
    );
  }
  console.log('');
  console.log(
    `[t1k:doctor] check #${CHECK_NUM} Rationale: Global = always-on essentials (global-scope kits only, see rules/kit-install-scope.md). ` +
      `Per-project = engine/domain-specific kits. Mixing engine kits globally causes ` +
      `activation bleed, irrelevant skill auto-load, and stale-install drift.`,
  );

  // Exit 0 — WARN level does not block CI
  process.exit(0);
}

main();

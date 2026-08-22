#!/usr/bin/env node
// t1k-origin: kit=theonekit-core | repo=The1Studio/theonekit-core | module=t1k-base | protected=true
// check-oversized-rules.cjs — Doctor check #38: Per-rule-file token size.
//
// Warns when any individual file in `.claude/rules/` exceeds 5000 tokens
// (char/4 heuristic). Oversized rule files inflate the always-loaded context
// budget and are a signal to split or move content to docs/.
//
// Usage:
//   node check-oversized-rules.cjs [path/to/project-root]
//
// Exits 0 always (WARN level). Prints one WARN line per oversized file.

'use strict';

const fs   = require('node:fs');
const path = require('node:path');
const { estimateTokens } = require('../../../hooks/lib/token-estimate.cjs');

const WARN_TOKENS = 5000;

function run() {
  const projectRoot    = process.argv[2] || process.cwd();
  const projectRulesDir = path.join(projectRoot, '.claude', 'rules');

  if (!fs.existsSync(projectRulesDir)) {
    console.log('[t1k:doctor] oversized-rules: SKIP — no .claude/rules/ directory');
    return;
  }

  let ruleFiles;
  try {
    ruleFiles = fs.readdirSync(projectRulesDir)
      .filter((f) => f.endsWith('.md'))
      .sort();
  } catch (err) {
    console.log(`[t1k:doctor] oversized-rules: SKIP — could not read rules dir: ${err.message}`);
    return;
  }

  if (ruleFiles.length === 0) {
    console.log('[t1k:doctor] oversized-rules: SKIP — no .md files in rules/');
    return;
  }

  const oversized = [];
  for (const filename of ruleFiles) {
    const filePath = path.join(projectRulesDir, filename);
    let content;
    try {
      content = fs.readFileSync(filePath, 'utf8');
    } catch (err) {
      console.log(`[t1k:doctor] oversized-rules: SKIP file ${filename} — read error: ${err.message}`);
      continue;
    }
    const tokens = estimateTokens(content);
    if (tokens > WARN_TOKENS) {
      oversized.push({ filename, tokens });
    }
  }

  if (oversized.length === 0) {
    console.log(`[t1k:doctor] oversized-rules: PASS — all ${ruleFiles.length} rule file(s) within ${WARN_TOKENS}-token budget`);
    return;
  }

  console.log(
    `[t1k:doctor] oversized-rules: WARN — ${oversized.length} rule file(s) exceed ${WARN_TOKENS} tokens`,
  );
  for (const { filename, tokens } of oversized) {
    console.log(`  ${filename}: ~${tokens} tokens (over by ${tokens - WARN_TOKENS})`);
  }
  console.log('  fix: split the rule into smaller focused files or move implementation details to docs/.');
}

try {
  run();
} catch (err) {
  console.log(`[t1k:doctor] oversized-rules: WARN — check errored: ${err.message}`);
}

#!/usr/bin/env node
// t1k-origin: kit=theonekit-core | repo=The1Studio/theonekit-core | module=t1k-base | protected=true
// check-context-budget.cjs — Doctor check #37: Context-window token budget.
//
// Sums the token estimates for all tree-walk-reachable rule files
// (`.claude/rules/*.md`) and the project `CLAUDE.md`. Warns when total
// exceeds 12 000 tokens, fails (exit 1) when it exceeds 15 000 tokens.
//
// This is the session-time complement to the release-time gate
// `validate-context-window-budget.cjs` in theonekit-release-action.
//
// Usage:
//   node check-context-budget.cjs [path/to/project-root]
//
// Exit 0 = PASS or WARN. Exit 1 = FAIL (over hard budget).

'use strict';

const fs   = require('node:fs');
const path = require('node:path');
const { sumTokens } = require('../../../hooks/lib/token-estimate.cjs');

const WARN_TOKENS = 12000;
const FAIL_TOKENS = 15000;

function run() {
  const projectRoot    = process.argv[2] || process.cwd();
  const projectRulesDir = path.join(projectRoot, '.claude', 'rules');
  const claudeMdPath   = path.join(projectRoot, 'CLAUDE.md');

  const filePaths = [];

  // Collect .claude/rules/*.md
  if (fs.existsSync(projectRulesDir)) {
    try {
      const ruleFiles = fs.readdirSync(projectRulesDir)
        .filter((f) => f.endsWith('.md'))
        .map((f) => path.join(projectRulesDir, f));
      filePaths.push(...ruleFiles);
    } catch (err) {
      console.log(`[t1k:doctor] context-budget: WARN — could not read rules dir: ${err.message}`);
    }
  }

  // Include project CLAUDE.md if present
  if (fs.existsSync(claudeMdPath)) {
    filePaths.push(claudeMdPath);
  }

  if (filePaths.length === 0) {
    console.log('[t1k:doctor] context-budget: SKIP — no rules/ files and no CLAUDE.md found');
    return;
  }

  const total = sumTokens(filePaths);

  if (total <= WARN_TOKENS) {
    console.log(`[t1k:doctor] context-budget: PASS (~${total} tokens, budget ${FAIL_TOKENS})`);
    return;
  }

  if (total <= FAIL_TOKENS) {
    console.log(
      `[t1k:doctor] context-budget: WARN — context load is ~${total} tokens (warn threshold ${WARN_TOKENS}, hard limit ${FAIL_TOKENS})`,
    );
    console.log('  fix: move verbose docs to docs/ (searchable), trim rules/*.md, reduce CLAUDE.md.');
    return;
  }

  // Over hard limit
  console.log(
    `[t1k:doctor] context-budget: FAIL — context load is ~${total} tokens, exceeds hard limit ${FAIL_TOKENS}`,
  );
  console.log('  fix: move verbose docs to docs/ (searchable), trim rules/*.md, reduce CLAUDE.md.');
  process.exit(1);
}

try {
  run();
} catch (err) {
  console.log(`[t1k:doctor] context-budget: WARN — check errored: ${err.message}`);
}

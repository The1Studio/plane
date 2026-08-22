#!/usr/bin/env node
// t1k-origin: kit=theonekit-core | repo=The1Studio/theonekit-core | module=t1k-base | protected=true
// check-claude-md-bloat.cjs — Doctor check #35: CLAUDE.md token budget.
//
// Warns when the project `CLAUDE.md` exceeds 5000 tokens (char/4 heuristic),
// since oversized CLAUDE.md duplicates content that belongs in
// `.claude/rules/` (auto-loaded) or `docs/` (searchable on demand).
//
// Usage:
//   node check-claude-md-bloat.cjs [path/to/project-root]
//
// Exits 0 always (WARN level). Prints a single PASS/WARN line with token
// estimate and remediation hint.

'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { estimateTokens } = require('../../../hooks/lib/token-estimate.cjs');

const BUDGET_TOKENS = 5000;

function run() {
  const projectRoot = process.argv[2] || process.cwd();
  const claudeMdPath = path.join(projectRoot, 'CLAUDE.md');

  if (!fs.existsSync(claudeMdPath)) {
    console.log('[t1k:doctor] claude-md-bloat: SKIP — no CLAUDE.md in project root');
    return;
  }

  let content;
  try {
    content = fs.readFileSync(claudeMdPath, 'utf8');
  } catch (err) {
    console.log(`[t1k:doctor] claude-md-bloat: SKIP — read error: ${err.message}`);
    return;
  }

  const tokens = estimateTokens(content);

  if (tokens <= BUDGET_TOKENS) {
    console.log(`[t1k:doctor] claude-md-bloat: PASS (~${tokens} tokens, budget ${BUDGET_TOKENS})`);
    return;
  }

  console.log(
    `[t1k:doctor] claude-md-bloat: WARN — CLAUDE.md is ~${tokens} tokens (budget ${BUDGET_TOKENS}, over by ${tokens - BUDGET_TOKENS})`,
  );
  console.log(
    '  fix: move details to docs/ (searchable on demand) and rules in .claude/rules/ (auto-loaded).',
  );
  console.log(
    '  typical wins: remove duplicates of rules/*.md, cut CI gate backlogs, cut implementation details',
  );
}

try {
  run();
} catch (err) {
  console.log(`[t1k:doctor] claude-md-bloat: WARN — check errored: ${err.message}`);
}

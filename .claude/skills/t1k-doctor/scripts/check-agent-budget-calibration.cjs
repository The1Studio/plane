#!/usr/bin/env node
// t1k-origin: kit=theonekit-core | repo=The1Studio/theonekit-core | module=t1k-base | protected=true
// check-agent-budget-calibration.cjs — Doctor check #51: Agent budget-checkpoint + maxTurns calibration.
//
// Per rules/agent-completion-discipline.md, every tool-heavy (mutating/orchestrating)
// agent body MUST carry a budget checkpoint that is RELATIVE to the agent's `model:`
// context window — never a flat token number — AND a `maxTurns` sized to its task class.
//
// Flags (WARN level — exit 0 always):
//   (a) FLAT-token checkpoint  — a literal token threshold (150K / 150,000 / 200K …) in the
//       body that is NOT tied to the model window. Should be window-relative (~75%@200K / ~55%@1M).
//   (b) MISSING checkpoint     — a tool-heavy agent (Bash and/or Task/Agent in `tools:`) with no
//       budget/context checkpoint language in the body at all.
//   (c) UNDER-SIZED maxTurns   — a tool-heavy agent with `maxTurns < 50`. Multi-PR/refactor/
//       MCP-validation work hits the turn cap before tokens (#528: t1k-kit-developer 45->90).
//
// Usage:
//   node check-agent-budget-calibration.cjs [path/to/project-root]

'use strict';

const fs   = require('node:fs');
const path = require('node:path');

// Only agents that BOTH write (Bash) AND orchestrate sub-agents (Task/Agent) are
// "multi-step heavy" — the #528 failure class (e.g. t1k-kit-developer: multi-PR
// merges via gh/git Bash + sub-agent fan-out). Pure utility agents (git=15,
// docs=20) and read-mostly reviewers are intentionally low-maxTurns by the
// documented sizing table and are NOT flagged. SSOT: the maxTurns table in
// t1k-agent-creator/SKILL.md.
const MIN_HEAVY_MAXTURNS = 45;

// Window-relative checkpoint language: any of these phrases means the author tied
// the threshold to the model window rather than hardcoding a flat number.
const WINDOW_RELATIVE_RE = /window-relative|% of (?:the |your )?(?:context |model )?window|relative to (?:the |your )?(?:context |model )?(?:budget|window)|agent-completion-discipline|maxTurns/i;
// Any explicit budget/checkpoint language at all (presence test for tool-heavy agents).
const CHECKPOINT_RE = /budget checkpoint|context[- ]budget|checkpoint at|budget ceiling|commit before (?:you )?summari[sz]e/i;
// A flat hardcoded token threshold (e.g. 150K, 150,000, 200K) — the anti-pattern.
const FLAT_TOKEN_RE = /\b(?:1[0-9]{2}|2[0-9]{2})(?:,?0{3}|K)\b\s*(?:tokens?|context)?/i;

function parseFrontmatter(content) {
  const m = content.match(/^---\n([\s\S]*?)\n---/);
  if (!m) return { fm: {}, body: content };
  const fmText = m[1];
  const body = content.slice(m[0].length);
  const fm = {};
  for (const line of fmText.split('\n')) {
    const kv = line.match(/^([A-Za-z][\w-]*):\s*(.*)$/);
    if (kv) fm[kv[1]] = kv[2].trim();
  }
  return { fm, body };
}

// Mutating: can write to disk / run destructive commands.
function canMutate(fm) {
  const tools = fm.tools || '';
  return /\bBash\b/.test(tools) || /\bWrite\b/.test(tools) || /\bEdit\b/.test(tools);
}

// Multi-step heavy: BOTH mutates (Bash) AND orchestrates sub-agents (Task/Agent).
// This is the #528 stall class; pure utility/reviewer agents are excluded so the
// check matches the documented per-role maxTurns sizing rather than over-firing.
function isMultiStepHeavy(fm) {
  const tools = fm.tools || '';
  const orchestrates = /\bTask\b/.test(tools) || /\bAgent\b/.test(tools);
  return /\bBash\b/.test(tools) && orchestrates;
}

function run() {
  const projectRoot = process.argv[2] || process.cwd();
  const agentsDir = path.join(projectRoot, '.claude', 'agents');

  if (!fs.existsSync(agentsDir)) {
    console.log('[t1k:doctor] agent-budget-calibration: SKIP — no .claude/agents/ directory');
    return;
  }

  let files;
  try {
    files = fs.readdirSync(agentsDir).filter((f) => f.endsWith('.md')).sort();
  } catch (err) {
    console.log(`[t1k:doctor] agent-budget-calibration: SKIP — could not read agents dir: ${err.message}`);
    return;
  }

  if (files.length === 0) {
    console.log('[t1k:doctor] agent-budget-calibration: SKIP — no agent .md files');
    return;
  }

  const findings = [];
  for (const filename of files) {
    let content;
    try {
      content = fs.readFileSync(path.join(agentsDir, filename), 'utf8');
    } catch (err) {
      console.log(`[t1k:doctor] agent-budget-calibration: SKIP file ${filename} — read error: ${err.message}`);
      continue;
    }
    const { fm, body } = parseFrontmatter(content);
    const mutates = canMutate(fm);
    const heavy = isMultiStepHeavy(fm);
    const hasCheckpoint = CHECKPOINT_RE.test(body);
    const hasWindowRelative = WINDOW_RELATIVE_RE.test(body);
    const hasFlatToken = FLAT_TOKEN_RE.test(body);
    const maxTurns = parseInt(fm.maxTurns, 10);

    // (a) flat-token checkpoint without window-relative anchoring — applies to ANY
    //     agent that hardcoded a token threshold (the literal anti-pattern).
    if (hasFlatToken && !hasWindowRelative) {
      findings.push(`  ${filename}: flat-token checkpoint — make it window-relative (~75%@200K / ~55%@1M) per agent-completion-discipline`);
    }
    // (b) multi-step heavy (Bash + Task/Agent) mutating agent with no checkpoint at all
    if (heavy && mutates && !hasCheckpoint && !hasWindowRelative) {
      findings.push(`  ${filename}: multi-step heavy agent missing a budget checkpoint — add window-relative + ~80%-maxTurns checkpoint`);
    }
    // (c) under-sized maxTurns for the #528 multi-step heavy class only
    if (heavy && Number.isFinite(maxTurns) && maxTurns < MIN_HEAVY_MAXTURNS) {
      findings.push(`  ${filename}: maxTurns=${maxTurns} may be under-sized for a multi-step heavy agent (turns bind before tokens — #528: 45->90)`);
    }
  }

  if (findings.length === 0) {
    console.log(`[t1k:doctor] agent-budget-calibration: PASS — all ${files.length} agent(s) calibrated per agent-completion-discipline`);
    return;
  }

  console.log(`[t1k:doctor] agent-budget-calibration: WARN — ${findings.length} calibration issue(s)`);
  for (const f of findings) console.log(f);
  console.log('  fix: derive the checkpoint from the agent model window and size maxTurns to the task. See rules/agent-completion-discipline.md.');
}

try {
  run();
} catch (err) {
  console.log(`[t1k:doctor] agent-budget-calibration: WARN — check errored: ${err.message}`);
}

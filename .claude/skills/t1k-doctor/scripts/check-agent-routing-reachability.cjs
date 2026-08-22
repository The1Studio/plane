#!/usr/bin/env node
// t1k-origin: kit=theonekit-core | repo=The1Studio/theonekit-core | module=t1k-base | protected=true
// check-agent-routing-reachability.cjs — Doctor check #53: agent routing reachability.
//
// Every installed agent under `.claude/agents/` should be REACHABLE by the
// data-driven routing index (`hooks/lib/agent-routing-index.cjs`) that
// `generic-agent-detector` consults. An agent that contributes zero keywords can
// never be suggested, so its task shape silently falls through to
// `general-purpose` — and the silence reads as "no specialist exists" (#659).
//
// Two signals, both WARN:
//   1. unreachable — the agent owns no keyword in the index. Cause: no
//      `<example>` block carrying a `user:` prompt / `Context:` line, or every
//      one of its tokens is already claimed by an alphabetically earlier agent.
//   2. undeclared-roles — the agent is absent from every `t1k-routing-*.json`
//      `roles` map AND its frontmatter has no `roles:` key at all. `roles: none`
//      is a legitimate, explicit opt-out (utility agents); saying nothing is
//      drift, which is exactly how the #659 blind spot went unnoticed.
//
// Usage:
//   node check-agent-routing-reachability.cjs [path/to/.claude]
//
// Exits 0 always (WARN level), fail-open on internal error.

'use strict';

const fs = require('node:fs');
const path = require('node:path');

// The algorithm is the shipped one; the DATA comes from the target .claude dir.
const INDEX_LIB = path.join(__dirname, '..', '..', '..', 'hooks', 'lib', 'agent-routing-index.cjs');

function readRolesKey(content) {
  if (!content.startsWith('---')) return null;
  const end = content.indexOf('\n---', 3);
  if (end === -1) return null;
  const block = content.slice(3, end);
  for (const line of block.split('\n')) {
    const m = line.match(/^roles\s*:\s*(.*)$/);
    if (m) return m[1].trim();
  }
  return null;
}

function run() {
  const claudeDir = process.argv[2] || path.join(process.cwd(), '.claude');
  const agentsDir = path.join(claudeDir, 'agents');
  if (!fs.existsSync(agentsDir)) {
    console.log('[t1k:doctor] agent-routing-reachability: SKIP — no agents/ directory');
    return;
  }

  let buildIndex, readRoles;
  try {
    ({ buildIndex, readRoles } = require(INDEX_LIB));
  } catch (err) {
    console.log(
      `[t1k:doctor] agent-routing-reachability: SKIP — routing index lib unavailable (${err.message})`,
    );
    return;
  }

  const agentFiles = fs.readdirSync(agentsDir).filter(f => f.endsWith('.md'));
  if (agentFiles.length === 0) {
    console.log('[t1k:doctor] agent-routing-reachability: SKIP — no agent .md files');
    return;
  }

  const index = buildIndex(claudeDir, agentsDir);
  const keywordCount = new Map();
  for (const agent of index.keywordToAgent.values()) {
    keywordCount.set(agent, (keywordCount.get(agent) || 0) + 1);
  }

  const routedAgents = new Set(Object.values(readRoles(claudeDir)));

  const unreachable = [];
  const undeclared = [];
  for (const file of agentFiles) {
    const name = file.replace(/\.md$/, '');
    if (!keywordCount.get(name)) unreachable.push(name);

    if (routedAgents.has(name)) continue;
    let content;
    try {
      content = fs.readFileSync(path.join(agentsDir, file), 'utf8');
    } catch {
      continue;
    }
    if (readRolesKey(content) === null) undeclared.push(name);
  }

  if (unreachable.length === 0 && undeclared.length === 0) {
    console.log(`[t1k:doctor] agent-routing-reachability: PASS — ${agentFiles.length} agent(s) reachable`);
    return;
  }

  console.log(
    '[t1k:doctor] agent-routing-reachability: WARN — ' +
    `${unreachable.length} unreachable, ${undeclared.length} with undeclared roles ` +
    `(of ${agentFiles.length} agent(s))`,
  );
  if (unreachable.length > 0) {
    console.log(`  unreachable (never suggestable): ${unreachable.join(', ')}`);
    console.log('  fix: add an <example> block with a `user: "..."` prompt (and a `Context:` line) to the agent description, or map a role to it in a t1k-routing-*.json `roles` map');
  }
  if (undeclared.length > 0) {
    console.log(`  undeclared roles: ${undeclared.join(', ')}`);
    console.log('  fix: state the intent in the agent frontmatter — `roles: [<role>]` to make it role-addressable, or `roles: none` to opt out explicitly');
  }
}

try {
  run();
} catch (err) {
  // Fail-open: doctor checks must never crash the suite.
  console.log(`[t1k:doctor] agent-routing-reachability: WARN — check errored: ${err.message}`);
}

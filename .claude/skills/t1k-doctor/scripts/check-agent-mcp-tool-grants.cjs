#!/usr/bin/env node
// t1k-origin: kit=theonekit-core | repo=The1Studio/theonekit-core | module=t1k-base | protected=true
// check-agent-mcp-tool-grants.cjs — Doctor check #54: agent MCP tool-grant drift.
//
// An agent's `tools:` frontmatter is a CLAIM about what an MCP server serves,
// and it rots silently in BOTH directions (#651):
//
//   granted but not served → the agent quietly substitutes a weaker method and
//                            reports that weaker result as the verdict;
//   served but not granted → identical symptom from the outside.
//
// Neither errors. To the agent, to whoever writes its brief, and to anyone
// reading the `.md`, a stale grant reads as a capability the agent has — so the
// failure gets mis-attributed to an MCP-server bug rather than to our own
// allowlist. Prose cannot be the control here: a careful human sweep got it
// wrong in both directions on the same day (DOTS-AI, 2026-07-31).
//
// SOURCE OF TRUTH for "what does this server actually serve?"
// ----------------------------------------------------------
// A declared manifest: `mcp.{required,recommended,optional}[].servedTools` in
// any `t1k-config-*.json` fragment. Deliberately NOT a live `tools/list` probe:
//
//   - `claude mcp list` / `claude mcp get` do not expose a tool list, so a live
//     probe would mean speaking MCP JSON-RPC to a server this check would have
//     to spawn — seconds per stdio server, against a doctor suite budgeted at
//     < 60s, and unavailable whenever the server is simply not running;
//   - a false "this tool doesn't exist" is EXACTLY the failure that produced the
//     over-correction half of #651 (`rendering_stats`, a real tool, deleted from
//     8 agents as "phantom"). Silence is the safe default, so a server with no
//     declared manifest is reported unverified, never as a violation.
//
// Usage:
//   node check-agent-mcp-tool-grants.cjs [path/to/.claude] [--include-ungranted]
//
// `--include-ungranted` adds the informational served-but-ungranted direction
// (noisy by design — opt-in). Exits 0 always (WARN level), fail-open.

'use strict';

const fs = require('node:fs');
const path = require('node:path');

const CONFIG_PREFIX = 't1k-config-';
const GRANT_RE = /^mcp__([^_][^\s]*?)__(\S+)$/;

/** Read the `tools:` YAML-array frontmatter field of an agent .md. */
function readToolGrants(content) {
  if (!content.startsWith('---')) return [];
  const end = content.indexOf('\n---', 3);
  if (end === -1) return [];
  const block = content.slice(3, end);
  const m = block.match(/^tools\s*:\s*\[([^\]]*)\]/m);
  if (!m) return [];
  return m[1].split(',').map(s => s.trim().replace(/^["']|["']$/g, '')).filter(Boolean);
}

/**
 * Collect `server → Set(servedTools)` from every t1k-config-*.json fragment.
 * A server appears here only when a fragment declares `servedTools`.
 */
function readServedManifests(claudeDir) {
  const served = new Map();
  let files = [];
  try {
    files = fs.readdirSync(claudeDir)
      .filter(f => f.startsWith(CONFIG_PREFIX) && f.endsWith('.json'));
  } catch { return served; }
  for (const f of files) {
    let config;
    try { config = JSON.parse(fs.readFileSync(path.join(claudeDir, f), 'utf8')); } catch { continue; }
    const mcp = config && config.mcp;
    if (!mcp || typeof mcp !== 'object') continue;
    for (const tier of ['required', 'recommended', 'optional']) {
      if (!Array.isArray(mcp[tier])) continue;
      for (const entry of mcp[tier]) {
        if (!entry || typeof entry.name !== 'string') continue;
        if (!Array.isArray(entry.servedTools)) continue;
        const set = served.get(entry.name) || new Set();
        for (const t of entry.servedTools) {
          if (typeof t === 'string' && t) set.add(t);
        }
        served.set(entry.name, set);
      }
    }
  }
  return served;
}

/**
 * The three name shapes that look like a tool but can never be granted. Naming
 * them in the warning is what stops the "delete it, it's phantom" over-correction.
 */
const SHAPE_HINT =
  'likely shapes: an `action` of another tool (grant the parent tool), an MCP ' +
  'resource (never grantable — read via the resource URI), or a handler with no ' +
  'registered wrapper';

function run() {
  const args = process.argv.slice(2);
  const includeUngranted = args.includes('--include-ungranted');
  const claudeDir = args.find(a => !a.startsWith('--')) || path.join(process.cwd(), '.claude');
  const agentsDir = path.join(claudeDir, 'agents');

  if (!fs.existsSync(agentsDir)) {
    console.log('[t1k:doctor] agent-mcp-tool-grants: SKIP — no agents/ directory');
    return;
  }

  const served = readServedManifests(claudeDir);

  const violations = [];      // { agent, grant, server, tool }
  const unverified = new Map(); // server → Set(agent)
  const grantedByServer = new Map(); // server → Set(tool)

  const agentFiles = fs.readdirSync(agentsDir).filter(f => f.endsWith('.md'));
  for (const file of agentFiles) {
    const agent = file.replace(/\.md$/, '');
    let content;
    try { content = fs.readFileSync(path.join(agentsDir, file), 'utf8'); } catch { continue; }
    for (const grant of readToolGrants(content)) {
      if (!grant.startsWith('mcp__')) continue;
      const m = grant.match(GRANT_RE);
      // `mcp__server__*` / `mcp__server` are server-level grants — nothing to
      // reconcile against a per-tool manifest.
      if (!m || m[2] === '*') continue;
      const [, server, tool] = m;
      const manifest = served.get(server);
      if (!manifest) {
        const agents = unverified.get(server) || new Set();
        agents.add(agent);
        unverified.set(server, agents);
        continue;
      }
      const grants = grantedByServer.get(server) || new Set();
      grants.add(tool);
      grantedByServer.set(server, grants);
      if (!manifest.has(tool)) violations.push({ agent, grant, server, tool });
    }
  }

  const ungranted = [];
  if (includeUngranted) {
    for (const [server, manifest] of served) {
      const grants = grantedByServer.get(server);
      if (!grants) continue; // no agent grants this server at all — not drift
      for (const tool of manifest) {
        if (!grants.has(tool)) ungranted.push(`mcp__${server}__${tool}`);
      }
    }
  }

  if (served.size === 0) {
    console.log(
      '[t1k:doctor] agent-mcp-tool-grants: SKIP — no `servedTools` manifest declared ' +
      `in any ${CONFIG_PREFIX}*.json (${unverified.size} server(s) referenced by agent grants, unverified)`,
    );
    return;
  }

  if (violations.length === 0 && ungranted.length === 0) {
    console.log(
      `[t1k:doctor] agent-mcp-tool-grants: PASS — ${served.size} server manifest(s), ` +
      `${unverified.size} unverified`,
    );
    return;
  }

  console.log(
    `[t1k:doctor] agent-mcp-tool-grants: WARN — ${violations.length} grant(s) not in the ` +
    `declared served-tool manifest`,
  );
  for (const v of violations) {
    console.log(`  ${v.agent}: ${v.grant} — "${v.tool}" is not served by ${v.server}`);
  }
  if (violations.length > 0) {
    console.log(`  ${SHAPE_HINT}`);
    console.log(`  fix: drop the grant, or add the tool to \`mcp.*[].servedTools\` if the manifest is the stale half`);
  }
  if (ungranted.length > 0) {
    console.log(`  served but ungranted (informational): ${ungranted.join(', ')}`);
  }
  if (unverified.size > 0) {
    console.log(`  unverified (no servedTools manifest): ${[...unverified.keys()].join(', ')}`);
  }
}

try {
  run();
} catch (err) {
  // Fail-open: doctor checks must never crash the suite.
  console.log(`[t1k:doctor] agent-mcp-tool-grants: WARN — check errored: ${err.message}`);
}

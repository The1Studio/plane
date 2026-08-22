#!/usr/bin/env node
// t1k-origin: kit=theonekit-core | repo=The1Studio/theonekit-core | module=null | protected=true
'use strict';

/**
 * statusline-agent-model.cjs — resolve which MODEL a ledger row actually ran
 * on, for the statusline agent-tree segment.
 *
 * TWO LAYERS, AND THE DISTINCTION IS THE POINT
 * -----------------------------------------------
 * An agent's `.md` frontmatter `model:` field is the PINNED tier — what the
 * agent author declared. Under transparent routing (`mr-task-interceptor.cjs`),
 * that is not necessarily what ran: a write-capable / spawn-capable agent is
 * floored back to Anthropic passthrough regardless of a cheap `modelMapping`
 * entry, and a routable agent can land on any configured provider/model.
 * `~/.model-router/debug.jsonl` records the interceptor's ACTUAL decision per
 * delegation. This module prefers that confirmed record and falls back to the
 * pinned tier, marked UNCONFIRMED, only when no matching record exists — never
 * silently presenting a guess as a fact (`docs/green-that-proves-nothing.md`).
 *
 * CORRELATION — NO SHARED ID, SO NEAREST-TIMESTAMP MATCH
 * -----------------------------------------------------------
 * debug.jsonl carries no field shared with the fork-depth ledger's `pending`
 * records. What IS shared: `session` (the SAME 16-hex digest
 * `session-state-path.cjs`'s `sessionKey()` produces — confirmed empirically
 * against a live ledger filename), `parentId` (`'ROOT'` or the spawner's own
 * agentId, byte-identical convention to the ledger's own `parentId`), and
 * `agent` (the ledger's `childType`). A ledger row is matched to the debug
 * record with the SAME (session, parentId, agent) whose `ts` is closest to the
 * row's own `ts`, within `MATCH_WINDOW_MS` — the interceptor's PreToolUse fires
 * essentially the same moment `fork-depth-guard.cjs` writes the pending record,
 * so a tight window is deliberate: a distant match is a coincidence, not a
 * correlation, and coincidence must not be presented as confirmation.
 *
 * BOUNDED READ — NOT THE WHOLE FILE, EVEN THOUGH IT'S CURRENTLY CHEAP
 * -----------------------------------------------------------------------
 * A full read of the observed 6274-line/1.3MB debug.jsonl costs ~5ms — already
 * comfortably cheap today. But the file is append-only for the LIFETIME of the
 * machine, not scoped per-session like a ledger, so "cheap today" is not a
 * property of the design. `readTailLines()` bounds the read to the last
 * `DEBUG_TAIL_BYTES` regardless of total file size, the same posture as the
 * per-agent transcript tail read in `statusline-agent-tokens.cjs`.
 */

const fs = require('fs');
const os = require('os');
const path = require('path');

let readFrontmatter = null;
let findAgentFile = null;
try {
  ({ readFrontmatter, findAgentFile } = require('../task-description-model-badge.cjs'));
} catch { /* optional — badge hook not shipped in this install */ }

const DEBUG_TAIL_BYTES = 512 * 1024; // ~512KB — generous for "this session's recent activity"
const MATCH_WINDOW_MS = 30000; // interceptor + ledger writes are near-simultaneous; 30s is generous, not lax

function debugJsonlPath() {
  return path.join(os.homedir(), '.model-router', 'debug.jsonl');
}

/**
 * Read the last `maxBytes` of a jsonl file and parse whatever complete lines
 * survive. The (possibly truncated) first line of the tail is dropped rather
 * than risking a malformed-JSON parse of a partial record.
 * Never throws; returns [] on any fault (missing file, read error, empty tail).
 */
function readTailLines(filePath, maxBytes) {
  let fd;
  try {
    fd = fs.openSync(filePath, 'r');
    const size = fs.fstatSync(fd).size;
    if (size === 0) return [];
    const start = Math.max(0, size - maxBytes);
    const buf = Buffer.alloc(size - start);
    fs.readSync(fd, buf, 0, buf.length, start);
    const lines = buf.toString('utf8').split('\n');
    if (start > 0) lines.shift(); // drop a possibly-truncated leading line
    const out = [];
    for (const line of lines) {
      if (!line) continue;
      try { out.push(JSON.parse(line)); } catch { /* skip malformed */ }
    }
    return out;
  } catch {
    return [];
  } finally {
    if (Number.isInteger(fd)) { try { fs.closeSync(fd); } catch {} }
  }
}

/**
 * Find the debug.jsonl record that most plausibly describes ONE ledger row's
 * routing decision. Nearest-`ts`-wins within `MATCH_WINDOW_MS`; ties broken by
 * the earliest record (interceptor logs before the child's own turn starts).
 */
function findRoutingRecord(records, { session, parentId, agentType, ts }) {
  let best = null;
  let bestDelta = Infinity;
  for (const rec of records) {
    if (!rec || rec.event !== 'intercept') continue;
    if (rec.session !== session) continue;
    if ((rec.parentId || 'ROOT') !== (parentId || 'ROOT')) continue;
    if (rec.agent !== agentType) continue;
    const recTs = Date.parse(rec.ts);
    if (!Number.isFinite(recTs)) continue;
    const delta = Math.abs(recTs - ts);
    if (delta > MATCH_WINDOW_MS) continue;
    if (delta < bestDelta) { bestDelta = delta; best = rec; }
  }
  return best;
}

/** Render one CONFIRMED routing record as a `model@provider` label. */
function labelFromRoutingRecord(rec) {
  if (rec.decision === 'route' && rec.pick && rec.pick.model) {
    const provider = rec.pick.provider || 'unknown';
    return `${rec.pick.model}@${provider}`;
  }
  if (typeof rec.decision === 'string' && rec.decision.startsWith('pass-')) {
    // Floored/excluded/disabled — the interceptor did NOT route; the request
    // went to Anthropic on whatever tier `modelKey` names (frontmatter-derived,
    // read by the interceptor itself — so this is confirmed, not guessed).
    const tier = rec.modelKey || 'unknown';
    return `${tier}@anthropic`;
  }
  return null;
}

/**
 * Pinned-tier fallback, read straight from the agent's own frontmatter.
 * `projectRoot` is the directory ONE ABOVE `.claude/` (i.e. `findAgentFile`'s
 * own contract: `<projectRoot>/.claude/agents/<name>.md`), never `claudeDir`
 * itself — passing `claudeDir` here would look for `.claude/.claude/agents/`.
 */
function resolvePinnedTier(agentType, projectRoot) {
  if (!readFrontmatter || !findAgentFile || !agentType) return null;
  try {
    const file = findAgentFile(agentType, projectRoot || process.cwd());
    if (!file) return null;
    const fm = readFrontmatter(file);
    return fm.model && fm.model.trim() ? fm.model.trim() : null;
  } catch {
    return null;
  }
}

/**
 * Resolve the model label for one ledger row.
 *
 * @param {{ childType: string|null, parentId: string|null, ts: number }} row
 * @param {{ projectRoot?: string, session?: string, now?: number, deps?: object }} [options]
 * @returns {{ label: string|null, confirmed: boolean }}
 *   `label: null`  — nothing resolvable (no debug record, no agent file)
 *   `confirmed: true`  — read from a matched model-router routing decision
 *   `confirmed: false` — pinned frontmatter tier, routing outcome unconfirmed
 */
function resolveAgentModel(row, options = {}) {
  try {
    const deps = Object.assign({ readTailLines, debugJsonlPath }, options.deps || {});
    const agentType = row && row.childType;
    if (!agentType) return { label: null, confirmed: false };

    if (options.session) {
      const records = deps.readTailLines(deps.debugJsonlPath(), DEBUG_TAIL_BYTES);
      const rec = findRoutingRecord(records, {
        session: options.session, parentId: row.parentId, agentType, ts: row.ts,
      });
      if (rec) {
        const label = labelFromRoutingRecord(rec);
        if (label) return { label, confirmed: true };
      }
    }

    const tier = resolvePinnedTier(agentType, options.projectRoot);
    if (tier) return { label: `${tier}?`, confirmed: false };
    return { label: null, confirmed: false };
  } catch {
    return { label: null, confirmed: false };
  }
}

module.exports = {
  resolveAgentModel,
  findRoutingRecord,
  labelFromRoutingRecord,
  resolvePinnedTier,
  readTailLines,
  debugJsonlPath,
  DEBUG_TAIL_BYTES,
  MATCH_WINDOW_MS,
};

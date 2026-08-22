#!/usr/bin/env node
// t1k-origin: kit=theonekit-core | repo=The1Studio/theonekit-core | module=null | protected=true
'use strict';

/**
 * statusline-ledger-read.cjs — PINNED, READ-ONLY COPY of the fork-depth ledger
 * primitives the statusline agent-tree feature needs, kept deliberately
 * separate from `fork-depth.cjs` / `session-state-path.cjs` / `telemetry-
 * utils.cjs` / `agent-tree-view.cjs` / `subagent-transcript.cjs`.
 *
 * WHY A PINNED COPY INSTEAD OF REQUIRING THE CANONICAL FILES (READ THIS FIRST)
 * ------------------------------------------------------------------------------
 * The first two rounds of this feature required those files directly, and
 * CI's `gates / quality-gates` run caught the real defect PR #1055 review
 * flagged as a possibility and this fixes: `t1k-base/module.json` claiming
 * ANY of them in `files.hooks` moves that file from SHARED-ZIP staging
 * (`build-shared-zip.cjs` ships `hooks/**` unconditionally, regardless of
 * module selection) into t1k-base-ONLY packaging — and every one of these
 * files is required, unclaimed, by hooks OUTSIDE t1k-base's own closure:
 *
 *   fork-depth.cjs          <- delegation-drift.cjs, fork-depth-guard.cjs, fork-depth-release.cjs
 *   session-state-path.cjs  <- routed-stop-guard.cjs, context-bloat-guard.cjs, delegation-floor-nudge.cjs, delegation-drift.cjs
 *   telemetry-utils.cjs     <- 89 files across the kit
 *   subagent-transcript.cjs <- delegation-floor-nudge.cjs, delegation-floor-detector.cjs, subagent-uncommitted-guard.cjs, workflow-failure-detector.cjs, lib/silent-return-recheck.cjs
 *   subagent-tool-names.cjs <- fork-depth-guard.cjs, lib/delegation-drift.cjs, lib/subagent-transcript.cjs
 *   agent-tree-view.cjs (.claude/scripts/) <- pulls in fork-depth.cjs + session-state-path.cjs + telemetry-utils.cjs itself
 *
 * `validate-module-hook-deps.cjs` (#751) demands every file reachable from a
 * SHIPPED hook be claimed by that SAME module. `validate-shared-zip-hook-
 * requires.cjs` demands every hook resolvable ONLY from the shared zip's own
 * staged tree still resolve there. Claiming any commons file above satisfies
 * the first gate and fails the second — CI showed this concretely: claiming
 * `telemetry-utils.cjs` broke `telemetry-skill-tracker.cjs`,
 * `unity-process-guard.cjs`, `workflow-failure-detector.cjs`, and others that
 * plain-`require()` it and were never meant to move.
 *
 * The only files SAFE for `t1k-base/module.json` to claim are ones with NO
 * other unclaimed consumer — this file included: nothing outside
 * `lib/statusline-agent-tree.cjs` / `lib/statusline-agent-tokens.cjs`
 * requires it, so claiming it moves nothing else.
 *
 * WHAT IS AND IS NOT MIRRORED
 * ----------------------------
 * `sessionKey`/`ledgerPath` (session-state-path.cjs), `emptyLedger`/
 * `normalizeLedger`/`loadLedger` minus `pruneLedger` (fork-depth.cjs),
 * `buildTree`/`statusOf` (agent-tree-view.cjs), and `deriveAgentTranscript`
 * (subagent-transcript.cjs) are copied VERBATIM below — same algorithm, same
 * output, so a change to those canonical files (a path-shape change most of
 * all — `sessionKey`/`ledgerPath` are pinned compatibility contracts there
 * with their own frozen-digest test) must be mirrored here or this file
 * silently drifts onto orphaned state. `pruneLedger`'s per-record TTL
 * trimming (6h `PENDING_TTL_MS`/`BOUND_TTL_MS`) is DELIBERATELY NOT mirrored:
 * this module never WRITES the ledger back, so skipping it cannot leak an
 * oversized on-disk file (the writer already caps at `MAX_PENDING`=500/
 * `MAX_BOUND`=1000), and a record older than 6h without being pruned reads no
 * differently here than one pruned a moment sooner — `statusOf()`'s own
 * `liveChildTtlMinutes` floor (default 15 MINUTES) already marks it stale
 * long before the 6h prune threshold would matter. `readForkDepthConfig()`'s
 * full config surface (`fanOutCaps`, `budget`, `sessionSpawnCeiling`,
 * `fanOutCapEnforce`, `routedReconcile`) is likewise NOT mirrored — this
 * feature reads exactly one of its keys (`liveChildTtlMinutes`), so
 * `readLiveChildTtlMinutes()` below is a narrower, single-purpose reader, not
 * a full clone of `readForkDepthConfig()`.
 *
 * NEVER WRITES ANYTHING. Read-only by construction: no `writeLedger`,
 * `recordSpawn`, `releaseChild`, or lock acquisition exists in this file.
 */

const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');

// ── session / path (pinned from session-state-path.cjs) ────────────────────

const SESSION_KEY_LEN = 16;
const NO_SESSION = 'no-session';

function sessionKey(sessionId) {
  return crypto.createHash('sha1').update(String(sessionId || NO_SESSION)).digest('hex').slice(0, SESSION_KEY_LEN);
}

function ledgerPath(sessionId) {
  return path.join(os.tmpdir(), `t1k-fork-depth-${sessionKey(sessionId)}.json`);
}

// ── ledger read (pinned from fork-depth.cjs, minus pruneLedger — see docblock) ─

const FILE_TTL_MS = 24 * 60 * 60 * 1000; // 24h — whole file discarded past this age
const DEFAULT_LIVE_CHILD_TTL_MINUTES = 15; // fork-depth.cjs DEFAULTS.liveChildTtlMinutes

function emptyLedger() {
  return { version: 1, bound: {}, pending: [], seen: [], routedSeen: [], spawnCount: 0 };
}

function normalizeLedger(raw) {
  const led = emptyLedger();
  if (!raw || typeof raw !== 'object') return led;
  if (raw.bound && typeof raw.bound === 'object') {
    for (const [id, entry] of Object.entries(raw.bound)) {
      if (!entry || typeof entry !== 'object' || !Number.isInteger(entry.depth)) continue;
      led.bound[id] = {
        depth: entry.depth,
        type: typeof entry.type === 'string' ? entry.type : null,
        boundAt: Number.isFinite(entry.boundAt) ? entry.boundAt : 0,
        boundVia: typeof entry.boundVia === 'string' ? entry.boundVia : 'unknown',
      };
    }
  }
  if (Array.isArray(raw.pending)) {
    led.pending = raw.pending.filter(p => p && typeof p === 'object' && Number.isInteger(p.depth));
  }
  if (Array.isArray(raw.seen)) led.seen = raw.seen.filter(s => typeof s === 'string');
  if (Array.isArray(raw.routedSeen)) led.routedSeen = raw.routedSeen.filter(s => typeof s === 'string');
  if (Number.isFinite(raw.spawnCount)) led.spawnCount = raw.spawnCount;
  return led;
}

/**
 * Load the ledger. Never throws. A malformed, unreadable, or absent file
 * yields an EMPTY ledger with `fault` set.
 * @returns {{ ledger: object, fault: string|null, existed: boolean }}
 */
function loadLedger(file, now) {
  const t = Number.isFinite(now) ? now : Date.now();
  let existed = false;
  try {
    const st = fs.statSync(file);
    existed = true;
    if (st.isFile() && (t - st.mtimeMs) > FILE_TTL_MS) {
      return { ledger: emptyLedger(), fault: null, existed: false };
    }
  } catch (err) {
    if (err && err.code === 'ENOENT') return { ledger: emptyLedger(), fault: null, existed: false };
    return { ledger: emptyLedger(), fault: `stat:${(err && err.code) || 'unknown'}`, existed: true };
  }

  let raw;
  try {
    raw = fs.readFileSync(file, 'utf8');
  } catch (err) {
    return { ledger: emptyLedger(), fault: `read:${(err && err.code) || 'unknown'}`, existed };
  }

  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return { ledger: emptyLedger(), fault: 'parse:malformed', existed };
  }

  return { ledger: normalizeLedger(parsed), fault: null, existed };
}

/**
 * `forkDepth.liveChildTtlMinutes` only — see docblock for why the rest of
 * `readForkDepthConfig()`'s surface is not mirrored. Same override-by-priority
 * merge rule (CLAUDE.md § Architecture): fragments applied ascending priority,
 * highest wins. Never throws; unreadable/absent config -> the same 15-minute
 * default `fork-depth.cjs` itself ships.
 */
function readLiveChildTtlMinutes(claudeDir) {
  if (!claudeDir) return DEFAULT_LIVE_CHILD_TTL_MINUTES;
  let value = DEFAULT_LIVE_CHILD_TTL_MINUTES;
  try {
    const fragments = fs.readdirSync(claudeDir)
      .filter(f => f.startsWith('t1k-config-') && f.endsWith('.json'))
      .map(f => {
        try {
          const parsed = JSON.parse(fs.readFileSync(path.join(claudeDir, f), 'utf8'));
          return { priority: Number(parsed && parsed.priority) || 0, forkDepth: parsed && parsed.forkDepth };
        } catch { return null; }
      })
      .filter(Boolean)
      .sort((a, b) => a.priority - b.priority);
    for (const frag of fragments) {
      const v = frag.forkDepth && frag.forkDepth.liveChildTtlMinutes;
      if (Number.isFinite(v) && v >= 0) value = v;
    }
  } catch { /* fail-open to the default */ }
  return value;
}

// ── feature flags (minimal read of `features.*`, pinned from telemetry-utils.cjs) ─

/**
 * Same opt-out-wins / opt-in-wins / default semantics as `telemetry-
 * utils.cjs`'s `readFeatureFlag()`. Scoped to `features.*` only — this file
 * does not need, and does not read, `scopeEnforcement` or any other block.
 */
function readFeatureFlag(claudeDir, flagName, defaultValue) {
  let seenExplicit = false;
  let explicitValue = defaultValue;
  try {
    const files = fs.readdirSync(claudeDir).filter(f => f.startsWith('t1k-config-') && f.endsWith('.json'));
    for (const cf of files) {
      try {
        const c = JSON.parse(fs.readFileSync(path.join(claudeDir, cf), 'utf8'));
        const v = c.features && c.features[flagName];
        if (v === false) return false;
        if (v === true) { seenExplicit = true; explicitValue = true; }
      } catch { /* skip unreadable fragment */ }
    }
  } catch { /* no claudeDir or unreadable */ }
  return seenExplicit ? explicitValue : defaultValue;
}

// ── tree construction (pinned from agent-tree-view.cjs) ────────────────────

/** @returns {{ root: object, orphans: object[] }} */
function buildTree(ledger) {
  const root = { id: 'ROOT', label: 'main (root session)', depth: 0, children: [], record: null };
  const nodesByOwnId = new Map();
  nodesByOwnId.set('ROOT', root);

  const nodes = ledger.pending.map(record => ({
    id: record.claimedBy || null,
    label: record.childName || record.childType || 'unknown-agent',
    type: record.childType || null,
    depth: record.depth,
    parentId: record.parentId || 'ROOT',
    children: [],
    record,
  }));

  for (const node of nodes) {
    if (node.id) nodesByOwnId.set(node.id, node);
  }

  const orphans = [];
  for (const node of nodes) {
    const parent = nodesByOwnId.get(node.parentId);
    if (parent) parent.children.push(node);
    else orphans.push(node);
  }

  const byTs = (a, b) => (a.record.ts || 0) - (b.record.ts || 0);
  const sortRec = n => { n.children.sort(byTs); n.children.forEach(sortRec); };
  sortRec(root);
  orphans.sort(byTs);

  return { root, orphans };
}

function statusOf(record, now, liveChildTtlMs) {
  if (record.released) {
    return { label: 'released', durationMs: (record.releasedAt || now) - record.ts };
  }
  const age = now - record.ts;
  const stale = liveChildTtlMs > 0 && age > liveChildTtlMs;
  return {
    label: stale ? 'live (stale — no longer holds a fan-out slot)' : 'live',
    durationMs: age,
  };
}

// ── per-agent transcript path (pinned from subagent-transcript.cjs) ────────

const SUBAGENT_DIR_NAME = 'subagents';
const SAFE_AGENT_ID_RE = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;

/**
 * Pure string derivation, no fs call. A derived path that does not exist is
 * not an error here — callers already treat a missing/unreadable file as
 * "no data available".
 */
function deriveAgentTranscript(parentTranscriptPath, agentId) {
  if (!parentTranscriptPath || typeof parentTranscriptPath !== 'string') return null;
  if (!agentId || typeof agentId !== 'string') return null;
  const id = agentId.trim();
  if (!SAFE_AGENT_ID_RE.test(id) || id.includes('..')) return null;
  const dir = path.dirname(parentTranscriptPath);
  const sessionDir = path.basename(parentTranscriptPath).replace(/\.jsonl$/i, '');
  if (!sessionDir) return null;
  return path.join(dir, sessionDir, SUBAGENT_DIR_NAME, `agent-${id}.jsonl`);
}

module.exports = {
  sessionKey,
  ledgerPath,
  emptyLedger,
  normalizeLedger,
  loadLedger,
  readLiveChildTtlMinutes,
  readFeatureFlag,
  buildTree,
  statusOf,
  deriveAgentTranscript,
  FILE_TTL_MS,
  DEFAULT_LIVE_CHILD_TTL_MINUTES,
};

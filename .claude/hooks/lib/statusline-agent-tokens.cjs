#!/usr/bin/env node
// t1k-origin: kit=theonekit-core | repo=The1Studio/theonekit-core | module=null | protected=true
'use strict';

/**
 * statusline-agent-tokens.cjs — bounded-cost per-agent token count + spawn
 * description for the statusline agent-tree segment.
 *
 * DELIBERATELY NOT `lib/subagent-transcript.cjs`'s `scanTranscript()` —
 * AND NOT A DIRECT REQUIRE OF `subagent-transcript.cjs` AT ALL
 * ------------------------------------------------------------------------
 * `scanTranscript()` is the existing SSOT for reading a sub-agent's transcript
 * (`code-conventions.md` § No Duplicated Logic normally means "reuse it"), and
 * an earlier revision of this file DID reuse its `deriveAgentTranscript()` via
 * a direct plain-require of that module — the cheap, fs-free path
 * derivation. That require was removed: `subagent-transcript.cjs` is required,
 * UNCLAIMED, by six other hooks outside t1k-base's closure (`delegation-floor-
 * nudge.cjs`, `delegation-floor-detector.cjs`, `subagent-uncommitted-
 * guard.cjs`, `workflow-failure-detector.cjs`, `lib/silent-return-
 * recheck.cjs`), so claiming it here (forced by `validate-module-hook-
 * deps.cjs` / #751) would move it out of shared-ZIP staging and break every
 * one of them — see `statusline-agent-tree.cjs`'s docblock § PACKAGING for the
 * concrete CI failure this caused. `deriveAgentTranscript()` is now a pinned,
 * verbatim copy in `statusline-ledger-read.cjs` (nothing else requires that
 * file, so claiming it is safe) instead.
 *
 * It deliberately does NOT reuse `scanTranscript()` itself, pinned copy or
 * not: that
 * function does one full forward walk of the ENTIRE transcript file, which is
 * the right shape for its own callers (`SubagentStop`, once per agent, whole
 * file already the size it will ever be) and the wrong shape for a statusline
 * segment that re-derives this on every cache-miss for every LIVE agent, on a
 * transcript that is actively growing. Measured against this session's own 25
 * real sub-agent transcripts (14.2MB total): `scanTranscript()` cost 249ms
 * cumulative (two files spiked to ~90ms each); a bounded tail read of the same
 * 25 files cost 2.2ms total — two orders of magnitude cheaper, and the values
 * agreed. Two implementations of "read a transcript" is a real seam split, not
 * a duplication: they serve incompatible performance envelopes
 * (`code-conventions.md` § Modular Boundaries — a seam earns its keep when the
 * alternative is force-fitting one shape onto two different cost budgets).
 *
 * WHAT "BOUNDED" BUYS AND WHAT IT DOES NOT
 * -----------------------------------------
 * `usage` on Claude's own message envelope is a per-TURN snapshot, not a
 * lifetime cumulative counter (`subagent-transcript.cjs`'s own #753 docblock
 * documents this same fact for its peak-context measure). The LAST assistant
 * turn's `usage` is the agent's current total context — exactly analogous to
 * what `statusline.cjs`'s OWN main-session render already does with
 * `context_window.current_usage`. Reading only the tail is correct AS LONG AS
 * that last assistant turn falls inside the tail window; on a real transcript
 * the last written entries during a live run are almost always the
 * most-recent assistant turn plus its immediate tool round-trip, which is why
 * a bounded tail finds it in practice (verified against all 25 files above).
 * When it genuinely is not found in the window, this returns `null` rather
 * than reading further or estimating — per the brief: "render the column only
 * for agents where a cheap source exists, rather than inventing an estimate."
 */

const fs = require('fs');

// Pinned copy, not the canonical subagent-transcript.cjs — see file docblock.
// Always available (stdlib-only), so no guard needed here.
const { deriveAgentTranscript } = require('./statusline-ledger-read.cjs');

const TOKEN_TAIL_BYTES = 32 * 1024; // proven sufficient against 25 real, up-to-1.2MB transcripts

/**
 * Read the last `maxBytes` of a file and return its lines (leading possibly-
 * truncated line dropped). Never throws; [] on any fault.
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
    if (start > 0) lines.shift();
    return lines.filter(Boolean);
  } catch {
    return [];
  } finally {
    if (Number.isInteger(fd)) { try { fs.closeSync(fd); } catch {} }
  }
}

/**
 * Walk tail lines BACKWARD for the last assistant turn's usage total.
 * Same formula `statusline.cjs` already uses for the main session's own
 * `context_window.current_usage` (input + cache_read + cache_creation).
 * `output_tokens` is added too — unlike the main-session snapshot (which is a
 * PRE-response context measurement), a completed subagent turn's output is
 * part of what it actually consumed, matching `subagent-transcript.cjs`'s own
 * `turnContext` formula (#753).
 */
function lastAssistantTokenTotal(lines) {
  for (let i = lines.length - 1; i >= 0; i--) {
    let entry;
    try { entry = JSON.parse(lines[i]); } catch { continue; }
    const isAssistant = entry.type === 'assistant' || (entry.message && entry.message.role === 'assistant');
    if (!isAssistant) continue;
    const usage = entry.message && entry.message.usage;
    if (!usage) continue;
    const total = (usage.input_tokens || 0)
      + (usage.cache_read_input_tokens || 0)
      + (usage.cache_creation_input_tokens || 0)
      + (usage.output_tokens || 0);
    return total > 0 ? total : null;
  }
  return null;
}

/**
 * Cheap spawn-description read from the `.meta.json` sidecar written beside
 * every per-agent transcript (`{agentType, description, toolUseId, ...}` —
 * tens to a few hundred bytes; NOT the transcript itself).
 */
function readSpawnDescription(transcriptPath) {
  if (!transcriptPath) return null;
  try {
    const metaPath = transcriptPath.replace(/\.jsonl$/i, '.meta.json');
    const raw = fs.readFileSync(metaPath, 'utf8');
    const parsed = JSON.parse(raw);
    const d = parsed && parsed.description;
    return typeof d === 'string' && d.trim() ? d.trim() : null;
  } catch {
    return null;
  }
}

/**
 * Resolve token count + spawn description for one ledger row.
 *
 * @param {{ claimedBy: string|null }} row
 * @param {{ parentTranscriptPath: string, deps?: object }} options
 *   `parentTranscriptPath` — the MAIN session's own transcript path (the
 *   statusline's stdin already carries this as `data.transcript_path`); the
 *   per-agent file is DERIVED from it, never read directly from a guess.
 * @returns {{ tokens: number|null, description: string|null }}
 */
function resolveAgentTokens(row, options = {}) {
  try {
    const deps = Object.assign({ readTailLines, readSpawnDescription }, options.deps || {});
    const claimedBy = row && row.claimedBy;
    if (!claimedBy || !options.parentTranscriptPath) {
      return { tokens: null, description: null };
    }
    const transcriptPath = deriveAgentTranscript(options.parentTranscriptPath, claimedBy);
    if (!transcriptPath) return { tokens: null, description: null };

    const lines = deps.readTailLines(transcriptPath, TOKEN_TAIL_BYTES);
    const tokens = lines.length ? lastAssistantTokenTotal(lines) : null;
    const description = deps.readSpawnDescription(transcriptPath);
    return { tokens, description };
  } catch {
    return { tokens: null, description: null };
  }
}

/** `71523` -> `"70.4k"`, `842` -> `"842"`. No arrow/prefix — the caller styles it. */
function formatTokenCount(n) {
  if (!Number.isFinite(n) || n <= 0) return null;
  if (n < 1000) return String(n);
  return `${(n / 1000).toFixed(1)}k`;
}

module.exports = {
  resolveAgentTokens,
  formatTokenCount,
  lastAssistantTokenTotal,
  readSpawnDescription,
  readTailLines,
  TOKEN_TAIL_BYTES,
};

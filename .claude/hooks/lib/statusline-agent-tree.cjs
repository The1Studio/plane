#!/usr/bin/env node
// t1k-origin: kit=theonekit-core | repo=The1Studio/theonekit-core | module=null | protected=true
'use strict';

/**
 * statusline-agent-tree.cjs — compact agent spawn-tree segment for the statusline.
 *
 * WHY THIS EXISTS
 * ----------------
 * `.claude/scripts/agent-tree-view.cjs` (t1k-maintainer, `/t1k:agents`) is the
 * ORIGINAL, canonical tree builder over the fan-out-cap ledger (`hooks/lib/
 * fork-depth.cjs`). This file does NOT require it — see "PACKAGING" below for
 * why not — but the tree-construction algorithm it uses IS a pinned, verbatim
 * copy of that file's `buildTree`/`statusOf`, kept in `lib/statusline-ledger-
 * read.cjs` alongside the ledger-read primitives. What THIS file adds on top
 * is a presentation layer neither of those needs: rendering CAPPED to a
 * handful of short lines that fits above the statusline's other segments,
 * because a full multi-line text tree (cap-usage rows, orphan list, full
 * duration strings) is sized for a terminal command, not a status bar that
 * redraws on every turn.
 *
 * PACKAGING — WHY THIS DOES NOT REQUIRE fork-depth.cjs / session-state-path.cjs
 * / telemetry-utils.cjs / agent-tree-view.cjs / subagent-transcript.cjs
 * -----------------------------------------------------------------------------
 * All five are widely required, UNCLAIMED, by hooks outside t1k-base's own
 * closure (`delegation-drift.cjs`, `routed-stop-guard.cjs`, `context-bloat-
 * guard.cjs`, `workflow-failure-detector.cjs`, 89 files for telemetry-
 * utils.cjs alone). `build-shared-zip.cjs` ships `hooks/**` UNCONDITIONALLY
 * via the shared ZIP for exactly that reason — every module install gets them
 * regardless of which modules were selected. `validate-module-hook-deps.cjs`
 * (#751) demands the OPPOSITE: every file reachable from a hook `t1k-base/
 * module.json` claims must ALSO be explicitly claimed there. Requiring any of
 * the five and claiming this file satisfies #751 but moves that shared file
 * OUT of shared-ZIP staging and into t1k-base-only packaging — breaking every
 * OTHER unclaimed hook that plain-`require()`s it. This is not theoretical:
 * an earlier revision of this PR did exactly that and CI failed on
 * `telemetry-skill-tracker.cjs`, `unity-process-guard.cjs`, `workflow-
 * failure-detector.cjs`, and others. `lib/statusline-ledger-read.cjs` is a
 * pinned, read-only copy of exactly the primitives needed from those five
 * files, and nothing else in the kit requires IT — claiming it is safe.
 *
 * `lib/statusline-agent-model.cjs` (requires only `task-description-model-
 * badge.cjs`, which nothing else plain-requires either) and `lib/statusline-
 * agent-tokens.cjs` (now also `statusline-ledger-read.cjs`'s
 * `deriveAgentTranscript`, not `subagent-transcript.cjs`) are the SAME safe
 * shape.
 *
 * CACHING — TTL'd via the statusline's OWN private session cache
 * -----------------------------------------------------------------
 * The statusline is invoked on essentially every render. `AGENT_TREE_CACHE_
 * TTL_MS` bounds re-computation to at most once per that window per session,
 * using the SAME owner-only, atomic-rename session cache (`statusline-
 * private-cache.cjs`) the auth/context caches use. The cache key is the
 * SESSION id (not cwd), matching how the ledger itself is keyed — one cache
 * file per live session, swept by the existing retention sweep once
 * `agent-tree` is added to that file's `CACHE_FILENAME_RE`.
 *
 * "HARD TIME BUDGET" — WHAT THIS ACTUALLY BUYS, STATED HONESTLY
 * -----------------------------------------------------------------
 * Node cannot preempt a synchronous `fs.readFileSync` mid-syscall — there is no
 * cooperative yield point to time out from inside this process. What IS
 * enforceable, and what this module does: (1) the TTL cache means the
 * expensive path runs at most once per `AGENT_TREE_CACHE_TTL_MS`, not once per
 * render; (2) the ledger is already SIZE-bounded by its own writer's caps
 * (`MAX_PENDING`=500 / `MAX_BOUND`=1000 — see `statusline-ledger-read.cjs`),
 * so a cache-miss computation is O(hundreds) of small JSON records, not
 * unbounded; (3) every fs/JSON operation is wrapped in try/catch and a fault
 * degrades to "render nothing" rather than throwing. A genuinely wedged/hung
 * filesystem call is outside what a same-process try/catch can bound — that
 * failure mode would need an out-of-process timeout, which is not worth the
 * complexity for an optional status-bar segment.
 *
 * NEVER WRITES THE LEDGER. Only reads (`loadLedger`) — never writes. Writing
 * from the statusline could race the fan-out-cap guard that owns the lock.
 */

const os = require('os');
const path = require('path');

const {
  readSessionCacheJson,
  writeSessionCacheJson,
} = require('./statusline-private-cache.cjs');

// The ONE safe-to-claim source for ledger reads, tree construction, and
// feature-flag reads — see "PACKAGING" above. Always available (stdlib-only,
// no cross-module dependency), unlike the two optional modules below.
const ledgerRead = require('./statusline-ledger-read.cjs');

// Optional — resolved-vs-pinned model column (#2 additions). Depends
// transitively on task-description-model-badge.cjs (t1k-base, always present)
// so this is expected to resolve whenever the tree itself does; guarded anyway
// per the file's own fail-quiet posture.
let resolveAgentModel = null;
try {
  ({ resolveAgentModel } = require('./statusline-agent-model.cjs'));
} catch { /* degrade: model column omitted */ }

// Optional — token count + spawn description column (#2 additions).
let resolveAgentTokens = null;
let formatTokenCount = null;
try {
  ({ resolveAgentTokens, formatTokenCount } = require('./statusline-agent-tokens.cjs'));
} catch { /* degrade: tokens/description columns omitted */ }

const AGENT_TREE_CACHE_TTL_MS = 3000; // re-derive the tree at most every 3s
const DEFAULT_MAX_ROWS = 4;
const DEFAULT_TERM_WIDTH = 120;
const ROW_INDENT = '  ';
const CONNECTOR = '└─';

// ── Config / opt-in resolution ──────────────────────────────────────────────

/**
 * `.claude/` resolution WITHOUT `telemetry-utils.cjs`'s `resolveClaudeDir()`
 * (see file docblock § PACKAGING — that function is off-limits, not merely
 * unavailable in the standalone install). Prefers a project-local `.claude/`
 * next to the statusline's reported cwd, then falls back to the global one —
 * never throws, never invents a path that doesn't exist on disk.
 */
function resolveClaudeDirForTree(rawDir) {
  const fs = require('fs'); // lazy — only the two branches below touch fs
  try {
    if (rawDir) {
      const projectClaude = path.join(rawDir, '.claude');
      if (fs.existsSync(projectClaude)) return projectClaude;
    }
  } catch { /* fail-open */ }
  try {
    const globalClaude = path.join(os.homedir(), '.claude');
    if (fs.existsSync(globalClaude)) return globalClaude;
  } catch { /* fail-open */ }
  return null;
}

/**
 * `features.statuslineAgentTree` — OFF by default. No existing statusline
 * segment (agents/todos/model-router) is feature-flag-gated today, so there is
 * no "default ON matches convention" precedent to follow (the one segment that
 * DOES default on, `sessionArchive`, records that as an explicit dated
 * maintainer decision — no such decision has been made for this segment).
 * `T1K_SKIP_STATUSLINE_AGENT_TREE=1` is the emergency kill switch, matching the
 * `T1K_SKIP_*` convention already used by `context-budget-handoff.md` rather than inventing a new flag shape.
 */
function isEnabled(claudeDir, deps) {
  const d = deps || {};
  const readFeatureFlagFn = d.readFeatureFlag || ledgerRead.readFeatureFlag;
  if (String(process.env.T1K_SKIP_STATUSLINE_AGENT_TREE || '') === '1') return false;
  if (!claudeDir) return false;
  try {
    return readFeatureFlagFn(claudeDir, 'statuslineAgentTree', false);
  } catch {
    return false;
  }
}

// ── Row construction (pure — testable without a real ledger file) ──────────

/**
 * Walk `treeBuilder.buildTree()`'s output, collecting one row per LIVE node
 * (released nodes are never rendered individually — only counted) while still
 * recursing through released nodes, because a released spawner can still have
 * a live descendant (background children can outlive their spawner's own
 * turn). `node.depth` always comes straight from the ledger record — there is
 * no path here that can synthesize a depth for an unknown-depth spawn, because
 * `buildTree()` never creates a node for one in the first place (see
 * `agent-tree-view.cjs`'s own docblock).
 */
function collectLiveRows(node, out, now, liveChildTtlMs, statusOfFn, isRoot = true) {
  if (!isRoot && node.record) {
    if (!node.record.released) {
      const status = statusOfFn(node.record, now, liveChildTtlMs);
      out.push({
        depth: node.depth,
        label: node.label || node.type || 'unknown-agent',
        // Named `childType` (not `type`) to match the ledger record's own
        // field name — `statusline-agent-model.cjs`'s `findRoutingRecord`
        // matches debug.jsonl's `agent` field against exactly this value.
        childType: node.type || null,
        stale: status.label.startsWith('live (stale'),
        durationMs: status.durationMs,
        // Carried through for the model/token enrichment pass (#2 additions) —
        // never rendered directly, and never used to synthesize a depth: depth
        // above is ALWAYS `node.depth`, straight from the ledger record.
        parentId: node.record.parentId || null,
        claimedBy: node.id || null,
        ts: Number.isFinite(node.record.ts) ? node.record.ts : now,
      });
    }
  }
  for (const child of node.children) {
    collectLiveRows(child, out, now, liveChildTtlMs, statusOfFn, false);
  }
}

/**
 * Build the full data payload for a render: live rows (already tree-order,
 * depth-tagged), and the aggregate counts a truncated view must still surface
 * honestly (released count, and the ledger's own "untracked" gap — see
 * `docs/green-that-proves-nothing.md`: a silently-omitted gap reads as "no
 * gap" when the true state is "unmeasured").
 *
 * @param {object} ledger
 * @param {number} liveChildTtlMinutes  `forkDepth.liveChildTtlMinutes` — a
 *   plain number, not a config object (see `readLiveChildTtlMinutes()` in
 *   `statusline-ledger-read.cjs`, which is the ONLY config key this segment
 *   reads).
 */
function buildTreeData(ledger, liveChildTtlMinutes, now, deps) {
  const { buildTree, statusOf } = deps;
  const liveChildTtlMs = Number.isFinite(liveChildTtlMinutes)
    ? liveChildTtlMinutes * 60 * 1000
    : undefined;

  const { root, orphans } = buildTree(ledger);
  const rows = [];
  collectLiveRows(root, rows, now, liveChildTtlMs, statusOf, true);
  // An orphan's own PARENT is unknown/pruned, but the orphan itself is a real
  // record and may have real (correctly-nested) children of its own — walk
  // each orphan exactly like a root child so those descendants are not
  // silently dropped from the live-row count.
  for (const orphan of orphans) {
    collectLiveRows(orphan, rows, now, liveChildTtlMs, statusOf, false);
  }

  const trackedCount = ledger.pending.length;
  const releasedCount = ledger.pending.filter(p => p.released).length;
  const untracked = Math.max(0, ledger.spawnCount - trackedCount);

  return { rows, releasedCount, untracked, liveCount: rows.length };
}

// ── Text rendering ──────────────────────────────────────────────────────────

function truncateLabel(label, maxLen) {
  if (maxLen <= 1 || label.length <= maxLen) return label;
  return label.slice(0, Math.max(0, maxLen - 1)) + '…';
}

const DESCRIPTION_MAX_LEN = 28;

/**
 * Build ONE row's optional columns in PRIORITY order (index 0 = never
 * dropped, last index = dropped FIRST on a narrow terminal). `visibleLength`
 * is injected so this stays framework-agnostic of ANSI vs plain text.
 *
 * Priority, highest to lowest: label+status (always) > model (the whole
 * point of the #2 additions — a routed/pinned column with nothing to hide
 * behind) > elapsed time > tokens > spawn description (most decorative, and
 * the only column with no ledger-native source — read from a `.meta.json`
 * sidecar, see `statusline-agent-tokens.cjs`).
 */
function buildRowColumns(row, colors) {
  const cols = [];
  if (row.model && row.model.label) {
    cols.push(row.model.confirmed ? row.model.label : colors.dim(row.model.label));
  }
  if (Number.isFinite(row.durationMs)) {
    cols.push(colors.dim(formatElapsedShort(row.durationMs)));
  }
  if (row.tokensLabel) {
    cols.push(colors.dim(`↓${row.tokensLabel}`));
  }
  if (row.description) {
    cols.push(colors.dim(truncateLabel(row.description, DESCRIPTION_MAX_LEN)));
  }
  return cols;
}

/** `90000` -> `"1m30s"`-style short elapsed, matching `renderAgentsLines`'s existing terse style. */
function formatElapsedShort(ms) {
  if (!Number.isFinite(ms) || ms < 0) return '';
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  return `${h}h${m % 60}m`;
}

/**
 * Render the (already-truncated) row set as statusline lines.
 * `colors` is the injected `lib/colors.cjs` export set (green/yellow/dim) —
 * injectable so tests can assert on plain text without ANSI noise.
 *
 * `options.enrichRow(row) -> { model, tokensLabel, description }` is called
 * ONLY for rows that survive the `maxRows` cap (never for the full live set —
 * enrichment is the part that touches disk, so its cost is bounded by the cap,
 * not by session activity). Omit it (tests, or when the enrichment libs are
 * unavailable) and rows render with their existing columns only.
 */
function renderLines(data, options, colors) {
  const maxRows = Number.isFinite(options.maxRows) ? options.maxRows : DEFAULT_MAX_ROWS;
  const termWidth = Number.isFinite(options.termWidth) ? options.termWidth : DEFAULT_TERM_WIDTH;
  const { rows, releasedCount, untracked, liveCount } = data;

  if (liveCount === 0 && releasedCount === 0 && untracked === 0) return [];

  const lines = [];
  const summaryParts = [`${liveCount} live`];
  if (releasedCount > 0) summaryParts.push(`${releasedCount} released`);
  if (untracked > 0) summaryParts.push(`${untracked} untracked`);
  lines.push(`🌲 ${summaryParts.join(' · ')}`);

  const shown = rows.slice(0, maxRows);
  const overflow = rows.length - shown.length;
  const maxLabelWidth = Math.max(8, Math.floor(termWidth * 0.4) - 4);

  for (const row of shown) {
    if (typeof options.enrichRow === 'function') {
      try { Object.assign(row, options.enrichRow(row)); } catch { /* enrichment is best-effort */ }
    }
    const indent = ROW_INDENT.repeat(Math.max(0, row.depth - 1));
    const label = truncateLabel(row.label, maxLabelWidth);
    const dot = row.stale ? colors.yellow('●') : colors.green('●');
    const staleSuffix = row.stale ? colors.dim(' (stale)') : '';
    const head = `${indent}${CONNECTOR} ${dot} ${label}${staleSuffix}`;

    // Drop optional columns from the LOWEST-priority end until the row fits —
    // never wrap, per the brief.
    const optionalCols = buildRowColumns(row, colors);
    let line = optionalCols.length ? `${head}  ${optionalCols.join('  ')}` : head;
    while (optionalCols.length && visibleLengthPlain(line) > termWidth) {
      optionalCols.pop();
      line = optionalCols.length ? `${head}  ${optionalCols.join('  ')}` : head;
    }
    lines.push(line);
  }

  if (overflow > 0) {
    lines.push(`${ROW_INDENT}${colors.dim(`+${overflow} more live`)}`);
  }

  return lines;
}

/** ANSI-stripped length — good enough for the degrade check (no grapheme/CJK
 * width handling here; statusline.cjs's own `visibleLength` owns that for the
 * lines it composes at the top level, this only gates THIS segment's rows). */
function visibleLengthPlain(str) {
  return str.replace(/\x1b\[[0-9;]*m/g, '').length;
}

// ── Cache-wrapped orchestration ─────────────────────────────────────────────

function cachePath(sessionId) {
  return path.join(os.tmpdir(), `t1k-agent-tree-${sessionId}.json`);
}

/**
 * Top-level entry point. Returns a plain string[] of statusline lines (never
 * throws, never returns partial ANSI). Empty array = render nothing, which is
 * the correct response to: disabled, no session id, no ledger data, or any
 * internal fault.
 *
 * @param {{
 *   sessionId?: string, rawDir?: string, now?: number,
 *   transcriptPath?: string, cacheTtlMs?: number, maxRows?: number,
 *   termWidth?: number, deps?: object, colors?: object,
 * }} [options]
 *   `transcriptPath` — the MAIN session's own `transcript_path` (statusline
 *   stdin already carries this); required for the per-row token column, since
 *   a sub-agent's own transcript is DERIVED from it (never guessed).
 */
function renderAgentTreeLines(options = {}) {
  try {
    const now = Number.isFinite(options.now) ? options.now : Date.now();
    const sessionId = options.sessionId || null;
    if (!sessionId) return [];

    const deps = Object.assign({
      loadLedger: ledgerRead.loadLedger,
      readLiveChildTtlMinutes: ledgerRead.readLiveChildTtlMinutes,
      readFeatureFlag: ledgerRead.readFeatureFlag,
      buildTree: ledgerRead.buildTree,
      statusOf: ledgerRead.statusOf,
      readSessionCacheJson,
      writeSessionCacheJson,
      resolveAgentModel,
      resolveAgentTokens,
      formatTokenCount,
    }, options.deps || {});

    const claudeDir = options.claudeDir || resolveClaudeDirForTree(options.rawDir);
    if (!isEnabled(claudeDir, deps)) return [];

    const cacheTtlMs = Number.isFinite(options.cacheTtlMs) ? options.cacheTtlMs : AGENT_TREE_CACHE_TTL_MS;
    const cPath = options.cachePath || cachePath(sessionId);

    const cached = deps.readSessionCacheJson(cPath);
    if (cached && Number.isFinite(cached.ts) && (now - cached.ts) < cacheTtlMs && Array.isArray(cached.lines)) {
      return cached.lines;
    }

    const ledgerFile = options.ledgerPath || ledgerRead.ledgerPath(sessionId);
    const { ledger, fault, existed } = deps.loadLedger(ledgerFile, now);
    if (fault || !existed) {
      deps.writeSessionCacheJson(cPath, { ts: now, lines: [] });
      return [];
    }

    const liveChildTtlMinutes = deps.readLiveChildTtlMinutes(claudeDir);
    const data = buildTreeData(ledger, liveChildTtlMinutes, now, deps);
    const colors = options.colors || require('./colors.cjs');

    // Enrichment (model + tokens/description) touches disk — bounded to the
    // `maxRows` cap by renderLines(), never to the full live set.
    const enrichRow = (deps.resolveAgentModel || deps.resolveAgentTokens)
      ? (row) => {
          const out = {};
          if (deps.resolveAgentModel) {
            out.model = deps.resolveAgentModel(row, {
              session: ledgerRead.sessionKey(sessionId), projectRoot: options.rawDir,
            });
          }
          if (deps.resolveAgentTokens && options.transcriptPath) {
            const t = deps.resolveAgentTokens(row, { parentTranscriptPath: options.transcriptPath });
            if (t.tokens != null && deps.formatTokenCount) out.tokensLabel = deps.formatTokenCount(t.tokens);
            if (t.description) out.description = t.description;
          }
          return out;
        }
      : undefined;

    const lines = renderLines(data, Object.assign({ enrichRow }, options), colors);

    deps.writeSessionCacheJson(cPath, { ts: now, lines });
    return lines;
  } catch {
    // Fail-quiet per file docblock — an internal fault here must never look
    // like a broken statusline to the caller.
    return [];
  }
}

module.exports = {
  renderAgentTreeLines,
  isEnabled,
  collectLiveRows,
  buildTreeData,
  renderLines,
  truncateLabel,
  buildRowColumns,
  formatElapsedShort,
  resolveClaudeDirForTree,
  cachePath,
  AGENT_TREE_CACHE_TTL_MS,
  DEFAULT_MAX_ROWS,
};

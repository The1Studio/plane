#!/usr/bin/env node
// t1k-origin: kit=theonekit-core | repo=The1Studio/theonekit-core | module=null | protected=true
'use strict';

/**
 * TheOneKit Statusline for Claude Code
 * Cross-platform: Windows, macOS, Linux
 * Features: ANSI colors, context window, git status, agent/todo tracking, usage timer
 * T1K-native — no external dependencies beyond Node.js built-ins
 */

const { stdin, env } = require('process');
const os = require('os');
const fs = require('fs');
const path = require('path');

// T1K lib modules (self-contained, shipped with kit)
const { RESET, green, yellow, red, cyan, magenta, dim, coloredBar, getContextColor } = require('./lib/colors.cjs');
const { parseTranscript } = require('./lib/transcript-parser.cjs');
const { getGitInfo } = require('./lib/git-info-cache.cjs');
const {
  cleanupSessionCaches,
  readSessionCacheJson,
  writeSessionCacheJson,
} = require('./lib/statusline-private-cache.cjs');
// Optional fifth lib. The standalone `t1k-statusline-full` install copies only the four
// libs required above (install.sh `LIBS`), so a hard require would crash that copy with
// MODULE_NOT_FOUND — see the sanitizePath note above. Degrade to "quota unknown" instead.
let resolveModelScopedQuota = async () => ({});
try {
  ({ resolveModelScopedQuota } = require('./lib/model-scoped-quota.cjs'));
} catch { /* fail-open — model-scoped quota is a bonus segment, never a dependency */ }

// Sixth optional lib — the agent spawn-tree segment. Depends on t1k-maintainer's
// .claude/scripts/agent-tree-view.cjs (recommended, not required — CLAUDE.md)
// and telemetry-utils.cjs (absent from the t1k-statusline-full standalone
// install), both guarded internally. Missing either ⇒ renderAgentTreeLines()
// always returns []. See lib/statusline-agent-tree.cjs docblock.
let renderAgentTreeLines = () => [];
try {
  ({ renderAgentTreeLines } = require('./lib/statusline-agent-tree.cjs'));
} catch { /* fail-open — same posture as model-scoped-quota above */ }

const AUTOCOMPACT_BUFFER = 40000;
const GRAPHEME_SEGMENTER = (
  typeof Intl !== 'undefined' && typeof Intl.Segmenter === 'function'
)
  ? new Intl.Segmenter(undefined, { granularity: 'grapheme' })
  : null;

// ============================================================================
// UTILITIES
// ============================================================================

/**
 * Truncate path from the LEFT to show trailing directories
 * "/mnt/Work/1M/8. OneAI/theonekit-core" → "…/8. OneAI/theonekit-core"
 * Replaces home dir with ~ first, then truncates from left if still too long
 *
 * DUPLICATE ON PURPOSE — do not "fix" it by requiring lib/safe-paths.cjs.
 * `sanitizePath` also lives there (SSOT for lib consumers such as
 * lib/config-scrub.cjs), but this file is ALSO installed standalone to
 * `~/.claude/statusline.cjs` with only the four libs listed in
 * `skills/t1k-statusline-full/install.sh`. Requiring a fifth one crashes the
 * installed statusline with MODULE_NOT_FOUND until a CLI release ships it —
 * caught by `statusline-session-cache.test.cjs` and `validate-module-hook-deps`.
 * Widening the installed graph for a four-line helper is not worth that.
 */
function sanitizePath(p) {
  if (!p || typeof p !== 'string') return null;
  const homeDir = os.homedir();
  return p.startsWith(homeDir) ? '~' + p.slice(homeDir.length) : p;
}

function truncatePath(filePath, maxLen = 40) {
  const homeDir = os.homedir();
  let p = filePath.startsWith(homeDir) ? filePath.replace(homeDir, '~') : filePath;
  if (p.length <= maxLen) return p;
  // Split by separator and rebuild from the end
  const sep = p.includes('\\') ? '\\' : '/';
  const parts = p.split(sep);
  let result = parts[parts.length - 1];
  for (let i = parts.length - 2; i >= 0; i--) {
    const candidate = parts[i] + sep + result;
    if (candidate.length + 1 > maxLen) break; // +1 for the … prefix
    result = candidate;
  }
  return result === p ? p : '…' + sep + result;
}

/**
 * Get terminal width with fallback chain
 */
function getTerminalWidth() {
  if (process.stderr.columns) return process.stderr.columns;
  if (env.COLUMNS) {
    const parsed = parseInt(env.COLUMNS, 10);
    if (!isNaN(parsed) && parsed > 0) return parsed;
  }
  return 120;
}

/**
 * Calculate terminal-visible string length (handles ANSI, emoji, CJK)
 */
function visibleLength(str) {
  if (!str || typeof str !== 'string') return 0;
  const noAnsi = str.replace(/\x1b\[[0-9;]*m/g, '');
  const clusters = GRAPHEME_SEGMENTER
    ? Array.from(GRAPHEME_SEGMENTER.segment(noAnsi), s => s.segment)
    : Array.from(noAnsi);

  let len = 0;
  for (const cluster of clusters) {
    if (!cluster) continue;
    if (/^[\u0000-\u001f\u007f]+$/.test(cluster)) continue;
    if (/^\p{Mark}+$/u.test(cluster)) continue;

    const first = cluster.codePointAt(0);
    if (first === 0x200d || first === 0xfe0e || first === 0xfe0f) continue;

    if ((cluster.includes('\u200d') && /\p{Extended_Pictographic}/u.test(cluster)) ||
        /\p{Extended_Pictographic}/u.test(cluster)) {
      len += 2;
      continue;
    }

    if (first >= 0x1100 && (
      first <= 0x115f || first === 0x2329 || first === 0x232a ||
      (first >= 0x2e80 && first <= 0xa4cf && first !== 0x303f) ||
      (first >= 0xac00 && first <= 0xd7a3) ||
      (first >= 0xf900 && first <= 0xfaff) ||
      (first >= 0xfe10 && first <= 0xfe19) ||
      (first >= 0xfe30 && first <= 0xfe6f) ||
      (first >= 0xff00 && first <= 0xff60) ||
      (first >= 0xffe0 && first <= 0xffe6) ||
      (first >= 0x1f200 && first <= 0x1f251) ||
      (first >= 0x20000 && first <= 0x3fffd)
    )) {
      len += 2;
      continue;
    }

    len += 1;
  }
  return len;
}

/**
 * Format elapsed time
 */
function formatElapsed(startTime, endTime) {
  if (!startTime) return '0s';
  const start = startTime instanceof Date ? startTime.getTime() : new Date(startTime).getTime();
  if (isNaN(start)) return '0s';
  const end = endTime ? (endTime instanceof Date ? endTime.getTime() : new Date(endTime).getTime()) : Date.now();
  if (isNaN(end)) return '0s';
  const ms = end - start;
  if (ms < 0 || ms < 1000) return '<1s';
  if (ms < 60000) return `${Math.round(ms / 1000)}s`;
  const mins = Math.floor(ms / 60000);
  const secs = Math.round((ms % 60000) / 1000);
  return `${mins}m ${secs}s`;
}

/**
 * Read stdin asynchronously
 */
async function readStdin() {
  return new Promise((resolve, reject) => {
    const chunks = [];
    stdin.setEncoding('utf8');
    stdin.on('data', chunk => chunks.push(chunk));
    stdin.on('end', () => resolve(chunks.join('')));
    stdin.on('error', reject);
  });
}

// ============================================================================
// LINE RENDERERS
// ============================================================================

/**
 * Build usage time string with optional percentage (5-hour window)
 */
function buildUsageString(ctx) {
  if (!ctx.sessionText || ctx.sessionText === 'N/A') return null;
  let str = ctx.sessionText;
  if (ctx.usagePercent != null) str += ` (${Math.round(ctx.usagePercent)}%)`;
  return str;
}

/**
 * Build weekly usage string (7-day window)
 */
function buildWeeklyString(ctx) {
  if (ctx.weeklyPercent == null) return null;
  let str = `${Math.round(ctx.weeklyPercent)}% weekly`;
  if (ctx.weeklyText) str += ` · ${ctx.weeklyText}`;
  return str;
}

/**
 * Find the Fable weekly bucket in the model-scoped quota map.
 * Display names vary ("Fable", "Fable 5"), so match a case-insensitive `fable`
 * prefix — never an equality check, and never an enumerated model list.
 */
function findFableQuota(modelScoped) {
  if (!modelScoped || typeof modelScoped !== 'object') return null;
  for (const name of Object.keys(modelScoped)) {
    if (!name.toLowerCase().startsWith('fable')) continue;
    const quota = modelScoped[name];
    if (quota && typeof quota.percent === 'number') return quota;
  }
  return null;
}

/**
 * Build the model-scoped weekly quota segment (e.g. "Fable:34%").
 * percent arrives 0..100 already — do not rescale.
 */
function buildFableString(ctx) {
  const quota = findFableQuota(ctx.modelScoped);
  if (!quota) return null;
  const percent = Math.round(quota.percent);
  const text = `Fable:${percent}%`;
  if (percent >= 80) return red(text);
  if (percent >= 50) return yellow(text);
  return green(text);
}

/**
 * Render session lines with multi-level responsive wrapping
 */
function renderSessionLines(ctx) {
  const lines = [];
  const termWidth = getTerminalWidth();
  const threshold = Math.floor(termWidth * 0.85);

  const dirPart = `📁 ${yellow(ctx.currentDir)}`;

  let branchPart = '';
  if (ctx.gitBranch) {
    branchPart = `🌿 ${magenta(ctx.gitBranch)}`;
    const gitIndicators = [];
    if (ctx.gitUnstaged > 0) gitIndicators.push(`${ctx.gitUnstaged}`);
    if (ctx.gitStaged > 0) gitIndicators.push(`+${ctx.gitStaged}`);
    if (ctx.gitAhead > 0) gitIndicators.push(`${ctx.gitAhead}↑`);
    if (ctx.gitBehind > 0) gitIndicators.push(`${ctx.gitBehind}↓`);
    if (gitIndicators.length > 0) {
      branchPart += ` ${yellow(`(${gitIndicators.join(', ')})`)}`;
    }
  }

  let locationPart = branchPart ? `${dirPart}  ${branchPart}` : dirPart;

  // Build session part: 🤖 model  contextBar%  ⌛ time left (usage%)
  let sessionPart = `🤖 ${cyan(ctx.modelName)}`;
  if (ctx.contextPercent > 0) {
    const ctxColor = getContextColor(ctx.contextPercent);
    sessionPart += `  ${coloredBar(ctx.contextPercent, 12)} ${ctxColor}${ctx.contextPercent}%${RESET}`;
  }
  const usageStr = buildUsageString(ctx);
  if (usageStr) {
    sessionPart += `  ⌛ ${dim(usageStr)}`;
  }
  const weeklyStr = buildWeeklyString(ctx);
  if (weeklyStr) {
    sessionPart += `  📅 ${dim(weeklyStr)}`;
  }
  const fableStr = buildFableString(ctx);
  if (fableStr) {
    sessionPart += `  🟣 ${fableStr}`;
  }

  // Lines changed stats
  const statsItems = [];
  if (ctx.linesAdded > 0 || ctx.linesRemoved > 0) {
    statsItems.push(`📝 ${green(`+${ctx.linesAdded}`)} ${red(`-${ctx.linesRemoved}`)}`);
  }
  const statsPart = statsItems.join('  ');

  const locationLen = visibleLength(locationPart);
  const sessionLen = visibleLength(sessionPart);
  const statsLen = visibleLength(statsPart);

  const allOneLine = `${sessionPart}  ${locationPart}  ${statsPart}`;
  const sessionLocation = `${sessionPart}  ${locationPart}`;

  if (visibleLength(allOneLine) <= threshold && statsLen > 0) {
    lines.push(allOneLine);
  } else if (visibleLength(sessionLocation) <= threshold) {
    lines.push(sessionLocation);
    if (statsLen > 0) lines.push(statsPart);
  } else if (sessionLen <= threshold) {
    lines.push(sessionPart);
    lines.push(locationPart);
    if (statsLen > 0) lines.push(statsPart);
  } else {
    lines.push(sessionPart);
    lines.push(dirPart);
    if (branchPart) lines.push(branchPart);
    if (statsLen > 0) lines.push(statsPart);
  }

  return lines;
}

function safeGetTime(dateValue) {
  if (!dateValue) return 0;
  const time = new Date(dateValue).getTime();
  return isNaN(time) ? 0 : time;
}

/**
 * Render agents as compact chronological flow with duplicate collapsing
 */
function renderAgentsLines(transcript) {
  const { agents } = transcript;
  if (!agents || agents.length === 0) return [];

  const running = agents.filter(a => a.status === 'running');
  const completed = agents.filter(a => a.status === 'completed');
  const allAgents = [...running, ...completed];
  allAgents.sort((a, b) => safeGetTime(a.startTime) - safeGetTime(b.startTime));
  if (allAgents.length === 0) return [];

  // Collapse consecutive duplicate types
  const collapsed = [];
  for (const agent of allAgents) {
    const type = agent.type || 'agent';
    const last = collapsed[collapsed.length - 1];
    if (last && last.type === type && last.status === agent.status) {
      last.count++;
      last.agents.push(agent);
    } else {
      collapsed.push({ type, status: agent.status, count: 1, agents: [agent] });
    }
  }

  const toShow = collapsed.slice(-4);
  const flowParts = toShow.map(group => {
    const icon = group.status === 'running' ? yellow('●') : dim('○');
    const suffix = group.count > 1 ? ` ×${group.count}` : '';
    return `${icon} ${group.type}${suffix}`;
  });

  const lines = [];
  const completedCount = agents.filter(a => a.status === 'completed').length;
  const flowSuffix = completedCount > 2 ? ` ${dim(`(${completedCount} done)`)}` : '';
  lines.push(flowParts.join(' → ') + flowSuffix);

  const runningAgent = running[0];
  const lastCompleted = completed[completed.length - 1];
  const detailAgent = runningAgent || lastCompleted;
  if (detailAgent && detailAgent.description) {
    const desc = detailAgent.description.length > 50
      ? detailAgent.description.slice(0, 47) + '...'
      : detailAgent.description;
    const elapsed = formatElapsed(detailAgent.startTime, detailAgent.endTime);
    const icon = detailAgent.status === 'running' ? yellow('▸') : dim('▸');
    lines.push(`   ${icon} ${desc} ${dim(`(${elapsed})`)}`);
  }

  return lines;
}

/**
 * Render todos line
 */
function renderTodosLine(transcript) {
  const { todos } = transcript;
  if (!todos || todos.length === 0) return null;

  const inProgress = todos.find(t => t.status === 'in_progress');
  const completedCount = todos.filter(t => t.status === 'completed').length;
  const pendingCount = todos.filter(t => t.status === 'pending').length;
  const total = todos.length;

  if (!inProgress) {
    if (completedCount === total && total > 0) {
      return `${green('✓')} All ${total} todos complete`;
    }
    if (pendingCount > 0) {
      const nextPending = todos.find(t => t.status === 'pending');
      const nextTask = nextPending?.content || 'Next task';
      const display = nextTask.length > 40 ? nextTask.slice(0, 37) + '...' : nextTask;
      return `${dim('○')} Next: ${display} ${dim(`(${completedCount} done, ${pendingCount} pending)`)}`;
    }
    return null;
  }

  const displayText = inProgress.activeForm || inProgress.content;
  const display = displayText.length > 50 ? displayText.slice(0, 47) + '...' : displayText;
  return `${yellow('▸')} ${display} ${dim(`(${completedCount} done, ${pendingCount} pending)`)}`;
}

/**
 * Numeric semver compare. Returns negative if a<b, 0 if equal, positive if a>b.
 */
function compareSemver(a, b) {
  const norm = s => String(s).split('-')[0].split('.').map(n => parseInt(n, 10) || 0);
  const A = norm(a);
  const B = norm(b);
  const len = Math.max(A.length, B.length);
  for (let i = 0; i < len; i++) {
    const x = A[i] || 0;
    const y = B[i] || 0;
    if (x !== y) return x - y;
  }
  return 0;
}

/**
 * Read model-router installed version + freshness state.
 * Returns a single display string or null when model-router is not installed.
 */
function getModelRouterStatus() {
  const homeDir = process.env.HOME || os.homedir();

  // 1. Installed version from global manifest
  const manifestPath = path.join(homeDir, '.claude', 'modules', 'model-router', '.t1k-manifest.json');
  let installedVer = null;
  try {
    if (fs.existsSync(manifestPath)) {
      installedVer = JSON.parse(fs.readFileSync(manifestPath, 'utf8')).version;
    }
  } catch { /* fail-open */ }

  if (!installedVer) return null;

  // 2. Freshness cache written by mr-doctor-check.cjs (12h TTL)
  const cachePath = path.join(homeDir, '.model-router', 'freshness-cache.json');
  let latestVer = null;
  let cacheValid = false;
  try {
    if (fs.existsSync(cachePath)) {
      const cache = JSON.parse(fs.readFileSync(cachePath, 'utf8'));
      if (cache.latest_version && cache.valid_until) {
        latestVer = cache.latest_version;
        cacheValid = new Date(cache.valid_until).getTime() > Date.now();
      }
    }
  } catch { /* fail-open */ }

  const versionStr = `🌐 model-router v${installedVer}`;
  if (!cacheValid || !latestVer) {
    return `${versionStr} ${dim('(freshness unknown)')}`;
  }

  if (compareSemver(installedVer, latestVer) >= 0) {
    return `${versionStr} ${green('(latest)')}`;
  }

  return `${versionStr} ${yellow(`(update available: v${latestVer})`)}`;
}

/**
 * Main render function — full mode (multi-line)
 */
function renderFull(ctx) {
  const lines = [];
  lines.push(...renderSessionLines(ctx));
  const agentsLines = renderAgentsLines(ctx.transcript);
  lines.push(...agentsLines);
  const todosLine = renderTodosLine(ctx.transcript);
  if (todosLine) lines.push(todosLine);

  const mrStatus = getModelRouterStatus();
  if (mrStatus) lines.push(mrStatus);

  // Opt-in (features.statuslineAgentTree — see lib/statusline-agent-tree.cjs);
  // renders [] when disabled, unavailable, or on any internal fault. Placed
  // last (below model-router status, above Claude Code's own panel line) per
  // the requested layout.
  const treeLines = renderAgentTreeLines({
    sessionId: ctx.sessionId, rawDir: ctx.rawDir, transcriptPath: ctx.transcriptPath,
    termWidth: getTerminalWidth(),
  });
  lines.push(...treeLines);

  for (const line of lines) console.log(line);
}

/**
 * Minimal mode — single line with emojis
 */
function renderMinimal(ctx) {
  const parts = [`🤖 ${cyan(ctx.modelName)}`];
  if (ctx.contextPercent > 0) {
    const batteryIcon = ctx.contextPercent > 70 ? red('🔋') : '🔋';
    parts.push(`${batteryIcon} ${ctx.contextPercent}%`);
  }
  const usageStr = buildUsageString(ctx);
  if (usageStr) parts.push(`⌛ ${dim(usageStr)}`);
  const weeklyStr = buildWeeklyString(ctx);
  if (weeklyStr) parts.push(`📅 ${dim(weeklyStr)}`);
  const fableStr = buildFableString(ctx);
  if (fableStr) parts.push(`🟣 ${fableStr}`);
  if (ctx.gitBranch) parts.push(`🌿 ${magenta(ctx.gitBranch)}`);
  parts.push(`📁 ${yellow(ctx.currentDir)}`);
  console.log(parts.join('  '));
}

/**
 * Compact mode — 2 lines
 */
function renderCompact(ctx) {
  let line1 = `🤖 ${cyan(ctx.modelName)}`;
  if (ctx.contextPercent > 0) {
    const ctxColor = getContextColor(ctx.contextPercent);
    line1 += `  ${coloredBar(ctx.contextPercent, 12)} ${ctxColor}${ctx.contextPercent}%${RESET}`;
  }
  const usageStr = buildUsageString(ctx);
  if (usageStr) line1 += `  ⌛ ${dim(usageStr)}`;
  const weeklyStr = buildWeeklyString(ctx);
  if (weeklyStr) line1 += `  📅 ${dim(weeklyStr)}`;
  const fableStr = buildFableString(ctx);
  if (fableStr) line1 += `  🟣 ${fableStr}`;
  console.log(line1);

  let line2 = `📁 ${yellow(ctx.currentDir)}`;
  if (ctx.gitBranch) line2 += `  🌿 ${magenta(ctx.gitBranch)}`;
  console.log(line2);

  const mrStatus = getModelRouterStatus();
  if (mrStatus && !mrStatus.includes('(latest)')) {
    console.log(mrStatus);
  }
}

// ============================================================================
// MAIN
// ============================================================================

async function main() {
  try {
    const input = await readStdin();
    if (!input.trim()) {
      console.error('No input provided');
      process.exit(1); // gate:exit-1-allowed (statusline display failure; non-blocking by design)
    }

    const data = JSON.parse(input);

    // Directory — truncate from left to show trailing path
    const rawDir = data.workspace?.current_dir || data.cwd || process.cwd();
    const currentDir = truncatePath(rawDir);

    const modelName = data.model?.display_name || 'Claude';

    // Git info (cached, cross-platform)
    const gitInfo = getGitInfo(rawDir);
    const gitBranch = gitInfo?.branch || '';
    const gitUnstaged = gitInfo?.unstaged || 0;
    const gitStaged = gitInfo?.staged || 0;
    const gitAhead = gitInfo?.ahead || 0;
    const gitBehind = gitInfo?.behind || 0;

    // Context window
    const usage = data.context_window?.current_usage || {};
    const contextSize = data.context_window?.context_window_size || 0;
    let contextPercent = 0;
    let totalTokens = 0;

    if (contextSize > 0) {
      totalTokens = (usage.input_tokens ?? 0) +
                    (usage.cache_creation_input_tokens ?? 0) +
                    (usage.cache_read_input_tokens ?? 0);

      const preCalcPercent = data.context_window?.used_percentage;
      if (typeof preCalcPercent === 'number' && preCalcPercent >= 0) {
        contextPercent = Math.round(preCalcPercent);
      } else if (contextSize > AUTOCOMPACT_BUFFER) {
        contextPercent = Math.min(100, Math.round(((totalTokens + AUTOCOMPACT_BUFFER) / contextSize) * 100));
      }
    }

    // Model-scoped weekly quota (e.g. Fable). Free stdin path when present, throttled
    // API fallback otherwise. Always resolves — `{}` when unknown, never throws.
    const modelScoped = await resolveModelScopedQuota(data.rate_limits);

    // Write context data for hooks to read
    const sessionId = data.session_id;
    if (sessionId && contextSize > 0) {
      try {
        const tempDir = os.tmpdir();
        cleanupSessionCaches({ tempDir });
        const contextDataPath = path.join(tempDir, `t1k-context-${sessionId}.json`);
        // Cache Claude auth info per session (avoids spawning `claude auth status`
        // on every statusline tick). Refreshed once per session or when file is missing.
        let authInfo = null;
        const authCachePath = path.join(tempDir, `t1k-auth-${sessionId}.json`);
        try {
          if (fs.existsSync(authCachePath)) {
            authInfo = readSessionCacheJson(authCachePath);
          }
          if (authInfo === null) {
            // A cache that cannot be made private is never trusted or reused.
            try { fs.unlinkSync(authCachePath); } catch {}
            const { execFileSync } = require('child_process');
            const out = execFileSync('claude', ['auth', 'status'], {
              encoding: 'utf8', timeout: 3000, stdio: ['pipe', 'pipe', 'ignore'],
              windowsHide: true
            });
            authInfo = JSON.parse(out);
            writeSessionCacheJson(authCachePath, authInfo);
          }
        } catch { /* fail-open — auth info is best-effort */ }

        writeSessionCacheJson(contextDataPath, {
          percent: contextPercent,
          remaining: data.context_window?.remaining_percentage ?? (100 - contextPercent),
          tokens: totalTokens,
          size: contextSize,
          usage,
          // Model info is in statusline stdin but NOT in UserPromptSubmit stdin.
          // Persist here so prompt-telemetry.cjs can read it (see telemetry-utils → readContextSnapshot).
          modelId: data.model?.id || null,
          modelName: data.model?.display_name || null,
          // Rate limits (subscription plan quota tracking)
          rateLimits: {
            fiveHourPercent: data.rate_limits?.five_hour?.used_percentage ?? null,
            sevenDayPercent: data.rate_limits?.seven_day?.used_percentage ?? null,
            fiveHourResetsAt: data.rate_limits?.five_hour?.resets_at ?? null,
            sevenDayResetsAt: data.rate_limits?.seven_day?.resets_at ?? null,
            // Model-scoped weekly buckets keyed by display name — {} when unknown
            modelScoped,
          },
          // Productivity metrics
          linesAdded: data.cost?.total_lines_added || 0,
          linesRemoved: data.cost?.total_lines_removed || 0,
          // Cost & timing (from data.cost.*)
          estimatedCostUsd: typeof data.cost?.total_cost_usd === 'number' ? data.cost.total_cost_usd : null,
          totalDurationMs: typeof data.cost?.total_duration_ms === 'number' ? data.cost.total_duration_ms : null,
          totalApiDurationMs: typeof data.cost?.total_api_duration_ms === 'number' ? data.cost.total_api_duration_ms : null,
          // Session cumulative tokens (distinct from per-turn `usage` above)
          contextTotalInputTokens: typeof data.context_window?.total_input_tokens === 'number' ? data.context_window.total_input_tokens : null,
          contextTotalOutputTokens: typeof data.context_window?.total_output_tokens === 'number' ? data.context_window.total_output_tokens : null,
          // Workspace & worktree — paths sanitized (HOME → ~)
          workspaceProjectDir: sanitizePath(data.workspace?.project_dir),
          workspaceGitWorktree: data.workspace?.git_worktree || null,
          worktreePath: sanitizePath(data.worktree?.path),
          // Session/environment
          sessionName: data.session_name || null,
          claudeCodeVersion: data.version || null,
          outputStyle: data.output_style?.name || null,
          subAgentName: data.agent?.name || null,
          // Claude account (cached per session — users can switch between sessions)
          claudeEmail: authInfo?.email || null,
          claudeOrgId: authInfo?.orgId || null,
          subscriptionType: authInfo?.subscriptionType || null,
          timestamp: Date.now()
        });
      } catch {}
    }

    // Rate limits — prefer native stdin data (Claude Code v2.1.80+), fallback to cache
    let sessionText = '';
    let usagePercent = null;
    let weeklyText = '';
    let weeklyPercent = null;

    // Source 1: Native rate_limits from Claude Code stdin JSON (authoritative, real-time)
    const rateLimits = data.rate_limits;
    if (rateLimits) {
      // 5-hour window
      const fiveHour = rateLimits.five_hour;
      if (fiveHour) {
        usagePercent = fiveHour.used_percentage ?? null;
        const resetAt = fiveHour.resets_at;
        if (resetAt) {
          const remaining = (typeof resetAt === 'number' ? resetAt : Math.floor(new Date(resetAt).getTime() / 1000)) - Math.floor(Date.now() / 1000);
          if (remaining > 0) {
            const rh = Math.floor(remaining / 3600);
            const rm = Math.floor((remaining % 3600) / 60);
            sessionText = `${rh}h ${rm}m left`;
          }
        }
      }
      // 7-day (weekly) window
      const sevenDay = rateLimits.seven_day;
      if (sevenDay) {
        weeklyPercent = sevenDay.used_percentage ?? null;
        const resetAt = sevenDay.resets_at;
        if (resetAt) {
          const remaining = (typeof resetAt === 'number' ? resetAt : Math.floor(new Date(resetAt).getTime() / 1000)) - Math.floor(Date.now() / 1000);
          if (remaining > 0) {
            const rd = Math.floor(remaining / 86400);
            const rh = Math.floor((remaining % 86400) / 3600);
            weeklyText = rd > 0 ? `${rd}d ${rh}h left` : `${rh}h left`;
          }
        }
      }
    }

    // Source 2: Fallback to cache file (CK compatibility)
    if (!usagePercent && !sessionText) {
      try {
        const cachePaths = [
          env.T1K_USAGE_CACHE_PATH,
          env.CK_USAGE_CACHE_PATH,
          path.join(os.tmpdir(), 'ck-usage-limits-cache.json')
        ].filter(Boolean);

        for (const cachePath of cachePaths) {
          if (!fs.existsSync(cachePath)) continue;
          const cache = JSON.parse(fs.readFileSync(cachePath, 'utf8'));
          if (cache.status === 'unavailable') { sessionText = 'N/A'; break; }

          const fiveHour = cache.data?.five_hour;
          usagePercent = fiveHour?.utilization ?? null;
          const resetAt = fiveHour?.resets_at;
          if (resetAt) {
            const remaining = Math.floor(new Date(resetAt).getTime() / 1000) - Math.floor(Date.now() / 1000);
            if (remaining > 0) {
              const rh = Math.floor(remaining / 3600);
              const rm = Math.floor((remaining % 3600) / 60);
              sessionText = `${rh}h ${rm}m left`;
            }
          }
          break;
        }
      } catch {}
    }

    // Transcript — parse for agents/todos
    const transcriptPath = data.transcript_path;
    const transcript = transcriptPath ? await parseTranscript(transcriptPath) : { tools: [], agents: [], todos: [], sessionStart: null };

    // Lines changed
    const linesAdded = data.cost?.total_lines_added || 0;
    const linesRemoved = data.cost?.total_lines_removed || 0;

    // Build render context
    const ctx = {
      modelName, currentDir, gitBranch, gitUnstaged, gitStaged, gitAhead, gitBehind,
      contextPercent, sessionText, usagePercent,
      weeklyText, weeklyPercent, modelScoped,
      linesAdded, linesRemoved, transcript,
      sessionId, rawDir, transcriptPath
    };

    // Statusline mode: check T1K config or env var
    const mode = env.T1K_STATUSLINE_MODE || 'full';

    switch (mode) {
      case 'none':
        console.log('');
        break;
      case 'minimal':
        renderMinimal(ctx);
        break;
      case 'compact':
        renderCompact(ctx);
        break;
      case 'full':
      default:
        renderFull(ctx);
        break;
    }

  } catch (err) {
    // Fallback: output minimal single line on any error
    console.log('📁 ' + (process.cwd() || 'unknown'));
  }
}

main().catch(() => {
  console.log('📁 error');
  process.exit(1); // gate:exit-1-allowed (statusline display failure; non-blocking by design)
});

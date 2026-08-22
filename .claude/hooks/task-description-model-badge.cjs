#!/usr/bin/env node
// t1k-origin: kit=theonekit-core | repo=The1Studio/theonekit-core | module=null | protected=true
/**
 * task-description-model-badge.cjs — PreToolUse:Task hook
 *
 * Appends the agent's resolved model to the Task description so it surfaces
 * in the Claude Code backgrounded-agent manage pane. Instead of:
 *
 *   t1k-git-manager(Process lesson queue)
 *
 * the pane shows:
 *
 *   t1k-git-manager(Process lesson queue [haiku])
 *
 * or, when transparent routing is active:
 *
 *   t1k-git-manager(Process lesson queue [kimi/kimi-k2.5])
 *
 * Algorithm (per task spec):
 *   1. Validate PreToolUse for Task tool — else passthrough (exit 0).
 *   2. Extract subagent_type + description.
 *   3. Skip cases: already-badged, no subagent_type, MR_SPAWNED=1.
 *   4. Resolve agent frontmatter `model:` via priority chain
 *      (project .claude/agents/ → ~/.claude/agents/).
 *   5. Apply transparent-routing override from t1k-config-mr.json.
 *   6. Rewrite description: `${description} [${resolvedModel}]`.
 *   7. Emit `{"tool_input": {...modified...}}` on stdout; exit 0.
 *
 * Fail-open: any internal exception → exit 0, original input unchanged.
 *
 * Kill switch: T1K_TASK_DESCRIPTION_MODEL_BADGE_DISABLED=1 env var.
 *
 * Composes with mr-task-interceptor.cjs (transparent-routing consumers):
 *   - This hook runs FIRST (listed before mr-task-interceptor in settings.json).
 *   - PASSTHROUGH cases (Opus stays Opus, excluded agent, mode≠transparent,
 *     unknown agent): the interceptor ALLOWS the Task, so the badged description
 *     reaches the real spawn and appears in the manage pane. This hook owns the
 *     badge for these cases.
 *   - ROUTED cases (the common path): the interceptor uses `permissionDecision:
 *     deny` as its PRIMARY delivery mechanism — it denies the original Task and
 *     returns the cheap-model output via `permissionDecisionReason`. The denied
 *     Task (and this hook's badged description) is therefore DROPPED. For routed
 *     spawns the model is surfaced by the interceptor's own banner (model-router
 *     ships the `agent[model]` banner — #379 bug #5 option (a)), NOT by this hook.
 *     See The1Studio/theonekit-core#379 bug #5 for the full architectural note.
 *   - Registration: this hook MUST be wired under BOTH the `Task` and `Agent`
 *     PreToolUse matchers in settings.json — current Claude Code emits `Agent`
 *     (see #379 bug #1 / bug #4).
 */
'use strict';

const fs = require('fs');
const path = require('path');
const os = require('os');

// ── helpers ────────────────────────────────────────────────────────────────

function passthrough() { process.exit(0); }

// Tool names that spawn a sub-agent. Current Claude Code emits 'Agent'; older
// builds emit 'Task'. Mirrors SUBAGENT_TOOL_NAMES in mr-task-interceptor.cjs.
// (Bug #1 in The1Studio/theonekit-core#379.)
const SUBAGENT_TOOL_NAMES = new Set(['Task', 'Agent']);

// Shorthand ↔ canonical model-id aliases. Agent frontmatter usually declares the
// shorthand (`model: sonnet`) while t1k-config-mr.json keys modelMapping by the
// canonical id (`claude-sonnet-4-6`). Try every alias when looking up the mapping
// so the badge resolves the routed model instead of falling back to the literal.
// (Bug #2 in #379.)
const SHORT_TO_FULL = {
  opus: 'claude-opus-4-7',
  sonnet: 'claude-sonnet-4-6',
  haiku: 'claude-haiku-4-5-20251001',
};
const FULL_TO_SHORT = Object.fromEntries(
  Object.entries(SHORT_TO_FULL).map(([short, full]) => [full, short]),
);

// Models the model-router interceptor passes through unconditionally (Opus stays
// Opus; `inherit` is never swapped). Mirrors KIT_PASSTHROUGH_MODELS in
// mr-task-interceptor.cjs. When the frontmatter model is one of these the
// interceptor never routes, so the badge must NOT pretend a swap happened.
// (Bug #5 in #379 — don't badge a routed model on a passthrough case.)
const KIT_PASSTHROUGH_MODELS = new Set([
  'opus',
  'claude-opus-4-7',
  'claude-opus-4-7[1m]',
]);

// Tier ranking + quality-driven caps — mirrors mr-task-interceptor.cjs so the
// badge picks the SAME model the interceptor's rule-based selector would.
// (Bug #3 in #379 — capability hints were previously ignored by the badge.)
const TIER_RANK = { budget: 0, standard: 1, premium: 2 };
const QUALITY_DRIVEN = new Set(['reasoning', 'long-context']);

// Reasoning keyword set — byte-identical to mr-task-interceptor.cjs's KEYWORDS.
const REASONING_KEYWORDS = /\b(audit|security|architecture|design\s+(decision|review)|threat\s+model|deep\s+review|root\s+cause|exploit|vulnerability)\b/i;

function readJsonFile(p) {
  try {
    if (!fs.existsSync(p)) return null;
    return JSON.parse(fs.readFileSync(p, 'utf8'));
  } catch { return null; }
}

/**
 * Read providers-config.json (project first, then global). Same resolution
 * order as mr-task-interceptor.cjs::readProvidersConfig. Returns null when
 * absent — in which case the rule-based selector has nothing to pick from and
 * the badge falls back to modelMapping (matching interceptor behaviour exactly).
 */
function readProvidersConfig(projectRoot) {
  return (
    readJsonFile(path.join(projectRoot, '.claude', 'providers-config.json')) ||
    readJsonFile(path.join(process.env.HOME || os.homedir(), '.claude', 'providers-config.json'))
  );
}

/**
 * Detect required capabilities from the prompt + frontmatter.
 * Byte-faithful port of detectRequiredCapabilities() in mr-task-interceptor.cjs
 * so the badge's prediction matches the interceptor's actual route. (Bug #3.)
 *
 * @param {*} promptValue  string OR content-block array (vision)
 * @param {Object} fm      agent frontmatter
 * @returns {string[]}     required capability tags
 */
function detectRequiredCapabilities(promptValue, fm) {
  const caps = new Set();

  // 1. Image content blocks → vision.
  if (Array.isArray(promptValue)) {
    if (promptValue.some(b => b && (b.type === 'image' || b.type === 'input_image'))) {
      caps.add('vision');
    }
  }

  const promptText = typeof promptValue === 'string'
    ? promptValue
    : JSON.stringify(promptValue || '');

  // 2. Long-context: >50K chars.
  if (promptText.length > 50000) caps.add('long-context');

  // 3. Reasoning keywords — leading 2K chars only (matches interceptor).
  if (REASONING_KEYWORDS.test(promptText.slice(0, 2000))) caps.add('reasoning');

  // 4. Frontmatter mrHints.requires override.
  if (fm && fm.mrHints) {
    try {
      const hints = typeof fm.mrHints === 'string' ? JSON.parse(fm.mrHints) : fm.mrHints;
      if (Array.isArray(hints.requires)) {
        hints.requires.forEach(c => typeof c === 'string' && caps.add(c));
      }
    } catch { /* ignore malformed hints */ }
  }

  return Array.from(caps);
}

/** capabilityPipes lookup — mirrors pipeForCaps() in the interceptor. */
function pipeForCaps(requiredCaps, providersCfg) {
  const pipes = providersCfg && providersCfg.capabilityPipes;
  if (!pipes) return null;
  for (const cap of requiredCaps) {
    if (Array.isArray(pipes[cap]) && pipes[cap].length > 0) return pipes[cap];
  }
  return null;
}

/**
 * Pick the best candidate model for the required capabilities.
 * Byte-faithful port of pickFromCandidates() in mr-task-interceptor.cjs.
 * Returns { provider, model } or null. (Bug #3.)
 */
function pickFromCandidates(requiredCaps, providersCfg) {
  if (!providersCfg || !providersCfg.providers) return null;
  const candidates = [];
  for (const [pname, p] of Object.entries(providersCfg.providers)) {
    if (p.enabled !== true) continue;
    for (const [mname, m] of Object.entries(p.models || {})) {
      if (m.enabled !== true) continue;
      const caps = Array.isArray(m.capabilities) ? m.capabilities : [];
      if (requiredCaps.every(r => caps.includes(r))) {
        candidates.push({
          provider: pname,
          model: mname,
          tier: m.tier || 'standard',
          tier_rank: TIER_RANK[m.tier || 'standard'] ?? 1,
          context_window: typeof m.context_window === 'number' ? m.context_window : 0,
        });
      }
    }
  }
  if (candidates.length === 0) return null;

  const wantsLongContext = requiredCaps.includes('long-context');
  const wantsQuality = requiredCaps.some(c => QUALITY_DRIVEN.has(c));
  const pipe = pipeForCaps(requiredCaps, providersCfg);

  candidates.sort((a, b) => {
    if (pipe) {
      const ra = pipe.indexOf(a.model); const rb = pipe.indexOf(b.model);
      const na = ra === -1 ? Infinity : ra; const nb = rb === -1 ? Infinity : rb;
      if (na !== nb) return na - nb;
    }
    if (wantsLongContext) {
      if (a.context_window !== b.context_window) return b.context_window - a.context_window;
      return b.tier_rank - a.tier_rank;
    }
    if (wantsQuality) {
      return b.tier_rank - a.tier_rank;
    }
    return a.tier_rank - b.tier_rank;
  });
  return candidates[0];
}

/**
 * Parse YAML frontmatter from a markdown file.
 * Borrows the same lightweight approach as mr-task-interceptor.cjs:
 * match the first ---…--- block, then parse key: value lines.
 * Does NOT use a full YAML parser — intentional per task constraints.
 *
 * @param {string} filePath
 * @returns {Object} flat map of frontmatter key→value (all strings)
 */
function readFrontmatter(filePath) {
  let text;
  try { text = fs.readFileSync(filePath, 'utf8'); } catch { return {}; }
  // Normalize CRLF -> LF before parsing. A committed .md checked out with
  // Windows line endings (git core.autocrlf) leaves a trailing \r on every
  // frontmatter line; JS regex `.` excludes line-terminator chars (\r
  // included), so the per-line `key: value` match below silently fails and
  // EVERY frontmatter field is dropped — caught on Windows CI via
  // lib/statusline-agent-model.cjs's resolvePinnedTier() test, which is the
  // first caller to exercise this against a real committed agent file there.
  text = text.replace(/\r\n/g, '\n');
  const m = text.match(/^---\s*\n([\s\S]*?)\n---\s*\n/);
  if (!m) return {};
  const fm = {};
  for (const line of m[1].split('\n')) {
    const kv = line.match(/^([A-Za-z_][\w-]*):\s*(.*)$/);
    if (!kv) continue;
    let v = kv[2].trim().replace(/^["'](.*)["']$/, '$1');
    fm[kv[1]] = v;
  }
  return fm;
}

/**
 * Find the agent's .md file using the priority chain:
 *   1. <projectRoot>/.claude/agents/<name>.md
 *   2. ~/.claude/agents/<name>.md
 *
 * @param {string} agentName — basename without .md, e.g. "t1k-git-manager"
 * @param {string} projectRoot
 * @returns {string|null} absolute path or null if not found
 */
function findAgentFile(agentName, projectRoot) {
  const dirs = [
    path.join(projectRoot, '.claude', 'agents'),
    path.join(process.env.HOME || os.homedir(), '.claude', 'agents'),
  ];
  for (const dir of dirs) {
    const p = path.join(dir, `${agentName}.md`);
    try { fs.accessSync(p, fs.constants.R_OK); return p; } catch { /* try next */ }
  }
  return null;
}

/**
 * Resolve the effective model for `agentName` after transparent-routing override.
 *
 * Selection precedence — byte-for-byte the same as mr-task-interceptor.cjs so the
 * badge never lies about which model the Task will actually run on:
 *   a. Read agent frontmatter → `model:` field (or "inherit" if missing).
 *   b. If MR off / not transparent / excluded / Opus-or-inherit passthrough →
 *      return the frontmatter label (no swap happens).
 *   c. Rule-based selector: detect required capabilities (vision / long-context /
 *      reasoning / mrHints) and pick the best candidate from providers-config.json.
 *      This OVERRIDES modelMapping, exactly as the interceptor does. (Bug #3.)
 *   d. Fallback: static modelMapping lookup with shorthand↔canonical aliases.
 *      (Bug #2.)
 *   e. Else return the frontmatter label.
 *
 * @param {string} agentName
 * @param {string} projectRoot
 * @param {*} prompt          the Task prompt (string or content-block array)
 * @returns {string} e.g. "haiku", "kimi/kimi-k2.6", "opencode-go/glm-5.1", "?", "inherit"
 */
function resolveModel(agentName, projectRoot, prompt) {
  // Step 1: agent file + frontmatter
  const agentFile = findAgentFile(agentName, projectRoot);
  if (!agentFile) return '?';

  const fm = readFrontmatter(agentFile);
  const frontmatterModel = fm.model && fm.model.trim() ? fm.model.trim() : 'inherit';

  // Step 2: transparent routing config
  const mrCfg = (
    readJsonFile(path.join(projectRoot, '.claude', 't1k-config-mr.json')) ||
    readJsonFile(path.join(process.env.HOME || os.homedir(), '.claude', 't1k-config-mr.json'))
  );

  const mr = mrCfg && mrCfg.modelRouter;
  if (!mr || mr.enabled !== true || mr.mode !== 'transparent') {
    return frontmatterModel;
  }

  // Step 2b: Opus / inherit passthrough — the interceptor never routes these,
  // so the badge must show the frontmatter model, not a routed one. (Bug #5.)
  if (KIT_PASSTHROUGH_MODELS.has(frontmatterModel)) {
    return frontmatterModel;
  }

  // Step 3: excluded agents — no override
  if (Array.isArray(mr.excludeAgents) && mr.excludeAgents.includes(agentName)) {
    return frontmatterModel;
  }

  // Step 4: rule-based selector OVERRIDES modelMapping when capability hints fire
  // (reasoning keywords, >50K-char prompt, vision, or frontmatter mrHints). This
  // is what the interceptor actually routes to — without it the badge would show
  // the modelMapping pick while the real route went to a premium reasoning model.
  // (Bug #3 in #379.)
  const requiredCaps = detectRequiredCapabilities(prompt, fm);
  const providersCfg = readProvidersConfig(projectRoot);
  const ruleBased = pickFromCandidates(requiredCaps, providersCfg);
  if (ruleBased && ruleBased.model) {
    return ruleBased.provider ? `${ruleBased.provider}/${ruleBased.model}` : ruleBased.model;
  }

  // Step 5: model mapping lookup — try the raw frontmatter value plus its
  // shorthand↔canonical aliases so `model: sonnet` matches a `claude-sonnet-4-6`
  // mapping key (and vice versa). (Bug #2 in #379.)
  const lookupKeys = [frontmatterModel, SHORT_TO_FULL[frontmatterModel], FULL_TO_SHORT[frontmatterModel]]
    .filter(Boolean);
  const modelMapping = mr.modelMapping || {};
  for (const key of lookupKeys) {
    const mapping = modelMapping[key];
    if (mapping && mapping.model) {
      // Include provider prefix so the badge distinguishes kimi/kimi-k2.5 from
      // a same-named model on a different provider. Keep it concise.
      return mapping.provider ? `${mapping.provider}/${mapping.model}` : mapping.model;
    }
  }

  return frontmatterModel;
}

// ── main ───────────────────────────────────────────────────────────────────

function main() {
  // Kill switch
  if (process.env.T1K_TASK_DESCRIPTION_MODEL_BADGE_DISABLED === '1') {
    passthrough();
  }

  // Recursion guard: don't badge inside an already-delegated session
  if (process.env.MR_SPAWNED === '1') {
    passthrough();
  }

  // Read + validate stdin
  let hookData;
  try {
    const raw = fs.readFileSync(0, 'utf8').trim();
    if (!raw) passthrough();
    hookData = JSON.parse(raw);
  } catch {
    // Malformed JSON → fail-open, don't block
    passthrough();
  }

  if (!hookData || !SUBAGENT_TOOL_NAMES.has(hookData.tool_name)) passthrough();

  const ti = hookData.tool_input || {};
  const agentName = ti.subagent_type;
  const description = typeof ti.description === 'string' ? ti.description : '';

  // Skip: no subagent_type
  if (!agentName) passthrough();

  // Security: reject path-traversal attempts in agent name
  if (!/^[A-Za-z0-9._-]+$/.test(agentName) || agentName.includes('..')) passthrough();

  // Skip: description already ends with [...] — already badged (re-spawn case)
  // Match: ends with `[something]` optionally followed by whitespace
  if (/\[[^\]]+\]\s*$/.test(description)) passthrough();

  // Resolve project root using the same logic as mr-task-interceptor
  const projectRoot = hookData.cwd || process.env.CLAUDE_PROJECT_DIR || process.cwd();

  // The interceptor routes on the prompt (falls back to description). Mirror that
  // so the badge's capability detection sees the same text the interceptor does.
  const prompt = ti.prompt || description;

  // Resolve the effective model
  const resolvedModel = resolveModel(agentName, projectRoot, prompt);

  // Build the modified tool_input
  const modifiedInput = Object.assign({}, ti, {
    description: `${description} [${resolvedModel}]`,
  });

  // Emit modified tool_input per Claude Code PreToolUse protocol
  process.stdout.write(JSON.stringify({ tool_input: modifiedInput }));
  process.exit(0);
}

if (require.main === module) {
  try {
    main();
  } catch (err) {
    // Fail-open: any uncaught exception must never block the Task spawn
    try { process.stderr.write(`[t1k:task-description-model-badge] error: ${err && err.message || err}\n`); } catch {}
    process.exit(0);
  }
}

// Exported for reuse by lib/statusline-agent-model.cjs (the statusline's own
// pinned-tier fallback needs the SAME frontmatter read this hook already does —
// `rules/code-conventions.md` § No Duplicated Logic). `main()` stays guarded
// above so requiring this file as a library never touches stdin/exit.
module.exports = { readFrontmatter, findAgentFile, resolveModel };

#!/usr/bin/env node
// t1k-origin: kit=theonekit-model-router | repo=The1Studio/theonekit-model-router | module=null | protected=false
//
// mr-task-interceptor.cjs — PreToolUse hook on the Task tool.
//
// Implements The1Studio/theonekit-model-router#42 + #45 (Phase 1 + 2):
// decouple agent identity from model choice, then pick the model that best
// fits the task using a rule-based selector over capability tags.
//
// Flow:
//   1. Find the resolved agent's .md file (priority chain: project → user).
//   2. Parse frontmatter for `model:` and optional `mrHints.requires`.
//   3. Detect required capabilities from prompt + hints:
//        - prompt > 50K chars                                    → long-context
//        - prompt contains image content blocks                  → vision
//        - prompt matches reasoning keywords (audit/security/…)  → reasoning
//        - agent mrHints.requires array merges in
//   4. Filter providers-config.json candidates: enabled, all required caps.
//   5. Sort by tier (budget < standard < premium) — cheapest wins.
//   6. If no candidates fit → fall back to v2 static modelRouter.modelMapping.
//   7. If matched AND agent not in excludeAgents → run mr-delegate.sh, deny
//      the original Task, return cheap delegation's output via systemMessage.
//
// Fail-open: ANY internal exception → exit 0 (Task proceeds). A buggy hook
// must never block legitimate work. mr-delegate.sh owns safety; this hook
// is just the dispatcher.

'use strict';

const fs = require('fs');
const path = require('path');
const os = require('os');
const { spawnSync } = require('child_process');

// ─── Provider-budget library (hot path — no fork) ───────────────────────
// Shared SSOT for daily per-provider budget/quota tracking. The interceptor
// reads usage directly from the JSONL file; bash callers use the CLI wrapper.
let providerUsageLib;
try {
  providerUsageLib = require(path.join(__dirname, '..', 'scripts', 'provider-usage-lib.cjs'));
} catch { providerUsageLib = null; }

// ─── Lock-serialized JSONL append ───────────────────────────────────────────
// debug.jsonl has a second independent writer (mr-inline-tracker.cjs); see
// mr-jsonl-append.cjs for why an unlocked fs.appendFileSync isn't sufficient.
// Fail-open: if the module can't load, fall back to a plain unlocked append
// rather than dropping the debug line.
let jsonlAppend;
try {
  jsonlAppend = require(path.join(__dirname, '..', 'scripts', 'mr-jsonl-append.cjs'));
} catch { jsonlAppend = null; }

// ─── Data-classification gate (#158 P0) ─────────────────────────────────────
// Classifies the prompt for secrets/credentials/PII BEFORE routing so sensitive
// content is kept on Anthropic native instead of shipped to a third-party
// provider in plaintext. Fail-open: if the module can't load, the gate is
// skipped (best-effort) and delegation is never blocked.
let dataClassifier;
try {
  dataClassifier = require(path.join(__dirname, '..', 'scripts', 'mr-data-classifier.cjs'));
} catch { dataClassifier = null; }

// ─── Per-spawn model override (#153) ────────────────────────────────────────
// Resolves an explicit per-call model (Task `tool_input.model` or an `mr-model:`
// prompt directive) to a {provider, model}. Applied AFTER the opus/write-agent
// passthrough floors, so it only redirects agents that were already routable —
// it never pierces the kit opus floor. Fail-open: null module → feature off.
let modelOverride;
try {
  modelOverride = require(path.join(__dirname, '..', 'scripts', 'mr-model-override.cjs'));
} catch { modelOverride = null; }

// ─── Spawn attribution (#277) ───────────────────────────────────────────
// WHO spawned the agent each decision is about. Without it a decision record
// names only the child, so "does a floored premium agent then spawn cheap
// routable children?" — the whole basis of the delegation-cascade question —
// cannot be answered from telemetry at all.
//
// Observability only: it never influences a routing decision. Fail-open twice
// over — a require failure leaves the literal below in place, and a throw at
// resolve time is caught at the call site — because this sits on the hot path
// of every Task spawn and must never cost the user a tool call.
let spawnAttributionLib;
try {
  spawnAttributionLib = require(path.join(__dirname, '..', 'scripts', 'mr-spawn-attribution.cjs'));
} catch { spawnAttributionLib = null; }

// Explicitly-unknown, never absent: a consumer must be able to tell "attribution
// failed" from "this line predates the feature". Kept in step with
// `UNATTRIBUTED` in mr-spawn-attribution.cjs, which supersedes it when loadable.
let spawnAttribution = (spawnAttributionLib && spawnAttributionLib.UNATTRIBUTED)
  ? { ...spawnAttributionLib.UNATTRIBUTED }
  : { parentAgent: 'unknown', parentId: 'unknown', parentDepth: null, depthSource: 'unavailable', session: 'unknown' };

// ─── Debug log ──────────────────────────────────────────────────────────
// Every Task spawn this hook sees writes one JSONL line to ~/.model-router/
// debug.jsonl. Always on (low overhead — ~200 bytes per Task). Disable with
// MR_DEBUG_DISABLE=1. Read with: bash .claude/scripts/mr-tail-debug.sh
const DEBUG_LOG = path.join(os.homedir(), '.model-router', 'debug.jsonl');

function logDebug(entry) {
  if (process.env.MR_DEBUG_DISABLE === '1') return;
  try {
    const line = JSON.stringify({
      ts: new Date().toISOString(),
      ...entry,
      // MR_TEST_FIXTURE stamps every row a test harness writes so routing KPIs
      // computed off debug.jsonl can exclude them instead of measuring the
      // test suite. See tests/test-bug-unknown-subagent-type.sh, whose
      // `no-such-agent-xyz` fixture alone was 64% of current-era
      // `pass-unknown-agent` rows and 21% of ALL rows in the file.
      ...(process.env.MR_TEST_FIXTURE ? { testFixture: process.env.MR_TEST_FIXTURE } : {}),
      // Last, so a caller's `entry` can never shadow the attribution a
      // dashboard joins on.
      ...spawnAttribution,
    });
    if (jsonlAppend && typeof jsonlAppend.appendJsonlLine === 'function') {
      jsonlAppend.appendJsonlLine(DEBUG_LOG, line);
    } else {
      // Fallback only if the shared module failed to load — best-effort
      // unlocked append rather than dropping the line entirely.
      fs.mkdirSync(path.dirname(DEBUG_LOG), { recursive: true });
      fs.appendFileSync(DEBUG_LOG, line + '\n', { encoding: 'utf8', mode: 0o600 });
      if (process.platform !== 'win32') fs.chmodSync(DEBUG_LOG, 0o600);
    }
  } catch { /* fail-open: a broken log MUST never break delegation */ }
}

// Shared telemetry helpers (SSOT) — user/host/project/ghUser resolution + host
// hashing, identical to what the tool-use, inline-tool, and parent-tool-result
// builders use. Fail-open: if the module can't load, delegation telemetry is
// skipped (best-effort) and the delegation itself is never blocked.
let telemetryHelpers;
try {
  telemetryHelpers = require(path.join(__dirname, '..', 'scripts', 'mr-telemetry-helpers.cjs'));
} catch { telemetryHelpers = null; }

// Failover budget constants (SSOT) — see scripts/mr-defaults.cjs. Fail-open for
// the same reason as every other sibling require: a hook that throws on a
// missing script blocks the user's Task instead of routing it. The last-resort
// literals at the use site carry `mr-ssot:` markers and are held in step with
// this module by scripts/mr-validate-timeout-ssot.cjs.
let mrDefaults;
try {
  mrDefaults = require(path.join(__dirname, '..', 'scripts', 'mr-defaults.cjs'));
} catch { mrDefaults = null; }

// ─── Delegation telemetry ───────────────────────────────────────────────────
// Emits model-router:delegation events for BOTH success and failure so D1
// has a complete picture of delegation outcomes. Previously only failures
// were emitted (spawn errors/timeouts) and successes relied on the delegated
// session's mr-telemetry.cjs, which under-reported because it only fires
// PostToolUse + Stop inside the child. This meant D1 had ~10% of actual
// delegation volume and success rates were unreliable.
//
// User request: include machine + user identification for operational debugging.

function readMrVersion() {
  const home = os.homedir();
  const proj = process.env.CLAUDE_PROJECT_DIR || process.cwd();
  for (const candidate of [
    path.join(proj, '.claude', 'modules', 'model-router', 'module.json'),
    path.join(home, '.claude', 'modules', 'model-router', 'module.json'),
    path.join(home, '.claude', 'modules', 'model-router', '.t1k-manifest.json'),
  ]) {
    try {
      const j = JSON.parse(fs.readFileSync(candidate, 'utf8'));
      if (j && typeof j.version === 'string') return j.version;
    } catch { /* try next */ }
  }
  return 'unknown';
}

function emitDelegationEvent(agentName, pick, modelKey, exitCode, errorType, extra = {}) {
  try {
    const emit = path.join(__dirname, 'telemetry-emit.cjs');
    if (!fs.existsSync(emit) || !telemetryHelpers) return;
    const ctx = telemetryHelpers.resolveUserContext();
    const hostHashValue = telemetryHelpers.hostHash(ctx.hostnameRaw);
    const payload = {
      type: 'model-router:delegation',
      kit: 'theonekit-model-router',
      mrVersion: readMrVersion(),
      role: agentName,
      profile: pick && pick.provider,
      model: pick && pick.model,
      requestModel: modelKey,
      exit: exitCode,
      errorType: errorType || undefined,
      ts: new Date().toISOString(),
      hostname: hostHashValue,
      hostnameRaw: ctx.hostnameRaw,
      username: ctx.username,
      projectName: ctx.projectName,
      ghUser: ctx.ghUser,
      platform: os.platform(),
      arch: os.arch(),
      ...extra,
    };
    spawnSync('node', [emit], {
      input: JSON.stringify(payload),
      timeout: 15000,
      stdio: ['pipe', 'ignore', 'ignore'],
      windowsHide: true,
    });
  } catch { /* fail-open — telemetry must never break delegation */ }
}

// Safety net for spawn-level failures ONLY (mr-delegate.sh never ran, so it
// could not emit its own outcome). Completion-path outcomes — success, non-zero
// exit, and all-providers-failed (exit 42) — are owned by the script's
// _emit_delegation_outcome, which records a real delegation_id + post-failover
// model. Re-emitting those here would double-count; see the dispatch block below.
function emitDelegationFailure(agentName, pick, modelKey, exitCode, errorType) {
  emitDelegationEvent(agentName, pick, modelKey, exitCode, errorType);
}

// ─── Passthrough (route-declined) telemetry ─────────────────────────────────
// A routable subagent spawn was intercepted but NOT routed — captures WHY the
// router declined (secret blocked, provider not allowlisted, failover exhausted,
// spawn failure, config disabled, ...). Emitted as model-router:passthrough so
// analytics can see the router's decisions, not just its successful routes.
// Identity/agent/model come from `extra` (the substantive call sites already
// pass { agent, modelKey }), never from module-level vars — passthrough() runs
// before those consts initialize (TDZ), and the noise guards below are excluded.
// Fire-and-forget + fail-open: telemetry must never delay or break a passthrough.
function emitPassthroughEvent(reason, extra = {}) {
  try {
    const emit = path.join(__dirname, 'telemetry-emit.cjs');
    if (!fs.existsSync(emit) || !telemetryHelpers) return;
    const ctx = telemetryHelpers.resolveUserContext();
    const payload = {
      type: 'model-router:passthrough',
      kit: 'theonekit-model-router',
      mrVersion: readMrVersion(),
      scenario: reason,                       // WHY it declined (e.g. data-class-blocked)
      role: extra.agent || undefined,         // the subagent that would have been routed
      requestModel: extra.modelKey || undefined,
      errorType: extra.errorType || undefined,
      // Already computed by stderrTail() at the non-provider-failure /
      // all-providers-failed call sites and threaded through `extra` — this
      // was the only place it was silently dropped before reaching D1, which
      // is exactly the diagnosability gap #303 reported. Raw, unredacted
      // (server-side sanitizePrompt() is the one redaction point, per
      // t1k-telemetry-worker's existing pattern for the `prompt` column).
      //
      // RESTORED here (#315): #312 shipped this line; #314's rebase/merge
      // silently dropped it with no stated reason — a regression this PR's
      // own conflict resolution caught, not a deliberate revert. If you are
      // looking at this comment because it happened a THIRD time, that is a
      // process problem (rebase discipline on this file), not a code one.
      stderrTail: extra.stderrTail || undefined,
      // #311 follow-up — the fleet-wide equivalent of debug.jsonl for EVERY
      // decision, not just failures. `extra` already carries the floor's own
      // evidence (which clause fired, what tools made it write-capable,
      // whether a per-spawn override got silently dropped by a floor); the
      // spread of `spawnAttribution` below already enriches every LOCAL
      // debug.jsonl line the same way (see logDebug()) — this is that same
      // global, finally reaching D1 too.
      overrideDropped: extra.overrideDropped || undefined,
      agentTools: extra.tools || undefined,
      floorScope: extra.scope || undefined,
      floorClause: extra.clause || undefined,
      parentAgent: spawnAttribution.parentAgent,
      parentId: spawnAttribution.parentId,
      parentDepth: spawnAttribution.parentDepth,
      depthSource: spawnAttribution.depthSource,
      sessionId: spawnAttribution.session,
      ts: new Date().toISOString(),
      hostname: telemetryHelpers.hostHash(ctx.hostnameRaw),
      hostnameRaw: ctx.hostnameRaw,
      username: ctx.username,
      projectName: ctx.projectName,
      ghUser: ctx.ghUser,
      platform: os.platform(),
      arch: os.arch(),
    };
    spawnSync('node', [emit], {
      input: JSON.stringify(payload),
      timeout: 15000,
      stdio: ['pipe', 'ignore', 'ignore'],
      windowsHide: true,
    });
  } catch { /* fail-open — telemetry must never break a passthrough */ }
}

// Reasons excluded from passthrough telemetry: high-volume per-tool-call noise
// that fires on EVERY non-routable tool use (not a routing decision). Everything
// else a passthrough(reason) reports IS a routing decision and gets tracked.
const NOISE_PASSTHROUGH_REASONS = new Set([
  'not-task',           // fires on every Bash/Edit/Read — not a spawn at all
  'mr-spawned',         // recursion guard inside an already-delegated session
  'invalid-input',      // unparseable hook stdin
  'invalid-agent-name', // malformed subagent_type
]);

// ─── Provider budget-exhaustion telemetry ───────────────────────────────────
// A provider hitting its daily budget/quota is skipped on EVERY routing attempt
// for the rest of the day, so emitting on each skip would flood D1. Dedup to ONE
// event per provider per UTC day via a tiny date-stamped marker file — the
// "provider X went over budget on day D" signal. Fire-and-forget + fail-open.
function budgetAlreadyEmitted(provider) {
  try {
    const day = new Date().toISOString().slice(0, 10);
    const file = path.join(os.homedir(), '.model-router', `budget-emitted-${day}.json`);
    let seen = {};
    try { seen = JSON.parse(fs.readFileSync(file, 'utf8')) || {}; } catch { /* fresh */ }
    if (seen[provider]) return true;
    seen[provider] = true;
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, JSON.stringify(seen));
    return false;
  } catch {
    return false; // fail-open: on marker error, allow the emit (worst case a dup)
  }
}

function emitBudgetEvent(provider) {
  try {
    if (budgetAlreadyEmitted(provider)) return;
    const emit = path.join(__dirname, 'telemetry-emit.cjs');
    if (!fs.existsSync(emit) || !telemetryHelpers) return;
    const ctx = telemetryHelpers.resolveUserContext();
    const payload = {
      type: 'model-router:budget-exhausted',
      kit: 'theonekit-model-router',
      mrVersion: readMrVersion(),
      profile: provider,          // the provider that hit its daily budget/quota
      scenario: 'exhausted',
      ts: new Date().toISOString(),
      hostname: telemetryHelpers.hostHash(ctx.hostnameRaw),
      hostnameRaw: ctx.hostnameRaw,
      username: ctx.username,
      projectName: ctx.projectName,
      ghUser: ctx.ghUser,
      platform: os.platform(),
      arch: os.arch(),
    };
    spawnSync('node', [emit], {
      input: JSON.stringify(payload),
      timeout: 8000,
      stdio: ['pipe', 'ignore', 'ignore'],
      windowsHide: true,
    });
  } catch { /* fail-open — telemetry must never break routing */ }
}

// passthrough() exits the hook with no routing decision. When a reason is
// passed, log the decision so consumers can diagnose "why didn't it route?"
// via mr-tail-debug.sh.
/**
 * #246 — tell the SPAWNER that the route was declined.
 *
 * The routed path returns its result as a `systemMessage`, so the spawner sees
 * that something happened. The declined path exited silently: the decision went
 * to `~/.model-router/debug.jsonl` and stderr, neither of which is in the
 * parent's transcript. An orchestrator therefore could not tell a cheap-routed
 * child from an Anthropic-native one — and in particular could not tell that a
 * per-spawn `model` override had been dropped by a floor.
 *
 * That drop is correct and deliberate (#84 opus, #216 fable, #105 write-capable):
 * the override resolves AFTER the floors and can never pierce them. But correct
 * and invisible is how core#848's author ran six agents on Opus believing they
 * had been routed to Sonnet.
 *
 * CONSTANT SHAPE, deliberately. Per `agent-security-boilerplate.md` an output
 * header must not interpolate variable-cardinality values, which would bust the
 * parent's prompt cache. `reason` is a fixed enum and the agent roster is
 * bounded and stable; no count, timestamp or hash appears.
 */
function announcePassthrough(reason, extra) {
  try {
    const agent = (extra && typeof extra.agent === 'string' && extra.agent) || 'unknown-agent';
    const lines = [`[t1k:mr] ↩ ${agent} — Anthropic native (${reason})`];

    // Name a DROPPED override explicitly. It is the one case with no other
    // signal available to the caller: the spawn looks honoured and is not.
    if (extra && extra.overrideDropped) {
      lines.push(`[t1k:mr]   per-spawn model override "${extra.overrideDropped}" not applied — floors run first`);
    }

    // A bare `systemMessage` with NO hookSpecificOutput makes no permission
    // decision, so the Task proceeds exactly as before. Emitting a decision here
    // would turn every passthrough into a blocked spawn.
    process.stdout.write(JSON.stringify({ systemMessage: lines.join('\n') }));
  } catch { /* announcing must never block a spawn */ }
}

/**
 * The per-spawn override the caller ASKED for, whether or not it survives.
 * Read at floor time, where the resolver has not run yet — the floors are
 * upstream of it by design.
 */
function requestedOverride(toolInputModel, promptText) {
  if (typeof toolInputModel === 'string' && toolInputModel.trim()) return toolInputModel.trim();
  try {
    if (modelOverride && typeof modelOverride.parseMrModelDirective === 'function') {
      const d = modelOverride.parseMrModelDirective(
        typeof promptText === 'string' ? promptText : ''
      );
      if (d) return d;
    }
  } catch { /* a malformed directive is not this function's problem */ }
  return null;
}

function passthrough(reason, extra) {
  if (reason) {
    logDebug({ event: 'intercept', decision: 'pass-' + reason, ...(extra || {}) });
    // Track substantive route-declined decisions centrally (skip per-tool noise).
    if (!NOISE_PASSTHROUGH_REASONS.has(reason)) {
      emitPassthroughEvent(reason, extra || {});
      announcePassthrough(reason, extra || {});
    }
  }
  process.exit(0);
}

let input;
try {
  input = JSON.parse(fs.readFileSync(0, 'utf8'));
} catch {
  passthrough();  // No reason logged — we have nothing to identify
}

// Anthropic renamed the subagent-spawn tool from `Task` (legacy) to `Agent`
// (current Claude Code as of 2026-05). Accept both — strict on either-or so
// unrelated tool fires (e.g. Bash, Edit) still passthrough fast.
// Fixes: The1Studio/theonekit-model-router#70 (interceptor exited 'not-task'
// on every spawn → transparent routing silently dead in current CC versions).
const SUBAGENT_TOOL_NAMES = new Set(['Task', 'Agent']);
if (!input || !SUBAGENT_TOOL_NAMES.has(input.tool_name)) {
  passthrough('not-task', { tool: input && input.tool_name });
}

const projectRoot = input.cwd || process.env.CLAUDE_PROJECT_DIR || process.cwd();

// Attribute the spawn BEFORE the first decision can be logged, so every record
// from here on carries the same join keys. Wrapped even though the module
// already catches internally: a stubbed or corrupted copy must degrade to the
// unknown markers, never block the spawn.
if (spawnAttributionLib && typeof spawnAttributionLib.resolveSpawnAttribution === 'function') {
  try {
    const attributed = spawnAttributionLib.resolveSpawnAttribution(input, { projectRoot });
    if (attributed && typeof attributed === 'object') spawnAttribution = attributed;
  } catch { /* keep the unattributed default */ }
}

// Recursion guard — don't intercept inside an already-delegated session.
if (process.env.MR_SPAWNED === '1') passthrough('mr-spawned');

const ti = input.tool_input || {};
const agentName = ti.subagent_type;
const prompt = ti.prompt || ti.description;
// Per-call model param (#153). Claude Code's Task/Agent tool exposes `model`;
// it (or an `mr-model:` prompt directive) is honored as an explicit routing
// override for routable agents. Read here; resolved after the passthrough floors.
const perSpawnModel = typeof ti.model === 'string' ? ti.model : undefined;
if (!agentName || !prompt) passthrough('invalid-input', { agent: agentName || null });

// Defense-in-depth: agent names are basenames of files under .claude/agents/.
// Reject anything with path separators, dot-dot, or other shell-meta chars.
// Without this, a Task spawn with subagent_type="../../etc/passwd" would
// have path.join() escape the agents dir and look for ".md" files outside.
if (!/^[A-Za-z0-9._-]+$/.test(agentName) || agentName.includes('..')) {
  passthrough('invalid-agent-name', { agent: agentName });
}

function fileExists(p) {
  try { fs.accessSync(p, fs.constants.R_OK); return true; } catch { return false; }
}

const homeDir = process.env.HOME || os.homedir();

// Walk UP from `startDir` toward the filesystem root, collecting every existing
// `<dir>/.claude` directory, nearest-first. This mirrors Claude Code's own
// project-root discovery (it climbs to find `.claude/`).
//
// Why: in nested-project layouts the live cwd is often a SUBFOLDER of the repo
// root that holds `.claude/` (e.g. a Unity project where cwd drifts into the
// Unity subdir, or any monorepo subpackage). Resolving config/agents/scripts
// against ONLY the cwd's `.claude/` then misses the repo-root `.claude/` and
// every delegated spawn silently fails — the interceptor can't find the agent
// `.md` (model resolution), nor `t1k-config-mr.json`/`providers-config.json`
// (routing gate), nor `mr-delegate.sh` (dispatch).
// Fixes: The1Studio/theonekit-model-router#137.
//
// Loop terminates at the filesystem root (path.dirname(root) === root), so it
// can never infinite-loop. Nearest-ancestor matches come first to preserve the
// existing "nearest project-local wins" precedence.
function collectAncestorClaudeDirs(startDir) {
  const dirs = [];
  let dir;
  try { dir = path.resolve(startDir); } catch { return dirs; }
  while (true) {
    const candidate = path.join(dir, '.claude');
    if (fileExists(candidate)) dirs.push(candidate);
    const parent = path.dirname(dir);
    if (parent === dir) break; // reached filesystem root — stop
    dir = parent;
  }
  return dirs;
}

// Ordered list of `.claude` roots to consult: every ancestor of cwd that has
// one (nearest first), then the user-level `~/.claude` fallback last. The home
// dir is de-duplicated in case it coincides with an ancestor (e.g. cwd inside
// $HOME). Used uniformly for agents, config, providers, and the delegate script
// so a nested layout resolves ALL of them consistently.
const homeClaudeDir = path.join(homeDir, '.claude');
const claudeDirs = [];
for (const d of collectAncestorClaudeDirs(projectRoot)) {
  if (!claudeDirs.includes(d)) claudeDirs.push(d);
}
if (!claudeDirs.includes(homeClaudeDir)) claudeDirs.push(homeClaudeDir);

// Resolve a file path relative to each `.claude` root, nearest-first, returning
// the first that exists. `...segments` is the path under `.claude/`
// (e.g. 'agents', `${name}.md`). Returns null when found nowhere — callers
// preserve the existing silent-passthrough fallthrough.
function resolveClaudeFile(...segments) {
  for (const dir of claudeDirs) {
    const p = path.join(dir, ...segments);
    if (fileExists(p)) return p;
  }
  return null;
}

function findAgentFile(name) {
  return resolveClaudeFile('agents', `${name}.md`);
}

/**
 * #263 — parse the `mrHints` forms the documentation actually shows.
 *
 * This is a line scanner, not a YAML parser, and that was fine while every
 * consumed key (`model:`, `tools:`, `name:`) held a scalar on one line. `mrHints`
 * does not: the README writes it as an indented block, the kit's own routing rule
 * writes it as a flow mapping with bare keys, and NEITHER parsed. The block form
 * yielded `""`; the flow form reached `JSON.parse`, threw, and was swallowed by
 * the `catch` at the consumption site. An author following either document
 * believed a capability was declared and it was not — silently, which is the
 * part that makes it expensive.
 *
 * The only form that worked — bare JSON on one line — appears in no document.
 *
 * Scalars keep the exact old behaviour. The block path engages only when a key's
 * value is empty AND the lines under it are indented, which no scalar key can be,
 * and it falls back to the old empty-string result whenever the block is not a
 * shape it recognises. So this widens what parses without changing what parsed.
 */

/** A `- item` sequence, or a `key:` map of them. Returns null if unrecognised. */
function parseIndentedBlock(lines) {
  const kept = lines.filter((l) => l.trim() !== '');
  if (kept.length === 0) return null;

  const seq = [];
  const map = {};
  let currentKey = null;
  let sawKey = false;

  for (const line of kept) {
    const item = line.match(/^\s+-\s+(.*)$/);
    if (item) {
      const v = item[1].trim().replace(/^["'](.*)["']$/, '$1');
      if (currentKey) (map[currentKey] = map[currentKey] || []).push(v);
      else seq.push(v);
      continue;
    }
    const kv = line.match(/^\s+([A-Za-z_][\w-]*):\s*(.*)$/);
    if (kv) {
      sawKey = true;
      currentKey = kv[1];
      const inline = kv[2].trim();
      if (inline) {
        // `requires: [a, b]` on one line, or a scalar.
        const flow = inline.match(/^\[(.*)\]$/);
        map[currentKey] = flow
          ? flow[1].split(',').map((x) => x.trim().replace(/^["'](.*)["']$/, '$1')).filter(Boolean)
          : inline.replace(/^["'](.*)["']$/, '$1');
        currentKey = null;
      } else {
        map[currentKey] = [];
      }
      continue;
    }
    return null; // a shape this subset does not model — do not guess
  }

  if (sawKey) return map;
  return seq.length ? seq : null;
}

/** `{ requires: ["a"] }` — a flow mapping whose keys are bare. Returns null if not one. */
function parseFlowMapping(v) {
  if (!/^\{[\s\S]*\}$/.test(v)) return null;
  try { return JSON.parse(v); } catch { /* fall through to bare-key repair */ }
  try {
    return JSON.parse(v.replace(/([{,]\s*)([A-Za-z_][\w-]*)(\s*:)/g, '$1"$2"$3'));
  } catch { return null; }
}

function readFrontmatter(file) {
  let text;
  try { text = fs.readFileSync(file, 'utf8'); } catch { return {}; }
  const m = text.match(/^---\s*\n([\s\S]*?)\n---\s*\n/);
  if (!m) return {};
  const fm = {};
  const lines = m[1].split('\n');

  for (let i = 0; i < lines.length; i++) {
    const kv = lines[i].match(/^([A-Za-z_][\w-]*):\s*(.*)$/);
    if (!kv) continue;
    const key = kv[1];
    let v = kv[2].trim();

    if (v === '') {
      const block = [];
      let j = i + 1;
      while (j < lines.length && (lines[j].trim() === '' || /^\s+\S/.test(lines[j]))) {
        block.push(lines[j]);
        j++;
      }
      const parsed = block.length ? parseIndentedBlock(block) : null;
      if (parsed !== null) {
        fm[key] = parsed;
        i = j - 1;
        continue;
      }
    }

    const flow = parseFlowMapping(v);
    if (flow !== null) { fm[key] = flow; continue; }

    fm[key] = v.replace(/^["'](.*)["']$/, '$1');
  }
  return fm;
}

function readJsonFile(p) {
  if (!fileExists(p)) return null;
  try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch { return null; }
}

function readConfig() {
  const p = resolveClaudeFile('t1k-config-mr.json');
  return p ? readJsonFile(p) : null;
}

function readProvidersConfig() {
  const p = resolveClaudeFile('providers-config.json');
  return p ? readJsonFile(p) : null;
}

function hasCatalog(providersCfg) {
  return !!(providersCfg && providersCfg.providers);
}

function isEnabledCatalogTarget(providersCfg, target) {
  if (!hasCatalog(providersCfg) || !target) return false;
  const provider = providersCfg.providers[target.provider];
  if (!provider || provider.enabled !== true) return false;
  const model = provider.models && provider.models[target.model];
  return !!model && model.enabled === true;
}

// Dispatch gate. An UNRESOLVABLE catalog is not the same fact as "this target is
// disabled", and conflating the two inverts routing: `isEnabledCatalogTarget`
// returns false when providersCfg is null, so every task would passthrough to
// Anthropic on any install where providers-config.json is missing — silently
// losing all routing (and its cost saving) for exactly the broken-config case.
//
// The bash half already fails OPEN here: `_target_enabled` in mr-delegate.sh
// returns enabled when PROVIDERS_CONFIG is empty. Keep the two halves agreeing.
//   absent catalog  ⇒ fail open (honor modelMapping, as before this check)
//   present catalog ⇒ enforce (the integrity guarantee this check exists for)
function isDispatchableTarget(providersCfg, target) {
  if (!target) return false;
  if (!hasCatalog(providersCfg)) return true;
  return isEnabledCatalogTarget(providersCfg, target);
}

// ─── Load-balance: round-robin quota split across provider pools ─────────
// modelRouter.loadBalance rotates plain routable delegations across an explicit
// set of targets so quota is SPLIT between independent provider pools (e.g.
// opencode-go/deepseek-v4-flash ⇄ kimi/kimi-k2.7-code, 50/50). It runs BEFORE
// capability selection but only claims a delegation when EVERY required
// capability is satisfied by the chosen target AND the target is healthy
// (allowlisted, enabled, provider not over its daily budget). So specialised
// tasks (long-context / vision / image — whose caps neither generalist target
// declares) fall through to pickFromCandidates unchanged. Per-target `weight`
// (default 1) gives a weighted round-robin.
function targetCapabilities(providersCfg, target) {
  const prov = providersCfg && providersCfg.providers && providersCfg.providers[target.provider];
  const m = prov && prov.models && prov.models[target.model];
  return Array.isArray(m && m.capabilities) ? m.capabilities : [];
}

// Persist a per-group rotation counter under ~/.model-router/lb-counter.json.
// Best-effort: any I/O error returns index 0 (always a valid, in-range pick).
function lbCounterNext(groupKey, modulo) {
  if (!Number.isInteger(modulo) || modulo <= 0) return 0;
  try {
    const dir = path.join(os.homedir(), '.model-router');
    fs.mkdirSync(dir, { recursive: true });
    const file = path.join(dir, 'lb-counter.json');
    let state = {};
    try { state = JSON.parse(fs.readFileSync(file, 'utf8')) || {}; } catch (_) { state = {}; }
    const cur = Number.isInteger(state[groupKey]) ? state[groupKey] : 0;
    const idx = ((cur % modulo) + modulo) % modulo;
    state[groupKey] = (cur + 1) % 1000000000;
    try { fs.writeFileSync(file, JSON.stringify(state)); } catch (_) { /* best-effort */ }
    return idx;
  } catch (_) {
    return 0;
  }
}

function pickLoadBalanced(requiredCaps, providersCfg, allowedProviderSet, mr) {
  const lb = mr && mr.loadBalance;
  if (!lb || lb.enabled === false) return null;
  const targets = Array.isArray(lb.targets) ? lb.targets : [];
  if (targets.length < 2) return null;
  // Task-specific gate: NEVER cost-balance a QUALITY-DRIVEN task (reasoning /
  // long-context). Those must go to the BEST model via capability selection
  // (quality-first policy — "even when we need cheap routing, quality still must
  // be guaranteed", user 2026-05-25). Load-balancing is a COST optimisation for
  // the plain/mechanical/general bucket only; a 50/50 with a cheaper pool would
  // silently degrade an audit / security / architecture / root-cause task.
  if (requiredCaps.some((c) => QUALITY_DRIVEN.has(c))) return null;
  const exhausted = getExhaustedProviders(providersCfg);
  const breakerOpen = getOpenBreakerProviders(mr);
  const eligible = targets.filter((t) => {
    if (!t || !t.provider || !t.model) return false;
    if (allowedProviderSet && allowedProviderSet.size > 0 && !allowedProviderSet.has(t.provider)) return false;
    if (exhausted.has(t.provider)) return false;
    if (!isDispatchableTarget(providersCfg, t)) return false;
    // Capability fit: a specialised requirement (long-context/vision/…) that the
    // generalist target does not declare must NOT be load-balanced — fall through
    // to capability selection. Plain text (no required caps) is always eligible.
    if (requiredCaps.length === 0) return true;
    const caps = targetCapabilities(providersCfg, t);
    if (caps.length === 0) return false;
    return requiredCaps.every((r) => caps.includes(r));
  });
  if (eligible.length === 0) return null;
  // Drop targets whose provider is a known-dead breaker — but only while a live
  // one remains. Balancing across a pool that includes a provider we already
  // know is refusing traffic just hands it its share of the rotation. If EVERY
  // target is down, keep the full pool rather than returning null: capability
  // selection would only re-pick the same providers, and losing load-balancing
  // during a total outage helps nobody.
  const liveTargets = eligible.filter((t) => !breakerOpen.has(t.provider));
  const balanceOver = liveTargets.length > 0 ? liveTargets : eligible;
  if (liveTargets.length !== eligible.length) {
    logDebug({
      event: 'intercept',
      decision: 'lb-demoted-breaker-open',
      dropped: eligible.filter((t) => breakerOpen.has(t.provider)).map((t) => t.provider),
      remaining: balanceOver.length,
    });
  }
  // Weighted expansion (weight default 1): repeat each eligible target `weight`×.
  const pool = [];
  for (const t of balanceOver) {
    const w = Number.isInteger(t.weight) && t.weight > 0 ? t.weight : 1;
    for (let i = 0; i < w; i++) pool.push(t);
  }
  if (pool.length === 1) return { provider: pool[0].provider, model: pool[0].model };
  const groupKey = pool.map((t) => `${t.provider}/${t.model}`).join('|');
  const chosen = pool[lbCounterNext(groupKey, pool.length)];
  return { provider: chosen.provider, model: chosen.model };
}

// ─── Observed context-overflow guard (#249 part 2) ──────────────────────
// Preferring the widest model is necessary but not sufficient. Benchmarked over
// 40 delegations through this interceptor against live providers: small (~2.4K)
// and medium (~75K) payloads reached 31/33, while a ~318K accumulation reached
// 3/7 EVEN ON the 1,000,000-token model. Those failures read `Autocompact is
// thrashing` — the CLIENT abandoning the transcript, which no catalog number can
// influence. Re-attempting that work anywhere cheap is a doomed hop that still
// bills a full per-hop timeout.
//
// This keys on the OBSERVED failure, never on a size proxy. An earlier revision
// compared a per-agent payload percentile against the model's declared window and
// was reverted: `inputTokens` is cumulative across turns, not peak context, and
// 27 recorded successes exceeded their model's declared window (one by 4.5x —
// 905,293 tokens on a 200,000-window model). Size predicts nothing here; the
// runtime's own "I gave up" does.
//
// Necessarily reactive — the first overflow for a new agent still fails, because
// nothing observable at spawn time distinguishes it. What it prevents is the
// SECOND through Nth, which is where the sustained cost lives.
const DEFAULT_OVERFLOW_GUARD = Object.freeze({
  enabled: true,
  window: 12,         // recent delegations per agent to consider
  threshold: 2,       // overflows within that window before declining
  minSamples: 3,      // below this, one bad run must not trip the guard
  maxScanBytes: 262144,
});

function overflowGuardCfg(mr) {
  const c = (mr && mr.overflowGuard) || {};
  const int = (v, d) => (Number.isInteger(v) && v > 0 ? v : d);
  return {
    enabled: c.enabled !== false,
    window: int(c.window, DEFAULT_OVERFLOW_GUARD.window),
    threshold: int(c.threshold, DEFAULT_OVERFLOW_GUARD.threshold),
    minSamples: int(c.minSamples, DEFAULT_OVERFLOW_GUARD.minSamples),
    maxScanBytes: int(c.maxScanBytes, DEFAULT_OVERFLOW_GUARD.maxScanBytes),
  };
}

// Bounded tail-read of traces.jsonl, parsed once per process.
//
// Two consumers now need this window (the overflow guard and the latency
// tie-break), and both run on the hot path. Reading and JSON-parsing the same
// 256KB twice per Task spawn to answer two questions about the same rows would
// be a self-inflicted cost, so the parse is memoized on the scan size.
let _traceTailCache = null;
function readTraceTail(maxScanBytes) {
  if (_traceTailCache && _traceTailCache.bytes === maxScanBytes) return _traceTailCache.rows;
  const rows = [];
  try {
    const file = path.join(os.homedir(), '.model-router', 'traces.jsonl');
    const size = fs.statSync(file).size;
    const start = Math.max(0, size - maxScanBytes);
    const len = size - start;
    if (len > 0) {
      const buf = Buffer.allocUnsafe(len);
      const fd = fs.openSync(file, 'r');
      try { fs.readSync(fd, buf, 0, len, start); } finally { fs.closeSync(fd); }
      const lines = buf.toString('utf8').split('\n');
      if (start > 0) lines.shift(); // discard the partial first line
      for (const ln of lines) {
        if (!ln) continue;
        let r; try { r = JSON.parse(ln); } catch { continue; }
        if (r) rows.push(r);
      }
    }
  } catch { /* fail-open: no history is not an error */ }
  _traceTailCache = { bytes: maxScanBytes, rows };
  return rows;
}

// Observed median latency per `provider/model`, over SUCCESSFUL delegations only.
//
// Selection had no notion of speed anywhere — tier is a hand-authored string and
// the catalog carries no timing at all — while the recorded spread is enormous:
// 30 days of this user's traffic showed deepseek-v4-flash averaging 7.7s against
// kimi-k2.5 at 220s over 93 requests, a 29x difference that nothing in the
// comparator could see.
//
// Deliberately narrow. This is a TIE-BREAK inside an already-chosen tier, never
// a reason to change tier: the tier ordering encodes the cost/quality policy
// ("even when we need cheap routing, quality still must be guaranteed"), and a
// fast premium model must not be able to pull a task out of the budget tier, nor
// a fast budget model out of a quality-driven one.
//
// Failures are excluded because a failed hop's `duration` is a timeout ceiling,
// not a latency measurement — including them would rank a model that reliably
// times out at 300s as merely "slow" rather than broken, and the breaker and
// overflow guard already own brokenness. Median, not mean, so a single outlier
// cannot decide the order.
const LATENCY_MIN_SAMPLES = 3;
let _latencyCache = null;
function observedLatencyByTarget(maxScanBytes) {
  // pickFromCandidates can run twice in one spawn (the contextGrowth preference
  // and then the rules path), and both would otherwise re-fold the same rows.
  if (_latencyCache && _latencyCache.bytes === maxScanBytes) return _latencyCache.map;
  const acc = new Map();
  for (const r of readTraceTail(maxScanBytes)) {
    if (!r || r.exit !== 0) continue;
    // A delegation whose model id Claude Code REFUSED still exits 0 and still
    // returns an answer — from whatever the CLI fell back to (#248). Crediting
    // that duration to the refused model donates another model's speed to it and
    // makes it win this tie-break more often, so the poisoned input compounds.
    // Observed live: opencode-go/minimax-m3, exit 0, duration 30, errorType "".
    if (r.modelRejected === 1) continue;
    if (!r.provider || !r.model) continue;
    const d = Number(r.duration);
    if (!Number.isFinite(d) || d <= 0) continue;
    const k = `${r.provider}/${r.model}`;
    if (!acc.has(k)) acc.set(k, []);
    acc.get(k).push(d);
  }
  const out = new Map();
  for (const [k, xs] of acc) {
    if (xs.length < LATENCY_MIN_SAMPLES) continue;   // too few to rank on
    xs.sort((a, b) => a - b);
    out.set(k, xs[Math.floor(xs.length / 2)]);
  }
  _latencyCache = { bytes: maxScanBytes, map: out };
  return out;
}

// Returns the overflow count over the agent's most recent `window` delegations.
function recentOverflowCount(agentName, cfg) {
  try {
    const mine = readTraceTail(cfg.maxScanBytes).filter((r) => r && r.agent === agentName);
    const recent = mine.slice(-cfg.window);
    if (recent.length < cfg.minSamples) return null;
    const overflows = recent.filter(r => r.errorType === 'context-overflow').length;
    return { overflows, samples: recent.length };
  } catch {
    return null; // fail open — telemetry I/O must never block a delegation
  }
}

// ─── Context-growth agents (#249) ───────────────────────────────────────
// Rule 2 below sizes the SPAWN PROMPT. For an agentic sub-agent that is
// dispatched with a short instruction and then reads its own context in via
// tool calls, the prompt is not a proxy for anything — the real payload does
// not exist yet at selection time and no prompt-length heuristic can see it.
//
// Measured 2026-08-15: `Explore` spawned on a one-line search instruction,
// was classed plain → loadBalance → deepseek-v4-flash (128K window), then read
// ~830K tokens of files. 0/7 such hops survived; each returned inputTokens:0
// and burned the full per-hop timeout (~24 min of wall clock for zero output).
// The only two that succeeded went to glm-5.2, and only because their prompts
// incidentally tripped the reasoning KEYWORDS regex below.
//
// These agents are BUILT-IN — they have no `.md` on disk, so the `mrHints`
// escape hatch in rule 5 is structurally unavailable to them. Declaring them
// here is the only place the signal can live.
//
// Consumers override with `modelRouter.contextGrowthAgents: [...]`; an empty
// array disables the rule entirely.
// The list itself lives in scripts/mr-defaults.cjs so mr-delegate.sh's copy (it
// needs the same membership to resolve the per-agent hop ceiling, #261 A) can be
// gate-checked against ONE source. The literal below is the usual fail-open
// last resort for a missing sibling, and carries the marker the gate reads.
const DEFAULT_CONTEXT_GROWTH_AGENTS = Object.freeze(
  (mrDefaults && mrDefaults.DEFAULT_CONTEXT_GROWTH_AGENTS)
  || ['Explore', 'general-purpose'],  // mr-ssot-list:contextGrowthAgents
);

function contextGrowthAgents(mr) {
  const cfg = mr && mr.contextGrowthAgents;
  if (Array.isArray(cfg)) return new Set(cfg.filter(s => typeof s === 'string' && s));
  return new Set(DEFAULT_CONTEXT_GROWTH_AGENTS);
}

// ─── Rule-based capability detection ────────────────────────────────────
// Hot path: this runs on every Task call. Stay deterministic + cheap.
// Rules adapted from LiteLLM's Complexity Router pattern — see
// docs/research-multi-provider-multimodal.md § 5.
function detectRequiredCapabilities(promptValue, fm) {
  const caps = new Set();

  // 1. Image content blocks → vision. Claude Code's Task tool today passes
  // `prompt` as a string, but the schema may grow to support content arrays
  // (image input) — handle both shapes.
  if (Array.isArray(promptValue)) {
    if (promptValue.some(b => b && (b.type === 'image' || b.type === 'input_image'))) {
      caps.add('vision');
    }
  }

  const promptText = typeof promptValue === 'string'
    ? promptValue
    : JSON.stringify(promptValue);

  // 2. Long-context: rough heuristic — >50K chars in the prompt.
  // ~12.5K tokens at 4 chars/token. Real long-context jobs are typically
  // much larger (whole codebases). Catches the obvious cases without
  // requiring a tokenizer.
  if (promptText.length > 50000) caps.add('long-context');


  // 3. Reasoning keywords. Check only the leading 2K chars to keep
  // detection fast for very long prompts; the topic usually surfaces early.
  const KEYWORDS = /\b(audit|security|architecture|design\s+(decision|review)|threat\s+model|deep\s+review|root\s+cause|exploit|vulnerability)\b/i;
  if (KEYWORDS.test(promptText.slice(0, 2000))) caps.add('reasoning');

  // 4. MCP dependency: prompt references MCP tool calls (mcp__ namespace).
  // Cheap providers lack the consumer's MCP server configuration, so delegation
  // would fail with permission-denied or bill for zero work (#109).
  if (/\bmcp__/.test(promptText)) caps.add('mcp');

  // 5. Agent frontmatter override: `mrHints: { requires: ["vision", ...] }`
  // Authors can pin requirements that the prompt-based heuristics would miss.
  // Frontmatter parser flattens, so mrHints arrives as a string of JSON.
  if (fm.mrHints) {
    try {
      const hints = typeof fm.mrHints === 'string' ? JSON.parse(fm.mrHints) : fm.mrHints;
      if (Array.isArray(hints.requires)) {
        hints.requires.forEach(c => typeof c === 'string' && caps.add(c));
      }
    } catch { /* ignore malformed hints */ }
  }

  return Array.from(caps);
}

// ─── Per-agent MCP server forwarding (#XXX, design doc plans/260822-0711-
// mcp-server-forwarding-design.md) ───────────────────────────────────────
// Ground-truth derivation of the MCP servers an agent's OWN `tools:`
// frontmatter grants — mirrors isWriteCapable's read of fm.tools. This
// supersedes the old "prompt mentions mcp__ -> floor" heuristic (case 4
// above, kept ONLY as a fallback for the unresolvable case below): MCP need
// is a property of the agent's granted tools, not the prompt's vocabulary.
const MCP_TOOL_RE = /\bmcp__([A-Za-z0-9_.-]+)__/g;

function parseMrHintsObject(fm) {
  if (!fm.mrHints) return null;
  try {
    return typeof fm.mrHints === 'string' ? JSON.parse(fm.mrHints) : fm.mrHints;
  } catch { return null; }
}

/**
 * @returns {{servers: string[], resolvable: boolean}} `resolvable=true` means
 * the agent's full mcp__ tool surface is known (possibly empty — a real,
 * provable negative). `resolvable=false` means `tools:` is absent (built-in,
 * no `.md`), unrestricted (`*`/`[*]`), or unparseable — a negative cannot be
 * proven, so the caller must fall back to a conservative heuristic instead of
 * concluding "no MCP need".
 */
function deriveMcpServersFromTools(fm, hasAgentFile) {
  if (!hasAgentFile) return { servers: [], resolvable: false }; // built-in: no tools: to read
  const raw = typeof fm.tools === 'string' ? fm.tools.trim() : '';
  if (!raw || raw === '*' || raw === '[*]') return { servers: [], resolvable: false }; // can't rule out
  const set = new Set();
  let m;
  MCP_TOOL_RE.lastIndex = 0;
  while ((m = MCP_TOOL_RE.exec(raw))) set.add(m[1]);
  let servers = Array.from(set);
  // Optional narrowing override (design doc §5.1): mrHints.mcpServers may
  // SHRINK the derived set, never widen it — an agent cannot forward a
  // server it holds no mcp__ tool for, no matter what mrHints claims.
  const hints = parseMrHintsObject(fm);
  if (hints && Array.isArray(hints.mcpServers)) {
    const allowed = new Set(hints.mcpServers.filter(s => typeof s === 'string'));
    servers = servers.filter(s => allowed.has(s));
  }
  return { servers, resolvable: true };
}

/**
 * `modelRouter.security.allowedMcpServers` — FAIL CLOSED (deliberate
 * divergence from `allowedProviders`'s fail-open legacy default, see design
 * doc §6 item 1): absent/empty/malformed all resolve to an EMPTY set, so an
 * agent with declared MCP servers always ends up with an empty routable set
 * and today's `mcp-required` passthrough applies unconditionally, exactly as
 * before this feature existed.
 */
function resolveAllowedMcpServers(securityCfg) {
  const cfg = securityCfg && securityCfg.allowedMcpServers;
  if (!Array.isArray(cfg)) return new Set(); // absent, malformed (e.g. a string) -> closed
  return new Set(cfg.filter(s => typeof s === 'string' && s));
}

// ─── Candidate filtering + capability-aware sort ────────────────────────
const TIER_RANK = { budget: 0, standard: 1, premium: 2 };

// Quality-driven capabilities: when a task needs `reasoning` or `long-context`,
// pick the BEST model that satisfies the requirement, not the cheapest.
// (User feedback 2026-05-25: "even when we need cheap model routing, quality
// still must be guaranteed".) Other capabilities stay cost-driven.
//
// long-context is a special case: tier is a weak proxy — sort by context_window
// descending so the model with the biggest window wins, then tier desc as tiebreaker.
const QUALITY_DRIVEN = new Set(['reasoning', 'long-context']);

// capabilityPipes: explicit ordered preference per capability (data-driven, in
// providers-config.json). When a required cap has a pipe, candidates are sorted
// by their index in it — authoritative over tier. Returns the first matching
// pipe array, or null.
function pipeForCaps(requiredCaps, providersCfg) {
  const pipes = providersCfg && providersCfg.capabilityPipes;
  if (!pipes) return null;
  for (const cap of requiredCaps) {
    if (Array.isArray(pipes[cap]) && pipes[cap].length > 0) return pipes[cap];
  }
  return null;
}

// Per-provider daily-budget guard: the set of providers that have reached 95%
// of their configured dailyRequests / dailyBudgetUsd. Memoized for the process
// lifetime so EVERY selection path (capability rules AND the modelMapping
// fallback) consults the SAME set. Without this the capability path skips an
// exhausted provider — which empties its candidate list — and the fallback
// modelMapping branch then re-picks that very provider, defeating the guard in
// exactly the end-of-day case it exists for. Fail-open: any error yields an
// empty set, so the budget check can never block routing.
let _exhaustedProvidersCache = null;
function getExhaustedProviders(providersCfg) {
  if (_exhaustedProvidersCache) return _exhaustedProvidersCache;
  const set = new Set();
  try {
    if (providerUsageLib && providersCfg && providersCfg.providers) {
      for (const [pname, u] of providerUsageLib.computeAllUtilization(providersCfg)) {
        if (u.exhausted) set.add(pname);
      }
    }
  } catch { /* fail-open: budget check must never block routing */ }
  _exhaustedProvidersCache = set;
  return set;
}

// Providers whose circuit breaker is OPEN and still inside its cooldown.
//
// The breaker already exists and already works — but only one layer DOWN, in
// mr-delegate.sh's per-hop gate. The selector knew nothing about it, so a
// provider that had failed 3 times in a row still WON selection and became
// hop 0; the delegate then forked node, read the same state file, recorded a
// skip and advanced. Every delegation during an outage paid for a hop slot
// that was known-dead before it was chosen.
//
// Read directly rather than shelling out to mr-circuit-breaker.cjs: this runs
// on EVERY Task spawn, and a node fork per spawn to learn something already
// sitting in a small JSON file would be its own inefficiency.
//
// Cooldown is honoured exactly as the breaker defines it: `open` past its
// cooldown is half-open and admits one trial, so it is NOT reported here — that
// trial is how a recovered provider gets re-admitted, and suppressing it would
// keep a healthy provider demoted forever.
//
// 'half-open-trial' IS reported (#276). It is not the admitting state — it is
// the state of a trial ALREADY claimed by someone else, and mr-circuit-breaker's
// `check` returns EXIT_OPEN for it every time: 'open:trial-in-flight' while the
// trial is live, 'open:trial-abandoned-*' once #272 reclaims it. Either way the
// delegate skips the provider, so leaving it eligible here reproduced exactly
// the waste this function exists to prevent — the wedged provider kept winning
// hop 0 and was thrown away one layer down. It cannot strand a healthy provider
// the way suppressing half-open would: the trial is bounded by trialTimeoutSec,
// and the delegate's EXIT trap now frees an abandoned one in milliseconds.
//
// Read the cooldown clock from `openedAt` — the field the breaker itself writes
// when it opens — NOT from lastFailure. The two used to disagree: the #272
// reclaim (and the #276 release) refresh openedAt and deliberately leave
// lastFailure alone, because an abandoned trial observed no failure. Measuring
// from lastFailure therefore told the selector a cooldown had elapsed while the
// delegate was still skipping the provider. lastFailure stays as the fallback
// for a legacy state file written before openedAt was persisted.
//
// Fail-open: any error yields an empty set. A breaker read must never be able
// to block routing.
let _openBreakerCache = null;
function getOpenBreakerProviders(mr) {
  if (_openBreakerCache) return _openBreakerCache;
  const set = new Set();
  try {
    const stateFile = process.env.MR_CB_STATE_FILE
      || path.join(os.homedir(), '.model-router', 'circuit-breaker.json');
    const cbCfg = (mr && mr.failover && mr.failover.circuitBreaker) || {};
    if (cbCfg.enabled === false) { _openBreakerCache = set; return set; }
    const cooldownSec = Number.isInteger(cbCfg.cooldownSec) && cbCfg.cooldownSec >= 0
      ? cbCfg.cooldownSec : 300;
    const raw = JSON.parse(fs.readFileSync(stateFile, 'utf8'));
    const now = Math.floor(Date.now() / 1000);
    for (const [pname, st] of Object.entries((raw && raw.providers) || {})) {
      if (!st) continue;
      // A claimed trial is skipped by the delegate unconditionally — no clock
      // to consult, and none that would change the answer.
      if (st.state === 'half-open-trial') { set.add(pname); continue; }
      if (st.state !== 'open') continue;
      const openedAt = Number.isFinite(st.openedAt) ? st.openedAt
        : (Number.isFinite(st.lastFailure) ? st.lastFailure : null);
      const since = openedAt === null ? Infinity : now - openedAt;
      if (since < cooldownSec) set.add(pname);
    }
  } catch { /* fail-open: a breaker read must never block routing */ }
  _openBreakerCache = set;
  return set;
}

// The #158 security.allowedProviders list, as a Set — or null when absent/empty
// (null = allow-all, preserving legacy configs). Consumed as a candidate FILTER
// inside pickFromCandidates so a non-allowlisted cheapest-tier provider does not
// win selection only to be vetoed afterward (which passed the whole Task through
// to Anthropic even when an allowlisted sibling was already a candidate). Same
// shape as getExhaustedProviders — a guard that filters, not a post-hoc abort.
function getAllowedProviderSet(securityCfg) {
  const list = securityCfg && Array.isArray(securityCfg.allowedProviders)
    ? securityCfg.allowedProviders : null;
  return list && list.length > 0 ? new Set(list) : null;
}

function pickFromCandidates(requiredCaps, providersCfg, allowedSet, mr) {
  if (!providersCfg || !providersCfg.providers) return null;

  const exhaustedProviders = getExhaustedProviders(providersCfg);
  const breakerOpen = getOpenBreakerProviders(mr);
  const latency = observedLatencyByTarget(overflowGuardCfg(mr).maxScanBytes);

  const candidates = [];
  for (const [pname, p] of Object.entries(providersCfg.providers)) {
    if (p.enabled !== true) continue;
    if (allowedSet && !allowedSet.has(pname)) {
      logDebug({ event: 'intercept', decision: 'skip-provider-not-allowlisted', provider: pname });
      continue;
    }
    if (exhaustedProviders.has(pname)) {
      logDebug({ event: 'provider-budget', provider: pname, decision: 'skip-exhausted' });
      emitBudgetEvent(pname); // deduped to one event per provider per UTC day
      continue;
    }
    for (const [mname, m] of Object.entries(p.models || {})) {
      if (m.enabled !== true) continue;
      const caps = Array.isArray(m.capabilities) ? m.capabilities : [];
      // Baseline floor: a delegation always runs `claude -p --agent <name>`, so
      // the target must be a TEXT model. Without this, `requiredCaps.every(...)`
      // is vacuously true for an empty requiredCaps and every enabled catalog
      // entry becomes a candidate — including image-generation-only models
      // (capabilities:["image-generation"], context_window:0), which then WIN
      // the cheapest-tier sort and get dispatched an agentic coding task.
      // `text` (not `tool-use`) is the floor so vision models — which ship
      // capabilities:["text","vision"] — stay eligible for the vision pipe.
      // Fail OPEN on an undeclared capability list (same posture as
      // isDispatchableTarget): an empty/absent list means "not annotated" and
      // must not silently drop a catalog from routing; only a model that
      // DECLARES capabilities and omits `text` is treated as a non-text model.
      if (caps.length > 0 && !caps.includes('text')) continue;
      if (requiredCaps.every(r => caps.includes(r))) {
        candidates.push({
          provider: pname,
          model: mname,
          tier: m.tier || 'standard',
          tier_rank: TIER_RANK[m.tier || 'standard'] ?? 1,
          context_window: typeof m.context_window === 'number' ? m.context_window : 0,
          // Demotion signal, not a filter — see the comparator.
          breaker_open: breakerOpen.has(pname) ? 1 : 0,
          // undefined when fewer than LATENCY_MIN_SAMPLES successes are known.
          latency_ms: latency.get(`${pname}/${mname}`),
        });
      }
    }
  }
  if (candidates.length === 0) return null;

  const wantsLongContext = requiredCaps.includes('long-context');
  const wantsQuality = requiredCaps.some(c => QUALITY_DRIVEN.has(c));
  const pipe = pipeForCaps(requiredCaps, providersCfg);

  candidates.sort((a, b) => {
    // A provider whose breaker is OPEN and still cooling is known to be refusing
    // traffic right now. Demote it ahead of every other rule — including an
    // explicit capability pipe, which is authoritative about PREFERENCE, not
    // about availability; routing to a dead provider satisfies neither.
    //
    // Demote, never exclude. If every candidate is down we still return one and
    // let the delegate's own gate decide, because a selector that can return
    // nothing turns a provider outage into a total passthrough to Anthropic.
    if (a.breaker_open !== b.breaker_open) return a.breaker_open - b.breaker_open;
    if (pipe) {
      // Explicit capability pipe is authoritative. Listed models first, in pipe
      // order; unlisted models (rank Infinity) fall through to the rules below.
      const ra = pipe.indexOf(a.model); const rb = pipe.indexOf(b.model);
      const na = ra === -1 ? Infinity : ra; const nb = rb === -1 ? Infinity : rb;
      if (na !== nb) return na - nb;
    }
    if (wantsLongContext) {
      // Larger context first, then premium-tier first as tiebreaker.
      if (a.context_window !== b.context_window) return b.context_window - a.context_window;
      return b.tier_rank - a.tier_rank;
    }
    if (wantsQuality) {
      // Premium-tier first for reasoning.
      return b.tier_rank - a.tier_rank;
    }
    // Default: cheapest tier first.
    if (a.tier_rank !== b.tier_rank) return a.tier_rank - b.tier_rank;
    // Same tier: prefer the one observed to be faster. This is the ONLY place
    // speed enters selection, and it cannot move a task between tiers — the tie
    // is already broken on cost/quality by the time it is consulted. Previously
    // this tie fell through to catalog order, which is arbitrary.
    // Unmeasured models keep catalog order rather than being ranked last: a new
    // catalog entry has no samples yet, and burying it would ensure it never
    // gets any.
    if (a.latency_ms !== undefined && b.latency_ms !== undefined) {
      return a.latency_ms - b.latency_ms;
    }
    return 0;
  });
  return candidates[0];
}

// ─── Canonical model alias tables ───────────────────────────────────────
// modelMapping lookups try BOTH the raw frontmatter value AND its canonical
// alias, so config can be authored with either shorthand OR full-ID keys.
// Aliases per https://code.claude.com/docs/en/sub-agents.
// Fixes: The1Studio/theonekit-model-router#61 (Sonnet/Haiku silent passthrough)
const SHORT_TO_FULL = Object.freeze({
  opus:   'claude-opus-4-7',
  sonnet: 'claude-sonnet-4-6',
  haiku:  'claude-haiku-4-5-20251001',
});
const FULL_TO_SHORT = Object.freeze(
  Object.fromEntries(Object.entries(SHORT_TO_FULL).map(([s, f]) => [f, s]))
);

// ─── Kit-enforced passthrough policy ────────────────────────────────────
// Kit-author dictate: agents declaring an Opus-family model — OR `inherit`
// (Claude Code's default when `model:` is omitted) — MUST stay on Opus.
// Consumers cannot soften this via t1k-config-mr.json; the policy is the floor.
// Forms covered (per https://code.claude.com/docs/en/sub-agents):
//   - shorthand alias: `opus`
//   - full ID:         `claude-opus-4-7`
//   - 1M variant:      `claude-opus-4-7[1m]`
//   - inherit:         explicit `model: inherit` AND omitted-`model:` default
// excludeAgents (per-agent, consumer-editable) remains additive — consumers
// can ESCALATE more agents to passthrough but never DEMOTE one to cheap.
const KIT_PASSTHROUGH_MODELS = new Set([
  'opus',
  'claude-opus-4-7',
  'claude-opus-4-7[1m]',
  // #216 — `fable` is a premium tier and must clear the same quality floor as
  // `opus`. It is not a SHORT_TO_FULL alias and not a shipped modelMapping key,
  // so without these rows a `model: fable` agent fell ALL the way through to
  // capability-based selection — whose comparator sorts "cheapest tier first" —
  // and landed on the BUDGET tier. That left `fable` with less protection than
  // `sonnet` (which at least maps to a code-capable model): an outright quality
  // inversion, and the delegation was observed failing outright twice.
  'fable',
  'claude-fable-5',
  'claude-fable-5[1m]',
  'inherit',
]);

// ─── Kit-enforced write-capable-agent passthrough policy (#105) ──────────
// A small set of git/gh-mutating, judgment-heavy agents stay on Anthropic for
// reliability (observed in #105):
//   1. Permissions — the delegated headless session surfaces interactive
//      approval prompts (file writes, git, gh) it cannot satisfy, so the agent
//      asks the PARENT for approval instead of doing the work → task never runs.
//   2. Provider liveness — cheap providers flake (http=000000) mid-edit; a
//      half-applied write/commit is worse than a clean Opus run.
// NOTE: the former "single GLOBAL write-lock breaks parallelism" axis no longer
// applies — mr-delegate.sh no longer serializes write delegations (callers own
// isolation, e.g. per-spawn worktrees), so parallel cheap write fan-out runs
// concurrently. This list is now purely the reliability floor for named agents.
// Like KIT_PASSTHROUGH_MODELS this is a FLOOR: it takes effect with zero config
// (fixes existing installs on update) and consumers may ESCALATE more agents via
// excludeAgents but cannot DEMOTE these back onto cheap providers. Read/review/
// explore/test agents are unaffected and keep saving Opus tokens.
// Explicit floor for agents whose write risk is NOT expressible in `tools:` —
// e.g. an agent that mutates the repo through Bash (git-manager commits and
// pushes) rather than through Write/Edit. Everything expressible in `tools:` is
// now handled by isWriteCapable() below, so this list stays small on purpose.
const KIT_PASSTHROUGH_AGENTS = new Set([
  't1k-git-manager',
]);

// #121 kept ON PURPOSE, against #235's suggestion to drop it. An engine kit's
// `*-developer` agent (t1k-unity-developer, t1k-cocos-developer) does multi-file
// write work through MCP tools — `mcp__unity__manage_script` and friends — which
// no Write/Edit match can see. Removing the suffix rule would silently un-floor
// exactly the heavy implementer agents #121 was filed about. It only ever ADDS a
// floor, so the cost of keeping it is Anthropic tokens for a hypothetical
// read-only `*-developer`; the cost of dropping it is a write-capable agent on a
// third-party provider. Those are not symmetric.
const DEVELOPER_SUFFIX_FLOOR = /-developer$/;

// File-mutating tools. Bash is deliberately NOT here: nearly every agent has it
// (tester, code-reviewer, researcher), so flooring on Bash would floor the whole
// fleet and end transparent routing. Agents whose writes go through Bash are
// named in KIT_PASSTHROUGH_AGENTS above instead.
const WRITE_TOOL_RE = /\b(?:Write|Edit|MultiEdit|NotebookEdit)\b/;

/**
 * Does this agent's OWN frontmatter declare file-mutating tools? (#235)
 *
 * The floor used to match the agent NAME against a 4-entry set plus an
 * `endsWith('-developer')` heuristic, while `fm.tools` sat parsed and unused two
 * lines away. That was wrong in both directions: `t1k-docs-manager`
 * (Read, Edit, Write) and `t1k-code-simplifier` (Edit, Write, MultiEdit) were
 * routed to third-party providers, while any read-only agent merely NAMED
 * `*-developer` paid Anthropic rates for its name. Three more write-capable
 * agents were protected only incidentally by the opus floor running first, so a
 * retier to sonnet would have started routing them silently.
 *
 * Reading the declared capability means a write-capable agent from any kit is
 * floored on arrival with no interceptor edit — per code-conventions
 * "Data-Driven Over Hardcoded": deleting the static list must not break policy.
 *
 * `hasAgentFile` matters: built-ins (general-purpose, Explore) ship no `.md`, so
 * their `tools` is absent for a completely different reason than a file-based
 * agent omitting it. Treating that absence as "unrestricted" would floor every
 * built-in and end most routing outright.
 */
function isWriteCapable(fm, hasAgentFile) {
  if (!hasAgentFile) return false;      // built-in: absence is not a declaration
  const raw = typeof fm.tools === 'string' ? fm.tools.trim() : '';
  // An agent file that declares no tools (or a wildcard) has the UNRESTRICTED
  // toolset, which includes Write — floor it. This is also the safe landing spot
  // for a multi-line YAML `tools:` list, which the flat frontmatter reader
  // returns as empty.
  if (!raw || raw === '*' || raw === '[*]') return true;
  return WRITE_TOOL_RE.test(raw);
}

// ─── Kit-enforced spawn-capable-agent passthrough policy (#245) ──────────
// Sub-agent spawn tools. `\bTask\b` deliberately does NOT match the
// todo-tracking family (TaskCreate/TaskGet/TaskUpdate/TaskList/TaskOutput/
// TaskStop) — `\b` after "Task" requires a non-word char, and those all
// continue with one. It DOES match the restricted form `Task(Explore)` that
// every Unity module agent declares, which is correct: that is still a spawn,
// merely capped to one child type.
//
// `TeamCreate` is included to align with the predicate theonekit-core already
// uses for fork detection: `doctor-check-46-fork-agent-preflight.cjs` matches
// `/(\bAgent\s*\(|\bTeamCreate\s*\()/`, and `team-create-preflight-gate.cjs`
// exists specifically because an agent can declare `TeamCreate` in `tools:`
// while omitting `Agent` and still fan out an entire team. Diverging from
// core's own predicate here would be an SSOT violation — an agent core's own
// fork-preflight treats as a spawn must not be cheap-routed by this hook.
const SPAWN_TOOL_RE = /\b(?:Agent|Task|TeamCreate)\b/;

/**
 * Does this agent's OWN frontmatter declare sub-agent spawn tools? (#245)
 *
 * An agent that fans out stops doing its own task and starts doing
 * decomposition, brief-writing, coverage and synthesis. That is different work,
 * and a bad brief produces confident, well-executed, WRONG work no worker can
 * recover from — the failure mode Anthropic's multi-agent research post names
 * directly ("without detailed task descriptions, agents duplicate work, leave
 * gaps, or fail to find necessary information").
 *
 * Until now nothing floored on it. Spawn-capable agents were protected only
 * INCIDENTALLY — by the opus tier, by write-capability, by the `-developer`
 * suffix, or by being named in KIT_PASSTHROUGH_AGENTS — and all three of those
 * incidental floors were observed failing in the wild (core#848 triage, 4,462
 * router decisions):
 *
 *   general-purpose      64 routings  modelKey=sonnet  tools=*      → builtin gap
 *   t1k-researcher       15 routings  modelKey=sonnet  tools=Agent  → version skew
 *   t1k-kit-developer     3 routings  modelKey=sonnet  tools=Agent  → version skew
 *   git-manager           2 routings  modelKey=haiku   tools=Agent  → name variant
 *
 * Core ships researcher and kit-developer as `model: opus`, and t1k-git-manager
 * is the sole KIT_PASSTHROUGH_AGENTS entry — yet all three routed, because the
 * opus floor reads `model:` off whatever .md is ON DISK (a stale consumer copy
 * pinned lower walks straight past it) and the name set is an exact-string match
 * (the unprefixed `git-manager` walks past that). Reading `tools:` is immune to
 * both: `Agent`/`Task` is declared regardless of tier and regardless of
 * staleness. This is #235's lesson finished — that fix moved the WRITE floor off
 * names and onto declared tools, and left the same latent hole one axis over.
 *
 * `hasAgentFile` governs built-ins, which ship no .md and so declare no tools.
 * Their absence is not a declaration (same reasoning as isWriteCapable), but
 * unlike the write case they DO carry the unrestricted `*` toolset and CAN fan
 * out — general-purpose above is the single largest instance. Scope is therefore
 * config-gated via `modelRouter.spawnCapableFloor`:
 *   'file-agents' (default) — floor agents that declare a spawn tool in an .md.
 *   'all'                   — additionally floor the spawn-capable built-ins.
 *   'off'                   — disable the floor entirely (escape hatch).
 * The default lands the fix with no routing-volume regression; 'all' is the
 * knob for consumers who want the built-in closed too. Unlike the opus and
 * write floors this one IS softenable, because its cost is paid in tokens
 * rather than in a corrupted repo — but it is on by default.
 */
const SPAWN_CAPABLE_BUILTINS = new Set(['general-purpose', 'claude']);

function isSpawnCapable(fm, hasAgentFile, agentName, scope) {
  if (!hasAgentFile) {
    // Explore and Plan ship no spawn tool and stay routable at every scope.
    return scope === 'all' && SPAWN_CAPABLE_BUILTINS.has(agentName);
  }
  const raw = typeof fm.tools === 'string' ? fm.tools.trim() : '';
  // Mirrors isWriteCapable's empty/wildcard handling: no declaration or an
  // explicit wildcard means the UNRESTRICTED toolset, which includes Agent.
  //
  // In practice this branch is currently UNREACHABLE: the write floor above
  // runs first in the main flow and already exits on this exact condition
  // (empty/`*`/`[*]` `tools:` → isWriteCapable returns true → passthrough
  // before isSpawnCapable is ever called), and a census of all 177 agent
  // files in the ecosystem found zero multi-line-YAML `tools:` blocks and
  // zero `*`/`[*]` values — the "safe landing spot for multi-line YAML" this
  // comment used to claim does not exist today. The branch is kept anyway,
  // deliberately, as defense-in-depth: if floor ordering ever changes (or
  // isSpawnCapable is ever called standalone), an agent with no declared
  // tools restriction must still be treated as spawn-capable rather than
  // silently falling through to SPAWN_TOOL_RE.test('') === false.
  if (!raw || raw === '*' || raw === '[*]') return true;
  return SPAWN_TOOL_RE.test(raw);
}

/**
 * Normalizes `modelRouter.spawnCapableFloor` into 'off' | 'file-agents' | 'all'.
 *
 * Only an exact case-insensitive 'off' string, or the boolean `false` (the
 * obvious "flip the flag" shape a person reaches for to disable a feature),
 * turns the floor off. Every other unrecognized value — a typo'd string,
 * `true`, `null`, a number, an object, or the key being absent — FAILS CLOSED
 * to the default 'file-agents' scope rather than silently disabling
 * protection. Fail-closed-on-garbage is intentional here: this knob's failure
 * mode if it silently disabled would be "spawn-capable agents get cheap-routed
 * with nobody noticing" — exactly what the floor exists to prevent.
 *
 * NOTE — this in-code fallback is the safety net for a config that OMITS the
 * key entirely (a stripped-down or hand-edited install), not the effective
 * default a fresh consumer sees. The shipped `t1k-config-mr.json` sets
 * `spawnCapableFloor: "off"` explicitly, so sub-premium agents route with zero
 * per-install config — the same "ships an explicit value in config, code
 * fallback stays conservative" split already used for `defaultBuiltInModel`
 * and `contextGrowthAgents`. Do NOT "fix" this function to return 'off' by
 * default — that would silently remove the floor for any install whose config
 * is missing or stripped, which is exactly the garbage input this fail-closed
 * default exists to protect.
 */
function resolveSpawnCapableFloorScope(raw) {
  if (raw === false) return 'off';
  if (typeof raw === 'string') {
    const norm = raw.trim().toLowerCase();
    if (norm === 'off') return 'off';
    if (norm === 'all') return 'all';
    return 'file-agents'; // 'file-agents' itself, or any unrecognized string
  }
  return 'file-agents'; // absent, true, null, number, object, ... — fail closed
}

/**
 * Normalizes `modelRouter.writeAgentFloor` into
 * 'premium-only' | 'named-agents' | 'all'.
 *
 * THE AXIS IS TIER. The kit's routing policy has exactly one floor that is a
 * quality assertion by the agent's author: KIT_PASSTHROUGH_MODELS (opus/fable).
 * A consumer may hold that everything BELOW that line — sonnet, haiku — should
 * be routable, full stop, and that write-capability is a reliability worry to be
 * managed rather than a second, independent quality line. This knob expresses
 * that position; it does not invent a new one.
 *
 * The write floor is three separate policies wearing one `if`, and they do not
 * rest on the same evidence:
 *
 *   1. KIT_PASSTHROUGH_AGENTS — a maintainer NAME list, for agents whose writes
 *      go through Bash (t1k-git-manager commits and pushes). Invisible to `tools:`.
 *   2. DEVELOPER_SUFFIX_FLOOR — a NAME pattern; engine-kit `*-developer` agents
 *      write through MCP tools (mcp__unity__manage_script). Also invisible.
 *   3. isWriteCapable() — the agent's own `tools:` DECLARE Write/Edit/MultiEdit/
 *      NotebookEdit. This one is a declaration, readable and auditable.
 *
 * None of the three reads `model:`. So under a tier-based reading all three are
 * floors for a NON-tier reason, and 'premium-only' therefore gates all three —
 * gating only (3) would leave a sonnet agent floored by the shape of its own
 * name, which is precisely the outcome the tier reading rejects.
 *
 *   'all' (default)  — all three clauses floor. Byte-identical to pre-knob
 *                      behavior, so an existing install that sets nothing sees
 *                      no change on upgrade.
 *   'named-agents'   — only the name-based clauses (1) + (2) floor. The middle
 *                      position: a consumer who discounts a DECLARATION has not
 *                      thereby decided anything about write paths they cannot
 *                      see. NOTE this is NOT the "sonnet should route" setting —
 *                      t1k-fullstack-developer stays floored by its name.
 *   'premium-only'   — no clause floors. Only KIT_PASSTHROUGH_MODELS remains, so
 *                      the net policy is exactly "premium tiers floor, nothing
 *                      else does".
 *
 * 'off' and boolean `false` are accepted ALIASES of 'premium-only'. They are the
 * shapes a person reaches for to disable a flag, and 'off' is the vocabulary
 * resolveSpawnCapableFloorScope already established — refusing them here would
 * be a gratuitous divergence between two adjacent knobs. 'premium-only' is the
 * canonical spelling because it names the resulting POLICY rather than the
 * mechanism, which is what a consumer is actually choosing.
 *
 * Naming caveat, deliberate: this key does not itself guarantee the premium
 * floor — KIT_PASSTHROUGH_MODELS does, upstream. 'premium-only' is accurate
 * only because that floor is unconditional and has no knob of its own. If it
 * ever gains one, this value's name becomes a lie and must change with it.
 *
 * Every other unrecognized value — a typo'd string, `true`, `null`, a number, an
 * object, or the key being absent — FAILS CLOSED to 'all'. A safety floor must
 * never be disabled by a typo, and the failure mode of a silent disable here is
 * a cheap provider half-applying a write or a commit.
 *
 * NOTE the asymmetry with spawnCapableFloor's fail-closed default: there the
 * closed default is the NARROWER scope ('file-agents', not 'all'), because its
 * widest scope floors built-ins and would cost routing volume. Here 'all' IS
 * the pre-existing behavior, so fail-closed and preserve-on-upgrade coincide —
 * for a config that OMITS the key. That is a narrower claim than it used to
 * be: the shipped `t1k-config-mr.json` now sets `writeAgentFloor:
 * "premium-only"` explicitly, so a FRESH consumer's effective default is
 * open, not 'all' — only a config that drops the key entirely (a stripped-down
 * or hand-edited install) falls back to this in-code 'all'. Same split as
 * `defaultBuiltInModel`/`contextGrowthAgents`: shipped config carries the
 * effective default, code carries the fail-closed floor for when it is
 * missing. Do NOT "fix" this function to return 'premium-only' by default —
 * that would remove the fail-closed floor for exactly the installs it exists
 * to protect.
 */
function resolveWriteAgentFloorScope(raw) {
  if (raw === false) return 'premium-only';
  if (typeof raw === 'string') {
    const norm = raw.trim().toLowerCase();
    if (norm === 'premium-only' || norm === 'off') return 'premium-only';
    if (norm === 'named-agents') return 'named-agents';
    return 'all'; // 'all' itself, or any unrecognized string
  }
  return 'all'; // absent, true, null, number, object, ... — fail closed
}

// ─── Main flow ──────────────────────────────────────────────────────────
const cfg = readConfig();
const mr = cfg && cfg.modelRouter;
if (!mr) passthrough('no-config', { agent: agentName });
if (mr.enabled !== true) passthrough('disabled', { agent: agentName });
if (mr.mode !== 'transparent') passthrough('mode-' + (mr.mode || 'unset'), { agent: agentName });

const agentFile = findAgentFile(agentName);
let fm;
if (!agentFile) {
  // Built-in agents (e.g. general-purpose, Explore) have no .md file under
  // .claude/agents/. When the consumer configures `defaultBuiltInModel`, route
  // them through the normal pipeline using that model — the behavior documented
  // in rules/mr-transparent-routing.md. Only passthrough to Anthropic native
  // when NO default is configured; that preserves the #119 guard for consumers
  // who never opted into built-in routing.
  //
  // The original #119 fix unconditionally passed built-ins through, which
  // short-circuited `defaultBuiltInModel` entirely (process.exit in passthrough
  // ran before the default was read). #119's premise — that cheap providers
  // hard-fail on a built-in's missing .md (mr-delegate.sh exit 1) — is stale:
  // mr-delegate.sh treats the agent name as a label and succeeds without a .md.
  // So a configured default is safe to route. Arbitrary unknown agent names with
  // no default still passthrough (test-passthrough-opus.sh E4).
  const BUILTIN_AGENTS = new Set(['general-purpose', 'Explore', 'Plan', 'claude', 'claude-code-guide']);
  const isBuiltin = BUILTIN_AGENTS.has(agentName);
  const defaultModel = (mr && mr.defaultBuiltInModel) || undefined;
  if (!defaultModel || !isBuiltin) {
    const searched = claudeDirs.map(d => path.join(d, 'agents'));
    // An unresolvable subagent_type is a BROKEN SPAWN, not merely an unroutable
    // one — whatever the caller intended did not happen. The router is the only
    // component positioned to notice, so it must say so out loud; logging to
    // debug.jsonl alone is how `t1k-rule-creator` was spawned twice, resolved to
    // nothing both times, and went unnoticed for days (#227).
    if (!isBuiltin) {
      // Check the skills tree first: naming a skill as a subagent_type is the
      // most likely cause and by far the most actionable thing to report.
      let skillDir = null;
      for (const d of claudeDirs) {
        const cand = path.join(d, 'skills', agentName);
        try { if (fs.statSync(cand).isDirectory()) { skillDir = cand; break; } } catch { /* keep looking */ }
      }
      if (skillDir) {
        process.stderr.write(
          `[t1k:model-router] BROKEN SPAWN: subagent_type="${agentName}" matched no agent, `
          + `but a SKILL of that name exists. Skills are invoked with the Skill tool, not spawned `
          + `as subagents — this spawn resolved to nothing.\n`);
      } else {
        process.stderr.write(
          `[t1k:model-router] BROKEN SPAWN: subagent_type="${agentName}" matched no agent .md in `
          + `${searched.join(', ')} — this spawn resolved to nothing.\n`);
      }
    }
    // Still a passthrough: never block a spawn over this. The change is purely
    // making a silent failure visible.
    passthrough(isBuiltin ? 'builtin-no-md' : 'unknown-agent',
      { agent: agentName, searched, ...(isBuiltin ? {} : { brokenSpawn: true }) });
  }
  fm = { model: defaultModel };
} else {
  fm = readFrontmatter(agentFile);
}
const modelKey = fm.model || 'inherit';

// #246 — what the caller ASKED for per-spawn, captured before the floors run.
// The floors are upstream of the override resolver by design (#84/#216/#105), so
// this is the only point at which a request that is about to be dropped is still
// observable.
const droppedOverride = requestedOverride(perSpawnModel, prompt);

if (KIT_PASSTHROUGH_MODELS.has(modelKey)) {
  process.stderr.write(`[t1k:model-router] passthrough: agent=${agentName} model=${modelKey} (kit policy: Opus stays Opus)\n`);
  passthrough('kit-policy', { agent: agentName, modelKey, overrideDropped: droppedOverride });
}

// Write-capable floor. Config-gated via `modelRouter.writeAgentFloor` — the
// shipped `t1k-config-mr.json` sets 'premium-only' explicitly, so a fresh
// consumer sees NO clause floor here and KIT_PASSTHROUGH_MODELS above is the
// only passthrough policy in effect. The in-code fallback below ('all', the
// pre-knob behavior) only applies when a config omits the key entirely — see
// resolveWriteAgentFloorScope for why the tier reading gates all three clauses.
//
// `writeFloorClause` records WHICH clause matched, not merely that one did. The
// three carry different evidence, so "this agent was floored" is not an
// actionable fact on its own — a consumer tuning the knob needs to know whether
// the agent was caught by its own declaration or by a name rule it cannot see
// from the agent file.
const writeFloorScope = resolveWriteAgentFloorScope(mr && mr.writeAgentFloor);
const writeFloorClause = writeFloorScope === 'premium-only' ? null
  : KIT_PASSTHROUGH_AGENTS.has(agentName) ? 'named-agent'
  : DEVELOPER_SUFFIX_FLOOR.test(agentName) ? 'developer-suffix'
  : (writeFloorScope === 'all' && isWriteCapable(fm, Boolean(agentFile))) ? 'declared-tools'
  : null;
if (writeFloorClause) {
  process.stderr.write(`[t1k:model-router] passthrough: agent=${agentName} (kit policy: write-capable agent stays on Anthropic; clause=${writeFloorClause})\n`);
  passthrough('kit-policy-write-agent', { agent: agentName, modelKey, tools: fm.tools || null, scope: writeFloorScope, clause: writeFloorClause, overrideDropped: droppedOverride });
}

// Spawn-capable floor (#245) — separate passthrough reason from the write floor
// so the two are distinguishable in debug.jsonl and in the routing dashboard.
const spawnFloorScope = resolveSpawnCapableFloorScope(mr && mr.spawnCapableFloor);
if (spawnFloorScope !== 'off'
    && isSpawnCapable(fm, Boolean(agentFile), agentName, spawnFloorScope)) {
  process.stderr.write(`[t1k:model-router] passthrough: agent=${agentName} (kit policy: spawn-capable agent orchestrates; stays on Anthropic)\n`);
  passthrough('kit-policy-spawn-agent', { agent: agentName, modelKey, tools: fm.tools || null, scope: spawnFloorScope, overrideDropped: droppedOverride });
}

const excluded = Array.isArray(mr.excludeAgents) && mr.excludeAgents.includes(agentName);
if (excluded) passthrough('excluded', { agent: agentName, modelKey, overrideDropped: droppedOverride });

const requiredCaps = detectRequiredCapabilities(prompt, fm);
const securityCfg = (mr && mr.security) || {};

// MCP guard (#109), amended by the per-agent forwarding design (plans/260822-
// 0711-mcp-server-forwarding-design.md §5.2): cheap providers do not have the
// consumer's MCP servers configured UNLESS this agent's own `tools:` grants
// specific mcp__ tools AND at least one of their servers is on the
// operator's allowlist — in which case mr-delegate.sh forwards exactly that
// subset (re-derived independently there, §5.3; nothing crosses the process
// boundary beyond the agent name, which already crosses).
//
// Bug fix folded in here (Finding 1, observed live 2026-08-22): the OLD
// predicate floored on `requiredCaps.includes('mcp')` alone, which case 4 of
// detectRequiredCapabilities sets from prompt TEXT matching `mcp__` — so a
// prompt merely discussing an mcp__ tool name floored an agent that holds
// NONE. MCP need is a property of the agent's granted tools, not the
// prompt's vocabulary; the prompt/name heuristic is now used ONLY where
// `tools:` cannot prove a negative (built-ins with no `.md`; an unrestricted
// `tools:` we cannot resolve; agents whose NAME signals dynamic/runtime MCP
// discovery with no static tool list, e.g. t1k-mcp-manager, which declares
// zero mcp__ entries in `tools:` by design).
const { servers: agentMcpServers, resolvable: mcpSurfaceKnown } =
  deriveMcpServersFromTools(fm, Boolean(agentFile));
const allowedMcpServers = resolveAllowedMcpServers(securityCfg);
const routableMcpServers = agentMcpServers.filter(s => allowedMcpServers.has(s));

let mcpFloor = false;
if (agentMcpServers.length > 0) {
  // Ground truth: this agent DOES statically declare specific MCP tools.
  // Floor only if NONE of its declared servers survive the allowlist.
  mcpFloor = routableMcpServers.length === 0;
} else if (!mcpSurfaceKnown) {
  // Cannot prove a negative (built-in, or unrestricted tools:) — preserve
  // today's conservative heuristic exactly.
  mcpFloor = requiredCaps.includes('mcp') || agentName.includes('mcp');
} else if (agentName.includes('mcp')) {
  // tools: is resolvable and MCP-free, but the agent's own name signals a
  // dynamic/runtime MCP-discovery role a static list cannot capture.
  mcpFloor = true;
}
// else: resolvable, empty, name doesn't say "mcp" -> routes regardless of
// prompt content. This is Finding 1's fix.

if (mcpFloor) {
  process.stderr.write(`[t1k:model-router] passthrough: agent=${agentName} requires MCP; cheap providers lack MCP server config\n`);
  passthrough('mcp-required', { agent: agentName, modelKey, requiredCaps, agentMcpServers, routableMcpServers });
}

// ─── Data-classification gate (#158 P0) ─────────────────────────────────────
// Before routing ANY content to a third-party provider, classify the prompt for
// secrets/credentials/private-keys/PII. When a blocked class is detected, do NOT
// route — passthrough so the task runs on Anthropic native (the trusted path).
// Precision-first: a false positive only costs a passthrough; a false negative
// leaks a secret across the provider boundary. Config lives under
// modelRouter.security.dataClassification; enabled by default.
const dcCfg = securityCfg.dataClassification || {};
const dcEnabled = dcCfg.enabled !== false; // default ON
let dataClass = ''; // audit breadcrumb for the route-decision log
if (dcEnabled && dataClassifier) {
  let cls;
  try { cls = dataClassifier.classify(typeof prompt === 'string' ? prompt : JSON.stringify(prompt)); }
  catch { cls = null; }
  if (cls && Array.isArray(cls.classes) && cls.classes.length > 0) {
    // blockClasses (optional) narrows which detected classes actually block.
    // Absent/empty => block on ANY detected sensitive class (secure default).
    const blockClasses = Array.isArray(dcCfg.blockClasses) ? dcCfg.blockClasses : null;
    const blocked = blockClasses && blockClasses.length > 0
      ? cls.classes.filter((c) => blockClasses.includes(c))
      : cls.classes;
    if (blocked.length > 0) {
      process.stderr.write(`[t1k:model-router] passthrough: agent=${agentName} — sensitive data detected (${blocked.join(',')}); keeping on Anthropic native\n`);
      passthrough('data-class-blocked', { agent: agentName, modelKey, dataClasses: blocked, detector: cls.sample });
    }
    dataClass = cls.classes.join(',');
  }
}

const providersCfg = readProvidersConfig();

// ─── Per-spawn model override (#153) ────────────────────────────────────────
// Honor an explicit per-call model (tool_input.model or an `mr-model:` prompt
// directive) BEFORE capability-based selection. Reached only for routable agents
// (the opus/write-agent floors ran earlier), so it never pierces the opus floor.
// Disabled via modelRouter.perSpawnModelOverride:false. The resolved provider is
// still validated by the allowlist gate below (#158).
let pick = null;
let selectionSource = null;
if (modelOverride && mr.perSpawnModelOverride !== false) {
  const ov = modelOverride.resolveModelOverride({
    toolInputModel: perSpawnModel,
    promptText: typeof prompt === 'string' ? prompt : JSON.stringify(prompt),
    providersCfg,
    modelMapping: mr.modelMapping,
    shortToFull: SHORT_TO_FULL,
  });
  if (ov && ov.provider && ov.model) {
    pick = { provider: ov.provider, model: ov.model };
    selectionSource = ov.source;
    process.stderr.write(`[t1k:model-router] per-spawn model override: agent=${agentName} → ${ov.provider}/${ov.model} (${ov.source})\n`);
  }
}

const allowedProviderSet = getAllowedProviderSet(securityCfg);

// #249 — context-growth preference. A built-in agentic sub-agent is dispatched
// with a short instruction and reads its real context in afterwards, so the
// prompt-length rule that feeds `long-context` is structurally blind to it
// (see DEFAULT_CONTEXT_GROWTH_AGENTS). Prefer a long-context-capable model for
// these agents, ahead of the cost-driven load balancer.
//
// `tool-use` is demanded alongside `long-context`, and that pairing is load-
// bearing: the candidate sort for a long-context task is context_window DESC,
// so without it the widest window in the catalog wins whether or not it can
// call a tool. The shipped catalog contains exactly that trap — minimax-m2.7
// and minimax-m2.5 both declare ["text","long-context"] at 1,000,000 tokens,
// the widest windows in the catalog, and either would take every one of these
// delegations outright on window size alone. Both are `enabled: false` today,
// so the trap is latent rather than live — re-enable one without this clause
// and it fires immediately. A model that cannot call tools does not fail
// loudly: it returns a confident answer having read nothing (the #229
// gpt-5.6-luna failure mode), and nothing downstream can detect it. A dead hop
// is recoverable; a fabricated one is not.
//
// NOT minimax-m3: it shares the 1M window but DOES declare `tool-use`, added
// from measurement in #249 (5/5 probes made a real Read call). Do not cite it
// as the cautionary example — an earlier revision of this comment did, and
// that staleness cost a full investigation cycle chasing a hypothesis the
// catalog and the telemetry both refuted.
//
// Deliberately a PREFERENCE, not a required capability. Making it required
// would (a) break the standing contract that built-ins stay routable when no
// long-context model is enabled, surrendering the savings on what was 89% of
// routed traffic on 2026-08-14, and (b) over-correct: Explore's median payload
// that day was ~5.2K tokens at 162/183 success — most of these fit a 128K
// window fine. When a capable model exists we use it; when none does we fall
// through to the existing path unchanged, exactly as before this fix.
const growthPreferred = (!pick
    && agentName
    && contextGrowthAgents(mr).has(agentName)
    && !requiredCaps.includes('long-context'))
  ? pickFromCandidates(requiredCaps.concat(['long-context', 'tool-use']), providersCfg, allowedProviderSet, mr)
  : null;

const loadBalanced = (pick || growthPreferred) ? null : pickLoadBalanced(requiredCaps, providersCfg, allowedProviderSet, mr);
const ruleBased = (pick || growthPreferred || loadBalanced) ? null : pickFromCandidates(requiredCaps, providersCfg, allowedProviderSet, mr);

if (pick) {
  // override already set — skip capability/mapping selection
} else if (growthPreferred) {
  pick = growthPreferred;
  selectionSource = `contextGrowth:${growthPreferred.provider}/${growthPreferred.model}`;
  process.stderr.write(`[t1k:model-router] context-growth agent=${agentName} → ${growthPreferred.provider}/${growthPreferred.model} (long-context preferred; payload arrives post-spawn)\n`);
} else if (loadBalanced) {
  // Quota split across provider pools (modelRouter.loadBalance) — runs before
  // capability selection but only for tasks whose required caps the target
  // satisfies (specialised tasks still fall through to pickFromCandidates).
  pick = loadBalanced;
  selectionSource = `loadBalance:${loadBalanced.provider}/${loadBalanced.model}`;
  process.stderr.write(`[t1k:model-router] load-balanced: agent=${agentName} → ${loadBalanced.provider}/${loadBalanced.model}\n`);
} else if (ruleBased) {
  pick = ruleBased;
  selectionSource = requiredCaps.length > 0
    ? `rules:${requiredCaps.join(',')}`
    : `tier:${ruleBased.tier}`;
} else {
  // Fallback: v2 static modelMapping (preserves backward compat when no
  // candidate matches the required capability set).
  // Try raw key first, then cross-form alias (shorthand→full or full→shorthand)
  // so config authored with either form works. Fixes #61.
  const lookupCandidates = [modelKey, SHORT_TO_FULL[modelKey], FULL_TO_SHORT[modelKey]].filter(Boolean);
  let mapping = null;
  let matchedKey = null;
  if (mr.modelMapping) {
    for (const k of lookupCandidates) {
      if (mr.modelMapping[k]) { mapping = mr.modelMapping[k]; matchedKey = k; break; }
    }
  }
  if (mapping && mapping.provider && mapping.model) {
    if (getExhaustedProviders(providersCfg).has(mapping.provider)) {
      // Same daily-budget guard the capability path applies (pickFromCandidates).
      // Without it, an exhausted provider skipped by the rule path is silently
      // re-picked here, so no candidate is within budget → passthrough.
      process.stderr.write(`[t1k:model-router] ignored modelMapping '${matchedKey}' → ${mapping.provider}/${mapping.model}: provider is over its daily budget\n`);
      emitBudgetEvent(mapping.provider); // deduped to one event per provider per UTC day
      logDebug({
        event: 'provider-budget',
        provider: mapping.provider,
        decision: 'skip-exhausted-mapping',
        agent: agentName,
        modelKey,
      });
    } else if (isDispatchableTarget(providersCfg, mapping)) {
      pick = { provider: mapping.provider, model: mapping.model };
      selectionSource = `modelMapping:${matchedKey}`;
    } else {
      process.stderr.write(`[t1k:model-router] ignored modelMapping '${matchedKey}' → ${mapping.provider}/${mapping.model}: target is unknown or disabled\n`);
      logDebug({
        event: 'intercept',
        decision: 'mapping-target-not-enabled',
        agent: agentName,
        modelKey,
        mappedProvider: mapping.provider,
        mappedModel: mapping.model,
      });
    }
  }
}

if (!pick) {
  passthrough('no-candidate', {
    agent: agentName, modelKey, requiredCaps,
    providersAvailable: providersCfg && providersCfg.providers
      ? Object.keys(providersCfg.providers).length : 0,
  });
}

// #249 part 2 — this agent has recently been abandoned by the client over
// context size. Re-attempting is a doomed hop that still bills a full per-hop
// timeout; Anthropic is where the work has to go. See DEFAULT_OVERFLOW_GUARD.
{
  const ogCfg = overflowGuardCfg(mr);
  if (ogCfg.enabled) {
    const seen = recentOverflowCount(agentName, ogCfg);
    if (seen && seen.overflows >= ogCfg.threshold) {
      process.stderr.write(`[t1k:model-router] passthrough: agent=${agentName} — ${seen.overflows} context-overflow failures in its last ${seen.samples} delegations; keeping on Anthropic native\n`);
      passthrough('recent-context-overflow', {
        agent: agentName,
        provider: pick.provider,
        model: pick.model,
        overflows: seen.overflows,
        samples: seen.samples,
      });
    }
  }
}

// Defense-in-depth for every selection source. Rule-based candidates and model
// overrides already consult the catalog, but keeping the invariant here ensures
// a future selector cannot dispatch an unknown/disabled provider or model.
if (!isDispatchableTarget(providersCfg, pick)) {
  process.stderr.write(`[t1k:model-router] passthrough: agent=${agentName} — target '${pick.provider}/${pick.model}' is unknown or disabled; keeping on Anthropic native\n`);
  passthrough('target-not-enabled', {
    agent: agentName,
    modelKey,
    provider: pick.provider,
    model: pick.model,
    selectionSource,
  });
}

// ─── Provider allowlist gate (#158 P0) ──────────────────────────────────────
// Treat every non-Anthropic hop as an untrusted subservice: only route to a
// provider explicitly vetted in modelRouter.security.allowedProviders. When the
// key is present and non-empty, a pick for any other provider is rejected
// (passthrough to Anthropic). When ABSENT/empty, allow-all (legacy configs that
// predate this gate keep working) — the shipped config declares the allowlist so
// new installs are locked down. mr-delegate.sh enforces the SAME allowlist on
// every failover.pipe hop (weakest-link: a chain is only as safe as its hops).
const allowedProviders = Array.isArray(securityCfg.allowedProviders)
  ? securityCfg.allowedProviders
  : null;
if (allowedProviders && allowedProviders.length > 0 && !allowedProviders.includes(pick.provider)) {
  process.stderr.write(`[t1k:model-router] passthrough: agent=${agentName} — provider '${pick.provider}' not in security.allowedProviders; keeping on Anthropic native\n`);
  passthrough('provider-not-allowlisted', { agent: agentName, modelKey, provider: pick.provider, allowedProviders });
}

// $HOME ONLY — never `claudeDirs` (cwd + ancestors).
//
// This hook is registered globally and runs in EVERY session, including
// sessions opened on a repo we do not control. `mr-delegate.sh` is handed
// straight to `spawnSync('bash', …)`, so resolving it from a project-local
// `.claude/scripts/` gives any repo that plants that file arbitrary code
// execution under the user's account — the exact trust-boundary class this
// hook's own settings.json hardening closes (#165 review finding 2; PR #172's
// fixture demonstrates the primitive by writing `$IPROJECT/.claude/scripts/
// mr-delegate.sh`).
//
// #65 (project → $HOME fallback) and #137 (nested-project layouts) are still
// satisfied: both were about consumers finding the script when there is no
// project-local copy, and the answer for both is the $HOME copy. post-install
// syncs `mr-*.sh` into `$HOME/.claude/scripts/` precisely so a project-local-
// only checkout still resolves — by being PROMOTED to $HOME, not by being
// executed in place.
const scriptPath = [
  path.join(process.env.HOME || os.homedir(), '.claude', 'scripts', 'mr-delegate.sh'),
].find(fileExists);
if (!scriptPath) passthrough('script-missing', { agent: agentName, pick });

let result;
try {
  // Pass --original-model so mr-delegate.sh can record the true model swap
  // in its savings telemetry event (requestModel=modelKey, routedModel=pick.model).
  // Without this, the script defaults requestModel=routedModel which makes the
  // worker's by-original-model breakdown meaningless. See #76 / contracts 35-36.
  // Outer spawnSync budget must cover every term mr-delegate.sh can spend.
  // Pre-#88 this was fixed at 320s, which is < 2 × 300s primary timeout,
  // so the failover hop got strangled mid-call (stacked-timeout bug,
  // confirmed via DOTS-AI 2026-05-29 telemetry — see issue #88).
  //
  // #261 C: the sum was `perHop × hops + buffer`, which assumes each hop runs
  // its ceiling exactly ONCE. mr-delegate.sh's in-hop retry re-enters a FULL
  // `timeout $MR_PER_HOP_TIMEOUT_SEC` on a transient rate-limit, and every hop
  // also pays a liveness probe first — so the real worst case is
  // (perHop × (1 + maxRetries) + probe) × hops + buffer. The arithmetic now
  // lives in scripts/mr-defaults.cjs computeOuterBudgetSec() so it is unit
  // testable rather than asserted inline.
  //
  // #261 A: the ceiling is per-AGENT. contextGrowthAgents pull their real
  // payload in after the spawn and legitimately run long; their pass rate
  // tracked the ceiling 10% → 20% → 43% as it rose 180 → 240 → 300.
  const failoverCfg = (mr && mr.failover) || {};
  const perHopSec = (mrDefaults && mrDefaults.resolvePerHopTimeoutSec)
    ? mrDefaults.resolvePerHopTimeoutSec(failoverCfg, agentName, contextGrowthAgents(mr))
    : (Number(failoverCfg.perHopTimeoutSec)
      || (mrDefaults && mrDefaults.PER_HOP_TIMEOUT_SEC)
      || 300);  // mr-ssot:perHopTimeoutSec
  // Count hops exactly as mr-delegate.sh's _build_pipe_hops does: the selected
  // primary runs as hop 0, then every failover.pipe entry that is NOT a
  // duplicate of it. Using pipe.length alone drops the primary hop whenever the
  // pick is not itself in the pipe (the common tier/capability-selected case),
  // so the budget covered one fewer hop than actually ran and the last failover
  // hop was SIGTERM'd mid-call — the exact stacked-timeout bug #88 addressed.
  const configuredPipe = Array.isArray(mr.failover && mr.failover.pipe) ? mr.failover.pipe : [];
  const hopCount = configuredPipe.length > 0
    ? 1 + configuredPipe.filter(h => h && !(h.provider === pick.provider && h.model === pick.model)).length
    : 2;
  const bufferSec = (mrDefaults && mrDefaults.OUTER_BUDGET_BUFFER_SEC) || 30;  // mr-ssot:outerBudgetBufferSec
  const inHopCfg = failoverCfg.inHopRetry || {};
  const maxRetries = inHopCfg.enabled === false
    ? 0
    : Number.isFinite(Number(inHopCfg.maxRetries))
      ? Number(inHopCfg.maxRetries)
      : (mrDefaults && mrDefaults.INHOP_MAX_RETRIES) || 1;
  const probeSec = Number(process.env.MR_PROBE_TIMEOUT_S)
    || (mrDefaults && mrDefaults.PROBE_TIMEOUT_SEC)
    || 30;
  const outerBudgetSec = (mrDefaults && mrDefaults.computeOuterBudgetSec)
    ? mrDefaults.computeOuterBudgetSec({ perHopSec, hopCount, maxRetries, probeSec, bufferSec })
    : ((perHopSec * (1 + maxRetries) + probeSec) * hopCount) + bufferSec;
  const outerBudgetMs = outerBudgetSec * 1000;

  result = spawnSync('bash', [
    scriptPath,
    agentName,
    typeof prompt === 'string' ? prompt : JSON.stringify(prompt),
    '--provider', pick.provider,
    '--model', pick.model,
    '--original-model', modelKey,
    '--selection-source', selectionSource,
  ], {
    encoding: 'utf8',
    timeout: outerBudgetMs,
    maxBuffer: 20 * 1024 * 1024,
    // MR_PER_HOP_TIMEOUT_SEC: hand the RESOLVED per-agent ceiling down rather
    // than letting bash re-derive it (#261 A). The outer budget above is sized
    // from this exact number, so the two can never disagree at runtime; bash's
    // own resolution stays for the standalone `mr-delegate.sh` path, and
    // tests/test-mr-per-agent-timeout.sh pins the two implementations together.
    env: { ...process.env, CLAUDE_PROJECT_DIR: projectRoot, MR_PER_HOP_TIMEOUT_SEC: String(perHopSec) },
  });
} catch (e) {
  emitDelegationFailure(agentName, pick, modelKey, 1, 'spawn-exception');
  passthrough('spawn-exception', { agent: agentName, pick, err: String(e && e.message || e) });
}

if (!result || result.error) {
  const errStr = result && String(result.error || '');
  const isTimeout = /ETIMEDOUT|timed out/i.test(errStr);
  emitDelegationFailure(agentName, pick, modelKey, isTimeout ? 124 : 1, isTimeout ? 'spawn-timeout' : 'spawn-error');
  passthrough('spawn-error', { agent: agentName, pick, err: errStr });
}

// Read stdout/stderr BEFORE the exit-42 branch below. They used to be read
// only at this point (after the 42 branch's process.exit(0)), so on the exit
// 42 path — the ONLY path that most needs them — both streams were discarded
// outright and the passthrough carried nothing but `{ agent, pick }`. Nothing
// downstream could tell a real provider outage from a client-side non-provider
// failure (budget cap, turn limit, unrecognized-model) that also exits 42, or
// join the row back to the delegate's own per-call trace in traces.jsonl.
const stdout = (result.stdout || '').trim();
const stderr = (result.stderr || '').trim();
const ok = result.status === 0;

// Bounded tail — stdout/stderr can run to the 20MB maxBuffer ceiling above
// (a runaway hop dumping a stack trace or a large partial result), and this
// value is appended verbatim into a JSONL debug row. 4000 chars is enough to
// carry the failure banner mr-delegate.sh prints plus the last few hop lines
// without ballooning debug.jsonl entries.
const STDERR_TAIL_CAP = 4000;
function stderrTail(text) {
  if (!text) return '';
  return text.length > STDERR_TAIL_CAP ? text.slice(-STDERR_TAIL_CAP) : text;
}

// mr-delegate.sh prints two single-line markers to stderr (never stdout, so a
// JSON result is never corrupted): `[t1k:mr-trace-id] <id>` — the CALL_ID that
// keys its own per-call row in ~/.model-router/traces.jsonl, printed once near
// script start on every real invocation — and, only on the exit-42 exhaustion
// path, `[t1k:mr-terminal-class] non-provider|provider-exhausted` recording
// whether the terminal hop's failure was actually classified as a provider
// fault (see mr-delegate.sh's IS_PROVIDER_FAIL / NON_PROVIDER_FAILURE_RE).
function extractMarker(text, name) {
  if (!text) return null;
  const m = text.match(new RegExp(`\\[t1k:${name}\\]\\s+(\\S+)`));
  return m ? m[1] : null;
}
const traceId = extractMarker(stderr, 'mr-trace-id');
const terminalClass = extractMarker(stderr, 'mr-terminal-class');

// EXIT_ALL_PROVIDERS_FAILED: 42 — mr-delegate.sh signals all cheap providers
// exhausted and the user opted into Anthropic fallback (MR_FALLBACK_TO_ANTHROPIC=1
// or modelRouter.failover.fallbackToAnthropic: true in t1k-config-mr.json).
// Passthrough to let the original Task spawn on Anthropic instead of returning
// a useless partial-output error banner.
if (result.status === 42) {
  // `terminalClass === 'non-provider'` means mr-delegate.sh's own hop loop
  // already determined the terminal failure was NOT a provider fault (a local
  // cap or a client-side rejection that correctly broke the pipe per
  // NON_PROVIDER_FAILURE_RE) — reporting that as `all-providers-failed` mislabels
  // ~a quarter of exhaustions as a provider outage. Route it to a distinct
  // decision value instead; the pipe's control flow (still passthrough to
  // Anthropic, still exit 42) is unchanged.
  const reason = terminalClass === 'non-provider' ? 'non-provider-failure' : 'all-providers-failed';
  const bannerLabel = terminalClass === 'non-provider' ? 'A non-provider failure' : 'All cheap providers failed';
  process.stderr.write(`[t1k:model-router] ${bannerLabel} for agent=${agentName}; falling back to Anthropic\n`);
  passthrough(reason, {
    agent: agentName,
    pick,
    status: result.status,
    stderrTail: stderrTail(stderr),
    modelKey,
    selectionSource,
    traceId,
  });
}
const promptChars = typeof prompt === 'string' ? prompt.length : JSON.stringify(prompt).length;

// Delegation-outcome telemetry for any path where mr-delegate.sh RAN TO
// COMPLETION (exit 0, non-zero, or 42) is emitted by the script itself
// (_emit_delegation_outcome), which records the authoritative row: a real
// delegation_id plus the actual post-failover provider/model. The interceptor
// must NOT re-emit here — doing so wrote a SECOND, less-accurate delegation row
// per delegation (null delegation_id, stale pre-failover pick), double-counting
// every routed delegation in D1's type='delegation' rows. The only outcome the
// script cannot record is a spawn that never ran (spawn-exception /
// spawn-timeout / spawn-error), which the emitDelegationFailure() calls in the
// result.error branch above still cover as the safety net.

// Banner is the user-visible signal that routing fired. The `agent[model]`
// format gives at-a-glance visibility into the swap that core's
// task-description-model-badge.cjs (#349) was designed for but never
// delivers in the routed case (deny path drops its modified description).
// Putting the badge here means transparent-routing consumers see the
// model on every spawn, in the same field where the cheap output appears.
const reasonLine = `[t1k:mr] ✓ ${agentName}[${pick.model}] — ${pick.provider} (${selectionSource})`;

logDebug({
  event: 'intercept',
  decision: 'route',
  agent: agentName,
  modelKey,
  requiredCaps,
  pick,
  selectionSource,
  promptChars,
  dataClass: dataClass || undefined, // #158 audit: sensitive classes that passed the gate (none blocked)
  delegateExit: result.status,
  delegateOk: ok,
});

// Per https://code.claude.com/docs/en/hooks: `systemMessage` is shown to the
// USER only, NOT injected into Claude's context. Only `permissionDecisionReason`
// reaches the calling LLM. The kit's prior design put the cheap-model output
// in systemMessage — which meant the parent session received only the banner
// (the reason line) and the actual delegated answer was invisible to Claude.
// Symptom: agent spawn returns `[t1k:model-router] Delegated ...` with no body.
//
// Fix: put the FULL body into permissionDecisionReason so the LLM sees the
// cheap-model output. Keep systemMessage too so the user UI also shows it.
const body =
  `${reasonLine}\n\n` +
  (ok ? '' : `(mr-delegate.sh exited ${result.status} — output may be partial)\n\n`) +
  `--- Delegated agent output ---\n${stdout || '(empty)'}` +
  (stderr ? `\n\n--- stderr ---\n${stderr}` : '');

const payload = {
  hookSpecificOutput: {
    hookEventName: 'PreToolUse',
    permissionDecision: 'deny',
    permissionDecisionReason: body,
  },
  systemMessage: body,
};

process.stdout.write(JSON.stringify(payload));
process.exit(0);

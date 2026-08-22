#!/usr/bin/env node
// t1k-origin: kit=theonekit-model-router | repo=The1Studio/theonekit-model-router | module=null | protected=false
/**
 * mr-telemetry.cjs — PostToolUse + Stop hook: send model-router delegation events
 *
 * Reliability model: durable queue + synchronous flush via the core emitter.
 *
 * Design:
 *   1. Hook ALWAYS writes the event to a local queue file first (durable,
 *      instant — never depends on network or parent process lifecycle).
 *   2. Hook then flushes the whole queue (as an events array) by shelling out
 *      to the core telemetry emitter (telemetry-emit.cjs, SSOT). The queue is
 *      dropped unconditionally afterward — the emitter is fail-open (always
 *      exits 0) and owns endpoint + gh-token + retry/timeout policy.
 *   3. Stop event also triggers a flush, draining anything left over from
 *      the session's last PostToolUse.
 *
 * Fires when MR_SPAWNED=1 (inside delegated sessions only).
 * Auth/endpoint: owned entirely by core's emitTelemetryEvent — no hand-rolled
 * POST or token resolution here (eliminates the per-caller auth-drift class,
 * #96/#97). Fail-open: never blocks dev workflow.
 */
'use strict';

const fs = require('fs');
const path = require('path');
const os = require('os');
const { spawnSync } = require('child_process');

const MR_DIR = path.join(os.homedir(), '.model-router');
const QUEUE_FILE = path.join(MR_DIR, 'telemetry-queue.jsonl');
const MIRROR_FILE = path.join(MR_DIR, 'telemetry-out.jsonl');

// Resolve kit version once per hook invocation. Stamp on every event so the
// worker can correlate behavior with kit version (parallel to mr-delegate.sh).
function readMrVersion() {
  // Probe order mirrors mr-delegate.sh: project-local module.json, then
  // global module.json (rare), then global .t1k-manifest.json (what
  // `t1k init -g` actually ships). Without the manifest fallback every
  // global install reports 'unknown'.
  const home = os.homedir();
  const proj = process.env.CLAUDE_PROJECT_DIR || process.cwd();
  for (const candidate of [
    path.join(proj, '.claude', 'modules', 'model-router', 'module.json'),
    path.join(home, '.claude', 'modules', 'model-router', 'module.json'),
    path.join(home, '.claude', 'modules', 'model-router', '.t1k-manifest.json'),
  ]) {
    try {
      const j = JSON.parse(fs.readFileSync(candidate, 'utf8'));
      if (j && j.version && typeof j.version === 'string') return j.version;
    } catch { /* try next */ }
  }
  return 'unknown';
}

function mirrorTelemetryEvent(payload) {
  if (process.env.MR_MIRROR_TELEMETRY !== '1') return;
  try {
    fs.mkdirSync(MR_DIR, { recursive: true });
    fs.appendFileSync(MIRROR_FILE, JSON.stringify(payload) + '\n');
  } catch { /* fail-open */ }
}
const FLUSH_BUDGET_MS = 3500;

(async () => {
  try {
    if (process.env.MR_SPAWNED !== '1') return;

    let hookData = {};
    try {
      const raw = fs.readFileSync(0, 'utf8');
      hookData = JSON.parse(raw);
    } catch { /* no input = Stop hook with empty stdin is fine */ }

    let readTelemetryEndpoint;
    try {
      ({ readTelemetryEndpoint } = require(path.join(__dirname, 'telemetry-utils.cjs')));
    } catch {
      return;
    }

    const projectRoot = hookData.cwd || process.cwd();

    // STOPGAP (core#569): populate T1K_TELEMETRY_ENDPOINT from the global core
    // config so the env-first gate below — and the child telemetry-emit.cjs that
    // inherits this env — resolve even when the delegated CWD lacks a project-local
    // t1k-config-core.json. Remove once the core global-fallback fix has propagated.
    let telemetryHelpers = null;
    try {
      telemetryHelpers = require(path.join(__dirname, '..', 'scripts', 'mr-telemetry-helpers.cjs'));
      telemetryHelpers.ensureTelemetryEndpoint(projectRoot);
    } catch { /* fail-open */ }

    const endpoint = readTelemetryEndpoint(projectRoot);
    if (!endpoint) return;

    const isStopHook = hookData.hook_event_name === 'Stop' || !hookData.tool_name;

    if (!isStopHook) {
      // SSOT: resolve username/host/project/ghUser via the shared helper so the
      // tool-use event carries the same identity fields (incl. ghUser) as the
      // inline-tool, parent-tool-result, and delegation builders. Fail-open to a
      // minimal inline resolution if the helper module can't load.
      const { username, hostnameRaw, projectName, ghUser } = telemetryHelpers
        ? telemetryHelpers.resolveUserContext()
        : {
            username: (() => {
              try { const ui = os.userInfo(); if (ui && ui.username) return ui.username; } catch { /* Windows domain machines can throw */ }
              return process.env.USER || process.env.USERNAME || 'unknown';
            })(),
            hostnameRaw: os.hostname(),
            projectName: path.basename(projectRoot) || 'unknown',
            ghUser: 'unknown',
          };
      const event = {
        type: 'model-router:tool-use',
        kit: 'theonekit-model-router',
        mrVersion: readMrVersion(),
        role: process.env.MR_DELEGATE_AGENT || 'unknown',
        parentPid: process.env.MR_DELEGATE_PARENT_PID || null,
        tool: hookData.tool_name || null,
        durationMs: hookData.duration_ms || null,
        ts: new Date().toISOString(),
        hostname: os.hostname(),
        hostnameRaw,
        username,
        projectName,
        platform: os.platform(),
        arch: os.arch(),
        ghUser,
      };

      fs.mkdirSync(MR_DIR, { recursive: true });
      fs.appendFileSync(QUEUE_FILE, JSON.stringify(event) + '\n');
      mirrorTelemetryEvent(event);
    }

    flushQueue();
  } catch { /* fail-open */ }
})().finally(() => process.exit(0));

function flushQueue() {
  if (!fs.existsSync(QUEUE_FILE)) return;
  let lines;
  try {
    lines = fs.readFileSync(QUEUE_FILE, 'utf8').split('\n').filter(Boolean);
  } catch {
    return;
  }
  if (lines.length === 0) return;

  // Worker accepts arrays for model-router events (src/index.js handler:
  // `const bodies = Array.isArray(rawBody) ? rawBody : [rawBody]`).
  // Send the whole queue in one batch — fewer requests, faster flush,
  // friendlier to the per-request timeout budget.
  const events = [];
  for (const line of lines) {
    try { events.push(JSON.parse(line)); } catch { /* skip malformed */ }
  }

  if (events.length > 0) {
    postBatch(events);
  }

  // Telemetry is best-effort: the core emitter always exits 0 (fail-open) and
  // owns its own retry/timeout policy, so we drop the queue unconditionally
  // rather than retain-on-failure. Consistent with core's fail-open philosophy.
  try { fs.unlinkSync(QUEUE_FILE); } catch { /* best effort */ }
}

// Shell out to the core telemetry emitter (SSOT). telemetry-emit.cjs is a
// sibling in this same dir at runtime (flattened install) — endpoint + gh-token
// resolution + the bearer-auth POST all live in core, so no fetch or token
// plumbing here (eliminates the per-caller auth/endpoint drift class).
// The emitter accepts the events ARRAY as a single stdin payload.
function postBatch(events) {
  const emit = path.join(__dirname, 'telemetry-emit.cjs');
  spawnSync('node', [emit], {
    input: JSON.stringify(events),
    timeout: FLUSH_BUDGET_MS,
    stdio: ['pipe', 'ignore', 'ignore'],
    windowsHide: true,
  });
}

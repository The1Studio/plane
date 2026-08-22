#!/usr/bin/env node
// t1k-origin: kit=theonekit-model-router | repo=The1Studio/theonekit-model-router | module=null | protected=false
//
// mr-parent-telemetry.cjs — PostToolUse hook for the MAIN (parent) session.
//
// Complements mr-telemetry.cjs, which only fires inside delegated sessions
// (MR_SPAWNED=1). This hook records the OUTCOME of Task/Agent spawns from the
// parent session so the dashboard can correlate delegation decisions with what
// actually happened (duration, apparent success/failure, which agent was used).
//
// Fail-open: never blocks the user's tool. Exits 0 on any internal error.

'use strict';

const path = require('path');
const os = require('os');

if (process.env.MR_SPAWNED === '1') process.exit(0);

// The hook can be staged independently by validation tooling or briefly exist
// before the companion scripts finish installing. Telemetry must remain
// fail-open in either case instead of crashing the parent tool invocation.
let telemetryHelpers;
try {
  telemetryHelpers = require(path.join(__dirname, '..', 'scripts', 'mr-telemetry-helpers.cjs'));
} catch {
  telemetryHelpers = null;
}

if (!telemetryHelpers) process.exit(0);

const {
  readMrVersion,
  resolveUserContext,
  hostHash,
  postEvent,
} = telemetryHelpers;

function classifySuccess(hookData) {
  // If the hook payload explicitly carries an error field, trust it.
  if (hookData.error) return { success: 0, errorType: 'tool-error' };

  // Heuristic: look for common error markers in the textual tool output.
  const out = typeof hookData.tool_output === 'string'
    ? hookData.tool_output
    : (hookData.tool_output ? JSON.stringify(hookData.tool_output) : '');

  if (!out) return { success: 1, errorType: '' };

  const failMarkers = [
    /^Error:/m,
    /\[t1k:mr\]\s+ERROR/i,
    /\b(?:delegation failed|all providers failed|provider failure)\b/i,
    /\b(?:MODULE_NOT_FOUND|spawnSync failed|exited with code \d+)\b/i,
  ];
  for (const re of failMarkers) {
    if (re.test(out)) return { success: 0, errorType: 'output-error-marker' };
  }
  return { success: 1, errorType: '' };
}

(async () => {
  try {
    let hookData = {};
    try {
      hookData = JSON.parse(require('fs').readFileSync(0, 'utf8'));
    } catch { process.exit(0); }

    const tool = hookData.tool_name;
    if (!tool || (tool !== 'Task' && tool !== 'Agent')) process.exit(0);

    const input = hookData.tool_input || {};
    const agent = input.subagent_type || input.agent_name || input.agent || 'unknown';

    const { username, hostnameRaw, projectName, ghUser } = resolveUserContext();
    const { success, errorType } = classifySuccess(hookData);

    const event = {
      type: 'model-router:parent-tool-result',
      kit: 'theonekit-model-router',
      mrVersion: readMrVersion(),
      tool,
      role: agent, // worker column is `role` (SSOT); `agent` is off-contract → silently dropped
      durationMs: hookData.duration_ms || null,
      success,
      errorType,
      ts: new Date().toISOString(),
      hostname: hostHash(hostnameRaw),
      hostnameRaw,
      username,
      projectName,
      ghUser,
      platform: os.platform(),
      arch: os.arch(),
    };

    postEvent(event);
  } catch { /* fail-open */ }
})().finally(() => process.exit(0));

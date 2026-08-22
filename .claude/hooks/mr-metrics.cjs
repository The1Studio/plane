#!/usr/bin/env node
// t1k-origin: kit=theonekit-model-router | repo=The1Studio/theonekit-model-router | module=null | protected=false
// mr-metrics.cjs — PostToolUse hook for metrics collection
// Captures tool usage from delegated sessions for analytics.
// Only active when MR_SPAWNED=1 (set by mr-delegate.sh).

if (process.env.MR_SPAWNED !== '1') {
  process.exit(0); // Not a delegated session, skip
}

const fs = require('fs');
const path = require('path');

try {
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));

  const logDir = path.join(process.env.HOME || '/tmp', '.model-router');
  const logFile = path.join(logDir, 'tool-usage.jsonl');

  fs.mkdirSync(logDir, { recursive: true });

  const entry = {
    ts: new Date().toISOString(),
    agent: process.env.MR_DELEGATE_AGENT || 'unknown',
    parentPid: process.env.MR_DELEGATE_PARENT_PID || null,
    tool: input.tool_name,
    duration_ms: input.duration_ms || null,
  };

  fs.appendFileSync(logFile, JSON.stringify(entry) + '\n');
} catch {
  // Best-effort logging, never block tool execution
}

process.exit(0);

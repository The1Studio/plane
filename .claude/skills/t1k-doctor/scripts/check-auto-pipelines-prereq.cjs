#!/usr/bin/env node
// t1k-origin: kit=theonekit-core | repo=The1Studio/theonekit-core | module=t1k-base | protected=true
// check-auto-pipelines-prereq.cjs — Doctor check #46: GitHub MCP prereq for auto-pipelines.
//
// When `features.autoIssueSubmission` or `features.autoLessonSync` is ON, the
// pipeline relies on a background sub-agent that calls `mcp__github__*` tools
// (create_issue, create_pull_request, search_issues). If the GitHub MCP is
// missing or not authenticated, the marker queues silently and the sub-agent
// has no way to submit — the user sees nothing and maintainers receive nothing.
//
// This check correlates the enabled state of the two pipelines with the
// presence of the GitHub MCP and emits a diagnostic WARN when there is a
// mismatch.
//
// Output: JSON to stdout
//   { status: "pass" | "skip" | "warn",
//     enabled: { autoIssueSubmission, autoLessonSync },
//     githubMcpPresent: bool,
//     reason: string }
// Exit 0 always (advisory check; never blocks doctor).
//
// Usage:  node check-auto-pipelines-prereq.cjs [project-root]

'use strict';

const fs           = require('node:fs');
const path         = require('node:path');
const { execFileSync } = require('node:child_process');

function readMergedFeatureFlags(claudeDir) {
  const flags = { autoIssueSubmission: false, autoLessonSync: false };
  if (!fs.existsSync(claudeDir)) return flags;
  let entries;
  try { entries = fs.readdirSync(claudeDir); } catch { return flags; }
  for (const f of entries) {
    if (!f.startsWith('t1k-config-') || !f.endsWith('.json')) continue;
    try {
      const cfg = JSON.parse(fs.readFileSync(path.join(claudeDir, f), 'utf8'));
      if (cfg && cfg.features && typeof cfg.features === 'object') {
        if (typeof cfg.features.autoIssueSubmission === 'boolean') {
          flags.autoIssueSubmission = cfg.features.autoIssueSubmission;
        }
        if (typeof cfg.features.autoLessonSync === 'boolean') {
          flags.autoLessonSync = cfg.features.autoLessonSync;
        }
      }
    } catch { /* skip malformed fragment */ }
  }
  return flags;
}

function isGithubMcpPresent() {
  try {
    const out = execFileSync('claude', ['mcp', 'list'], {
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
      timeout: 5000,
      windowsHide: true,
    });
    return /^\s*github\s/m.test(out) || /\bgithub\b/i.test(out);
  } catch {
    return null;
  }
}

/**
 * Count unsubmitted entries in a JSONL queue file.
 * Returns 0 if the file does not exist, -1 on read error.
 */
function countPending(filePath) {
  try {
    if (!fs.existsSync(filePath)) return 0;
    const lines = fs.readFileSync(filePath, 'utf8').trim().split('\n');
    let count = 0;
    for (const line of lines) {
      if (!line) continue;
      try {
        const entry = JSON.parse(line);
        if (entry && entry.submitted !== true) count++;
      } catch { /* skip malformed line */ }
    }
    return count;
  } catch {
    return -1; // unknown — read error
  }
}

function main() {
  const projectRoot = process.argv[2] || process.cwd();
  const claudeDir = path.join(projectRoot, '.claude');
  const telemetryDir = path.join(claudeDir, 'telemetry');

  const pendingLessonUpdates = countPending(path.join(telemetryDir, 'pending-skill-updates.jsonl'));
  const pendingIssueSubmissions = countPending(path.join(telemetryDir, 'pending-issue-submissions.jsonl'));

  const flags = readMergedFeatureFlags(claudeDir);
  const anyEnabled = flags.autoIssueSubmission || flags.autoLessonSync;

  if (!anyEnabled) {
    process.stdout.write(JSON.stringify({
      status: 'pass',
      enabled: flags,
      githubMcpPresent: null,
      pendingLessonUpdates,
      pendingIssueSubmissions,
      reason: 'auto-pipelines disabled — GH MCP prereq not applicable',
    }) + '\n');
    return;
  }

  const present = isGithubMcpPresent();

  if (present === null) {
    process.stdout.write(JSON.stringify({
      status: 'skip',
      enabled: flags,
      githubMcpPresent: null,
      pendingLessonUpdates,
      pendingIssueSubmissions,
      reason: 'claude CLI not available — cannot probe MCP state',
    }) + '\n');
    return;
  }

  if (present) {
    const pendingParts = [];
    if (pendingLessonUpdates > 0) pendingParts.push(`${pendingLessonUpdates} lesson updates pending`);
    if (pendingIssueSubmissions > 0) pendingParts.push(`${pendingIssueSubmissions} issue submissions pending`);
    const reason = pendingParts.length > 0
      ? `GitHub MCP present; ${pendingParts.join(', ')}`
      : 'GitHub MCP present and CLI reachable';
    process.stdout.write(JSON.stringify({
      status: 'pass',
      enabled: flags,
      githubMcpPresent: true,
      pendingLessonUpdates,
      pendingIssueSubmissions,
      reason,
    }) + '\n');
    return;
  }

  const enabledList = Object.entries(flags).filter(([, v]) => v).map(([k]) => k).join(', ');
  const msg = `auto-pipelines [${enabledList}] are ON but GitHub MCP is not registered — submissions will queue and silently fail. Fix: claude mcp add github`;
  process.stderr.write(`WARN: ${msg}\n`);
  process.stdout.write(JSON.stringify({
    status: 'warn',
    enabled: flags,
    githubMcpPresent: false,
    pendingLessonUpdates,
    pendingIssueSubmissions,
    reason: msg,
  }) + '\n');
}

main();

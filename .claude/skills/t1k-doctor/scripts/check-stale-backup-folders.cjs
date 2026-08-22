#!/usr/bin/env node
// t1k-origin: kit=theonekit-core | repo=The1Studio/theonekit-core | module=t1k-base | protected=true
// check-stale-backup-folders.cjs — Doctor check #50: Stale-backup folders inside auto-scanned dirs.
//
// Detects quarantine subdirectories (dot-prefixed names like `.stale-backup-*`,
// `.zombies-*`, `.backup-*`, `.old`, `.archive-*`) sitting INSIDE Claude Code's
// auto-scanned folders (`agents/`, `skills/`, `rules/`, `hooks/`, `commands/`).
//
// The naming-convention.md rule's historical "Move to `.stale-backup-{YYMMDD}/`
// subdir" advice was based on the assumption that dot-prefixed subdirs are
// hidden from tool scanning. They are NOT — Claude Code's `/agents` UI and
// skill discovery walk into dot-prefixed subdirectories and surface the files
// inside as live registrations. So a backup folder inside `agents/` produces
// zombie entries in the UI exactly like un-quarantined files would.
//
// Quarantine destinations MUST be OUTSIDE the auto-scanned folder (e.g.,
// `~/.claude/.zombies-{YYMMDD}/` as a sibling of `agents/`), or files should
// be deleted outright after verification.
//
// Scans BOTH `~/.claude/` (global) AND the project's `.claude/` (local).
//
// Usage:
//   node check-stale-backup-folders.cjs [path/to/.claude]
//
// Exits 0 always (WARN level). Prints a single PASS/WARN line, optionally
// followed by the offending paths and a fix hint.

'use strict';

const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');

// Claude Code folders that are auto-scanned for active registrations. Any
// quarantine subdirectory inside one of these will leak into the live registry.
const AUTO_SCANNED_DIRS = ['agents', 'skills', 'rules', 'hooks', 'commands'];

// Quarantine-folder name patterns. Anything matching these inside an
// auto-scanned dir is the anti-pattern we're flagging.
const QUARANTINE_PATTERNS = [
  /^\.stale-backup($|-)/,
  /^\.zombies?($|-)/,
  /^\.backup($|-)/,
  /^\.archive($|-)/,
  /^\.old($|-)/,
  /^\.deprecated($|-)/,
  /^\.trash($|-)/,
];

function isQuarantineName(name) {
  return QUARANTINE_PATTERNS.some((re) => re.test(name));
}

function scanClaudeDir(claudeDir) {
  const findings = [];
  if (!fs.existsSync(claudeDir)) return findings;
  for (const scannedName of AUTO_SCANNED_DIRS) {
    const scannedDir = path.join(claudeDir, scannedName);
    let entries;
    try {
      entries = fs.readdirSync(scannedDir, { withFileTypes: true });
    } catch {
      continue;
    }
    for (const entry of entries) {
      if (!entry.isDirectory()) continue;
      if (!isQuarantineName(entry.name)) continue;
      const fullPath = path.join(scannedDir, entry.name);
      let fileCount = 0;
      try {
        fileCount = fs.readdirSync(fullPath).length;
      } catch {
        // permission denied — still report the dir
      }
      findings.push({ path: fullPath, fileCount });
    }
  }
  return findings;
}

function resolveProjectClaudeDir(argPath) {
  if (argPath) {
    const resolved = path.resolve(argPath);
    return resolved.endsWith('.claude') ? resolved : path.join(resolved, '.claude');
  }
  // Default to CWD's .claude/ if present
  const cwdClaude = path.join(process.cwd(), '.claude');
  return fs.existsSync(cwdClaude) ? cwdClaude : null;
}

function main() {
  const globalClaude = path.join(os.homedir(), '.claude');
  const projectClaude = resolveProjectClaudeDir(process.argv[2]);

  const globalFindings = scanClaudeDir(globalClaude).map((f) => ({ ...f, scope: 'global' }));
  const projectFindings = projectClaude && projectClaude !== globalClaude
    ? scanClaudeDir(projectClaude).map((f) => ({ ...f, scope: 'project' }))
    : [];
  const all = [...globalFindings, ...projectFindings];

  if (all.length === 0) {
    console.log('PASS: no quarantine subdirs inside auto-scanned folders (#50)');
    return 0;
  }

  console.log(`WARN: #50 — ${all.length} quarantine folder(s) inside Claude Code's auto-scanned dirs:`);
  for (const f of all) {
    console.log(`  [${f.scope}] ${f.path} (${f.fileCount} file(s))`);
  }
  console.log('');
  console.log('  These dot-prefixed subdirs are STILL walked by the /agents UI and skill');
  console.log('  discovery — files inside surface as live registrations. Move them outside');
  console.log('  the auto-scanned folder OR delete after verification:');
  console.log('');
  for (const f of all) {
    const parent = path.dirname(f.path); // e.g., ~/.claude/agents
    const claudeRoot = path.dirname(parent); // e.g., ~/.claude
    const folderName = path.basename(f.path);
    console.log(`    mv "${f.path}" "${path.join(claudeRoot, folderName)}"   # or: rm -rf "${f.path}"`);
  }
  return 0;
}

process.exit(main());

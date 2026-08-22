#!/usr/bin/env node
// t1k-origin: kit=theonekit-core | repo=The1Studio/theonekit-core | module=t1k-base | protected=true
// check-inherits-from.cjs — Doctor check #37: inheritsFrom field integrity.
//
// When metadata.json contains an `inheritsFrom` field, this check validates
// that the declared parent path is well-formed: exists, is a directory, ends
// in `.claude`, contains a valid T1K metadata.json, is not a self-reference,
// and does not form a cycle.
//
// Validation rules (all ERROR severity — field is opt-in; if set, enforce strictly):
//   (a) path exists            → else ERROR: parent path missing
//   (b) path is a directory    → else ERROR: not a directory
//   (c) ends in `.claude`      → else ERROR: must end in .claude
//   (d) has metadata.json      → else ERROR: not a T1K install
//   (e) parent is T1K-shape    → else ERROR: not a valid T1K metadata
//   (f) no self-reference      → else ERROR: inheritsFrom points at self
//   (g) no cycle (≤5 hops)     → else ERROR: cycle detected
//
// Usage:
//   node check-inherits-from.cjs [path/to/project-claude-dir]
//
// Exits 0 on SKIP (no field) or PASS.
// Exits 1 on any ERROR.

'use strict';

const fs   = require('node:fs');
const os   = require('node:os');
const path = require('node:path');

// ── T1K metadata shape detection ─────────────────────────────────────────────
// Mirrors isT1KMetadata from telemetry-utils.cjs (independent CJS implementation
// to keep doctor scripts dependency-free from hooks/).

/**
 * @param {object|null|undefined} meta
 * @returns {boolean}
 */
function isT1KMetadata(meta) {
  if (!meta || typeof meta !== 'object') return false;
  if (meta.installedModules && typeof meta.installedModules === 'object') return true;
  if (meta.schemaVersion === 2 && (Array.isArray(meta.modules) || typeof meta.modules === 'object')) return true;
  if (typeof meta.name === 'string' && meta.name.startsWith('theonekit-')) return true;
  if (typeof meta.kitName === 'string' && meta.kitName.startsWith('theonekit-')) return true;
  return false;
}

/**
 * Read and parse metadata.json from a .claude/ dir.
 * Returns parsed object or null on absence/parse failure.
 * @param {string} claudeDir
 * @returns {object|null}
 */
function readMetadata(claudeDir) {
  const metaPath = path.join(claudeDir, 'metadata.json');
  if (!fs.existsSync(metaPath)) return null;
  try {
    return JSON.parse(fs.readFileSync(metaPath, 'utf8'));
  } catch {
    return null;
  }
}

// ── Validation helpers ────────────────────────────────────────────────────────

/**
 * Emit an ERROR message to stderr and exit 1.
 * @param {string} message
 * @param {string} [hint]   optional remediation hint
 */
function fail(message, hint) {
  process.stderr.write(`[t1k:doctor] inherits-from: ERROR — ${message}\n`);
  if (hint) process.stderr.write(`  fix: ${hint}\n`);
  process.exit(1);
}

// ── Main ──────────────────────────────────────────────────────────────────────

function run() {
  const projectClaudeDir = process.argv[2] || path.join(process.cwd(), '.claude');

  const meta = readMetadata(projectClaudeDir);

  // SKIP if no metadata or no inheritsFrom field
  if (!meta || !Object.prototype.hasOwnProperty.call(meta, 'inheritsFrom')) {
    console.log('[t1k:doctor] inherits-from: SKIP — inheritsFrom not set');
    return;
  }

  const inheritsFrom = meta.inheritsFrom;

  // (a) Path must exist
  if (!fs.existsSync(inheritsFrom)) {
    fail(
      `parent path does not exist: ${inheritsFrom}`,
      'remove the inheritsFrom field from .claude/metadata.json OR re-create the parent .claude/',
    );
  }

  // (b) Must be a directory
  if (!fs.statSync(inheritsFrom).isDirectory()) {
    fail(
      `inheritsFrom must point at a directory, not a file: ${inheritsFrom}`,
      'set inheritsFrom to the .claude/ directory path, e.g. /path/to/project/.claude',
    );
  }

  // (c) Must end in `.claude`
  if (path.basename(inheritsFrom) !== '.claude') {
    fail(
      `inheritsFrom should end in \`.claude\`, not \`${path.basename(inheritsFrom)}\``,
      'set inheritsFrom to the .claude/ directory itself, e.g. /path/to/parent/.claude',
    );
  }

  // (d) Parent must have metadata.json
  if (!fs.existsSync(path.join(inheritsFrom, 'metadata.json'))) {
    fail(
      `parent is not a T1K install — no metadata.json in: ${inheritsFrom}`,
      'point inheritsFrom at a directory that contains a valid T1K metadata.json',
    );
  }

  // (e) Parent metadata must be T1K-shape
  const parentMeta = readMetadata(inheritsFrom);
  if (!isT1KMetadata(parentMeta)) {
    fail(
      `parent metadata.json is not T1K-shape (CK stub or unknown format): ${inheritsFrom}`,
      'point inheritsFrom at a directory with a valid T1K metadata.json (schemaVersion 3, installedModules, etc.)',
    );
  }

  // (f) No self-reference
  try {
    const resolvedChild  = fs.realpathSync(projectClaudeDir);
    const resolvedParent = fs.realpathSync(inheritsFrom);
    if (resolvedChild === resolvedParent) {
      fail(
        `inheritsFrom points at self: ${inheritsFrom}`,
        'remove the inheritsFrom field — a .claude/ directory cannot inherit from itself',
      );
    }
  } catch {
    // realpathSync failed (race/perms) — skip self-reference check, proceed
  }

  // (g) Cycle guard — follow inheritsFrom chain up to MAX_HOPS
  const MAX_HOPS = 5;
  const visited  = new Set();
  let current    = inheritsFrom;

  for (let hop = 0; hop < MAX_HOPS; hop++) {
    let resolved;
    try {
      resolved = fs.realpathSync(current);
    } catch {
      break; // path gone mid-walk — fine, stop here
    }

    if (visited.has(resolved)) {
      fail(
        `inheritance cycle detected at: ${current}`,
        'remove the inheritsFrom field from one of the entries in the cycle',
      );
    }
    visited.add(resolved);

    const hopMeta = readMetadata(current);
    if (!hopMeta || typeof hopMeta.inheritsFrom !== 'string') break;
    current = hopMeta.inheritsFrom;
  }

  console.log('[t1k:doctor] inherits-from: PASS');
}

try {
  run();
} catch (err) {
  process.stderr.write(`[t1k:doctor] inherits-from: ERROR — unexpected exception: ${err.message}\n`);
  process.exit(1);
}

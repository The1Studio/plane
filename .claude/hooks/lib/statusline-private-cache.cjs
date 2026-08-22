#!/usr/bin/env node
// t1k-origin: kit=theonekit-core | repo=The1Studio/theonekit-core | module=null | protected=true
'use strict';

/**
 * Security and retention helpers for the statusline's per-session temp caches.
 *
 * POSIX cache files are created and repaired to owner-only mode (0600). Windows
 * does not implement POSIX permission bits equivalently; its ACLs are outside
 * this helper's guarantee, so chmod remains best-effort there.
 *
 * Cleanup is gated by a small marker in the user's ~/.claude state directory
 * before reading the shared temp directory. Every operation fails open because
 * statusline rendering must never depend on cache maintenance succeeding.
 */

const fs = require('fs');
const os = require('os');
const path = require('path');

const CACHE_MODE = 0o600;
const RETENTION_MS = 7 * 24 * 60 * 60 * 1000;
const SWEEP_INTERVAL_MS = 24 * 60 * 60 * 1000;
const LOCK_STALE_MS = 5 * 60 * 1000;
// Every statusline-owned temp cache prefix must be listed here or its files are
// never retention-swept and accumulate in the temp directory indefinitely.
const CACHE_FILENAME_RE = /^t1k-(?:auth|context|model-scoped-quota|agent-tree)-.+\.json(?:\.(?:tmp|sweep)-.+)?$/;
const SWEEP_MARKER_FILENAME = '.t1k-statusline-session-cache-sweep.stamp';
const LOCK_OWNER_FILENAME = 'owner';

function sweepMarkerPath() {
  return path.join(os.homedir(), '.claude', SWEEP_MARKER_FILENAME);
}

/**
 * Best-effort permission repair for a pre-existing cache file.
 * @returns {boolean} whether chmod completed successfully
 */
function hardenSessionCacheFile(filePath, fileSystem = fs) {
  try {
    if (!fileSystem.lstatSync(filePath).isFile()) return false;
    fileSystem.chmodSync(filePath, CACHE_MODE);
    return true;
  } catch {
    return false;
  }
}

/**
 * Read and harden one inode through a single descriptor. O_NOFOLLOW prevents
 * path replacement with a symlink between validation, chmod, and read.
 * @returns {unknown|null} parsed cache value, or null when it is untrusted
 */
function readSessionCacheJson(filePath, fileSystem = fs) {
  const constants = fileSystem.constants || fs.constants;
  const noFollow = process.platform === 'win32' ? 0 : (constants.O_NOFOLLOW || 0);
  let descriptor;
  try {
    descriptor = fileSystem.openSync(filePath, constants.O_RDONLY | noFollow);
    if (!fileSystem.fstatSync(descriptor).isFile()) return null;
    try {
      fileSystem.fchmodSync(descriptor, CACHE_MODE);
    } catch {
      if (process.platform !== 'win32') return null;
    }
    return JSON.parse(fileSystem.readFileSync(descriptor, 'utf8'));
  } catch {
    return null;
  } finally {
    if (Number.isInteger(descriptor)) {
      try { fileSystem.closeSync(descriptor); } catch {}
    }
  }
}
/**
 * Write to a unique owner-only inode, then atomically replace the canonical
 * cache. Concurrent statusline processes cannot interleave or leave trailing
 * JSON bytes. Failed temp cleanup remains eligible for retention sweeps.
 * @returns {boolean} whether the data write completed successfully
 */
function writeSessionCacheJson(filePath, value, fileSystem = fs) {
  const constants = fileSystem.constants || fs.constants;
  const noFollow = process.platform === 'win32' ? 0 : (constants.O_NOFOLLOW || 0);
  const flags = constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | noFollow;
  const tempPath = `${filePath}.tmp-${process.pid}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  let descriptor;
  let renamed = false;
  try {
    descriptor = fileSystem.openSync(tempPath, flags, CACHE_MODE);
    try {
      fileSystem.fchmodSync(descriptor, CACHE_MODE);
    } catch {
      if (process.platform !== 'win32') return false;
    }
    fileSystem.writeFileSync(descriptor, JSON.stringify(value), 'utf8');
    if (typeof fileSystem.fsyncSync === 'function') fileSystem.fsyncSync(descriptor);
    fileSystem.closeSync(descriptor);
    descriptor = undefined;
    fileSystem.renameSync(tempPath, filePath);
    renamed = true;
  } catch {
    return false;
  } finally {
    if (Number.isInteger(descriptor)) {
      try { fileSystem.closeSync(descriptor); } catch {}
    }
    if (!renamed) {
      try { fileSystem.unlinkSync(tempPath); } catch {}
    }
  }
  hardenSessionCacheFile(filePath, fileSystem);
  return true;
}

function markerIsRecent(markerPath, now, intervalMs, fileSystem) {
  try {
    const ageMs = now - fileSystem.statSync(markerPath).mtimeMs;
    // A process waiting on the lease may have captured `now` just before the
    // previous owner refreshed the marker. Treat bounded negative age as clock
    // skew/freshness, while a wildly future-dated marker cannot suppress cleanup
    // beyond one interval.
    return ageMs > -intervalMs && ageMs < intervalMs;
  } catch {
    return false;
  }
}

function refreshMarker(markerPath, now, fileSystem) {
  try {
    fileSystem.mkdirSync(path.dirname(markerPath), { recursive: true, mode: 0o700 });
    fileSystem.writeFileSync(markerPath, String(now), { mode: CACHE_MODE });
  } catch {
    return false;
  }
  hardenSessionCacheFile(markerPath, fileSystem);
  return true;
}

function sweepLockPath(markerPath) {
  return `${markerPath}.lock`;
}

function lockOwnerIsAlive(lockPath, fileSystem) {
  try {
    const token = fileSystem.readFileSync(path.join(lockPath, LOCK_OWNER_FILENAME), 'utf8');
    const match = token.match(/^(\d+)-/);
    if (!match) return false;
    const ownerPid = Number(match[1]);
    if (ownerPid === process.pid) return true;
    process.kill(ownerPid, 0);
    return true;
  } catch (error) {
    return error && error.code === 'EPERM';
  }
}
function createLease(lockPath, now, fileSystem) {
  const token = `${process.pid}-${now}-${Math.random().toString(16).slice(2)}`;
  try {
    fileSystem.mkdirSync(lockPath, { mode: 0o700 });
    const ownerPath = path.join(lockPath, LOCK_OWNER_FILENAME);
    fileSystem.writeFileSync(ownerPath, token, { flag: 'wx', mode: CACHE_MODE });
    hardenSessionCacheFile(ownerPath, fileSystem);
    return { lockPath, token };
  } catch {
    // Never delete the canonical path after a separate operation fails. A
    // suspended creator can be stale-displaced and replaced before this catch
    // runs; deleting here could remove that successor. An incomplete lease is
    // safe to retain and will be stale-taken over on a later attempt.
    return null;
  }
}

/**
 * Acquire the sweep lease with an atomic mkdir. A stale lease is first renamed
 * out of the lock path, so competing takeover attempts still converge on one
 * mkdir winner.
 */
function acquireSweepLease(lockPath, now, staleMs, fileSystem) {
  const lease = createLease(lockPath, now, fileSystem);
  if (lease) return lease;

  let stale = false;
  try {
    const stat = fileSystem.lstatSync(lockPath);
    const ageMs = now - stat.mtimeMs;
    const futureOwnerIsAlive = ageMs <= -staleMs && lockOwnerIsAlive(lockPath, fileSystem);
    stale = stat.isDirectory()
      && (ageMs >= staleMs || (ageMs <= -staleMs && !futureOwnerIsAlive));
  } catch {
    return null;
  }
  if (!stale) return null;

  const displacedPath = `${lockPath}.stale-${process.pid}-${now}-${Math.random().toString(16).slice(2)}`;
  try {
    fileSystem.renameSync(lockPath, displacedPath);
  } catch {
    return null;
  }
  try { fileSystem.rmSync(displacedPath, { recursive: true, force: true }); } catch {}
  return createLease(lockPath, now, fileSystem);
}

/**
 * Completed leases intentionally remain at the canonical lock path.
 *
 * A read-token-then-delete release has an unavoidable TOCTOU: after the token
 * check, stale takeover can install a new owner at the same path and the old
 * owner can recursively delete that successor. Retention makes completion
 * non-destructive. The fresh marker suppresses the hot path, and the next
 * eligible daily sweep atomically stale-renames and replaces this one lease.
 */
function completeSweepLease(lease) {
  return Boolean(lease);
}

/**
 * Remove stale statusline-owned JSON caches at most once per sweep interval.
 * Foreign temp files, directories, symlinks, and recent cache files survive.
 *
 * @param {{
 *   tempDir?: string,
 *   now?: number,
 *   retentionMs?: number,
 *   sweepIntervalMs?: number,
 *   lockStaleMs?: number,
 *   markerPath?: string,
 *   lockPath?: string,
 *   fs?: typeof fs
 * }} [options]
 * @returns {number} number of stale cache files removed
 */
function cleanupSessionCaches(options = {}) {
  const fileSystem = options.fs || fs;
  const tempDir = options.tempDir || os.tmpdir();
  const now = Number.isFinite(options.now) ? options.now : Date.now();
  const retentionMs = Number.isFinite(options.retentionMs)
    ? options.retentionMs
    : RETENTION_MS;
  const intervalMs = Number.isFinite(options.sweepIntervalMs)
    ? options.sweepIntervalMs
    : SWEEP_INTERVAL_MS;
  const lockStaleMs = Number.isFinite(options.lockStaleMs)
    ? options.lockStaleMs
    : LOCK_STALE_MS;
  const markerPath = options.markerPath || sweepMarkerPath();
  const lockPath = options.lockPath || sweepLockPath(markerPath);

  try {
    if (markerIsRecent(markerPath, now, intervalMs, fileSystem)) return 0;
    try {
      fileSystem.mkdirSync(path.dirname(markerPath), { recursive: true, mode: 0o700 });
    } catch {
      return 0;
    }
    const lease = acquireSweepLease(lockPath, now, lockStaleMs, fileSystem);
    if (!lease) return 0;

    let attemptedScan = false;
    try {
      // Another process may have completed its sweep between our initial marker
      // check and this lease acquisition.
      if (markerIsRecent(markerPath, now, intervalMs, fileSystem)) return 0;

      attemptedScan = true;
      let removed = 0;
      for (const name of fileSystem.readdirSync(tempDir)) {
        if (!CACHE_FILENAME_RE.test(name)) continue;
        const filePath = path.join(tempDir, name);
        try {
          const stat = fileSystem.lstatSync(filePath);
          const ageMs = now - stat.mtimeMs;
          if (!stat.isFile() || (ageMs <= retentionMs && ageMs >= -retentionMs)) continue;

          const displacedPath = `${filePath}.sweep-${process.pid}-${now}-${Math.random().toString(16).slice(2)}`;
          fileSystem.renameSync(filePath, displacedPath);
          const displacedStat = fileSystem.lstatSync(displacedPath);
          const displacedAgeMs = now - displacedStat.mtimeMs;
          if (displacedStat.isFile()
              && (displacedAgeMs > retentionMs || displacedAgeMs < -retentionMs)) {
            fileSystem.unlinkSync(displacedPath);
            removed++;
          } else if (fileSystem.existsSync(filePath)) {
            // A newer canonical successor exists, so this displaced snapshot is
            // redundant. Removing it cannot affect the successor path.
            fileSystem.unlinkSync(displacedPath);
          } else {
            fileSystem.renameSync(displacedPath, filePath);
          }
        } catch {
          // A raced-away or inaccessible entry must not block other candidates.
        }
      }
      return removed;
    } finally {
      // Record attempted maintenance before completing the retained lease. This
      // prevents repeated hot-path scans even when readdir/stat/unlink failed open.
      if (attemptedScan) refreshMarker(markerPath, now, fileSystem);
      completeSweepLease(lease);
    }
  } catch {
    return 0;
  }
}

module.exports = {
  cleanupSessionCaches,
  hardenSessionCacheFile,
  readSessionCacheJson,
  writeSessionCacheJson,
  CACHE_MODE,
  RETENTION_MS,
  SWEEP_INTERVAL_MS,
  LOCK_STALE_MS,
  _internal: {
    acquireSweepLease,
    CACHE_FILENAME_RE,
    completeSweepLease,
    createLease,
    lockOwnerIsAlive,
    markerIsRecent,
    refreshMarker,
    sweepLockPath,
    sweepMarkerPath,
  },
};

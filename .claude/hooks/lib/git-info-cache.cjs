#!/usr/bin/env node
// t1k-origin: kit=theonekit-core | repo=The1Studio/theonekit-core | module=null | protected=true
'use strict';

/**
 * Git Info Cache - Cross-platform git information with caching
 * Caches git query results for 30s to avoid repeated process spawns
 * T1K-native — no external dependencies
 */

const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const os = require('os');

const CACHE_TTL = 30000;
const CACHE_MISS = Symbol('cache_miss');
const CACHE_SKIP = Symbol('cache_skip');

function getExecTimeoutMs() {
  const parsed = Number.parseInt(process.env.T1K_GIT_TIMEOUT_MS || '', 10);
  if (Number.isFinite(parsed) && parsed > 0) return parsed;
  return 3000;
}

function execIn(cmd, cwd) {
  try {
    return {
      output: execSync(cmd, {
        encoding: 'utf8',
        stdio: ['pipe', 'pipe', 'ignore'],
        windowsHide: true,
        cwd: cwd || undefined,
        timeout: getExecTimeoutMs()
      }).trim(),
      timedOut: false
    };
  } catch (error) {
    return { output: '', timedOut: error?.killed || error?.signal === 'SIGTERM' || /timed out|etimedout/i.test(String(error?.message || '')) };
  }
}

function getCachePath(cwd) {
  const hash = require('crypto').createHash('md5').update(cwd).digest('hex').slice(0, 8);
  return path.join(os.tmpdir(), `t1k-git-cache-${hash}.json`);
}

function readCache(cachePath, options = {}) {
  try {
    const cache = JSON.parse(fs.readFileSync(cachePath, 'utf8'));
    if (Date.now() - cache.timestamp < CACHE_TTL || options.allowStale) return cache.data;
  } catch {}
  return CACHE_MISS;
}

function writeCache(cachePath, data) {
  const tmpPath = cachePath + '.tmp';
  try {
    fs.writeFileSync(tmpPath, JSON.stringify({ timestamp: Date.now(), data }));
    fs.renameSync(tmpPath, cachePath);
  } catch {
    try { fs.unlinkSync(tmpPath); } catch {}
  }
}

function countLines(str) {
  if (!str) return 0;
  return str.split('\n').filter(l => l.trim()).length;
}

function fetchGitInfo(cwd) {
  const repoCheck = execIn('git rev-parse --git-dir', cwd);
  if (repoCheck.timedOut) return CACHE_SKIP;
  if (!repoCheck.output) return null;

  const branchPrimary = execIn('git branch --show-current', cwd);
  const branchFallback = execIn('git rev-parse --short HEAD', cwd);
  const unstagedResult = execIn('git diff --name-only', cwd);
  const stagedResult = execIn('git diff --cached --name-only', cwd);
  const aheadBehindResult = execIn('git rev-list --left-right --count @{u}...HEAD', cwd);

  if ([branchPrimary, branchFallback, unstagedResult, stagedResult, aheadBehindResult].some(r => r.timedOut)) return CACHE_SKIP;

  let ahead = 0, behind = 0;
  if (aheadBehindResult.output) {
    const parts = aheadBehindResult.output.split(/\s+/);
    behind = parseInt(parts[0], 10) || 0;
    ahead = parseInt(parts[1], 10) || 0;
  }

  return {
    branch: branchPrimary.output || branchFallback.output,
    unstaged: countLines(unstagedResult.output),
    staged: countLines(stagedResult.output),
    ahead, behind
  };
}

function getGitInfo(cwd = process.cwd()) {
  const cachePath = getCachePath(cwd);
  const cached = readCache(cachePath);
  if (cached !== CACHE_MISS) return cached;

  const data = fetchGitInfo(cwd);
  if (data === CACHE_SKIP) {
    const stale = readCache(cachePath, { allowStale: true });
    return stale === CACHE_MISS ? null : stale;
  }

  writeCache(cachePath, data);
  return data;
}

function invalidateCache(cwd = process.cwd()) {
  try { fs.unlinkSync(getCachePath(cwd)); } catch {}
}

module.exports = { getGitInfo, invalidateCache };

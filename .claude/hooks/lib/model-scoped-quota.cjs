#!/usr/bin/env node
// t1k-origin: kit=theonekit-core | repo=The1Studio/theonekit-core | module=null | protected=true
'use strict';

/**
 * Model-scoped weekly quota resolution (e.g. the "Fable" weekly bucket).
 *
 * Two sources converge on ONE normalized shape:
 *   { "<display_name>": { percent: 0..100, resetsAt: string|null, severity: string|null } }
 *
 *   Path A — Claude Code statusline stdin (`rate_limits.model_scoped`). Free, but gated
 *            behind a remote flag that is currently empty, so it is DARK in practice.
 *   Path B — `GET https://api.anthropic.com/api/oauth/usage`, parsing `limits[]`.
 *            Load-bearing today. Throttled by a temp-dir cache (10 min TTL).
 *
 * Model names are NEVER enumerated here. Buckets are keyed by the display name the API
 * reports; matching a specific model (Fable) belongs at the render/threshold layer.
 *
 * Every failure path is fail-open: the caller gets `{}` and the statusline still renders.
 * The OAuth tokens are read from ~/.claude/.credentials.json and are never logged,
 * printed, or written to disk by this module.
 *
 * The throttle cache is bound to the logged-in ACCOUNT, not just the home directory:
 * `/login` rewrites ~/.claude/.credentials.json under the same $HOME, so a home-keyed
 * cache would serve the previous account's percentages for up to one TTL. Each entry
 * carries an `identity` fingerprint and a mismatch is a hard miss — never a stale
 * fallback, because another account's numbers are worse than no numbers.
 */

const crypto = require('crypto');
const fs = require('fs');
const https = require('https');
const os = require('os');
const path = require('path');

const {
  readSessionCacheJson,
  writeSessionCacheJson,
} = require('./statusline-private-cache.cjs');

const CACHE_TTL_MS = 600000;
const FETCH_TIMEOUT_MS = 5000;
const USAGE_HOST = 'api.anthropic.com';
const USAGE_PATH = '/api/oauth/usage';
const OAUTH_BETA_HEADER = 'oauth-2025-04-20';

/** @typedef {{ percent: number, resetsAt: string|null, severity: string|null }} ScopedQuota */
/** @typedef {Record<string, ScopedQuota>} ModelScopedQuota */

/**
 * Throttle cache path — per-home so multiple accounts on one box do not share a bucket.
 * @returns {string}
 */
function cachePathFor(homeDir = os.homedir(), tempDir = os.tmpdir()) {
  const hash = crypto.createHash('sha1').update(String(homeDir)).digest('hex');
  return path.join(tempDir, `t1k-model-scoped-quota-${hash}.json`);
}

function toPercent(value) {
  const num = Number(value);
  // Already 0..100 at both sources — never rescale.
  return Number.isFinite(num) ? num : null;
}

function toStringOrNull(value) {
  return typeof value === 'string' && value ? value : null;
}

/**
 * Path A — normalize `data.rate_limits.model_scoped` from statusline stdin.
 * @param {unknown} modelScoped
 * @returns {ModelScopedQuota}
 */
function normalizeStdinModelScoped(modelScoped) {
  /** @type {ModelScopedQuota} */
  const out = {};
  if (!Array.isArray(modelScoped)) return out;
  for (const entry of modelScoped) {
    if (!entry || typeof entry !== 'object') continue;
    const name = toStringOrNull(entry.displayName);
    if (!name || Object.prototype.hasOwnProperty.call(out, name)) continue;
    const percent = toPercent(entry.limit && entry.limit.utilization);
    if (percent === null) continue;
    out[name] = {
      percent,
      resetsAt: toStringOrNull(entry.limit && entry.limit.resets_at),
      severity: null,
    };
  }
  return out;
}

/**
 * Path B — normalize the API's `limits[]`. Keeps weekly model-scoped buckets only;
 * `seven_day_opus` / `seven_day_sonnet` are dead (null) and deliberately unread.
 * @param {unknown} limits
 * @returns {ModelScopedQuota}
 */
function normalizeApiLimits(limits) {
  /** @type {ModelScopedQuota} */
  const out = {};
  if (!Array.isArray(limits)) return out;
  for (const entry of limits) {
    if (!entry || typeof entry !== 'object') continue;
    const isWeeklyScoped = entry.kind === 'weekly_scoped' || entry.group === 'weekly';
    if (!isWeeklyScoped) continue;
    const model = entry.scope && entry.scope.model;
    const name = model ? toStringOrNull(model.display_name) : null;
    if (!name || Object.prototype.hasOwnProperty.call(out, name)) continue;
    const percent = toPercent(entry.percent);
    if (percent === null) continue;
    out[name] = {
      percent,
      resetsAt: toStringOrNull(entry.resets_at),
      severity: toStringOrNull(entry.severity),
    };
  }
  return out;
}

/**
 * Read the Claude Code OAuth credentials.
 *
 * `accessToken` is returned to the caller only — never logged, never persisted, never
 * included in any cache or error message. `identity` is a salted, truncated digest that
 * IS persisted, so it is derived from the refresh token in preference to the access
 * token: the access token rotates on every refresh (which would evict a still-valid
 * cache), while the refresh token is stable for the life of one login.
 *
 * @returns {{ accessToken: string|null, identity: string|null }}
 */
function readCredentials(homeDir = os.homedir()) {
  try {
    const raw = fs.readFileSync(path.join(homeDir, '.claude', '.credentials.json'), 'utf8');
    const parsed = JSON.parse(raw);
    const oauth = (parsed && parsed.claudeAiOauth) || parsed || {};
    const accessToken = typeof oauth.accessToken === 'string' && oauth.accessToken
      ? oauth.accessToken
      : null;
    const refreshToken = typeof oauth.refreshToken === 'string' && oauth.refreshToken
      ? oauth.refreshToken
      : null;
    return {
      accessToken,
      identity: accountIdentity(refreshToken || accessToken, homeDir),
    };
  } catch {
    return { accessToken: null, identity: null };
  }
}

/**
 * Fingerprint the logged-in account for cache binding.
 *
 * A SHA-256 digest of a high-entropy secret is not reversible, and it is salted with the
 * home directory and truncated so the stored value is a bare equality token — it carries
 * no usable key material even if the 0600 cache file is read.
 *
 * @param {string|null} secret
 * @param {string} homeDir
 * @returns {string|null} 16 hex chars, or null when no credential is available
 */
function accountIdentity(secret, homeDir) {
  if (typeof secret !== 'string' || !secret) return null;
  return crypto.createHash('sha256')
    .update(`t1k-model-scoped-quota\u0000${homeDir}\u0000${secret}`)
    .digest('hex')
    .slice(0, 16);
}

/**
 * @param {string} token
 * @returns {Promise<unknown|null>} parsed usage body, or null on any failure
 */
function fetchUsage(token) {
  return new Promise((resolve) => {
    let settled = false;
    const done = (value) => { if (!settled) { settled = true; resolve(value); } };
    let req;
    try {
      req = https.request({
        host: USAGE_HOST,
        path: USAGE_PATH,
        method: 'GET',
        timeout: FETCH_TIMEOUT_MS,
        headers: {
          Authorization: `Bearer ${token}`,
          'anthropic-beta': OAUTH_BETA_HEADER,
          Accept: 'application/json',
        },
      }, (res) => {
        if (res.statusCode !== 200) { res.resume(); done(null); return; }
        let body = '';
        res.setEncoding('utf8');
        res.on('data', (chunk) => {
          body += chunk;
          // Defensive cap — a runaway body must not grow the statusline's memory.
          if (body.length > 1000000) { req.destroy(); done(null); }
        });
        res.on('end', () => {
          try { done(JSON.parse(body)); } catch { done(null); }
        });
        res.on('error', () => done(null));
      });
    } catch {
      done(null);
      return;
    }
    req.on('timeout', () => { try { req.destroy(); } catch {} done(null); });
    req.on('error', () => done(null));
    req.end();
  });
}

/**
 * Read the throttle cache, rejecting any entry that does not belong to `identity`.
 *
 * Entries written before account binding existed carry no `identity` and are rejected
 * too: an unlabelled entry cannot be proven to be this account's.
 *
 * @param {string} cachePath
 * @param {string|null} identity fingerprint of the account asking
 * @returns {{ fetchedAt: number, data: ModelScopedQuota }|null}
 */
function readCache(cachePath, identity) {
  const cached = readSessionCacheJson(cachePath);
  if (!cached || typeof cached !== 'object') return null;
  if (!cached.data || typeof cached.data !== 'object') return null;
  const fetchedAt = Number(cached.fetchedAt);
  if (!Number.isFinite(fetchedAt)) return null;
  if (!identity || cached.identity !== identity) return null;
  return { fetchedAt, data: cached.data };
}

/**
 * Resolve model-scoped weekly quota, preferring the free stdin path.
 *
 * @param {unknown} rateLimitsFromStdin `data.rate_limits` from the statusline stdin JSON
 * @param {{ homeDir?: string, tempDir?: string, now?: number }} [options]
 * @returns {Promise<ModelScopedQuota>} `{}` when unknown — never throws
 */
async function resolveModelScopedQuota(rateLimitsFromStdin, options = {}) {
  try {
    const stdinScoped = normalizeStdinModelScoped(
      rateLimitsFromStdin && rateLimitsFromStdin.model_scoped
    );
    if (Object.keys(stdinScoped).length > 0) return stdinScoped;

    const homeDir = options.homeDir || os.homedir();
    const tempDir = options.tempDir || os.tmpdir();
    const now = typeof options.now === 'number' ? options.now : Date.now();
    const cachePath = cachePathFor(homeDir, tempDir);

    // Credentials are read before the cache: the account fingerprint is what decides
    // whether a cached entry is ours at all.
    const { accessToken, identity } = readCredentials(homeDir);
    const cached = readCache(cachePath, identity);
    if (cached && now - cached.fetchedAt < CACHE_TTL_MS && now - cached.fetchedAt > -CACHE_TTL_MS) {
      return cached.data;
    }

    // Stale data beats no data: an expired cache is still the last known truth — but
    // only for the account that wrote it, which readCache has already established.
    if (!accessToken) return cached ? cached.data : {};

    const body = await fetchUsage(accessToken);
    if (!body) return cached ? cached.data : {};

    const data = normalizeApiLimits(body.limits);
    writeSessionCacheJson(cachePath, { fetchedAt: now, identity, data });
    return data;
  } catch {
    return {};
  }
}

module.exports = {
  resolveModelScopedQuota,
  normalizeStdinModelScoped,
  normalizeApiLimits,
  cachePathFor,
  accountIdentity,
  readCredentials,
  CACHE_TTL_MS,
  FETCH_TIMEOUT_MS,
};

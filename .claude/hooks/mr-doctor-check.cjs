#!/usr/bin/env node
// t1k-origin: kit=theonekit-model-router | repo=The1Studio/theonekit-model-router | module=null | protected=false
/**
 * mr-doctor-check.cjs — Doctor hook for model-router (v2).
 *
 * Validates: CCS hosted endpoint, ccs auth proxy, delegate script,
 * interceptor hook, skill, gh auth, consumer agent roster.
 *
 * Runs as a SessionStart hook (settings.json) and emits a boot health summary.
 * Per the Claude Code hook contract a SessionStart hook may exit ONLY 0
 * (advisory) or 2 (block) — so this ALWAYS exits 0 and surfaces any failed
 * checks as a non-blocking stderr advisory. A diagnostic report must never
 * fail or block the user's session. For a failure exit code (scripting/CI),
 * use the standalone CLI `mr-doctor.sh`, which keeps its own exit 1.
 *
 * Exit codes:
 *   0 = always (advisory). Per-check pass/warn/fail is in the JSON summary.
 */

const { execSync, execFileSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

// ─── Interceptor-registration predicate (SSOT) ──────────────────────────────
// Shared with mr-transparent-routing-reminder.cjs so the banner and the doctor
// can never disagree about whether routing is wired. Deliberately NOT fail-open:
// a safety check that cannot run must report `fail`, not silently pass. Falling
// open here would recreate the exact false-green #242 and this phase exist to kill.
let settingsRegistry;
try {
  settingsRegistry = require(path.join(__dirname, '..', 'scripts', 'mr-settings-registry.cjs'));
} catch { settingsRegistry = null; }

/**
 * Mirrors the runtime fallback chain in mr-task-interceptor.cjs:105-107.
 * Returns { path, scope } or null if neither location has the file.
 */
function resolveProvidersConfigPath() {
  const projectPath = path.join(process.cwd(), '.claude', 'providers-config.json');
  if (fs.existsSync(projectPath)) return { path: projectPath, scope: 'project' };
  const globalPath = path.join(os.homedir(), '.claude', 'providers-config.json');
  if (fs.existsSync(globalPath)) return { path: globalPath, scope: 'global' };
  return null;
}

/**
 * The home directory the RUNTIME resolves against. Mirrors
 * mr-task-interceptor.cjs (`process.env.HOME || os.homedir()`) so this hook
 * can never assert a different path than the code it is validating.
 */
function homeDir() {
  return process.env.HOME || os.homedir();
}

/**
 * Numeric semver compare. Returns negative if a<b, 0 if equal, positive if a>b.
 * Tolerates pre-release suffixes by splitting on '-' and comparing numeric parts only.
 * Used by the kit-freshness check below.
 */
function compareSemver(a, b) {
  const norm = s => String(s).split('-')[0].split('.').map(n => parseInt(n, 10) || 0);
  const A = norm(a);
  const B = norm(b);
  const len = Math.max(A.length, B.length);
  for (let i = 0; i < len; i++) {
    const x = A[i] || 0;
    const y = B[i] || 0;
    if (x !== y) return x - y;
  }
  return 0;
}

const results = [];
let hasFailure = false;

function check(name, fn) {
  try {
    const result = fn();
    results.push({ name, status: result.status, message: result.message });
    if (result.status === 'fail') hasFailure = true;
  } catch (err) {
    results.push({ name, status: 'fail', message: err.message });
    hasFailure = true;
  }
}

// opencode-go hosted endpoint (CCS flat /v1/messages, gated by gh token).
check('opencode-go-hosted-reachable', () => {
  const endpoint = process.env.OPENCODE_GO_ENDPOINT || 'https://ccs.the1studio.org';
  try {
    const base = new URL(endpoint.endsWith('/') ? endpoint : `${endpoint}/`);
    if (!['http:', 'https:'].includes(base.protocol) || base.username || base.password) {
      throw new Error('endpoint must be an unauthenticated http(s) URL');
    }
    const healthUrl = new URL('health', base);
    const nullDevice = process.platform === 'win32' ? 'NUL' : '/dev/null';
    const code = execFileSync('curl', [
      '-s', '-o', nullDevice, '-w', '%{http_code}', '--max-time', '5', healthUrl.href,
    ],
      { encoding: 'utf8', stdio: ['pipe', 'pipe', 'ignore'], timeout: 6000 }).trim();
    if (code === '200') return { status: 'pass', message: `${endpoint} reachable (200)` };
    if (code === '403' || code === '401') return { status: 'pass', message: `${endpoint} reachable (HTTP ${code} = auth-proxy alive, gh token needed for real calls)` };
    return { status: 'warn', message: `${endpoint} returned HTTP ${code}` };
  } catch (err) {
    return { status: 'warn', message: `${endpoint} unreachable: ${err.message.split('\n')[0]}` };
  }
});

// Circuit-breaker health (#272). The other checks answer "is the provider up?"
// — none of them answered "are we actually USING it?", and those are different
// questions. On 2026-08-17 both providers sat wedged in 'half-open-trial' for
// 22h while provider-aliveness reported opencode-go passing at HTTP 200: every
// hop was skipped, 49 delegations fell through to Anthropic, exactly 1 routed,
// and every check in this file was green. A breaker state is only meaningful
// against its OWN clock, so read the ages, not just the labels.
check('circuit-breaker-state', () => {
  const stateFile = process.env.MR_CB_STATE_FILE
    || path.join(os.homedir(), '.model-router', 'circuit-breaker.json');
  let state;
  try {
    state = JSON.parse(fs.readFileSync(stateFile, 'utf8'));
  } catch {
    // No file = never tripped. That is the healthy resting state, not a gap.
    return { status: 'pass', message: 'no breaker state recorded (nothing has tripped)' };
  }
  const providers = Object.entries((state && state.providers) || {});
  if (providers.length === 0) return { status: 'pass', message: 'all providers closed' };

  let trialTimeoutSec = 1800;
  try {
    const d = require(path.join(process.cwd(), '.claude/scripts/mr-defaults.cjs'));
    let failover = null;
    try {
      const cfg = JSON.parse(fs.readFileSync(path.join(os.homedir(), '.claude', 't1k-config-mr.json'), 'utf8'));
      failover = cfg && cfg.modelRouter ? cfg.modelRouter.failover : null;
    } catch { /* defaults */ }
    trialTimeoutSec = d.worstPerHopTimeoutSec(failover || {}) * (1 + d.INHOP_MAX_RETRIES) + d.PROBE_TIMEOUT_SEC + 300;
  } catch { /* keep the fallback */ }

  const now = Math.floor(Date.now() / 1000);
  const wedged = [];
  const open = [];
  for (const [name, p] of providers) {
    if (p.state === 'half-open-trial') {
      const age = now - (p.halfOpenAt || 0);
      if (age >= trialTimeoutSec) wedged.push(`${name} (trial abandoned ${age}s ago)`);
    } else if (p.state === 'open') {
      open.push(name);
    }
  }
  // A wedged trial is a FAIL, not a warn: it silently routes 100% of traffic to
  // Anthropic and a warn in a green report is scrolled past — which is exactly
  // how this survived 22 hours.
  if (wedged.length) {
    return {
      status: 'fail',
      message: `${wedged.length} provider(s) wedged in half-open-trial: ${wedged.join(', ')} — `
        + 'every hop is being skipped and all delegations fall through to Anthropic. '
        + 'Fix: node .claude/scripts/mr-circuit-breaker.cjs reset',
    };
  }
  if (open.length === providers.length) {
    return { status: 'warn', message: `every provider is OPEN (${open.join(', ')}) — nothing can route until a cooldown elapses` };
  }
  if (open.length) return { status: 'warn', message: `open: ${open.join(', ')}` };
  return { status: 'pass', message: `${providers.length} provider(s) tracked, none wedged or open` };
});

// Consumer's installed agent roster — v2 ships zero agents; delegation
// requires consumer to have installed at least one other kit (or to have
// authored agents locally).
check('consumer-agent-roster', () => {
  const searchDirs = [
    path.join(process.cwd(), '.claude/agents'),
    path.join(process.env.CLAUDE_PROJECT_DIR || '', '.claude/agents'),
    path.join(process.env.HOME || '', '.claude/agents'),
  ].filter(Boolean).filter(d => { try { fs.accessSync(d); return true; } catch { return false; } });

  const seen = new Set();
  for (const dir of searchDirs) {
    for (const f of fs.readdirSync(dir)) {
      if (f.startsWith('t1k-') && f.endsWith('.md')) seen.add(f);
    }
  }
  if (seen.size === 0) {
    return {
      status: 'warn',
      message: 'No t1k-* agents discoverable. Install theonekit-core (or any kit) to give model-router something to delegate to.',
    };
  }
  return { status: 'pass', message: `${seen.size} t1k-* agent(s) discoverable across cwd + ~/.claude/agents` };
});

// Skill present.
check('skill-installed', () => {
  const skillPath = path.join(process.cwd(), '.claude/skills/t1k-model-router-delegate/SKILL.md');
  if (fs.existsSync(skillPath)) return { status: 'pass', message: 'Skill t1k-model-router-delegate installed' };
  return { status: 'fail', message: 'Skill t1k-model-router-delegate missing' };
});

// Delegate script. Asserted at $HOME/.claude/scripts/ — the ONLY location the
// interceptor resolves it from (mr-task-interceptor.cjs, deliberate per #165:
// a project-local copy is attacker-plantable and gets handed to
// spawnSync('bash', …)). A project copy that is never executed proves nothing.
check('delegate-script', () => {
  const scriptPath = path.join(homeDir(), '.claude', 'scripts', 'mr-delegate.sh');
  if (!fs.existsSync(scriptPath)) {
    return { status: 'fail', message: `mr-delegate.sh missing at ${scriptPath} — the interceptor resolves it from $HOME only, so every routed delegation aborts. Run: bash .claude/scripts/post-install.sh` };
  }
  try { fs.accessSync(scriptPath, fs.constants.X_OK); return { status: 'pass', message: `mr-delegate.sh executable (global: ${scriptPath})` }; }
  catch { return { status: 'warn', message: `mr-delegate.sh exists but not executable (${scriptPath})` }; }
});

// 5b. THE routing prerequisite: the interceptor must exist AND be registered.
//
// Ported from mr-doctor.sh (#242) — that fix landed in the hand-run shell
// doctor only, leaving THIS hook (which runs automatically every session)
// carrying the exact blind spot #242 existed to kill.
//
// settings.json guards its require with `fs.existsSync(...)`, so a MISSING
// global hook is swallowed in silence: no error, no warning, every Task
// passes through to Anthropic, and every other check here still reports green.
// Production telemetry on 2026-08-14 showed 9 of 23 installs with
// routedCount=0 while reporting a healthy install.
check('task-interceptor', () => {
  const hookGlobal = path.join(homeDir(), '.claude', 'hooks', 'mr-task-interceptor.cjs');
  const hookLocal = path.join(process.cwd(), '.claude', 'hooks', 'mr-task-interceptor.cjs');
  if (fs.existsSync(hookGlobal)) {
    return { status: 'pass', message: `mr-task-interceptor.cjs installed (global: ${hookGlobal})` };
  }
  // FAIL, not WARN: the hook is registered, so `fs.existsSync` returns false and
  // every delegation silently reaches Anthropic. Routing is entirely off. A warning
  // buried in an otherwise-green report is how this went unnoticed across 9 installs.
  if (fs.existsSync(hookLocal)) {
    return { status: 'fail', message: 'mr-task-interceptor.cjs found in repo but NOT in ~/.claude/hooks/ — settings.json loads the GLOBAL copy, so ALL routing is silently off. Run: bash .claude/scripts/post-install.sh' };
  }
  return { status: 'fail', message: 'mr-task-interceptor.cjs MISSING — every delegation silently passes through to Anthropic. Run: bash .claude/scripts/post-install.sh' };
});

// Registered in settings.json? The hook file alone routes nothing.
check('interceptor-registered', () => {
  if (!settingsRegistry) {
    return {
      status: 'fail',
      message: 'scripts/mr-settings-registry.cjs could not be loaded — cannot verify that the '
        + 'interceptor is registered. Treat routing as UNVERIFIED. Run: bash .claude/scripts/post-install.sh',
    };
  }
  const r = settingsRegistry.checkInterceptorRegistered({ home: homeDir() });
  return { status: r.status, message: r.message };
});

// modelMapping config.
check('model-mapping-config', () => {
  const cfgPath = path.join(process.cwd(), '.claude/t1k-config-mr.json');
  if (!fs.existsSync(cfgPath)) return { status: 'warn', message: 't1k-config-mr.json not in project (using global default)' };
  try {
    const cfg = JSON.parse(fs.readFileSync(cfgPath, 'utf8'));
    const mm = cfg && cfg.modelRouter && cfg.modelRouter.modelMapping;
    if (!mm || typeof mm !== 'object' || Object.keys(mm).length === 0) {
      return { status: 'warn', message: 'modelRouter.modelMapping is empty — interceptor will passthrough everything' };
    }
    return { status: 'pass', message: `modelMapping has ${Object.keys(mm).length} entry(ies)` };
  } catch (err) {
    return { status: 'fail', message: `t1k-config-mr.json invalid: ${err.message}` };
  }
});

// Capability-tag coverage (v2.1) — every enabled model in providers-config.json
// needs a `capabilities` array, else the rule-based selector silently drops it
// from every candidate list (because `requiredCaps.every(r => caps.includes(r))`
// is vacuously true on the empty set, but agents requiring vision/long-context/
// reasoning would never match a tag-less model).
check('capability-tags', () => {
  const resolved = resolveProvidersConfigPath();
  if (!resolved) return { status: 'warn', message: 'providers-config.json not found in project or global (~/.claude/)' };
  const cfgPath = resolved.path;
  const scopeTag = resolved.scope === 'global' ? ' (global)' : '';
  try {
    const cfg = JSON.parse(fs.readFileSync(cfgPath, 'utf8'));
    const untagged = [];
    for (const [pname, p] of Object.entries(cfg.providers || {})) {
      if (p.enabled !== true) continue;
      for (const [mname, m] of Object.entries(p.models || {})) {
        if (m.enabled !== true) continue;
        if (!Array.isArray(m.capabilities) || m.capabilities.length === 0) {
          untagged.push(`${pname}/${mname}`);
        }
      }
    }
    if (untagged.length > 0) {
      return { status: 'warn', message: `${untagged.length} enabled model(s) have no capabilities array${scopeTag}: ${untagged.slice(0, 3).join(', ')}${untagged.length > 3 ? '…' : ''}` };
    }
    return { status: 'pass', message: `all enabled models carry capability tags${scopeTag}` };
  } catch (err) {
    return { status: 'fail', message: `providers-config.json invalid${scopeTag}: ${err.message}` };
  }
});

// Core telemetry emitter (telemetry-emit.cjs) — required by mr-delegate.sh
// and mr-telemetry.cjs since PR #415. If missing, all telemetry silently
// drops and the worker sees zero events.
check('telemetry-emitter', () => {
  const globalHooksDir = path.join(process.env.HOME || os.homedir(), '.claude', 'hooks');
  const emitPath = path.join(globalHooksDir, 'telemetry-emit.cjs');
  const utilsPath = path.join(globalHooksDir, 'telemetry-utils.cjs');

  if (!fs.existsSync(emitPath)) {
    return {
      status: 'fail',
      message: 'telemetry-emit.cjs missing in ~/.claude/hooks/. Fix: t1k init -g --kit core --refresh',
    };
  }

  if (!fs.existsSync(utilsPath)) {
    return {
      status: 'fail',
      message: 'telemetry-utils.cjs missing in ~/.claude/hooks/. Fix: t1k init -g --kit core --refresh',
    };
  }

  try {
    const utils = require(utilsPath);
    if (typeof utils.emitTelemetryEvent !== 'function') {
      return {
        status: 'fail',
        message: 'telemetry-utils.cjs does not export emitTelemetryEvent. Your core kit is outdated. Fix: t1k init -g --kit core --refresh',
      };
    }
  } catch (err) {
    return {
      status: 'fail',
      message: `telemetry-utils.cjs failed to load: ${err.message}. Fix: t1k init -g --kit core --refresh`,
    };
  }

  return { status: 'pass', message: 'telemetry-emit.cjs + emitTelemetryEvent available' };
});

// gh auth (for remote providers).
check('gh-auth', () => {
  try {
    const token = execSync('gh auth token', { encoding: 'utf8', stdio: ['pipe', 'pipe', 'ignore'], timeout: 5000 }).trim();
    if (token) return { status: 'pass', message: 'gh auth token available' };
    return { status: 'warn', message: 'gh auth token empty' };
  } catch {
    return { status: 'warn', message: 'gh not authenticated. Run: gh auth login (needed for kimi/codex/opencode-go providers)' };
  }
});

// Remote endpoint (kimi/codex auth proxy).
check('remote-endpoint', () => {
  try {
    const resp = execSync('curl -s --max-time 5 https://ccs.the1studio.org/health',
      { encoding: 'utf8', stdio: ['pipe', 'pipe', 'ignore'], timeout: 8000 });
    const data = JSON.parse(resp);
    if (data.status === 'ok') return { status: 'pass', message: 'ccs.the1studio.org reachable (remote providers available)' };
    return { status: 'warn', message: 'Remote endpoint responded but status not ok' };
  } catch {
    return { status: 'warn', message: 'ccs.the1studio.org unreachable (kimi/codex providers unavailable, opencode-go still works)' };
  }
});

// Kit freshness — is the locally installed kit at or above the latest
// release on GitHub? Stale installs are a common source of "why is the
// routing not behaving like the docs say?" — old hook code shipped before
// some fix landed. This check makes the answer one banner-line away.
//
// Cached for 12h so we don't hammer the GH API on every session start;
// gh CLI uses the user's existing auth, so no extra credentials needed.
// Fail-open: no gh / no network / no manifest → warn, never fail.
check('kit-freshness', () => {
  // 1. Local: read installed version from manifest. Global install ships
  //    .t1k-manifest.json under ~/.claude/modules/model-router/.
  const manifestPath = path.join(
    process.env.HOME || os.homedir(),
    '.claude', 'modules', 'model-router', '.t1k-manifest.json'
  );
  if (!fs.existsSync(manifestPath)) {
    return { status: 'warn', message: 'manifest not found — kit may not be globally installed (skip check)' };
  }
  let installedVer;
  try {
    installedVer = JSON.parse(fs.readFileSync(manifestPath, 'utf8')).version;
  } catch {
    return { status: 'warn', message: 'manifest unreadable (skip check)' };
  }
  if (!installedVer || typeof installedVer !== 'string') {
    return { status: 'warn', message: 'manifest has no .version field (skip check)' };
  }

  // 2. Remote: latest GitHub release tag. 12h cache file lives next to
  //    the provider-probe cache so the file layout stays predictable.
  const CACHE_PATH = path.join(process.env.HOME || os.homedir(), '.model-router', 'freshness-cache.json');
  const TTL_MS = 12 * 60 * 60 * 1000;
  let latestVer = null;
  try {
    const cache = JSON.parse(fs.readFileSync(CACHE_PATH, 'utf8'));
    if (cache && cache.latest_version && cache.checked_at && (Date.now() - cache.checked_at < TTL_MS)) {
      latestVer = cache.latest_version;
    }
  } catch { /* cache miss; refresh below */ }

  if (!latestVer) {
    try {
      // `gh` reuses the user's existing auth. If gh is missing or unauth'd,
      // execSync throws → we warn and skip rather than fail the check.
      // Use /git/refs/tags (NOT /releases or /tags): the kit ships TWO tags
      // per release — `modules-YYYYMMDD-HHMM` (date-stamped, useless for
      // version compare) and `model-router@X.Y.Z` (the semver we want).
      // /releases shows only the date-stamped form because it's the release
      // tag; /tags is sorted by commit date and the semver tags share commits
      // with the date tags so they may not appear in the top page. Refs are
      // returned in lexicographic order — semver tags sort to the end.
      // execFileSync (no shell) rather than execSync: on Windows execSync goes
      // through cmd.exe, where single quotes are not quoting characters and `|`
      // is a pipe operator — cmd split the old jq filter at the pipe and tried
      // to run `select` as a program, so this check failed on every Windows
      // session and the freshness cache was never written. Passing argv
      // directly keeps the expression intact on every platform; the
      // `model-router@` filter lives in the JS loop below instead of jq.
      const refsJson = execFileSync(
        'gh',
        ['api', 'repos/The1Studio/theonekit-model-router/git/refs/tags', '--jq', '[.[].ref]'],
        { encoding: 'utf8', stdio: ['pipe', 'pipe', 'ignore'], timeout: 5000 }
      );
      const refs = JSON.parse(refsJson);
      // Compare every semver tag and keep the highest, NOT just the last
      // refs in lexicographic order ("model-router@3.10.0" sorts before
      // "model-router@3.9.0" lexicographically, breaking last-wins).
      let highest = null;
      for (const r of refs) {
        const m = String(r).match(/model-router@(\d+\.\d+\.\d+)$/);
        if (!m) continue;
        if (highest === null || compareSemver(m[1], highest) > 0) {
          highest = m[1];
        }
      }
      latestVer = highest;
      if (latestVer) {
        try {
          fs.mkdirSync(path.dirname(CACHE_PATH), { recursive: true });
          fs.writeFileSync(CACHE_PATH, JSON.stringify({
            latest_version: latestVer,
            checked_at: Date.now(),
            valid_until: new Date(Date.now() + TTL_MS).toISOString(),
          }));
        } catch { /* cache write fail-open */ }
      }
    } catch (err) {
      return {
        status: 'warn',
        message: `installed=${installedVer}, latest=unknown (gh API unreachable: ${String(err.message || err).split('\n')[0]})`,
      };
    }
  }

  if (!latestVer) {
    return { status: 'warn', message: `installed=${installedVer}, latest=unknown (no semver tag found in last 10 releases)` };
  }

  const cmp = compareSemver(installedVer, latestVer);
  if (cmp >= 0) {
    return { status: 'pass', message: `installed=${installedVer} (up to date with latest=${latestVer})` };
  }
  return {
    status: 'warn',
    message: `OUTDATED: installed=${installedVer} < latest=${latestVer}. Run: t1k init -g --kit model-router --refresh`,
  };
});

// Per-provider aliveness probes. The probe runs a real chat-completion
// (max_tokens=4) against each provider in providers-config.json so we catch
// the "endpoint up but upstream broken" case (e.g. codex returning 502
// while /providers reports it as authenticated — observed 2026-05-25).
//
// The probe script writes a `valid_until` ISO timestamp into the cache —
// that's the single source of truth for freshness. This hook just reads it.
(function probeProviders() {
  const CACHE_PATH = path.join(process.env.HOME || '', '.model-router', 'provider-probe-cache.json');

  let cache = null;
  try {
    if (fs.existsSync(CACHE_PATH)) {
      cache = JSON.parse(fs.readFileSync(CACHE_PATH, 'utf8'));
      if (cache.valid_until && Date.now() > new Date(cache.valid_until).getTime()) {
        cache = null;  // stale → reprobe
      }
    }
  } catch { cache = null; }

  if (!cache) {
    const probeSh = path.join(process.cwd(), '.claude/scripts/mr-probe-providers.sh');
    if (fs.existsSync(probeSh)) {
      try {
        execSync(`bash "${probeSh}" --json`, { encoding: 'utf8', stdio: ['pipe', 'pipe', 'ignore'], timeout: 30000 });
        if (fs.existsSync(CACHE_PATH)) cache = JSON.parse(fs.readFileSync(CACHE_PATH, 'utf8'));
      } catch { /* fail-open — leave cache null */ }
    }
  }

  if (!cache || !Array.isArray(cache.providers)) {
    results.push({ name: 'provider-aliveness', status: 'warn', message: 'provider probe cache unavailable — run: bash .claude/scripts/mr-probe-providers.sh' });
    return;
  }

  for (const p of cache.providers) {
    const name = `provider:${p.name}`;
    if (p.status === 'pass') {
      results.push({ name, status: 'pass', message: `${p.model} → 200 in ${p.latency_ms}ms` });
    } else if (p.status === 'skip') {
      results.push({ name, status: 'warn', message: p.reason });
    } else {
      // Dead provider is a 'warn' not 'fail' — the kit is fine; the upstream is broken.
      results.push({ name, status: 'warn', message: `DEAD — ${p.reason}. mr-delegate.sh will fail fast on --provider ${p.name}` });
    }
  }
})();

console.log(JSON.stringify({ kit: 'theonekit-model-router', checks: results }, null, 2));

// This script runs as a SessionStart hook (settings.json) that emits the boot
// health summary above. Per the Claude Code hook contract a SessionStart hook
// may exit ONLY 0 (advisory — stdout joins context) or 2 (block — stderr fed
// back); exit 1 is an invalid "non-blocking error" that the kit's
// validate-hook-smoke-test gate rejects. And a *diagnostic report* must never
// fail or block the user's session — a misconfigured model-router just makes
// transparent routing pass Task spawns through to Anthropic, which is not a
// session error. So surface any failures as a non-blocking stderr advisory
// (the per-check status is already in the summary above) and ALWAYS exit 0.
// The standalone CLI `mr-doctor.sh` keeps its own exit-1 for scripting use.
if (hasFailure) {
  const failed = results.filter(r => r.status === 'fail').map(r => r.name);
  process.stderr.write(
    `[t1k:model-router] doctor: ${failed.length} check(s) failed (${failed.join(', ')}) — ` +
    'see the health summary above; run `bash .claude/scripts/mr-doctor.sh` for detail.\n'
  );
}
process.exit(0);

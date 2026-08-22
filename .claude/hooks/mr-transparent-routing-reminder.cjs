#!/usr/bin/env node
// t1k-origin: kit=theonekit-model-router | repo=The1Studio/theonekit-model-router | module=null | protected=false
/**
 * mr-transparent-routing-reminder.cjs — SessionStart hook
 *
 * Emits a multi-line dashboard when transparent routing is active.
 * Provides at-a-glance presence so consumers know the kit is operating
 * without having to grep logs (user feedback 2026-05-28).
 *
 * Includes:
 *   • Status line (kit version + mode + agent-count)
 *   • Last 24h delegation count + success rate + models used
 *   • Provider health (from probe cache)
 *   • Delegation Bias rule reminder for inline edits
 *   • Per-spawn banner format the AI should expect
 *
 * Exit codes:
 *   0 = always (no-op if transparent routing is off)
 *
 * Fail-open: any read error → falls back to minimal reminder.
 */

'use strict';

const fs = require('fs');
const path = require('path');
const os = require('os');

// ─── Interceptor-registration predicate (SSOT) ──────────────────────────────
// Shared with mr-doctor-check.cjs. The config flags below say what the consumer
// ASKED FOR; this says whether Claude Code will actually run the interceptor.
// Only the second one can justify the word ACTIVE.
let settingsRegistry;
try {
  settingsRegistry = require(path.join(__dirname, '..', 'scripts', 'mr-settings-registry.cjs'));
} catch { settingsRegistry = null; }

/**
 * Registration state for the banner: 'wired' | 'unwired' | 'unknown'.
 *
 * 'unknown' is a distinct outcome on purpose — an unverifiable state must not
 * render as a healthy one (rules/green-that-proves-nothing.md). `reason` carries
 * the helper's diagnosis so the banner can print remediation, not just a verdict.
 */
function registrationState() {
  if (!settingsRegistry) {
    return { state: 'unknown', reason: 'scripts/mr-settings-registry.cjs not loadable' };
  }
  try {
    const r = settingsRegistry.checkInterceptorRegistered();
    return r.registered
      ? { state: 'wired', reason: r.message }
      : { state: 'unwired', reason: r.message };
  } catch (err) {
    return { state: 'unknown', reason: String((err && err.message) || err).split('\n')[0] };
  }
}

function tryReadJson(p) {
  try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch { return null; }
}

function tryReadJsonl(p, maxLines) {
  try {
    const text = fs.readFileSync(p, 'utf8');
    const lines = text.trim().split('\n').slice(-maxLines);
    return lines.map(l => { try { return JSON.parse(l); } catch { return null; } }).filter(Boolean);
  } catch { return []; }
}

function get24hCutoff() {
  return new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
}

function readKitVersion(projectDir) {
  // Try the module.json shipped with the kit.
  const candidates = [
    path.join(os.homedir(), '.claude', 'modules', 'model-router', 'module.json'),
    path.join(projectDir, '.claude', 'modules', 'model-router', 'module.json'),
  ];
  for (const p of candidates) {
    const j = tryReadJson(p);
    if (j && j.version) return j.version;
  }
  return null;
}

function loadDelegationStats(cutoff) {
  // calls.jsonl is the canonical lifecycle log. Read up to 5000 recent lines.
  const calls = tryReadJsonl(path.join(os.homedir(), '.model-router', 'calls.jsonl'), 5000);
  const recent = calls.filter(c => c && c.status === 'done' && c.ts && c.ts >= cutoff);
  const ok = recent.filter(c => c.exit === 0);
  const byModel = {};
  for (const c of recent) {
    const k = c.model || '?';
    byModel[k] = (byModel[k] || 0) + 1;
  }
  return { total: recent.length, ok: ok.length, byModel };
}

function loadProviderHealth() {
  const cache = tryReadJson(path.join(os.homedir(), '.model-router', 'provider-probe-cache.json'));
  if (!cache || !Array.isArray(cache.providers)) return null;
  // The cache now carries one row per (provider, model) so every pipe hop is
  // verified (#230), and a provider with two routed models yields two rows.
  // Collapse to one token per provider for the banner, WORST STATUS WINS: a
  // provider is only ✓ when every model probed for it passed. Naming the failing
  // model matters — "opencode-go✗" alone sends you to look at a provider that is
  // in fact serving its primary fine, when a single failover hop is what broke.
  const byProvider = new Map();
  for (const p of cache.providers) {
    if (!p || !p.name) continue;
    const entry = byProvider.get(p.name) || { ok: true, failed: [] };
    if (p.status !== 'pass') {
      entry.ok = false;
      if (p.model) entry.failed.push(p.model);
    }
    byProvider.set(p.name, entry);
  }
  const parts = [...byProvider.entries()].map(([name, e]) =>
    e.ok ? `${name}✓` : `${name}✗${e.failed.length ? `(${e.failed.join(',')})` : ''}`);
  const summary = parts.join(' · ');

  // The probe writes `valid_until` as the canonical freshness deadline
  // (mr-probe-providers.sh, mirrored by mr-doctor-check.cjs's own reprobe
  // check). This banner used to render `summary` unconditionally with no
  // expiry check at all — an expired cache (observed: generated_at 18:29:02Z,
  // valid_until 19:29:05Z, read an hour past expiry) still printed
  // `opencode-go✓ · kimi✓` looking identical to a fresh healthy probe. Per
  // rules/green-that-proves-nothing.md, *unknown* must not render as *good* —
  // a stale cache is a claim about the LAST probe, not the CURRENT state.
  const validUntilMs = cache.valid_until ? new Date(cache.valid_until).getTime() : NaN;
  const isStale = Number.isFinite(validUntilMs) && Date.now() > validUntilMs;
  if (!isStale) return { summary, stale: false };
  const ageMin = Math.round((Date.now() - validUntilMs) / 60000);
  return { summary, stale: true, staleForMin: ageMin };
}

function countAgents(projectDir) {
  // Where does the interceptor look for agents? Same search dirs.
  const dirs = [
    path.join(projectDir, '.claude', 'agents'),
    path.join(os.homedir(), '.claude', 'agents'),
  ];
  let total = 0;
  const seen = new Set();
  for (const d of dirs) {
    try {
      for (const f of fs.readdirSync(d)) {
        if (!f.endsWith('.md')) continue;
        if (seen.has(f)) continue;
        seen.add(f);
        total += 1;
      }
    } catch { /* dir may not exist */ }
  }
  return total;
}

// Route-vs-fallback rate over the recent decision window.
//
// The existing `success` figure counts DELEGATION outcomes, which is why a
// silently-degraded router looked healthy: when every hop fails the delegate
// falls back to Anthropic, the caller still gets a good answer, so nothing in
// the banner ever indicated that the router had stopped routing. This reads the
// interceptor's own decisions instead — the only place the distinction exists.
// Routing health, measured from DELEGATION OUTCOMES inside a time window (#236).
//
// Two things were wrong with reading `decision` counts out of debug.jsonl:
//
// 1. It was UNWINDOWED, so a past outage could never age out. On the box this
//    was reported from, `pass-all-providers-failed` totalled 112 — but 94 of
//    those landed on three days during the kimi-k2.5 era (29 + 31 + 34), which
//    is fixed. The lifetime ratio sat at 25% and would have stayed red forever
//    no matter how well the router ran today. An alarm that cannot clear is not
//    an alarm.
// 2. The numerator could not see delegations that bypass the interceptor.
//    `decision: 'route'` is emitted only on the Task-interception path, so a
//    direct `mr-delegate.sh` call (selectionSource "explicit", 16 of 46 traces
//    in one week) routed successfully and counted as nothing.
//
// traces.jsonl fixes both: every entrypoint writes exactly one trace per
// delegation, and a policy passthrough writes none — so the denominator is
// naturally "work that actually attempted to route", with no passthrough to
// subtract and no double counting.
const ROUTING_WINDOW_DAYS = 7;

function loadRoutingRate(windowDays = ROUTING_WINDOW_DAYS) {
  try {
    const f = path.join(os.homedir(), '.model-router', 'traces.jsonl');
    if (!fs.existsSync(f)) return null;
    const cutoff = new Date(Date.now() - windowDays * 86400000).toISOString();
    let routed = 0, fellback = 0;
    for (const l of fs.readFileSync(f, 'utf8').trim().split('\n')) {
      if (!l) continue;
      let t;
      try { t = JSON.parse(l); } catch { continue; }
      if (!t || typeof t.ts !== 'string' || t.ts < cutoff) continue;
      // A delegation that reached a cheap provider and finished is routed work;
      // anything that ended by handing the task back to Anthropic is a fallback.
      //
      // Read the TOP-LEVEL `exit`, not `hops`. `hops` only exists on traces
      // written since #220 — 17 of 58 on this box — so keying on it silently
      // scored every older delegation as a failure and reported days that were
      // genuinely fine as 0% routed. `exit` is present in both schemas.
      const succeeded = typeof t.exit === 'number'
        ? t.exit === 0
        : (Array.isArray(t.hops) && t.hops.some(h => h && h.exit === 0));
      if (succeeded) routed++; else fellback++;
    }
    const routable = routed + fellback;
    if (routable === 0) return null;
    return { routed, fellback, routable, windowDays, pct: Math.round((routed / routable) * 100) };
  } catch { return null; }
}

// Hoisted so the fail-open catch below can still tell a verified-wired install
// from an unverified one. Before this, ANY throw printed "ACTIVE" unconditionally.
let reg = { state: 'unknown', reason: 'not yet checked' };

try {
  const projectDir = process.env.CLAUDE_PROJECT_DIR || process.cwd();

  // Honor the project's config gate — same logic as before.
  const configPath = path.join(projectDir, '.claude', 't1k-config-mr.json');
  const globalConfigPath = path.join(os.homedir(), '.claude', 't1k-config-mr.json');
  const config = tryReadJson(configPath) || tryReadJson(globalConfigPath);
  const mr = config && config.modelRouter;
  if (!mr || mr.enabled !== true || mr.mode !== 'transparent') {
    process.exit(0);
  }

  // The config flags above are an INTENT, not a state. Claude Code only runs the
  // interceptor when $HOME/.claude/settings.json registers it, and post-install
  // skips that write in non-TTY without an opt-in (#136 consent gate). Gating the
  // banner on the flags alone printed "transparent routing ACTIVE" on installs
  // where every Task went to Anthropic — the same false-green family as #242.
  reg = registrationState();

  if (reg.state === 'unwired') {
    // Short-circuit: no delegation stats, no provider health, no Delegation Bias
    // nudge. None of it applies, and a full dashboard reads as health. One
    // unmissable block naming the consequence and the fix.
    process.stdout.write([
      '[t1k:model-router] ⚠ NOT ROUTING — transparent routing is enabled in config but the',
      '                   Task interceptor is NOT registered in ~/.claude/settings.json.',
      `                   ${reg.reason}`,
      '                   Consequence: EVERY Task spawn runs on Anthropic at full price.',
      '                   Fix: MR_ALLOW_GLOBAL_SETTINGS=1 node .claude/scripts/post-install.cjs',
      '                   Verify: bash .claude/scripts/mr-doctor.sh',
    ].join('\n') + '\n');
    process.exit(0);
  }

  const version = readKitVersion(projectDir);
  const stats = loadDelegationStats(get24hCutoff());
  const health = loadProviderHealth();
  const routing = loadRoutingRate();
  const agentCount = countAgents(projectDir);

  const versionStr = version ? `v${version}` : 'enabled';
  const succRate = stats.total > 0 ? Math.round((stats.ok / stats.total) * 100) : null;
  const modelsStr = Object.entries(stats.byModel)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 4)
    .map(([m, n]) => `${m}×${n}`)
    .join(' ');

  // Banner format the interceptor now uses (the AI should look for this).
  const sampleBanner = '[t1k:mr] ✓ <agent>[<model>] — <provider> (<selector>)';

  // 'wired' is the only state that earns the word ACTIVE. 'unknown' means the
  // registration could not be read at all — say so rather than pick a verdict.
  const statusStr = reg.state === 'wired'
    ? 'transparent routing ACTIVE'
    : `transparent routing UNVERIFIED (${reg.reason})`;

  const lines = [
    `[t1k:model-router] ${versionStr} · ${statusStr} · ${agentCount} agents in scope`,
    stats.total > 0
      ? `  ├─ Last 24h: ${stats.total} delegations · ${succRate}% success · models: ${modelsStr || '(none)'}`
      : `  ├─ Last 24h: 0 delegations (kit is idle but ready)`,
    health
      ? (health.stale
          ? `  ├─ Providers: ⚠ STALE (expired ${health.staleForMin}m ago) — last probe: ${health.summary} — reprobe: \`bash .claude/scripts/mr-probe-providers.sh\``
          : `  ├─ Providers: ${health.summary}`)
      : `  ├─ Providers: (no recent probe — run \`bash .claude/scripts/mr-probe-providers.sh\`)`,
    ...(routing && routing.routable >= 5 && routing.pct < 50
      ? [`  ├─ ⚠ ROUTING DEGRADED: ${routing.pct}% of delegations routed in the last `
         + `${routing.windowDays}d (${routing.fellback}/${routing.routable} fell back to Anthropic). `
         + `Diagnose: \`bash .claude/scripts/mr-dashboard.sh\` → Routing Health.`]
      : []),
    `  ├─ Per-Task banner: ${sampleBanner}`,
    `  └─ Delegation Bias (rules/mr-transparent-routing.md): mechanical/boilerplate work → Task tool; multi-file/judgment → inline.`,
    `     Diagnose any session: \`bash .claude/scripts/mr-tail-debug.sh\` — full playbook: wiki/Diagnostic-Playbook.`,
  ];

  process.stdout.write(lines.join('\n') + '\n');
  process.exit(0);
} catch {
  // Fail-open: emit the minimal reminder as a last resort.
  //
  // This path used to print "ACTIVE" unconditionally — with LESS gating than the
  // main path, so the least-informed branch made the strongest claim. It now
  // reports only what `reg` actually established before the throw.
  try {
    process.stdout.write(reg.state === 'wired'
      ? '[t1k:transparent-routing] ACTIVE — Delegation Bias enforced. See rules/mr-transparent-routing.md.\n'
      : '[t1k:transparent-routing] state UNVERIFIED — could not confirm the Task interceptor is '
        + 'registered in ~/.claude/settings.json; routing may be entirely off. '
        + 'Check: bash .claude/scripts/mr-doctor.sh\n');
  } catch { /* ignore */ }
  process.exit(0);
}

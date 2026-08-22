#!/usr/bin/env node
// t1k-origin: kit=theonekit-core | repo=The1Studio/theonekit-core | module=t1k-base | protected=true
// check-always-loaded-union.cjs — Doctor check #59: always-loaded UNION budget.
//
// WHAT THIS MEASURES THAT NOTHING ELSE DOES
// -----------------------------------------
// Every other budget check in this ecosystem measures ONE population:
//   - `validate-context-window-budget.cjs` (release-action) caps ONE KIT at
//     release time. Every kit can pass its own gate independently.
//   - check #37 `check-context-budget.cjs` sums the PROJECT scope only
//     (`<projectRoot>/.claude/rules/*.md` + `<projectRoot>/CLAUDE.md`).
//   - check #38 `check-oversized-rules.cjs` caps ONE FILE, project scope only.
//
// But a session loads the UNION of every installed kit's always-loaded surface,
// across BOTH scopes. Nothing owned that union, so nothing could observe it. On
// the machine this check was written for (2026-08-20) the global scope alone was
// ~40,500 tokens across 60 rule files — roughly 2x the per-kit release cap —
// while check #37 reported PASS, because a consumer's PROJECT `.claude/rules/`
// is usually near-empty and that is the only thing #37 can see.
//
// That is the `rules/green-that-proves-nothing.md` "measures the wrong
// population" shape: the existing check is real, it passes honestly, and it is
// structurally incapable of observing the cost that actually hurts. This check
// is the missing population.
//
// WHY BOTH SCOPES ARE SUMMED RATHER THAN SHADOWED
// -----------------------------------------------
// For KIT CONTENT resolution, project-local shadows global
// (`rules/prefer-local-over-global-edits.md`). For CONTEXT LOADING it does not:
// Claude Code injects the user's global rules AND the project's rules into the
// same session, so a rule present in both scopes is loaded TWICE and billed
// twice. That double-load is reported separately below as recoverable waste and
// is the per-file subject of check #36.
//
// WARN-ONLY, NEVER BLOCKS
// -----------------------
// RATCHET (dated 2026-08-20): this check is warn-first by design and always
// exits 0. A consumer who is already 2x over budget must not have their session
// broken by the check that tells them so. Revisit promoting the union breach to
// a FAIL only once the fleet median sits under DEFAULT_UNION_BUDGET; promoting
// it earlier would break more installs than it fixes. Per CLAUDE.md Core
// Requirement #13, this comment is the ratchet condition, not a TODO.
//
// UNKNOWN IS NOT ZERO
// -------------------
// With no resolvable install metadata in either scope the check reports UNKNOWN
// and says so in those words. An empty denominator must never render as a
// healthy zero (`rules/green-that-proves-nothing.md`).
//
// Usage:
//   node check-always-loaded-union.cjs [path/to/project-root]
//
// Environment overrides:
//   T1K_UNION_BUDGET_TOKENS=25000   # union budget
//   T1K_UNION_GLOBAL_DIR=<dir>      # global `.claude/` dir (test injection)
//   T1K_UNION_TOP_N=10              # how many offending files to list
//
// Exit code: always 0 (WARN level).

'use strict';

const fs   = require('node:fs');
const path = require('node:path');

const { estimateTokens } = require('../../../hooks/lib/token-estimate.cjs');

const CHECK_NAME = 'always-loaded-union';

// Union budget rationale (2026-08-20): the per-kit release cap is 20,000 tokens
// and a realistic install is core + one engine kit + model-router. 25,000 gives
// roughly one extra kit of headroom over core alone, and lands at ~12.5% of a
// 200K context window consumed before any work begins. It is deliberately BELOW
// today's measured reality (~40.5K) — a budget nobody currently breaches would
// be decoration.
const DEFAULT_UNION_BUDGET = 25000;
const DEFAULT_TOP_N = 10;

// ── scope + metadata resolution (reuses telemetry-utils; no inline .claude joins) ──

/**
 * Resolve the two scopes a session loads from.
 * `projectRootArg` wins when given (CLI arg / test injection); otherwise the
 * shared `resolveProjectDir()` decides, exactly as every other hook does.
 * @returns {{ globalClaudeDir: string|null, projectClaudeDir: string|null, projectRoot: string|null }}
 */
function resolveScopes(projectRootArg, utils) {
  const { resolveProjectDir, getHomeDir, isGlobalClaudeDir } = utils;

  const globalOverride = process.env.T1K_UNION_GLOBAL_DIR;
  let globalClaudeDir = null;
  if (globalOverride) {
    globalClaudeDir = path.resolve(globalOverride);
  } else {
    const home = getHomeDir();
    globalClaudeDir = home ? path.join(home, '.claude') : null;
  }
  if (globalClaudeDir && !fs.existsSync(globalClaudeDir)) globalClaudeDir = null;

  let projectRoot = projectRootArg ? path.resolve(projectRootArg) : null;
  let projectClaudeDir = projectRoot ? path.join(projectRoot, '.claude') : null;

  if (!projectClaudeDir) {
    try {
      const resolved = resolveProjectDir();
      if (resolved && resolved.t1kDir && !resolved.globalOnly) {
        projectClaudeDir = resolved.t1kDir;
        projectRoot = path.dirname(resolved.t1kDir);
      }
    } catch { /* fail-open — treated as global-only below */ }
  }

  // A "project" that resolves to $HOME/.claude is the global install, not a
  // second scope; counting it twice would double every global rule.
  if (projectClaudeDir && globalClaudeDir) {
    try {
      if (isGlobalClaudeDir(projectClaudeDir)) { projectClaudeDir = null; projectRoot = null; }
    } catch { /* keep both — over-reporting is the safe direction here */ }
  }
  if (projectClaudeDir && !fs.existsSync(projectClaudeDir)) { projectClaudeDir = null; }

  return { globalClaudeDir, projectClaudeDir, projectRoot };
}

function readJson(file) {
  try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch { return null; }
}

/**
 * The installed set for ONE scope, resolved the way a session resolves it:
 * `metadata.installedModules` first, filesystem `modules/` scan as fallback.
 *
 * `installedModules` keys come in TWO schemes and both must be handled: the
 * qualified `"<kit>:<module>"` form written since cli#245
 * (`metadataKeyScheme: "qualified"`) and the legacy bare `"<module>"` form.
 * Everything downstream — the on-disk `modules/<name>/` directory name and a
 * rule's `module:` frontmatter — speaks the BARE name, so the key is
 * normalized here. Skipping this normalization is not a silent no-op: the first
 * run of this check against a real qualified install reported all 25
 * module-owned rules as "owned by a module not installed", a false alarm on
 * every single one.
 *
 * @returns {{ present: boolean, modules: string[], kits: string[] }} `modules` is bare names
 */
function readInstalledSet(claudeDir, utils) {
  if (!claudeDir) return { present: false, modules: [], kits: [] };
  const meta = readJson(path.join(claudeDir, 'metadata.json'));
  if (!meta) return { present: false, modules: [], kits: [] };
  let modules = [];
  try {
    modules = utils.getModuleEntries(meta, claudeDir)
      .map((e) => bareModuleName(e.name))
      .filter(Boolean);
  } catch { modules = []; }
  const kits = meta.kits && typeof meta.kits === 'object' ? Object.keys(meta.kits) : [];
  return { present: true, modules: [...new Set(modules)], kits };
}

/** `"theonekit-core:t1k-base"` → `"t1k-base"`; a bare name passes through. */
function bareModuleName(key) {
  if (typeof key !== 'string' || !key) return null;
  const idx = key.lastIndexOf(':');
  return idx === -1 ? key : key.slice(idx + 1);
}

// ── always-loaded file collection ────────────────────────────────────────────

const UNATTRIBUTED = '(unattributed)';

/** Parse `origin:` / `module:` out of a leading YAML frontmatter block. */
function readAttribution(content) {
  const fm = /^---\r?\n([\s\S]*?)\r?\n---/.exec(content);
  if (!fm) return { origin: null, module: null };
  const pick = (key) => {
    const m = new RegExp(`^${key}:[ \\t]*(.*)$`, 'm').exec(fm[1]);
    if (!m) return null;
    const v = m[1].trim().replace(/^["']|["']$/g, '');
    return (!v || v === 'null' || v === '~') ? null : v;
  };
  return { origin: pick('origin'), module: pick('module') };
}

function listRuleFiles(dir) {
  if (!dir || !fs.existsSync(dir)) return [];
  try {
    return fs.readdirSync(dir).filter((f) => f.endsWith('.md')).sort()
      .map((f) => path.join(dir, f));
  } catch { return []; }
}

/**
 * Collect every always-loaded file for one scope: flat `rules/*.md`, the
 * nested `modules/<name>/rules/*.md` of INSTALLED modules that are not already
 * flattened, and that scope's `CLAUDE.md`.
 */
function collectScope(claudeDir, scopeLabel, installed, claudeMdPath) {
  const out = [];
  if (!claudeDir) return out;

  const flatBasenames = new Set();
  for (const file of listRuleFiles(path.join(claudeDir, 'rules'))) {
    flatBasenames.add(path.basename(file));
    out.push({ file, scope: scopeLabel, kind: 'rule' });
  }

  // Kit SOURCE trees keep module rules nested; consumer installs flatten them
  // into rules/. Count a nested rule only when no flat copy already covers it,
  // and only for modules that are actually installed — an uninstalled module's
  // rules never reach a session.
  const modulesRoot = path.join(claudeDir, 'modules');
  if (fs.existsSync(modulesRoot)) {
    for (const moduleName of installed.modules) {
      for (const file of listRuleFiles(path.join(modulesRoot, moduleName, 'rules'))) {
        if (flatBasenames.has(path.basename(file))) continue;
        out.push({ file, scope: scopeLabel, kind: 'rule', nestedModule: moduleName });
      }
    }
  }

  if (claudeMdPath && fs.existsSync(claudeMdPath)) {
    out.push({ file: claudeMdPath, scope: scopeLabel, kind: 'CLAUDE.md' });
  }
  return out;
}

/**
 * Measure the union. Pure over its inputs: no process.exit, no printing.
 * @returns {object} structured facts for the reporter and for tests
 */
function scanUnion({ globalClaudeDir, projectClaudeDir, projectRoot }, utils) {
  const globalInstalled  = readInstalledSet(globalClaudeDir, utils);
  const projectInstalled = readInstalledSet(projectClaudeDir, utils);

  const entries = [
    ...collectScope(globalClaudeDir, 'global', globalInstalled,
      globalClaudeDir ? path.join(globalClaudeDir, 'CLAUDE.md') : null),
    ...collectScope(projectClaudeDir, 'project', projectInstalled,
      projectRoot ? path.join(projectRoot, 'CLAUDE.md') : null),
  ];

  const installedModules = new Set([...globalInstalled.modules, ...projectInstalled.modules]);

  const files = [];
  const byKit = new Map();
  const byScope = { global: { tokens: 0, files: 0 }, project: { tokens: 0, files: 0 } };
  const orphaned = [];

  for (const entry of entries) {
    let content = '';
    try { content = fs.readFileSync(entry.file, 'utf8'); } catch { continue; }
    const tokens = estimateTokens(content);
    const { origin, module } = readAttribution(content);
    const kit = origin || (entry.kind === 'CLAUDE.md' ? '(project instructions)' : UNATTRIBUTED);

    const rec = { ...entry, tokens, kit, module: bareModuleName(module) || entry.nestedModule || null };
    files.push(rec);
    byKit.set(kit, (byKit.get(kit) || 0) + tokens);
    byScope[entry.scope].tokens += tokens;
    byScope[entry.scope].files += 1;

    // A rule owned by a module nobody installed still sits in rules/ and still
    // loads — recoverable waste, and the reason installedModules is read at all.
    if (rec.module && installedModules.size > 0 && !installedModules.has(rec.module)) {
      orphaned.push(rec);
    }
  }

  files.sort((a, b) => b.tokens - a.tokens);

  // Same RULE basename in both scopes ⇒ the same rule loaded twice, which is
  // recoverable waste. CLAUDE.md is deliberately excluded: the global and
  // project files share a basename but are different documents that are both
  // MEANT to load, so counting them here would report an unfixable "waste" and
  // send a user chasing a duplicate that does not exist.
  const seen = new Set();
  const doubleLoaded = [];
  for (const rec of files) {
    if (rec.kind !== 'rule') continue;
    const key = path.basename(rec.file);
    if (seen.has(key)) doubleLoaded.push(rec); else seen.add(key);
  }

  return {
    metadataPresent: globalInstalled.present || projectInstalled.present,
    globalClaudeDir,
    projectClaudeDir,
    installedModules: [...installedModules].sort(),
    installedKits: [...new Set([...globalInstalled.kits, ...projectInstalled.kits])].sort(),
    files,
    byScope,
    byKit: [...byKit.entries()].map(([kit, tokens]) => ({ kit, tokens })).sort((a, b) => b.tokens - a.tokens),
    doubleLoaded,
    orphaned,
    total: files.reduce((sum, f) => sum + f.tokens, 0),
  };
}

// ── reporting ────────────────────────────────────────────────────────────────

function say(line) { console.log(line); }
function emit(status, message) { say(`[t1k:doctor] ${CHECK_NAME}: ${status} — ${message}`); }
function marker(status, tokens, budget) {
  say(`[t1k:doctor:${CHECK_NAME} status=${status} tokens=${tokens} budget=${budget}]`);
}

function shortPath(file, scan) {
  const home = process.env.HOME || process.env.USERPROFILE || '';
  if (home && file.startsWith(home)) return `~${file.slice(home.length)}`;
  if (scan.projectClaudeDir) {
    const root = path.dirname(scan.projectClaudeDir);
    if (file.startsWith(root)) return `.${file.slice(root.length)}`;
  }
  return file;
}

function report(scan, budget, topN) {
  // UNKNOWN must not render as a healthy zero.
  if (!scan.metadataPresent) {
    emit('UNKNOWN', 'no T1K install metadata found in either scope — cannot determine what a session loads. '
      + 'This is NOT a zero; run `t1k doctor` from a project with `.claude/metadata.json`, or pass the project root.');
    say(`  looked in: global=${scan.globalClaudeDir || '(none)'}  project=${scan.projectClaudeDir || '(none)'}`);
    marker('unknown', -1, budget);
    return;
  }
  if (scan.files.length === 0) {
    emit('UNKNOWN', 'install metadata found but zero always-loaded files were readable — '
      + 'a real install always loads at least one rule, so treat this as unmeasured, not as 0 tokens.');
    marker('unknown', -1, budget);
    return;
  }

  const total = scan.total;
  const pct = Math.round((total / budget) * 100);
  const over = total > budget;

  emit(over ? 'WARN' : 'PASS',
    `a session loads ~${total} tokens of always-loaded content across ${scan.files.length} file(s) `
    + `— ${pct}% of the ${budget}-token union budget`);

  say(`  scope split: global ~${scan.byScope.global.tokens} (${scan.byScope.global.files} file(s))`
    + `  ·  project ~${scan.byScope.project.tokens} (${scan.byScope.project.files} file(s))`);
  say(`  installed: ${scan.installedModules.length} module(s)`
    + (scan.installedKits.length ? ` across kit(s): ${scan.installedKits.join(', ')}` : ''));

  say('  per-kit attribution (descending):');
  for (const { kit, tokens } of scan.byKit) {
    say(`    ${String(tokens).padStart(7)}  ${kit}`);
  }

  say(`  top offending files (descending, top ${Math.min(topN, scan.files.length)}):`);
  for (const f of scan.files.slice(0, topN)) {
    say(`    ${String(f.tokens).padStart(7)}  ${shortPath(f.file, scan)}  [${f.kit}]`);
  }

  if (scan.doubleLoaded.length > 0) {
    const wasted = scan.doubleLoaded.reduce((s, f) => s + f.tokens, 0);
    say(`  double-loaded across scopes: ${scan.doubleLoaded.length} file(s), ~${wasted} tokens `
      + 'billed twice in one session — see check #36 (rule duplication).');
  }
  if (scan.orphaned.length > 0) {
    const stale = scan.orphaned.reduce((s, f) => s + f.tokens, 0);
    say(`  ${scan.orphaned.length} rule(s) owned by module(s) not in the installed set (~${stale} tokens) `
      + '— possible stale files from an uninstalled module; see check #12.');
  }

  if (over) {
    say('  fix: attack the top offender first — split it, or move detail to docs/ (loaded on demand).');
    say('  WARN only, by design: a consumer already over budget must not have their session broken '
      + 'by the check that reports it.');
  }

  marker(over ? 'warn' : 'pass', total, budget);
}

function run() {
  const utils = require('../../../hooks/telemetry-utils.cjs');
  const budget = Number(process.env.T1K_UNION_BUDGET_TOKENS || DEFAULT_UNION_BUDGET);
  const topN = Number(process.env.T1K_UNION_TOP_N || DEFAULT_TOP_N);
  const scopes = resolveScopes(process.argv[2], utils);
  report(scanUnion(scopes, utils), budget, topN);
}

if (require.main === module) {
  try {
    run();
  } catch (err) {
    // Fail-open: a measurement must never break the doctor run it is part of.
    emit('SKIP', `check errored: ${err.message}`);
  }
}

module.exports = {
  resolveScopes,
  readInstalledSet,
  bareModuleName,
  readAttribution,
  collectScope,
  scanUnion,
  report,
  run,
  DEFAULT_UNION_BUDGET,
  DEFAULT_TOP_N,
};

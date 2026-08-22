#!/usr/bin/env node
// t1k-origin: kit=theonekit-core | repo=The1Studio/theonekit-core | module=t1k-base | protected=true
// check-dead-permission-rules.cjs — Doctor check #56: permission rules Claude Code never matches.
//
// Claude Code's file-permission matcher consults ONLY `Edit(path)` and
// `Read(path)` rules — `Edit` rules cover every file-editing tool, `Read` rules
// every file-reading tool. A path-form rule naming any other file tool
// (`Write(...)`, `MultiEdit(...)`, `NotebookEdit(...)`, `Glob(...)`) passes the
// settings schema, so nothing errors: the rule is simply DEAD. An allow rule
// grants nothing and a deny rule blocks nothing, while reading exactly like a
// live grant to whoever wrote it (#763).
//
// Claude Code does warn at startup — once, in a scroll-away banner, only for the
// file it happened to load. This check is the durable, greppable form of that
// signal across every settings file in both scopes.
//
// SOURCE OF TRUTH for "which forms are dead?"
// -------------------------------------------
// `references/permission-rule-forms.json`, transcribed from the rule validator
// shipped in the Claude Code binary itself (see `_verifiedAgainst` there) — not
// inferred from one observed warning string. NO tool name is hardcoded below:
// adding a newly-discovered dead form is a data edit, never a code edit
// (`rules/code-conventions.md` § "Data-Driven Over Hardcoded").
//
// Usage:
//   node check-dead-permission-rules.cjs [path/to/project-root] [--project-only]
//
// Scans `settings.json` + `settings.local.json` under the project `.claude/` and
// (unless --project-only) `$HOME/.claude/`. Exits 0 always (WARN level).

'use strict';

const fs   = require('node:fs');
const os   = require('node:os');
const path = require('node:path');

const TABLE_PATH = path.join(__dirname, '..', 'references', 'permission-rule-forms.json');
const SETTINGS_FILES = ['settings.json', 'settings.local.json'];
const RULE_LISTS = ['allow', 'deny', 'ask'];

/** `Write(/src/**)` → { toolName: 'Write', ruleContent: '/src/**' }; no parens → null content. */
function parseRule(rule) {
  const open = rule.indexOf('(');
  if (open === -1) return { toolName: rule.trim(), ruleContent: undefined };
  const close = rule.lastIndexOf(')');
  if (close < open) return { toolName: rule.slice(0, open).trim(), ruleContent: undefined };
  return { toolName: rule.slice(0, open).trim(), ruleContent: rule.slice(open + 1, close) };
}

function loadTable() {
  const raw = JSON.parse(fs.readFileSync(TABLE_PATH, 'utf8'));
  const rewrites = new Map();
  for (const entry of raw.pathRuleRewrites || []) {
    if (!entry || typeof entry.toolName !== 'string' || typeof entry.useInstead !== 'string') continue;
    rewrites.set(entry.toolName, entry);
  }
  return { rewrites, exempt: raw.exemptWhenRuleContentContains, version: raw._verifiedAgainst?.version };
}

function run() {
  const args = process.argv.slice(2);
  const projectOnly = args.includes('--project-only');
  const projectRoot = args.find(a => !a.startsWith('--')) || process.cwd();

  let table;
  try {
    table = loadTable();
  } catch (err) {
    console.log(`[t1k:doctor] dead-permission-rules: SKIP — cannot read permission-rule-forms.json: ${err.message}`);
    return;
  }
  if (table.rewrites.size === 0) {
    console.log('[t1k:doctor] dead-permission-rules: SKIP — permission-rule-forms.json declares no rewrites');
    return;
  }

  const dirs = [path.join(projectRoot, '.claude')];
  if (!projectOnly) {
    const globalDir = path.join(os.homedir(), '.claude');
    if (!dirs.includes(globalDir)) dirs.push(globalDir);
  }

  const targets = [];
  for (const dir of dirs) {
    for (const name of SETTINGS_FILES) {
      const file = path.join(dir, name);
      if (fs.existsSync(file)) targets.push(file);
    }
  }

  if (targets.length === 0) {
    console.log('[t1k:doctor] dead-permission-rules: SKIP — no settings.json / settings.local.json found');
    return;
  }

  const dead = [];       // { file, list, index, rule, useInstead, replacement }
  const unreadable = [];
  let scanned = 0;

  for (const file of targets) {
    let settings;
    try {
      settings = JSON.parse(fs.readFileSync(file, 'utf8'));
    } catch (err) {
      unreadable.push({ file, message: err.message });
      continue;
    }
    const permissions = settings && settings.permissions;
    if (!permissions || typeof permissions !== 'object') continue;
    for (const list of RULE_LISTS) {
      const rules = permissions[list];
      if (!Array.isArray(rules)) continue;
      rules.forEach((rule, index) => {
        if (typeof rule !== 'string' || !rule.trim()) return;
        scanned++;
        const { toolName, ruleContent } = parseRule(rule);
        if (ruleContent === undefined) return;             // bare `Write` is a real tool grant
        const entry = table.rewrites.get(toolName);
        if (!entry) return;
        // Mirrors the shipped validator: a `:*` content is Bash-prefix syntax,
        // rejected elsewhere and deliberately not reported here.
        if (table.exempt && ruleContent.includes(table.exempt)) return;
        dead.push({
          file, list, index, rule,
          useInstead: entry.useInstead,
          replacement: `${entry.useInstead}(${ruleContent})`,
          covers: entry.covers,
        });
      });
    }
  }

  for (const { file, message } of unreadable) {
    console.log(`[t1k:doctor] dead-permission-rules: SKIP file ${file} — not parseable JSON: ${message}`);
  }

  if (dead.length === 0) {
    console.log(
      `[t1k:doctor] dead-permission-rules: PASS — ${scanned} rule(s) across ` +
      `${targets.length} settings file(s), no dead path-form rules`,
    );
    return;
  }

  console.log(
    `[t1k:doctor] dead-permission-rules: WARN — ${dead.length} permission rule(s) are never ` +
    'matched by file permission checks (they grant/deny nothing)',
  );
  for (const d of dead) {
    console.log(
      `  ${d.file} → permissions.${d.list}[${d.index}]: "${d.rule}" — use "${d.replacement}" ` +
      `(${d.useInstead} rules cover all ${d.covers} tools)`,
    );
  }
  console.log(
    `  fix: replace each rule as shown above. Verified against Claude Code ${table.version || 'n/a'}; ` +
    'the dead-form table is `skills/t1k-doctor/references/permission-rule-forms.json`.',
  );
}

try {
  run();
} catch (err) {
  // Fail-open: doctor checks must never crash the suite.
  console.log(`[t1k:doctor] dead-permission-rules: WARN — check errored: ${err.message}`);
}

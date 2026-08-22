#!/usr/bin/env node
// t1k-origin: kit=theonekit-core | repo=The1Studio/theonekit-core | module=null | protected=true
/**
 * hook-command-form.cjs — SSOT for the shape of a settings.json hook command.
 *
 * Two forms are recognized:
 *
 *   LITERAL (legacy)
 *     node "$CLAUDE_PROJECT_DIR/.claude/hooks/hook-runner.cjs" privacy-guard
 *
 *   RESOLVER (current)
 *     node -e "<resolver>" privacy-guard
 *
 * The literal form is broken for a GLOBAL install whenever the project happens to
 * own a `.claude/hooks/` that does not contain the kit — `$CLAUDE_PROJECT_DIR`
 * resolves to a path with no `hook-runner.cjs` and Node throws MODULE_NOT_FOUND
 * before any hook code runs, on EVERY event.
 *
 * Rewriting it to `$HOME` does not fix it either: Claude Code 2.1.150+ passes
 * `HOME=$CLAUDE_PROJECT_DIR` (#49), so `$HOME/.claude/hooks/...` expands to the
 * same missing path. The only reliable home is `os.userInfo().homedir`, which
 * reads getpwuid(geteuid()) and is unaffected by the inherited env.
 *
 * The resolver form therefore: overrides HOME/USERPROFILE from userInfo(), tries
 * the project-local install first, and falls back to the global one. This is the
 * same shape theonekit-model-router adopted for its `mr-*` hooks (#94); this
 * module generalizes it to every hook.
 *
 * Two things the naive version of that shape gets wrong:
 *
 *   1. `userInfo()` THROWS (`uv_os_get_passwd` ENOENT) when the effective uid has
 *      no passwd entry — routine in distroless images and random-uid containers.
 *      Unguarded, that throw happens before the resolver picks a file, so every
 *      registered command dies on every event. It is wrapped, falling back to the
 *      inherited HOME/USERPROFILE: wrong on Claude Code 2.1.150+, but a wrong
 *      candidate is only ever rejected by `existsSync`, never trusted.
 *
 *   2. Resolving nothing is not uniformly harmless. For an advisory hook a no-op
 *      is right, but for `privacy-guard`/`secret-guard` it converts a loud
 *      MODULE_NOT_FOUND into a SILENT fail-open on a security control — the kit
 *      would stop scanning for secrets with no signal at all. Those hooks
 *      therefore exit(2) (both are PreToolUse, so exit 2 blocks the call);
 *      everything else warns on stderr and continues. See
 *      rules/development-principles.md § "Errors Over Silent Fallbacks":
 *      fail-CLOSED on a detected threat, fail-OPEN on an internal hook exception,
 *      and a security guard that cannot be found is the former.
 *
 * Parsing lives here because two gates need to agree on it:
 *   - scripts/generate-required-hook-registrations.cjs (derives the manifest)
 *   - hooks/doctor-check-52-hook-registration-drift.cjs (asserts a consumer install)
 * A second private copy of the regex is how those two silently disagree.
 */
'use strict';

/** Hook files invoked directly rather than dispatched through hook-runner. */
const DISPATCHER = 'hook-runner.cjs';

/**
 * Hooks whose absence must fail CLOSED instead of no-opping.
 *
 * Both are PreToolUse (privacy-guard on Read|Glob|Grep, secret-guard on Bash),
 * where exit 2 blocks the tool call and surfaces stderr — so an unresolvable
 * guard stops the session loudly rather than disarming itself quietly.
 */
const FAIL_CLOSED_HOOKS = new Set(['privacy-guard', 'secret-guard']);

/** The hook's own name, whether dispatched through hook-runner or invoked directly. */
function hookIdentity(file, args = '') {
  if (file !== DISPATCHER) return String(file).replace(/\.cjs$/, '');
  return String(args).trim().split(/\s+/)[0] || DISPATCHER;
}

/**
 * Build the resolver-form command for `file`, passing `args` through to it.
 *
 * @param {string} file  bare hook filename, e.g. 'hook-runner.cjs'
 * @param {string} [args] trailing argv, e.g. 'privacy-guard'
 * @returns {string} the full `node -e "..."` command
 */
function buildHookCommand(file, args = '') {
  const name = hookIdentity(file, args);
  // Single quotes only, ASCII only, no `$`/`%`/backticks: this string is embedded
  // in a double-quoted `node -e` argument that both sh and cmd.exe must pass through.
  const unresolved = FAIL_CLOSED_HOOKS.has(name)
    ? `else{console.error('[t1k] ${name}: security hook not found in project or home .claude/hooks - failing closed');process.exit(2)}`
    : `else{console.error('[t1k] ${name}: hook not found in project or home .claude/hooks - skipped')}`;
  const body =
    `let h;try{h=require('os').userInfo().homedir}catch{h=process.env.HOME||process.env.USERPROFILE}` +
    `const p=require('path'),f=require('fs');` +
    `if(h){process.env.HOME=h;process.env.USERPROFILE=h}` +
    `const d=process.env.CLAUDE_PROJECT_DIR;` +
    `const c=[d&&p.join(d,'.claude','hooks','${file}'),h&&p.join(h,'.claude','hooks','${file}')]` +
    `.filter(Boolean).find(x=>f.existsSync(x));` +
    `if(c){process.argv.splice(1,0,c);require(c)}${unresolved}`;
  return `node -e "${body}"${args ? ` ${args}` : ''}`;
}

/** True when `command` is the resolver form dispatching `file`. */
function isResolverFor(command, file) {
  if (typeof command !== 'string') return false;
  if (!/^\s*node\s+-e\s+"/.test(command)) return false;
  return command.includes(`'${file}'`);
}

/**
 * Hook name out of either form, or null when the command dispatches no kit hook.
 *
 * The literal regex is tried first and deliberately cannot match the resolver
 * form: there `hook-runner.cjs` is always followed by a closing quote, never by
 * whitespace, so the two branches stay mutually exclusive.
 */
function hookNameOf(command) {
  if (typeof command !== 'string') return null;
  const literal = /hook-runner\.cjs"?\s+([A-Za-z0-9_-]+)/.exec(command);
  if (literal) return literal[1];
  if (!isResolverFor(command, DISPATCHER)) return null;
  const trailing = /"\s+([A-Za-z0-9_-]+)\s*$/.exec(command);
  return trailing ? trailing[1] : null;
}

/**
 * True when `command` is the resolver form wiring `hookName` — either dispatched
 * through hook-runner or invoked directly as `<hookName>.cjs`.
 */
function resolverReferencesHook(command, hookName) {
  if (isResolverFor(command, `${hookName}.cjs`)) return true;
  return hookNameOf(command) === hookName && isResolverFor(command, DISPATCHER);
}

module.exports = {
  DISPATCHER,
  FAIL_CLOSED_HOOKS,
  hookIdentity,
  buildHookCommand,
  isResolverFor,
  hookNameOf,
  resolverReferencesHook,
};

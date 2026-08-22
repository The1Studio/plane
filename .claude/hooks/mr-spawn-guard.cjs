#!/usr/bin/env node
// t1k-origin: kit=theonekit-model-router | repo=The1Studio/theonekit-model-router | module=null | protected=false
// mr-spawn-guard.cjs — P0 safety hook
// Prevents delegated sessions from re-entering model-router delegation.
// Registered as PreToolUse hook matching "Bash" in spawned sessions.
//
// When MR_SPAWNED=1 (set by mr-delegate.sh), this hook blocks any
// Bash command that invokes mr-delegate.sh, preventing recursive delegation.

// Only block in spawned sessions (MR_SPAWNED=1 set by mr-delegate.sh)
if (process.env.MR_SPAWNED !== '1') {
  process.exit(0);
}

let input;
try {
  input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
} catch {
  process.exit(0);
}

// Hook payloads are expected to be JSON objects. Fail open when Claude Code
// supplies an empty, malformed, or structurally unexpected payload.
if (input === null || typeof input !== 'object' || Array.isArray(input)) {
  process.exit(0);
}

// Only check Bash tool calls
if (input.tool_name !== 'Bash') {
  process.exit(0);
}

const toolInput = input.tool_input;
if (toolInput === null || typeof toolInput !== 'object' || Array.isArray(toolInput)) {
  process.exit(0);
}

const command = toolInput.command;
if (typeof command !== 'string') {
  process.exit(0);
}

// Best-effort guard (can be bypassed via obfuscation).
// Authoritative guard is MR_SPAWNED=1 check in mr-delegate.sh itself.
const invokesClaudePrint = /(?:^|[\s;&|()/\\])claude(?:\.exe)?(?=\s)[^;&|\n]*(?:\s-p(?:\s|$)|\s--print(?:=|\s|$))/i.test(command);
const mentionsDelegation =
  command.includes('mr-delegate') ||
  command.includes('/t1k:model-router-delegate') ||
  invokesClaudePrint;

if (!mentionsDelegation) {
  process.exit(0);
}

// A *mention* of the delegate's path is not an invocation of it. Reading,
// grepping, or syntax-checking mr-delegate.sh does not re-enter delegation,
// and blocking those stranded routed agents with zero tool output (#283).
//
// Narrow, allow-list-shaped exemption — deliberately not a clever regex:
// the command is exempt only when EVERY segment leads with a known
// read-only utility. Any unrecognized leader (including `bash file`,
// `env`, `xargs`, `eval`, `claude`) fails closed and blocks.
// `awk` (system()/`| "sh"`) and `sed` (GNU `e` command) can execute, so they
// are deliberately absent despite being conventional read-only tools.
const READ_ONLY_LEADERS = new Set([
  'basename', 'cat', 'cksum', 'cmp', 'diff', 'dirname', 'du', 'echo',
  'egrep', 'fgrep', 'file', 'find', 'grep', 'head', 'less', 'ls', 'md5sum',
  'more', 'nl', 'od', 'printf', 'readlink', 'realpath', 'rg',
  'sha1sum', 'sha256sum', 'shellcheck', 'stat', 'strings', 'tail', 'wc',
]);
// Shells parse-only with -n; without it they EXECUTE. -c executes a string.
const SHELL_LEADERS = new Set(['ash', 'bash', 'dash', 'ksh', 'sh', 'zsh']);

function leadingCommandOf(segment) {
  const tokens = segment.trim().split(/\s+/).filter(Boolean);
  // Skip leading `VAR=value` assignments; they are not the command.
  let i = 0;
  while (i < tokens.length && /^[A-Za-z_][A-Za-z0-9_]*=/.test(tokens[i])) i++;
  if (i >= tokens.length) return null;
  const raw = tokens[i].replace(/^["']|["']$/g, '');
  const base = raw.split(/[/\\]/).pop().replace(/\.exe$/i, '').toLowerCase();
  return { base, args: tokens.slice(i + 1) };
}

function isReadOnlySegment(segment) {
  const lead = leadingCommandOf(segment);
  if (lead === null) return true; // empty segment (trailing `;`, `&&` tail)
  const { base, args } = lead;
  if (READ_ONLY_LEADERS.has(base)) {
    // `find -exec` / `-delete` escape read-only intent.
    return !args.some((a) => /^-(exec|execdir|ok|okdir|delete)$/.test(a));
  }
  if (SHELL_LEADERS.has(base)) {
    const shortFlags = args.filter((a) => /^-[A-Za-z]+$/.test(a));
    const parseOnly = shortFlags.some((a) => a.includes('n'));
    const runsString =
      shortFlags.some((a) => a.includes('c')) || args.includes('--command');
    return parseOnly && !runsString;
  }
  if (base === 'node') return args.includes('-c') || args.includes('--check');
  return false;
}

function isReadOnlyInspection(cmd) {
  // Substitution runs a nested command the leader check cannot see.
  if (/\$\(|`|<\(|>\(/.test(cmd)) return false;
  return cmd
    .split(/\|\||&&|[;\n|&]/)
    .every(isReadOnlySegment);
}

if (isReadOnlyInspection(command)) {
  process.exit(0);
}

process.stderr.write('Blocked: recursive delegation not allowed in spawned session\n');
process.exit(2); // exit 2 = block operation

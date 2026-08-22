// t1k-origin: kit=theonekit-core | repo=The1Studio/theonekit-core | module=null | protected=true
'use strict';

/**
 * Doctor check #52: report hooks that exist on disk but are not wired under
 * their required event + matcher in settings.json.
 *
 * Coverage is TOTAL — every registration this kit ships is asserted, not just
 * the blocking ones. An advisory hook vanishing is just as harmful and far
 * quieter: an install that lost `contribution-capture` silently dropped 60
 * contributions, and nothing reported it because that hook never exits 2.
 * The manifest is generated from settings.json by
 * `scripts/generate-required-hook-registrations.cjs` — do not hand-edit it.
 *
 * This is intentionally diagnostic. `t1k modules update` owns reconciliation;
 * doctor makes old consumer installs and partial updates observable.
 */

const fs = require('fs');
const path = require('path');
const { resolverReferencesHook } = require('./lib/hook-command-form.cjs');

const CHECK_ID = 52;
const CHECK_NAME = 'hook-registration-drift';
const LEGACY_REQUIRED_REGISTRATIONS = [
  { event: 'SubagentStop', hookName: 'lesson-collector' },
  { event: 'SubagentStop', hookName: 'workflow-failure-detector' },
  { event: 'SubagentStop', hookName: 'subagent-uncommitted-guard' },
  { event: 'PreToolUse', matcher: 'Task|Agent', hookName: 'generic-agent-detector' },
  { event: 'PreToolUse', matcher: 'Bash', hookName: 'workflow-artifact-gate' },
  { event: 'PreToolUse', matcher: 'Write', hookName: 'plan-write-guard' },
  { event: 'PreToolUse', matcher: 'Edit|MultiEdit', hookName: 'plan-write-guard' },
];

function loadRequiredRegistrations(claudeDir) {
  const manifestPath = path.join(claudeDir, 'scripts', 'required-hook-registrations.json');
  if (!fs.existsSync(manifestPath)) return LEGACY_REQUIRED_REGISTRATIONS;
  try {
    const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
    if (
      !manifest || typeof manifest !== 'object' || Array.isArray(manifest) ||
      Object.keys(manifest).some((key) => !['_origin', 'schemaVersion', 'registrations'].includes(key)) ||
      manifest.schemaVersion !== 1 ||
      !manifest._origin || typeof manifest._origin !== 'object' || Array.isArray(manifest._origin) ||
      Object.keys(manifest._origin).some(
        (key) => !['kit', 'repository', 'module', 'protected'].includes(key),
      ) ||
      manifest._origin.kit !== 'theonekit-core' ||
      manifest._origin.repository !== 'The1Studio/theonekit-core' ||
      // NOTE: `_origin.module` is deliberately NOT asserted. That field is
      // CI-injected, and the injector classifies `.claude/scripts/` as kit-wide
      // (module: null). Pinning it to 't1k-base' — the value the file was
      // hand-authored with in #611 — made the manifest fail validation from the
      // first CI metadata commit after that merge, silently falling back to
      // LEGACY_REQUIRED_REGISTRATIONS on every consumer. Provenance is already
      // established by `kit` + `repository`; `module` is an implementation
      // detail of the injector and must not gate parsing.
      manifest._origin.protected !== true ||
      !Array.isArray(manifest.registrations) ||
      manifest.registrations.length === 0
    ) {
      throw new Error('expected schemaVersion 1 and a non-empty registrations array');
    }
    const valid = manifest.registrations.every((item) => {
      if (!item || typeof item !== 'object' || Array.isArray(item)) return false;
      if (Object.keys(item).some((key) => !['event', 'matcher', 'hookName'].includes(key))) {
        return false;
      }
      return (
        typeof item.event === 'string' &&
        item.event.trim().length >= 1 &&
        item.event.trim().length <= 64 &&
        /^[a-zA-Z][a-zA-Z0-9]*$/.test(item.event.trim()) &&
        typeof item.hookName === 'string' &&
        item.hookName.trim().length >= 1 &&
        item.hookName.trim().length <= 128 &&
        /^[a-zA-Z0-9_-]+$/.test(item.hookName.trim()) &&
        (
          item.matcher === undefined ||
          (
            typeof item.matcher === 'string' &&
            item.matcher.trim().length >= 1 &&
            item.matcher.trim().length <= 512
          )
        )
      );
    });
    if (!valid) throw new Error('registration entries require event, hookName, and optional matcher strings');
    const unique = new Map();
    for (const item of manifest.registrations) {
      const normalized = {
        event: item.event.trim(),
        hookName: item.hookName.trim(),
        ...(item.matcher === undefined ? {} : { matcher: item.matcher.trim() }),
      };
      const identity = `${normalized.event}\u0000${normalized.matcher || ''}\u0000${normalized.hookName}`;
      unique.set(identity, normalized);
    }
    return [...unique.values()];
  } catch (err) {
    emit('WARN', `required-hook manifest is invalid; using legacy fallback: ${err.message}`);
    return LEGACY_REQUIRED_REGISTRATIONS;
  }
}

function emit(level, message) {
  process.stdout.write(`${level} [check #${CHECK_ID}] ${CHECK_NAME}: ${message}\n`);
}

function marker(status, count) {
  process.stdout.write(`[t1k:doctor:${CHECK_NAME} status=${status} count=${count}]\n`);
}

function resolveClaudeDir() {
  const arg = process.argv[2];
  if (arg) return path.resolve(arg);
  const fromCwd = path.join(process.cwd(), '.claude');
  return fs.existsSync(fromCwd) ? fromCwd : null;
}

function commandReferencesHook(command, hookName, claudeDir) {
  if (typeof command !== 'string') return false;
  // The resolver form (`node -e "..."`) carries the hook path inside quoted JS
  // rather than as a bare argv path, so the base-prefixed patterns below cannot
  // see it. Recognize it first — see hooks/lib/hook-command-form.cjs.
  if (resolverReferencesHook(command, hookName)) return true;
  const normalizedCommand = command.replace(/\\/g, '/');
  const escaped = hookName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const nodeExecutable = String.raw`(?:node(?:\.exe)?|["'][^"']*/node(?:\.exe)?["'])`;
  const allowedBases = [
    '$HOME/.claude/hooks',
    '$CLAUDE_PROJECT_DIR/.claude/hooks',
    path.join(claudeDir, 'hooks').replace(/\\/g, '/'),
    // A consumer may register the hook with a cwd-relative path. That is a
    // legitimate wiring the probe previously failed to recognize, reporting a
    // working registration as missing.
    '.claude/hooks',
    './.claude/hooks',
  ];
  return allowedBases.some((base) => {
    const escapedBase = base.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const flags = /^[A-Za-z]:\//.test(base) ? 'i' : '';
    return new RegExp(
      `^\\s*${nodeExecutable}\\s+["']?${escapedBase}/(?:` +
      `hook-runner\\.cjs["']?\\s+${escaped}|${escaped}\\.cjs["']?)\\s*$`,
      flags,
    ).test(normalizedCommand);
  });
}

// A matcher is a `|`-separated alternation, so "Agent|Task" and "Task|Agent"
// select the same tools. Strict string equality reported a correctly-wired
// consumer as inert purely because it had listed the alternatives in a
// different order (or split/merged the group). Compare as sets, and treat the
// registration as satisfied when the settings group covers everything the
// manifest asks for — a broader group still matches the required tools.
function matcherAlternatives(matcher) {
  if (matcher === null || matcher === undefined) return null;
  return new Set(String(matcher).split('|').map((part) => part.trim()).filter(Boolean));
}

function matcherSatisfies(groupMatcher, requiredMatcher) {
  const required = matcherAlternatives(requiredMatcher);
  const actual = matcherAlternatives(groupMatcher);
  if (required === null || actual === null) return required === actual;
  if (required.size === 0 || actual.size === 0) return false;
  for (const token of required) if (!actual.has(token)) return false;
  return true;
}

function registrationPresent(settings, registration, claudeDir) {
  const groups = settings?.hooks?.[registration.event];
  if (!Array.isArray(groups)) return false;
  return groups.some((group) => {
    if (!group || typeof group !== 'object') return false;
    if (!matcherSatisfies(group.matcher, registration.matcher)) return false;
    const entries = Array.isArray(group.hooks) ? group.hooks : [group];
    return entries.some((entry) =>
      commandReferencesHook(entry?.command, registration.hookName, claudeDir),
    );
  });
}

function run() {
  const claudeDir = resolveClaudeDir();
  if (!claudeDir || !fs.existsSync(claudeDir)) {
    emit('SKIP', 'no .claude/ directory resolvable');
    marker('skip', 0);
    return;
  }

  const requiredRegistrations = loadRequiredRegistrations(claudeDir);
  const applicable = requiredRegistrations.filter(({ hookName }) =>
    fs.existsSync(path.join(claudeDir, 'hooks', `${hookName}.cjs`)),
  );
  if (!applicable.length) {
    emit('SKIP', 'none of the required hook scripts are installed');
    marker('skip', 0);
    return;
  }

  const settingsPath = path.join(claudeDir, 'settings.json');
  let settings;
  if (!fs.existsSync(settingsPath)) {
    emit('FAIL', `settings.json is absent; ${applicable.length} installed hook registration(s) are inert`);
    marker('fail', applicable.length);
    process.exitCode = 1;
    return;
  }
  try {
    settings = JSON.parse(fs.readFileSync(settingsPath, 'utf8'));
  } catch (err) {
    emit('FAIL', `settings.json cannot be parsed: ${err.message}`);
    marker('fail', 1);
    process.exitCode = 1;
    return;
  }

  const missing = applicable.filter((registration) =>
    !registrationPresent(settings, registration, claudeDir),
  );
  if (!missing.length) {
    emit('OK', `${applicable.length} installed hook registrations are wired`);
    marker('ok', applicable.length);
    return;
  }

  emit('FAIL', `${missing.length} installed hook registration(s) are inert:`);
  for (const { event, matcher, hookName } of missing) {
    const scope = matcher ? `${event}/${matcher}` : event;
    emit('FAIL', `  - ${hookName} missing from ${scope}`);
  }
  emit('FAIL', 'Run `t1k modules update` with a current CLI to reconcile settings.json.');
  marker('fail', missing.length);
  process.exitCode = 1;
}

try {
  run();
} catch (err) {
  // Unexpected probe failures do not break the wider doctor pipeline.
  process.stderr.write(`[doctor-check-${CHECK_ID}] internal error (fail-open): ${err.message}\n`);
  marker('warn', 1);
}

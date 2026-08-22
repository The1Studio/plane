---

origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---
# Scope Remediation — the background agent's behavior spec

**Dispatched by:** Phase 4's `context-bloat-guard.cjs` SessionStart directive (Contract C), routed
to `t1k-doctor-manager` (`rules/orchestration-rules.md`, doctor row) — a sonnet, non-spawning,
return-class agent that holds no `Write`/`Edit`, so every removal must go through the CLI.

**This is a spec, not code.** It reads doctor findings, refuses far more often than it acts, and
when it does act, backs up, removes, verifies, records, and reports. Checks stay diagnostic-only —
nothing here is wired into `t1k doctor --fix`.

**HARD-GATE, per `rules/workflow-gates.md`.** The 12-step order below is fixed: no bypass without a
named user override, and **there is no override for the git guard (step 1), the divergence gate
(step 2), or the backup step (step 7).**

> **What this actually removes on a default install:** with `scopeEnforcement.autoRemoveKits`
> resolved from `.claude/t1k-config-core.json` (`["core", "model-router"]`, per
> `plans/260821-1904-context-bloat-scope-enforcement-v3/DECISION-autoremove-core.md`), a project
> with a git-tracked `.claude/` refuses at step 1 — the measured majority. An untracked project
> where `core` or `model-router` is duplicated across scopes is a live removal target. Read the
> DECISION file before touching `scopeEnforcement.autoRemoveKits` for any other kit — widening it
> is a consumer decision gated on a fleet population count, not something this spec's existence
> authorizes.

---

## Contracts consumed

Full shapes: [`../../../../plans/260821-1904-context-bloat-scope-enforcement-v3/contracts.md`](../../../../plans/260821-1904-context-bloat-scope-enforcement-v3/contracts.md).

- **Contract A** (`[t1k:doctor:scope-finding …]`) — checks #58/#63. `confidence=high` only when
  `action=remove`; `kit=` is always a `KitType` member; `scope=` is the scope **to remove from**,
  already derived by the emitter — never re-derive it here.
- **Contract B** (`[t1k:doctor:kit-file-drift kit=… …]`) — check #55's **per-kit** frame, obtained
  ONLY via `node .claude/hooks/doctor-check-55-kit-file-drift.cjs --kit <k>`. Never the aggregate
  run.
- **Contract E** — the suppression sentinel this agent writes on every run.
- **Contract F** — the remediation lock this agent holds for the whole run.
- **Contract G** — the CLI backup receipt (`BackupReceipt { path, files, bytes }`), feature-detected
  from the dry-run's `[t1k:backup] would create …` / `[t1k:backup] created …` lines — never from a
  `>=` version comparison.
- **Contract J** — the cumulative removal ledger this agent reads before acting and appends to
  before removing.
- **Contract H** — the brief shape this spec is the target of (paths + verbatim constraints, never
  pasted findings).

---

## The fixed order

```
0.  ACQUIRE  the project lock (Contract F, fs.openSync 'wx')  -- else report "already running", STOP
0b. ABORT    if <claudeDir>/metadata.json.lock is held         -- a CLI writer is mid-flight
1.  GIT      git -C <projectRoot> ls-files --error-unmatch <first target path>
             TRACKED => REFUSE, report, STOP
2.  DRIFT    doctor-check-55-kit-file-drift.cjs --kit <k>      -- per-kit frame, or STOP
3.  RE-READ  checks #58 and #63 at act time                    -- never act on the guard's snapshot
4.  FILTER   confidence=high only; cumulative ledger cap (J)   -- over cap => report everything, STOP
5.  DRY-RUN  t1k uninstall --dry-run --kit <k> --<scope> --yes  -- GATE on the preview
6.  LEDGER   append Contract J row (acknowledged:false) BEFORE removing
7.  REMOVE   t1k uninstall --kit <k> --<scope> --yes
8.  VERIFY   backup FILE COUNT + BYTES from stdout; re-run the checks
9.  RECORD   write <backup>/T1K-REMOVAL.json
10. REPORT   via SendMessage to "main"
11. RELEASE  the lock; write the suppression sentinel — ON EVERY RUN, not only no-op runs
```

Steps 1, 2, 5, and 8 are each capable of stopping the whole thing, and each is expected to, most of
the time.

---

## Step 0 — acquire the lock

File: `<claudeDir>/session-state/scope-remediation.lock` (Contract F).

1. **Atomic create only:** `fs.openSync(lockPath, 'wx')`. Fails if the file exists, in one syscall.
   Never `existsSync` then `writeFileSync` — that read-then-write window is exactly what lets two
   remediators both proceed.
2. If the create fails because the file exists: read it. If `heartbeatAt` is within
   `scopeEnforcement.lockStaleMinutes` (default 15) of now, another remediator is live — report
   `"already running"` and STOP. Otherwise the lock is stale (a crashed prior run) — overwrite it
   and proceed.
3. Refresh `heartbeatAt` and `step` at **every** step boundary below (0b, 1, 2, …, 11). Staleness is
   always measured against `heartbeatAt`, never `startedAt` — a live, slow run (a multi-GB backup
   copy, a full-surface hash) can exceed 15 minutes and must not read as dead.

### Step 0b — abort on a held CLI lock

`proper-lockfile` locks `<claudeDir>/metadata.json` directly, which creates
`<claudeDir>/metadata.json.lock` beside it (`writeManifest` / `removeKitFromManifest`,
`manifest-updater.ts`). If that file exists, a CLI writer (`t1k init`, `t1k modules update`) is
mid-flight. **Abort cleanly — do not hang, and do not force past it.** Report `"a CLI operation is
in progress; try again after it completes"` and release this agent's own lock before stopping.

**Stated, not fixed:** this lock binds remediator × remediator (step 0) and, since P1
(`removal-handler.ts` wraps `removeInstallations` in `withProcessLock("uninstall", …)`,
`~/.t1k/locks/uninstall.lock`), remediator × any other CLI writer holding that same named lock.
Step 0b's `metadata.json.lock` check is the belt-and-suspenders read for the manifest-write path
specifically. Residual CLI concurrency beyond those two mechanisms is **accepted, not silently
assumed covered.**

**Write guard, applies to every write this agent makes to `<claudeDir>/session-state/` (the lock,
and later the sentinel):** `t1k uninstall`'s `removal-handler.ts` `rmSync`s the installation
directory when a removal empties it, and `session-state/` is inside that tree. Before any write
under `<claudeDir>/session-state/`, `existsSync(claudeDir)` first — if it is gone, skip the write
(do not re-materialize a one-directory ghost install) and note the skip in the report.

---

## Step 1 — the git guard

```bash
git -C <projectRoot> ls-files --error-unmatch <first target path>
```

**Tracked ⟹ REFUSE, report, STOP.** No override exists for this step. The report:

<!-- The marker below MUST be on the SAME physical line as the `git rm -r .claude` text —
     validate-no-raw-rm-claude.cjs checks isAllowListed(line) against the exact line PATTERN
     matched, not a nearby comment. This is the REFUSAL text: it steers the user away from a
     background deletion toward a reviewable `git rm` + commit, so the command must stay literal
     and copy-pasteable. Rewording it to dodge the gate would make the guidance worse, not safer. -->
> These files are version-controlled. Remediate with `git rm -r .claude/… && git commit` so your <!-- gate:allow-rm-claude -->
> team gets the change — a background removal here would delete tracked files you did not author.

**Why no relaxation is ever correct:** a tracked-file removal propagates to the whole team on the
next `git add -A`; `git checkout` / `stash pop` / a branch switch / `git pull` puts the files back,
making the finding genuinely actionable again next SessionStart — an infinite loop this agent cannot
break by acting again, and each cycle burns a `~/.claude-backup-*` slot against keep-10, evicting
real backups. In a tracked repo the correct recovery is `git checkout -- .claude/`, not a restore
from this agent's backup, and `cp -a` can resurrect files git deliberately deleted. `git rm -r` +
commit + push is a team decision, not this agent's call.

---

## Step 2 — the divergence gate

**Invoke the targeted mode only. Never read the aggregate run.**

```bash
node .claude/hooks/doctor-check-55-kit-file-drift.cjs --kit <k>
```

```
[t1k:doctor:kit-file-drift kit=<k> status=… behind=… missing=… diverged=… comparable=<yes|no> surface=<executables|full> hashed=<n> claimed=<n>]
```

**Proceed ONLY on `surface=full` AND `comparable=yes` AND `diverged=0`.** (`comparable=yes` already REQUIRES `claimed > 0 AND hashed === claimed` — see `doctor-check-55-kit-file-drift.cjs`; restating `hashed === claimed` as a separate AND-clause here would be tautological, not an extra check — core#1062.)

Every other outcome — `comparable=no`, `diverged>0`, `status=skip`, `surface=executables`,
`hashed < claimed`, a malformed frame, or **no frame at all** — is a REFUSE. Absence of a finding is
not a clear:

| State | Why it refuses |
|---|---|
| `comparable=no` | **Two independent producers.** (a) The kit exists in one scope only — nothing to diff (the mirror case). (b) The hashing window did not reach 100% of `metadata.kits[k].files[]` — `hashed < claimed` (the coverage case, row below). On a real `core` install, (b) is what actually fires; do not read this row as only the mirror case. Both are installs most likely to hold unsynced local edits. |
| `status=skip` | The project dir *is* the global dir — "I did not look", not "I looked and it was clean." |
| `surface=executables` | Hashed `hooks/`+`scripts/` only; an engine kit is guaranteed `diverged=0` on that surface regardless of the truth. |
| `hashed < claimed` | The hashing window does not cover the whole manifested file set — for `core` this is most of the evidence, and it is exactly the surface `prefer-local-over-global-edits.md` tells users to edit locally. |

**On DIVERGED-AHEAD (`diverged>0`): do not remove.** Report it, recommend `/t1k:sync-back`, stop. A
backup makes the data recoverable; it does not make deleting someone's unsynced work correct
(`#367`).

---

## Step 3 — re-read, never trust the guard's snapshot

`doctor-check-58-kit-install-scope.cjs` documents a 60-second telemetry cache: a just-uninstalled
kit can still be reported for up to 60s after removal. Re-run checks #58 and #63 at act time rather
than acting on the frame that dispatched this agent — a stale cache produces only a false ALARM,
never a false clear, but this agent is the one consumer for which a false alarm is expensive because
it acts on it.

---

## Step 4 — confidence gating and the cumulative cap

| Confidence | Action |
|---|---|
| **HIGH** — only for kits named in `scopeEnforcement.autoRemoveKits` | Auto-remove, after every gate above |
| **LOW** — everything else, including all `zero-invocation` findings | **Report only. Never remove. No exceptions, no override.** |

Key on the explicit Contract A `confidence` attribute. **Never infer confidence from ordering,
position, or wording.** A frame missing any required attribute is invalid and MUST be ignored — do
not "repair" it by reading the surrounding prose.

**`kit=` is always a `KitType` member.** `t1k uninstall` has no `--module` flag; `kit` is a closed
12-value Zod enum. If a frame's `kit=` is not a `KitType` member, that is an emitter bug — report it
and STOP. Never widen to an owning kit; that turns "remove one idle module" into "delete all of that
kit's files."

**The cap is cumulative across runs, not per-run.** `scopeEnforcement.maxRemovalsPerRun` (default 2)
bounds one run; without a ledger, session 1 removes 2, session 2 removes 2 more, indefinitely. Read
`<claudeDir>/telemetry/scope-removals.jsonl` (Contract J) before acting. Once the cumulative count of
`acknowledged:false` entries for this project reaches `maxRemovalsPerRun`, refuse further
auto-removal until either a human acknowledges (an `acknowledged:true` entry appended) or
`scopeEnforcement.removalCooldownDays` (default 7) have passed since the last unacknowledged entry.

**If a single sweep produces MORE than `maxRemovalsPerRun` HIGH findings at once**, that is a signal
of systemic misdetection, not a queue to work through — remove **zero**, report the whole set, and
stop for human review.

Honor `allowKits` and `enabled` even if a check somehow emitted a finding for an allow-listed kit —
defence in depth at the acting layer. **Global-only mode:** when the project dir resolves to
`$HOME/.claude`, attempt no local removal; `t1k uninstall --local` at `$HOME` is refused by the CLI
regardless.

---

## Step 5 — the dry-run, gated on the preview

```bash
t1k uninstall --dry-run --kit <k> --<scope> --yes
```

**`--yes` is mandatory on every command in this spec.** Without it, `confirmUninstall()`'s
`prompts.confirm({ initialValue: false })` either hangs a background agent to timeout or resolves to
`false` and silently removes nothing.

**Two assertions, both blocking:**

1. **Containment** — every previewed path resolves under the target `.claude` directory.
2. **Magnitude** — the previewed count is within an order of magnitude of
   `metadata.kits[<k>].files.length`. 3 files against a manifest claiming 695, or 5,000 against 695,
   is a misattribution, not a removal.

Mismatch on either ⟹ report and STOP.

**Assert the backup announcement line appears** in the dry-run output —
`"backup will be created at <path>"` (or the equivalent receipt-preview line from
`formatBackupDryRunLine`). Its absence means the installed CLI predates the verified-backup fix;
report and STOP rather than proceeding to a real removal with no backup.

**`KIT_SCOPE_UNATTRIBUTABLE` is a first-class, expected outcome**, not a crash: the CLI's `--kit`
pre-flight throws before the preview renders, on purpose, "so we never delete from one installation
and then abort on the next." Catch it, report `"cannot attribute; nothing removed"`, and STOP — this
is the correct result on a non-T1K install, not an error to retry past.

**The dry-run does not rehearse the backup** — the CLI's dry-run path returns before the backup
insertion point, so a missing-backup condition must be caught by the announcement-line assertion
above, before the real removal, not discovered after it.

---

## Step 6 — the ledger row, BEFORE the removal

Append to `<claudeDir>/telemetry/scope-removals.jsonl` (Contract J) with `acknowledged:false`
**before** running the destructive command:

```json
{"ts":"<ISO8601>","kit":"<k>","scope":"<local|global>","reason":"<slug>","installationPath":"<claudeDir>","gitTracked":false,"backup":{"path":"/abs/…","files":<n>,"bytes":<n>},"sessionId":"<id>","acknowledged":false}
```

If this agent dies between the removal and its report, the ledger row is what survives it —
`SendMessage` fails outright once the session has ended, so a row written first is the only thing
that lets check #64 ever surface the removal to the user.

**Write `installationPath` and `gitTracked` on THIS row, not only on `T1K-REMOVAL.json` (step 9).**
A reader that infers the recovery target from `scope` alone — `local` resolving to whatever
`claudeDir` it happens to be invoked against, `global` resolving to `$HOME/.claude` — can resolve
against the wrong install if it is ever invoked from a project other than the one this removal ran
in. Write the actual `<claudeDir>` this run acted on (matching Contract I's `installationPath`
naming — the recovery project root is `path.dirname(installationPath)`) so no reader ever has to
guess it. `gitTracked` is always `false` here — step 1 already guarantees a tracked target never
reaches this step — but duplicate it onto this row anyway (not only the in-backup manifest) so the
fact survives the backup directory being deleted, archived, or simply unreachable to a reader: the
git-tracked refusal guard is this plan's whole safety story, and reporting it correctly must not
depend on a second file being available.

---

## Steps 7–8 — remove, then verify a NUMBER

```bash
t1k uninstall --kit <k> --<scope> --yes
```

1. **Assert the backup receipt's FILE COUNT and BYTE TOTAL**, not merely that a path appeared and
   the directory exists — both of those are true of a truncated backup. An ENOSPC- or timeout-killed
   copy leaves a partial tree at a path that still starts with `.claude-backup-`, still appears in
   `recover --list`, and still consumes a keep-10 slot. If either number is absent or implausible
   (e.g. `files: 0` against a non-trivial manifest), **abort and report** — do not treat the removal
   as done.
2. **Re-run checks #58 and #63; the finding must be gone.** Do not trust the exit code alone — there
   is a known, separately-filed CLI defect where `t1k uninstall --kit` can report success having
   removed nothing. Re-running the check is what catches it; report `"removal reported success but
   the finding persists"` if it does.
3. **Feature-detect the backup capability, never version-pin it.** The dry-run's receipt/announcement
   line (asserted in step 5) is the signal. A `>=` version comparison fails on a revert-forward: a
   published version can increase while the backup helper it once shipped is reverted out.

**One residual, stated rather than fixed:** the CLI's per-file safety check
(`isPathSafeToRemove`) returns `false` on any error including `EACCES`, so a permission-blocked file
is silently kept while the removal reports success elsewhere. Step 8's check re-run catches this as
"finding still present" — say so in the report rather than leaving it unexplained. **Second
residual, noted only:** if `.claude` is itself a symlink, deletes land under the resolved target;
per-file containment still holds, so this changes nothing about safety.

---

## Step 9 — the self-describing backup

Write `<backup>/T1K-REMOVAL.json` (Contract J), inside the backup directory itself:

```json
{"schemaVersion":1,"ts":"<ISO8601>","kit":"<k>","scope":"<local|global>","reason":"<slug>","findingFrame":"[t1k:doctor:scope-finding …]","filesRemoved":<n>,"gitTracked":false,"recoveryCommand":"cp -a --backup=numbered <backup>/. <projectRoot>/.claude/"}
```

The false-positive cost of a removal is not "run `cp -a`" — a deleted skill fails by **not
activating**, silently, possibly weeks later. The cost is: notice something broke, guess which of
ten backups, and learn the recovery is `cp -a` and NOT `t1k recover restore` — and the only artifact
that ever said so was a chat message that has since scrolled out of context. `recover --list` renders
only `<ts>-<slug>`; the backup directory itself must carry this file so the answer survives on disk.

---

## Step 10 — the report

Every element, every time, even on a no-op run:

- **What was removed**, and from which scope (or: nothing, and why — cite the refusing step).
- **The absolute backup path, with its file count and byte total.**
- **The recovery instruction, situation-correct:**
  - git-tracked ⟹ `git -C <projectRoot> checkout -- .claude/` (should not arise — step 1 refuses —
    print it only for a removal that predates this guard).
  - untracked ⟹ `cp -a --backup=numbered <backup>/. <projectRoot>/.claude/`. **Never bare `cp -a`**
    — verified (GNU coreutils 9.11): with an existing target it is a *merge*, not a replace. A file
    modified after the backup is silently overwritten with no prompt; the old `metadata.json` can
    clobber a newer one, orphaning a kit installed since the backup. `--backup=numbered` turns that
    silent clobber into a diffable `.~1~` sidecar.
  - backup archived (10+ backups since, or a `doctor --backup-everything` run) ⟹ the tar-aware form:
    `tar -xf ~/.claude-backup-archive/<name>.tar.gz -C <tmpdir> && cp -a --backup=numbered <tmpdir>/<name>/. <projectRoot>/.claude/`
    — the printed absolute path 404s once archived; always offer both.
  - **`t1k recover restore <ts>` is FORBIDDEN in every report for a local-scope removal.** Restore is
    deliberately unwired to whole-tree-overwrite semantics; pointing a user at it to undo one kit's
    removal is a second, larger destructive act.
- **What was NOT removed and why** — enumerate the refusing condition by name: git-tracked, LOW
  confidence, `comparable=no`, `hashed<claimed`, `surface=executables`, `status=skip`,
  DIVERGED-AHEAD, cumulative cap, allow-listed, unattributable.
- **Anything the verification step could not confirm.**

**"Auto-fix silently, report after" means the user is not interrupted — not that they are not
told.** A removal the user cannot see, undo, or explain is indistinguishable from data loss.

**The report is best-effort, not the record.** `SendMessage` to `"main"` fails once the session has
ended. Contract J's ledger and `T1K-REMOVAL.json` are the durable record; this report is the
courtesy on top of them.

---

## Step 11 — the sentinel, on every run

Write `<claudeDir>/session-state/scope-enforcement-suppression.json` (Contract E) at the end of
**every** run — success, no-op, or refusal alike — guarded by the same `existsSync(claudeDir)` check
from step 0b:

```json
{"schemaVersion":1,"doubleLoadedTokensAtClear":<n>,"clearedAt":"<ISO8601>","reason":"<slug>"}
```

Use the **post-removal** duplication figure (recompute after any removal in this run, not the figure
that dispatched this agent). Writing this only on a "nothing actionable" outcome — never after a
successful removal — is what makes a guaranteed redundant dispatch happen next session and, combined
with the git restore-fight loop, never terminate. Always release the lock (step 0) before this final
write.

---

## Agent brief this spec is the target of (Contract H)

Per `rules/lean-brief-pointer-not-payload.md`, the dispatching brief carries paths and verbatim
constraints — never pasted findings:

1. **Task** — remediate HIGH-confidence scope findings in this project.
2. **Paths** — this spec file; the doctor-check commands to run. Not their output pasted in.
3. **Verbatim constraints** — the fixed step order; the git guard; HIGH-only; the Contract B gate
   including `hashed === claimed`; the cumulative ledger cap; DIVERGED-AHEAD → stop; `--yes` on
   every command.
4. **Delivery channel, named literally** — `report via SendMessage to "main"`. A background
   sub-agent's final text does not reach its spawner. And it is best-effort — Contract J is the
   record.
5. **Re-read state at act time** — never trust the guard's dispatching snapshot.

---

## What this spec deliberately does not do

- **No auto-fix wired into `t1k doctor --fix`.** Checks #48/#55/#58/#63/#64 stay diagnostic-only and
  safely runnable by anyone at any time; only this dispatched agent, running the full gated order
  above, ever deletes anything.
- **No new agent `.md`.** A dedicated agent type for one procedure would violate SSOT and add
  always-loaded surface to a plan whose purpose is reducing exactly that.
- **No widening of `scopeEnforcement.autoRemoveKits` beyond what
  `DECISION-autoremove-core.md` sets.** Opting in another kit is a consumer decision gated on a
  measured fleet population, not something a future edit to this file should do casually.

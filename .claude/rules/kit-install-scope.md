---
origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---
# Kit Install Scope — One Kit, One Scope

## Rule

A kit is installed in **exactly one** scope. `core` and `model-router` are the global-scope baseline and belong in `~/.claude/`; every engine and domain kit (unity, designer, cocos, react-native, web, nakama, marketing) belongs **per-project** in `./.claude/`. Installing the same kit in both scopes is a misconfiguration, not a backup. Membership is the SSOT in `hooks/lib/kit-scope-policy.cjs` — a kit may also declare `installScope` for itself in its own `t1k-config-*.json` fragment, which overrides the two-kit fallback with no core release required.

**Why `model-router` is global-scope, not per-project.** The transparent-routing interceptor is registered in `~/.claude/settings.json` and is machine-wide, so a per-project router install is the anomaly, not a variant: settings.json loads only the global copy, so a project-local-only router installation is silently non-functional (routing passes straight through to Anthropic — the model-router kit's own doctor and post-install code exist specifically to guard against this).

**Why the duplicate is worse than it looks:** only ONE copy is ever served. Project-local shadows global, so the global copy becomes an invisible second install that still takes `t1k modules update` and still reports healthy in `t1k --version`, while every session reads the project copy. Updating the wrong one is silent — the command succeeds and nothing changes. Two installs also double the always-loaded rule surface the context-budget checks measure.

**This is NOT `prefer-local-over-global-edits.md`.** That rule answers *"both copies exist — which one do I EDIT?"* (answer: the project one). This rule answers *"should both copies exist at all?"* (answer: no). They are routinely conflated. The two are consistent, not competing: when an overlap does exist, project-local is what you edit and what the session loads — which is exactly why the shadowed global copy is dead weight rather than a fallback.

## The exemption is split in two — router and core score differently

An earlier version of this rule claimed a blanket exemption from Core Requirement #13's warn-first-with-a-dated-ratchet obligation, on evidence that turned out to be entirely about `model-router` — every cited row was the interceptor's own settings.json/post-install/doctor code proving a project-local router install is already non-functional. That evidence does not reach `core`: a project-local `core` install is fully functional (it is the CLI's own default output, and runs in production on multiple studio consumers today). Scored separately, the two halves land in different places:

| Half | Posture | Why |
|---|---|---|
| **`model-router` found in local scope** | **Exempt — no warn-first needed.** | Already non-functional by construction; a warn-first ramp protects nobody, because there is no live behavior to break. |
| **`core` found in local scope** | **Warn-first, with a dated ratchet.** | Fully functional, measured on multiple real consumers, and is what a fresh `t1k init --kit <engine>` produces today (engine kits declare `core` as a dependency). Removing it is a real behavior change for a working install. |

**The ratchet — ARMED 2026-08-22 by maintainer decision.** The shipped
`t1k-config-core.json` now sets `scopeEnforcement.autoRemoveKits: ["core", "model-router"]`, so
doctor check #58's `global-kit-in-project` finding promotes to `confidence=high action=remove` for
BOTH kits by default, for every consumer, with no exception.

An earlier revision of this section forbade arming `core` by default until the fleet population of
project-scoped-`core` installs had been re-measured across more than one developer machine and a
migration note existed. **That precondition was waived deliberately, not met** — the measurement
still covers exactly one machine (27 consumer projects, 2026-08-22). It is recorded here so the
next reader does not mistake the waiver for evidence. `model-router` needed no such waiver: a
project-local router install is non-functional by construction, so there is no working install to
lose.

**What still protects a consumer, and why arming is survivable:** the remediator REFUSES on the
first git-tracked target path (`git ls-files --error-unmatch`, step 1 of
`skills/t1k-doctor/references/scope-remediation.md`) and **that step has no override**. Every one
of the 27 measured consumers commits `.claude/`, so in practice they are refused and reported,
not removed. Removal reaches only untracked project-local copies. On top of that: a `--dry-run`
gate before any removal, `maxRemovalsPerRun` (2), a `removalCooldownDays` window (7), a per-project
lock, and a re-read of checks #58/#63 at act time rather than acting on the guard's snapshot.

**The in-code fallback stays `[]` on purpose.** `hooks/lib/scope-enforcement-config.cjs` still
resolves to an empty list when no config fragment is present at all. That is the fail-closed floor
for a stripped or hand-edited install, not an exception to the policy above — the shipped config
carries the effective default, exactly as `writeAgentFloor`/`defaultBuiltInModel` do.

## How to apply

1. **Before installing**, pick the scope from the kit: `core`/`model-router` → `t1k init --global`; anything else → per-project, from the project root.
2. **On a reported finding** (doctor check #58), drop the copy that does not belong — `t1k uninstall --local --kit core` (keep global) or `t1k uninstall --global --kit <engine-kit>` (keep project). Uninstalling is destructive; run it yourself rather than letting an agent sweep it, even when the finding ships `confidence=high` — that flag names what CAN be automated, not a standing instruction to automate it.
3. **Before dropping the project copy**, run `/t1k:sync-back` if it holds local edits — `prefer-local-over-global-edits.md` § "Gotcha" applies, and the edits live only in the copy you are about to delete.
4. **A declared `inheritsFrom` → global is the one legitimate overlap.** Layering is intentional there; check #58 reports it at INFO for visibility only, and never promotes it to `confidence=high` regardless of `autoRemoveKits`.

## Related

- `prefer-local-over-global-edits.md` — which copy to EDIT when both exist. Different question; see the contrast above.
- `hooks/lib/kit-scope-policy.cjs` — the SSOT for which kits are global-scope.
- Doctor check **#48** (`skills/t1k-doctor/scripts/check-global-core-only.cjs`) — the other half of this policy in prose: no non-global-scope kit installed globally at all.
- Doctor check **#58** (`hooks/doctor-check-58-kit-install-scope.cjs`) — the machine-readable half, both directions: a global-scope kit found locally, an engine/domain kit found globally, or the same kit in both scopes.
- Doctor check **#55** — whether two coexisting copies AGREE (BEHIND / DIVERGED-AHEAD / MISSING), and — via `--kit <name>` — whether the comparison actually covered enough of the kit's files to trust the answer.
- Doctor check **#36** — the same question one layer down, for individual rule files.

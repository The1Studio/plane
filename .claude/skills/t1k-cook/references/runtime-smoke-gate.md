---
origin: theonekit-core
repository: The1Studio/theonekit-core
module: t1k-base
protected: true
---

# Runtime Smoke Gate — Phase 2/3 Mandatory Check for Scene/Prefab Edits

When an implementation phase modifies scene or prefab assets, **compile-clean is not runtime-clean**. Edit-mode console may show zero errors while Play Mode immediately NREs because serialized references were silently dropped during the edit. This gate makes runtime smoke mandatory whenever scene/prefab assets were touched.

## When this gate fires

This gate fires automatically during **Step 3 (Implementation)** of `t1k-cook` if ANY of the following file patterns appear in the phase's changeset:

| Engine | File patterns |
|---|---|
| Unity | `**/*.unity`, `**/*.prefab`, `**/*.asset` (ScriptableObject references) |
| Cocos | `**/*.scene`, `**/*.prefab` |
| Godot | `**/*.tscn`, `**/*.tres` (when referenced from scenes) |
| Web/RN | n/a (no asset-serialized references) |

If the implementer modified, deleted, or moved any matching file, the gate becomes **mandatory** before Step 3 can be marked complete.

## What the implementer MUST do

The Step 3 sub-agent prompt MUST include the following clause when scene/prefab edits occurred:

> **Runtime Smoke Required.** This phase touched scene/prefab assets. Edit-mode "Console clean" is INSUFFICIENT evidence that the change is correct. You MUST execute a runtime smoke and report **Play Mode console output**, NOT just edit-mode console. Compile-clean is not runtime-clean.

### Unity — delegation path

For Unity projects, delegate to the kit's existing playtest tooling:

1. Invoke the `t1k-unity-editor-playtest` skill with `--quick` mode (Checks 1–3: Console Clean, Entity Spawn, Rendering).
2. The skill routes to the `dots-validator` agent which uses Unity MCP `read_console(filter: "Error")` after entering Play Mode.
3. The sub-agent MUST paste the Play Mode console transcript (or a "0 errors, 0 warnings of concern" attestation citing the MCP call) into its Step 3 report.

If `t1k-unity-editor-playtest` is not installed (Unity kit not present), the implementer MUST escalate via `AskUserQuestion` rather than silently skipping. Options: install Unity kit, manual Play Mode (user attestation), or abort.

### Cocos — delegation path

For Cocos projects, delegate to `t1k-cocos-runtime-smoke` (if present) or invoke the Cocos preview build + console scan. Same attestation contract: paste runtime console output, not editor console.

### Non-engine projects (web, RN, backend)

This gate is a no-op for projects without scene/prefab asset files. The file-pattern check filters them out automatically.

## Sub-agent prompt injection

When spawning the Step 3 implementer sub-agent, the calling skill MUST prepend the following block to the prompt **if and only if** the phase changeset includes any matching pattern:

```
RUNTIME SMOKE GATE — ACTIVE FOR THIS PHASE

This phase touches scene/prefab files (matched: <list-of-files>).
Before reporting Phase 3 done, you MUST:

1. Execute a runtime smoke (Play Mode for Unity, Preview for Cocos, etc.).
2. Capture Play Mode / runtime console output — NOT edit-mode console.
3. Report ZERO NullReferenceException, ZERO missing-reference errors,
   ZERO unbound serialized fields in the runtime console.
4. If the runtime is unreachable (no Editor connection, MCP unavailable),
   STOP and report "runtime smoke unreachable" — do NOT declare done.

Edit-mode "Console clean" is NOT acceptable evidence. Reporting only
edit-mode console for a scene/prefab change is a workflow violation
(ref: theonekit-core#176, GameManager.cs:219 incident, 2026-05-10).
```

## Failure modes this gate prevents

1. **Silent null-ref cascade** — removing a prefab from a scene drops all inbound serialized references (other scene objects pointing at its children). Edit-mode shows no error; Play Mode NREs in N unrelated systems. Origin incident: `IAP_Controller.prefab` deletion → GameManager.cs:219 + 6 other systems.
2. **Scene-shrink hiding cascade damage** — a "single object" deletion may shrink the scene `.unity` file by thousands of lines if the object was a god-prefab root. The diff size is itself a warning sign; pair this gate with `god-prefab-extraction-risk.md` for plan-phase prevention.
3. **"Console clean" attestation under-specified** — without this gate, "Console clean" was an implicit reference to *edit-mode* console. The sub-agent prompt now disambiguates: runtime console is required.

## Interaction with --tdd mode

In `--tdd` mode, Step 3.V (Verify full suite) covers compile + unit tests but does NOT cover runtime smoke. The runtime smoke gate is an **additional** check after 3.V when scene/prefab edits occurred — not a replacement for the test suite, and not subsumed by it.

## Interaction with --no-test mode

`--no-test` disables Step 4 (full test suite). It does NOT disable the runtime smoke gate. A scene-touching `--no-test` run still requires Play Mode smoke; otherwise the same NRE class of bugs ships.

## Why this gate is at Step 3, not Step 4

Step 4 (Testing) runs the test suite — typically Edit Mode tests in Unity. Edit Mode tests do not execute scene `Awake()`/`Start()` lifecycles in a real Play Mode session, so they don't catch dropped serialized references. The smoke must be a **separate runtime exercise** at the end of Step 3, before the phase is reported done.

## Related

- `references/workflow-steps.md` § Step 3 — gate invocation point
- `references/god-prefab-extraction-risk.md` — plan-phase prevention for the same incident class
- `references/subagent-patterns.md` — sub-agent prompt construction
- `theonekit-unity:t1k-unity-editor-playtest` — Unity-specific runtime smoke implementation
- The1Studio/theonekit-core#176 — originating incident

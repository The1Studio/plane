# Cascade a module's terminal status to everything in it

**Created:** 2026-08-28
**Branch:** `feat/module-cascade-terminal-status`
**Extends and partly AMENDS:** `plans/260822-cascade-complete-sub-items/` (the shipped per-issue
cascade) — Phase 0 reverses its Decision 5.
**Scope:** two new endpoints on the **existing** `cascade_ext` fork app + a widened
`packages/cascade-ext` + one new fenced core-frontend edit. No new Django app, no new model, no
migration, **no backend core edits, no new touch-point**.
**Plane:** [PLANE-189](https://plane.the1studio.org/infrastructure/projects/2eae4e83-f715-4e4b-8753-cdc289bbe37f/issues/f1318bf8-95f4-4642-b48f-2372e4bf7091)

## Problem

Setting a module to `completed` or `cancelled` leaves every work item in it untouched. The module
reads as finished while its work items sit in `In Progress`, the module's own progress ring
disagrees with its own status, and archiving is gated on `status in (completed, cancelled)` — so a
module can be archived with live work inside it.

The per-issue cascade shipped for exactly this problem one level down (a parent work item and its
sub-items). This plan applies the same treatment one level up.

## Prior art — the mechanism already exists; this reuses it

Passes 1–3 run over `apps/api/plane/`, `apps/web/`, `apps/space/`, `packages/`:

| Question                                                        | Answer                                                                                                                                                                                                                                                                                | Evidence                                                                                                                                                                                           |
| --------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Does anything cascade a module's status onto its issues today?  | **Zero across `apps/api/plane/app/views/module/`, `apps/api/plane/api/views/module.py`, `apps/api/plane/space/views/module.py`, `apps/api/plane/app/views/workspace/module.py`, `apps/api/plane/db/models/module.py`, `apps/api/plane/bgtasks/`, `apps/api/plane/ai_ext/signals.py`** | No `Issue.state` bulk-update is reachable from a `Module` write; the only such bulk-update in the repo is `bgtasks/issue_automation_task.py:131` (project-level stale-issue auto-close, unrelated) |
| Is there a descendant-collection + eligibility engine to reuse? | **Yes** — `plane/cascade_ext/service.py` `collect_descendants` / `apply_cascade`                                                                                                                                                                                                      | Level-order BFS, `visited` set, `MAX_DEPTH = 20`, per-project target-state resolution by `State.group`, per-project membership gate, atomic parent+children write                                  |
| Is there a confirm-modal + preview/apply client to reuse?       | **Yes** — `packages/cascade-ext`                                                                                                                                                                                                                                                      | `cascade-service.ts`, `cascade-confirm-store.ts`, `cascade-confirm-modal.tsx`, `should-prompt-cascade.ts`                                                                                          |
| Is there an MCP surface to mirror?                              | **Yes** — `plane_mcp/tools/cascade_ext.py` + `update_work_item(cascade=False)`                                                                                                                                                                                                        | `plane-mcp-server` repo                                                                                                                                                                            |

**Pass 4 (corpus sweep) — not applicable, recorded rather than skipped.** The studio
`knowledge-retrieval` corpus indexes the Unity/.NET and Cocos assemblies; it does not index this
Django/React monorepo, so it cannot answer prior-art questions about it. This finding is _not_
`greenfield` in any case — the capability exists and this plan extends it, so the greenfield gate
never fires.

Confirmed seams:

| Seam                                                                                                                         | Location                                                                                                                                                    |
| ---------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Module.status` (flat `CharField`, choices `backlog\|planned\|in-progress\|paused\|completed\|cancelled`, default `planned`) | `apps/api/plane/db/models/module.py:74-85`                                                                                                                  |
| `ModuleIssue` join (`related_name="issue_module"` on **both** FKs)                                                           | `apps/api/plane/db/models/module.py:152-171`                                                                                                                |
| Canonical "issues in a module" query                                                                                         | `Issue.issue_objects.filter(issue_module__module_id=…, issue_module__deleted_at__isnull=True)` — `app/views/module/issue.py:84-92`                          |
| Module status write path (app)                                                                                               | `ModuleViewSet.partial_update` — `app/views/module/base.py:651-721`, `@allow_permission([ROLE.ADMIN, ROLE.MEMBER])`                                         |
| Module status write path (public API)                                                                                        | `ModuleDetailAPIEndpoint.patch` — `api/views/module.py:402-450`, `ProjectEntityPermission`                                                                  |
| Archived-module write rejection                                                                                              | `app/views/module/base.py:663-667`, `api/views/module.py:412-416`                                                                                           |
| Module webhook dispatch                                                                                                      | `model_activity.delay(model_name="module", …)` — `app/views/module/base.py:708-716`                                                                         |
| Frontend choke point                                                                                                         | `updateModuleDetails` — `apps/web/core/store/module.store.ts:431`                                                                                           |
| Module PATCH service                                                                                                         | `patchModule` — `apps/web/core/services/module.service.ts:58-69`                                                                                            |
| Free client-side counts on `IModule`                                                                                         | `total_issues`, `completed_issues`, `cancelled_issues`, `backlog_issues`, `started_issues`, `unstarted_issues` — `packages/types/src/module/modules.ts:56+` |
| Fork-app mount block                                                                                                         | `apps/api/plane/urls.py:17-45` (`cascade_ext` already mounted at line 44)                                                                                   |

`apps/space` is **read-only** for modules (`ProjectModulesEndpoint` is `GET`/`AllowAny`, returns
`{id, name}`; `apps/space/store/module.store.ts` has no update method). Nothing to guard there.

## Decisions (resolved)

| #   | Decision                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| M1  | **Extend `cascade_ext`; do not create a new app.** The eligibility rules (target state by `group`, per-project membership, prune-at-terminal, atomic write, `notification=False` on cascaded rows) are the _same_ rules — a second app would be a second copy that drifts. Extending also costs **zero** touch-point edits (`INSTALLED_APPS` and `urls.py` already carry `cascade_ext`) and zero `forkApps` / CI registration, both of which a new app would need.                                                                                                                                                                   |
| M2  | **Cascade scope = every module member plus each member's full descendant subtree**, recursively — including sub-items that are not themselves module members. A member left with unfinished children reproduces the exact "finished at the top, unfinished underneath" problem the per-issue cascade exists to fix.                                                                                                                                                                                                                                                                                                                  |
| M3  | **The confirmation modal is the same modal.** `CascadeConfirmModal` grows a summary header (counts by outcome) and auto-collapses its row list above `LIST_COLLAPSE_THRESHOLD = 15`. Below the threshold the issue flow renders exactly as it does today, so this is not a behavior change for the shipped feature.                                                                                                                                                                                                                                                                                                                  |
| M4  | **Hard cap, explicit refusal.** `MAX_MODULE_CASCADE_ITEMS = 100` live nodes. "Live" is post-pruning (M8): terminal items and everything behind them are already gone before the count is taken, so the cap measures exactly what a confirm would write. Over the cap, preview returns `over_cap: true` with an **empty** `items` array (shipping 240 rows to a modal helps nobody) and apply returns **400** rather than half-applying. The module's own status still changes via the ordinary PATCH — only the cascade is refused.                                                                                                  |
| M5  | **The apply endpoint writes the module's `status` too**, inside the same transaction as the issues — mirroring how `cascade-apply` writes the parent issue's state. A module marked complete whose issue writes then failed is the outcome atomicity exists to prevent. The endpoint re-implements the two behaviors the core viewset applies to a status write: reject if `archived_at` is set, and fire `model_activity(model_name="module", …)` on success.                                                                                                                                                                       |
| M6  | **No cheap client-side skip; guard on `status ∈ {completed, cancelled}` AND `total_issues > 0` only.** The per-issue flow could skip the preview using `sub_issues_count` because a Done click is high-frequency. A module status change is not, and the tempting cheaper guard (`backlog + started + unstarted > 0`) is **wrong** under M2: those counts cover direct members only, so a module whose members are all terminal but whose sub-items are live would be skipped incorrectly. One request on a rare action buys correctness.                                                                                            |
| M7  | Terminal group is taken from the module's **new** status: `completed → completed`, `cancelled → cancelled`. A move between the two cascades the new one. Re-saving the same status is a no-op (nothing to enter). Any other status (`backlog`, `planned`, `in-progress`, `paused`) never cascades.                                                                                                                                                                                                                                                                                                                                   |
| M8  | A work item already in **either** terminal group is never listed and never touched, **and prunes its entire subtree** — nothing beneath it is listed, walked, or changed. A terminal item is a decision someone made about that branch, and reaching past it overrides that decision silently. This **reverses** the shipped per-issue rule (`260822` Decision 5, "still traversed through"), so Phase 0 applies the same reversal to the issue cascade rather than letting the two subjects disagree on one `Issue.parent` tree. Cost, stated: a live sub-item under a cancelled parent is now left live where it used to be swept. |
| M9  | Cross-project descendants are included and resolved to **their own** project's state of the same `group`, never by name. Direct module members are always same-project (a `ModuleIssue` is project-scoped), but a member's sub-items need not be. (Mirrors Decision 7.)                                                                                                                                                                                                                                                                                                                                                              |
| M10 | A node whose project has no state in the target group, or whose project the actor is not an active member of, is listed **disabled with a reason** — not hidden, not silently skipped. (Mirrors Decision 8.)                                                                                                                                                                                                                                                                                                                                                                                                                         |
| M11 | Each cascaded work item gets its own activity row with `notification=False`. Only the module's own `model_activity` fires. A 200-item module must not fire 200 watcher notifications. (Mirrors Decision 10.)                                                                                                                                                                                                                                                                                                                                                                                                                         |
| M12 | **No implicit cascade for API/MCP callers.** A plain `PATCH {status: "completed"}` on a module never cascades, from any client. MCP gets `update_module(..., cascade=False)` — default `false`, mirroring the UI's "only change this module".                                                                                                                                                                                                                                                                                                                                                                                        |
| M13 | Archived modules refuse both preview and apply with 400, mirroring the core viewset's own refusal to write an archived module.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| M14 | After a successful apply the client refetches the module, because `total_issues` / `completed_issues` / `cancelled_issues` drive the progress ring rendered right beside the status dropdown and would otherwise read stale.                                                                                                                                                                                                                                                                                                                                                                                                         |
| M15 | Fork UI strings stay in `packages/cascade-ext/src/strings.ts`, English-only — `packages/i18n` is an upstream `@plane/*` package the fork rules forbid editing in place. (Mirrors Decision 12.)                                                                                                                                                                                                                                                                                                                                                                                                                                       |

## Explicitly out of scope

- **Cycles.** They group work items the same way and deserve the same treatment, but that is a
  second endpoint pair, a second store fence, and a reconciliation with the existing
  `complete_cycle` action. The service layer below is written over a seed-id set rather than over
  `Module`, so adding cycles later is a new caller, not a rewrite.
- Reverse cascade — reopening a module does not reopen its work items.
- Auto-completing a module once all its work items finish.
- Cascading any field other than work-item state.
- Module **archive** as a trigger. Archiving is already gated on the status being terminal, so the
  cascade has run by then.
- `apps/space` — read-only for modules, nothing to guard.

## Flow

1. User changes a module's status (list row, grid card, analytics sidebar, create/update modal, or
   the power-K palette — all five funnel through `updateModuleDetails`).
2. Guard: is the new status `completed`/`cancelled` **and** `total_issues > 0`? If not → plain
   PATCH, unchanged behavior, zero extra requests.
3. `GET …/modules/<module_id>/cascade-preview/` → the flattened item list with eligibility per row,
   plus summary counts and the over-cap flag.
4. Preview has no eligible row → plain PATCH, no modal.
5. Over cap → modal opens in refusal mode: the count, the cap, and only **"Only change this
   module"**. No cascade path is offered.
6. Otherwise the modal opens with a summary header and (collapsed above 15 rows) the checkbox list.
   Focus rests on **"Only change this module."**
7. "Only change this module" → plain PATCH.
8. "Change work items too" → one `POST …/cascade-apply/` carrying the new `status` and the ticked
   ids. The server re-derives eligibility and applies module + items atomically, then the client
   refetches the module (M14).

## Phases

| Phase     | File                                                                                                                                                                    | Effort   |
| --------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| 0         | `phase-0-prune-terminal-subtrees.md` — reverse skip-but-traverse to prune-at-terminal in the **shipped** issue cascade, invert two tests, add `under_terminal_ancestor` | S (1.5h) |
| 1         | `phase-1-module-cascade-backend.md` — seed-set refactor of `service.py`, module preview + apply endpoints, cap, tests                                                   | M (4h)   |
| 2         | `phase-2-cascade-package.md` — `packages/cascade-ext`: module service + guard + store, summary header and collapsible list on the shared modal                          | M (3h)   |
| 3         | `phase-3-wire-module-store.md` — fenced interception in `module.store.ts`, refetch, `docs/FORK.md` exception row                                                        | S (2h)   |
| 4         | `phase-4-propagate.md` — `plane-propagate` sibling-repo issues, MCP `update_module(cascade=)` + `preview_module_cascade`, `CLAUDE.md` entry                             | S (1.5h) |
| **Total** |                                                                                                                                                                         | **12h**  |

Critical path 0 → 1 → 2 → 3. Phase 0 is independently shippable and revertible: it changes live
behavior and touches no module code. Phase 2 may start against the Phase 1 contract before Phase 1 merges —
that contract is fixed in Phase 1 § "Endpoint contract" and is the integration contract for the
fan-out.

## Parallel-safe decomposition

Phases 1 and 2 are the only pair that can overlap. File ownership is disjoint:

| Lane    | Owns                            |
| ------- | ------------------------------- |
| Phase 1 | `apps/api/plane/cascade_ext/**` |
| Phase 2 | `packages/cascade-ext/**`       |

Zero overlap. **Declaration hoisting:** the endpoint contract (paths, payload field names and
casing, the `reason` enum, the `over_cap` shape) is declared in Phase 1's contract section _before_
either lane starts and is quoted verbatim into both briefs — no lane invents a shared shape.
Phase 3 is serial after both (it imports Phase 2's exports and calls Phase 1's endpoints).
Verification is serialized: one `pytest` + one `pnpm check` at the end of each lane, not per file.

## Risk Assessment

| Risk                                                                                     | L   | I   | Score  | Mitigation                                                                                                                                                                                                                                                                                                                           |
| ---------------------------------------------------------------------------------------- | --- | --- | ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Refactoring `collect_descendants` to a seed-set breaks the shipped per-issue cascade     | 3   | 5   | **15** | `collect_descendants(root_issue=…)` is kept as a thin wrapper over the new internal with `include_seeds=False`; its existing 490-line suite must pass **unchanged by Phase 1** — Phase 0's two deliberate inversions are already in the tree, and Phase 1 may not edit a third assertion. Gate stated in Phase 1 § Success criteria. |
| Phase 0's reversal is silently undone later by a reader who finds the inverted tests odd | 3   | 3   | 9      | The two tests are renamed to state the rule (`..._and_prunes_its_subtree`) and carry a dated comment; `docs/FORK.md` and `CLAUDE.md` are corrected rather than left asserting the old rule. Phase 0 § 4.                                                                                                                             |
| A user relied on the cascade sweeping past a cancelled parent                            | 3   | 3   | 9      | Deliberate, user-directed reversal — documented with its date in FORK.md/CLAUDE.md so a surprised reader finds the answer instead of filing a bug. Phase 0 § Risk.                                                                                                                                                                   |
| Client posts item ids it may not move                                                    | 3   | 5   | **15** | Apply **re-derives** the eligible set server-side and rejects anything outside it. `item_ids` is a request, never an authorization. Mirrors the shipped risk-15 mitigation.                                                                                                                                                          |
| A large module holds a long write lock / floods Celery                                   | 3   | 4   | 12     | `MAX_MODULE_CASCADE_ITEMS = 100` hard cap (M4) + the existing 100-row `bulk_update` batching. Over the cap, apply refuses rather than starting.                                                                                                                                                                                      |
| Module status write bypasses the core viewset, losing a behavior it applies              | 3   | 4   | 12     | M5 names the two behaviors explicitly (archived rejection, `model_activity`) and Phase 1 tests both. The remaining serializer work on that path — start/target date ordering, name uniqueness — cannot be affected by a status-only write.                                                                                           |
| Progress ring reads stale after a cascade                                                | 4   | 2   | 8      | M14 — refetch the module after apply. Phase 3 asserts the counts move.                                                                                                                                                                                                                                                               |
| Rebase conflict at `module.store.ts`                                                     | 3   | 2   | 6      | One fenced block + a `docs/FORK.md` exception row. Phase 3.                                                                                                                                                                                                                                                                          |
| Preview goes stale between preview and apply                                             | 2   | 3   | 6      | Apply re-derives; an item that became terminal in the gap is skipped and reported in `rejected`.                                                                                                                                                                                                                                     |
| Modal fires on the create/update modal's whole-object save                               | 3   | 2   | 6      | The guard reads `data.status` — a payload that does not change status never reaches the preview. Phase 3 asserts a name-only edit on a completed module issues no preview request.                                                                                                                                                   |
| `parent` cycle among module members → infinite walk                                      | 1   | 5   | 5      | `visited` seeded with every member id; `MAX_DEPTH = 20` unchanged.                                                                                                                                                                                                                                                                   |

## Timeline

| Phase                            | Effort   | Notes                                                                                     |
| -------------------------------- | -------- | ----------------------------------------------------------------------------------------- |
| Phase 0: prune terminal subtrees | S (1.5h) | Changes shipped behavior. Independently shippable. Blocks 1.                              |
| Phase 1: backend                 | M (4h)   | Blocks 2 and 3. Contract must be frozen first.                                            |
| Phase 2: package                 | M (3h)   | Overlaps Phase 1 once the contract is frozen.                                             |
| Phase 3: wire store              | S (2h)   | Serial after 1 and 2.                                                                     |
| Phase 4: propagate               | S (1.5h) | Sibling-repo issues + a separate `plane-mcp-server` PR. Never edited from this repo's PR. |
| Total                            | **12h**  | Critical path 0 → 1 → 2 → 3 = 10.5h.                                                      |

## Verification

- `pytest apps/api/plane/cascade_ext/tests/` green — **including the pre-existing
  `test_cascade_db.py` with no assertion edited**.
- `python manage.py makemigrations --check --dry-run` — no changes (proves no model added).
- `python manage.py check` clean · `pnpm check` clean.
- `node .claude/scripts/plane-classify-path.cjs` over the diff — every path classifies `fork` or as
  a **registered** exception. Expect exactly one unregistered-core candidate
  (`apps/web/core/store/module.store.ts`), registered by Phase 3.
- Manual matrix: empty module → no modal, no preview request · module whose items are all done →
  no modal · module → `in-progress` → no preview request · name-only edit on a completed module →
  no preview request · 3-level tree under one member → every level listed · terminal member with live children → member
  and its children **all** absent · cross-project sub-item
  → mapped by group · renamed states (`Done` → `Shipped`) → still correct · item in a project you
  cannot access → listed, disabled, reason shown · untick one → that one stays · Enter on the modal
  → **only the module changes** · 240-item module → refusal mode, module status still changes ·
  archived module → 400 · all five status entry points.

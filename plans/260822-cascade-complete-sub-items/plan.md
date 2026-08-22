# Cascade state to sub-work items, behind a confirmation modal

**Created:** 2026-08-22 · **Revised:** 2026-08-22 (adopted issue #54's interaction model)
**Branch:** `feat/cascade-complete-sub-items`
**Issue:** [The1Studio/plane#54](https://github.com/The1Studio/plane/issues/54) — implements it as specified
**Plane:** [PLANE-109](https://plane.the1studio.org/infrastructure/projects/2eae4e83-f715-4e4b-8753-cdc289bbe37f/issues/01d2ec04-a501-4de0-b8b4-aa7128ee509d) — parent, Infrastructure › Plane
**Scope:** two new endpoints on a new `cascade_ext` fork app + a new `packages/cascade-ext` frontend package + three fenced core-frontend edits. No new model, no migration, **no backend core edits**.

## Problem

Setting a parent work item to a terminal state leaves its sub-work items untouched. The tree reads
as finished at the top and unfinished underneath, and every rollup that counts child states
disagrees with the parent. Closing each child by hand is easy to leave half-done.

## Prior art — there is no warning today

Confirmed independently twice: my own sweep found **zero** matches across `apps/web/`,
`apps/space/`, `packages/` and `apps/api/plane/` for any guard, toast, modal, or serializer
validation on this transition (the only `PARENT_HAS_CHILDREN` in the tree is
`apps/api/plane/workload/views.py:157`, which guards **estimates**). Issue #54 says the same:
*"Không có cảnh báo, không có gợi ý nào."* This plan adds behavior; it removes nothing.

Confirmed seams:

| Seam | Location |
| --- | --- |
| `Issue.parent` self-FK | `apps/api/plane/db/models/issue.py:113` |
| `State.group`, `State.sequence` | `apps/api/plane/db/models/state.py:84-90` |
| Detail-view state write | `issue-details/issue.store.ts:181` `updateIssue` |
| List / spreadsheet / kanban state write | `helpers/base-issues.store.ts` `updateIssue` |
| Kanban drop → store | `issue-layouts/utils.tsx:513` `handleDragDrop` → `updateIssueOnDrop` → store |
| Modal primitives | `packages/ui/src/modals/modal-core.tsx`, `alert-modal.tsx` |
| App provider mount | `apps/web/app/root.tsx:135` `<AppProvider>` (touch-point 7) |
| Fork-app precedent | `apps/api/plane/workload/`, `views_ext/`, `github_ext/` |

## Decisions (resolved)

| # | Decision |
| --- | --- |
| 1 | **Confirmation modal, per issue #54.** Changing a parent into a terminal state opens a modal listing every affected descendant — identifier, name, current state — each with a checkbox. |
| 2 | **Default is "only change this item."** That button holds initial focus, so a stray Enter never cascades. Accidental cascade is treated as the expensive mistake. |
| 3 | The modal appears **only when there is something to change** — at least one non-terminal descendant. No children, or all descendants already terminal → plain state change, no prompt. |
| 4 | Cascade fires for **both terminal groups** and mirrors the one the parent entered: completing completes, cancelling cancels. A move between two states of the same terminal group is a no-op. |
| 5 | Descendants already in a terminal group are **never** listed or touched — a cancelled child is not completed, a completed child is not cancelled. Their own live descendants still cascade through them. |
| 6 | **All descendants, recursively**, with a `visited` set and `MAX_DEPTH = 20` against `parent` cycles. |
| 7 | Cross-project descendants are included, each resolved to **its own** project's state of the same `group` — never by name, since states are renameable. |
| 8 | A descendant whose project has no state in the target group, or whose project the actor is not an active member of, is shown **disabled with a reason** rather than hidden or silently skipped. |
| 9 | Parent state change + selected children apply in **one transaction**. Partial failure rolls the whole thing back, including the parent. |
| 10 | Each cascaded child gets its own activity entry, with `notification=False`. Only the parent's own change notifies watchers. |
| 11 | **No implicit cascade for API/MCP callers.** A plain `PATCH state` never cascades, from any client. Cascading is an explicit call to the cascade endpoint. |
| 13 | **MCP gets a `cascade` option, default `false`** — mirroring the UI's "only change this item" default. It lives in the MCP tool layer, not in a new core-view parameter: `update_work_item(..., cascade=False)` does a plain PATCH; `cascade=True` calls `cascade-apply` instead. This costs **zero** additional core edits. |
| 14 | `cascade-apply` treats an **omitted or null `child_ids`** as "every currently-eligible descendant". The UI always sends an explicit list (the user ticks boxes); a headless caller with no UI to untick omits it. |
| 12 | Fork UI strings live in `packages/cascade-ext`, not `packages/i18n` — a `@plane/*` package the fork rules forbid editing in place. English-only at first. |

## What the modal decision bought

The first draft of this plan cascaded implicitly inside `IssueViewSet.partial_update` and
`IssueDetailAPIEndpoint.patch` — two core files outside the 7 touch-points, guaranteed to conflict
on every upstream rebase. **Adopting the modal removes both.** Because the default is "only change
this item", a plain PATCH must do nothing extra, so there is nothing to hook. The cascade becomes a
dedicated endpoint the client calls on purpose.

Backend core edits: **zero.** The new app mounts via touch-point 2 (`apps/api/plane/urls.py`).

The core edits that remain are all frontend: two mobx store files, plus `apps/web/app/root.tsx`
(touch-point 7 — a sanctioned path, so it classifies as a touch-point rather than an unregistered
core edit). The two store files are the only genuine exceptions, and they are registered in
`docs/FORK.md` in Phase 3.

## Flow

1. User picks a new state (detail dropdown, list/spreadsheet dropdown, or kanban drop).
2. Guard: is the new state terminal, and does the item have `sub_issues_count > 0`? If not → plain
   PATCH, unchanged behavior, zero extra requests. **This is the common case and must stay free.**
3. `GET …/cascade-preview/` → the flattened descendant tree with eligibility per node.
4. Preview empty → plain PATCH, no modal (Decision 3).
5. Otherwise open the modal. Focus rests on **"Only change this item."**
6. "Only change this item" → plain PATCH.
7. "Change sub-items too" → one `POST …/cascade-apply/` carrying the parent's new `state_id` and
   the ticked child ids. Server re-derives eligibility and applies parent + children atomically.

## Explicitly out of scope

- Reverse cascade — reopening a parent does not reopen children (out of scope in #54 too).
- Auto-completing a parent once all children finish (#54 defers this to its own issue).
- Cascading any field other than state.
- **Bulk multi-item state update.** #54 wants one prompt per batch, but
  `grep -rn "bulk-operation-issues|bulk_operation"` returns **zero across `apps/api/plane/`** — the
  web store's `bulkUpdateProperties` (`base-issues.store.ts:721`) POSTs to an EE-only route with no
  backend in this fork. There is no reachable bulk state-update path to prompt for.
- Intake accept and archive paths.

## Phases

| Phase | File | Effort |
| --- | --- | --- |
| 1 | `phase-1-cascade-backend.md` — `cascade_ext` app, preview + apply endpoints, tests | M (4h) |
| 2 | `phase-2-cascade-package.md` — `packages/cascade-ext`: store, modal, preview client | M (3.5h) |
| 3 | `phase-3-wire-stores.md` — fenced interception at the two store choke points + root mount | M (2.5h) |
| 4 | `phase-4-propagate.md` — MCP/SDK/docs propagation, close #54 | S (1.5h) |
| **Total** | | **11.5h** |

Critical path 1 → 2 → 3. Phase 2 can start against the endpoint contract in Phase 1 before Phase 1
merges, provided that contract is fixed first (it is — see Phase 1 § "Endpoint contract").

## Risk Assessment

| Risk | L | I | Score | Mitigation |
| --- | --- | --- | --- | --- |
| Client sends child ids it should not be allowed to move | 3 | 5 | **15** | Apply endpoint **re-derives** the eligible set server-side and rejects any id outside it — never trusts the posted list. Phase 1. |
| Preview request fires on every Done click, including leaves | 4 | 3 | 12 | Two-condition guard (terminal group AND `sub_issues_count > 0`) runs client-side before any request. Phase 3 asserts zero extra requests on a leaf. |
| Rebase conflicts at the two core store files | 4 | 2 | 8 | One fenced block each + `docs/FORK.md` exception rows. Phase 3. |
| `parent` cycle → infinite walk | 1 | 5 | 5 | `visited` set + `MAX_DEPTH = 20`; a cap hit is surfaced in the preview payload, not swallowed. |
| Deep tree → slow preview | 3 | 3 | 9 | Level-order BFS, one query per level; preview is read-only and cached for the modal's lifetime. |
| Preview goes stale — a child changes between preview and apply | 2 | 3 | 6 | Apply re-derives eligibility, so a child that became terminal in the gap is skipped and reported in the response. |
| Modal blocks a drag-drop the user thinks completed | 3 | 3 | 9 | Kanban drop applies the parent's state optimistically as today; the modal governs only the cascade. Phase 3. |

## Verification

- `pytest apps/api/plane/cascade_ext/tests/` green.
- `python manage.py makemigrations --check --dry-run` — no changes (proves no model added).
- `python manage.py check` clean · `pnpm check` clean.
- `node .claude/scripts/plane-classify-path.cjs` over the diff — every path classifies `fork` or as a
  **registered** exception. Expect exactly two unregistered-core candidates (the store files), both
  registered by Phase 3; `root.tsx` classifies as touch-point 7.
- Manual matrix: leaf → no modal, no preview request · all-children-done → no modal · 3-level tree →
  every level listed · cross-project child → mapped by group · renamed states (`Done` → `Shipped`) →
  still correct · child in a project you cannot access → listed, disabled, reason shown · untick one
  → that one stays · Enter on the modal → **only the parent changes** · all three entry points.

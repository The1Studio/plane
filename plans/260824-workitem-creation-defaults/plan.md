# Work-item creation defaults — assignee → creator, due date → today

**Branch:** `feat/workitem-creation-defaults` off `company-main`
**Created:** 2026-08-24

## Goal

When a work item is created and a field is left unset, fill it:

- **assignee** → the creator (only when the project has no `default_assignee`)
- **due date** (`target_date`) → today

## Decided facts

These were resolved with the user before this plan was written. They are settled, not open.

| # | Decision | Resolution |
|---|---|---|
| D1 | Where the rule lives | **Backend + modal prefill.** The backend is authoritative (covers the public API, MCP, quick-add). The create modal additionally prefills the assignee chip and due-date pill so the value is visible and overridable before saving. |
| D2 | What "unset" means | **Absent only.** A payload carrying `assignee_ids: []` or `target_date: null` is a deliberate "nobody" / "no due date" and is left alone. Only a payload with the key entirely missing gets a default. |
| D3 | Precedence vs project `default_assignee` | **Project default wins.** The creator is the fallback used only when the project has no default assignee, or its default assignee is no longer a valid project member. Zero behavior change for projects already configured. |
| D4 | Quick-add (inline "+ New work item" in list / kanban / calendar / spreadsheet) | **Prefills the creator too**, client-side, so inline-added items match modal-added items. |
| D5 | `start_date` clash | Existing validation rejects `start_date > target_date`. When `target_date` is unset and `start_date` is in the future, the default is **`max(today, start_date)`** — never today. No request that succeeds today starts failing. |
| D6 | Excluded creation paths | **Bulk import / migration writers** and **intake**. Drafts and sub-work-items are IN scope. |
| D7 | Propagation | **Everywhere. Issues filed FIRST (phase 1), implementation after.** |
| D8 | Timezone for "today" | The **creator's `user_timezone`** (`User.user_timezone`, defaults `"UTC"`). The browser prefill uses the user's local date; computing the backend default in UTC would disagree by a day for any user east of UTC — a real mismatch for a UTC+7 team creating items before 07:00 local. |

## Prior art (searched, with scope)

| Claim | Evidence |
|---|---|
| A project-level default-assignee fallback ALREADY exists | `apps/api/plane/app/serializers/issue.py:232-251` and `apps/api/plane/api/serializers/issue.py:194-206`. Both fire when `assignee_ids` is falsy, `[]` included. This plan reuses it and adds the creator as a second fallback. |
| Nothing defaults `target_date` anywhere | Zero hits for a target-date default across `apps/api/plane/app/`, `apps/api/plane/api/`, `apps/api/plane/db/`, `packages/constants/`, `packages/utils/`. `DEFAULT_WORK_ITEM_FORM_VALUES` (`packages/constants/src/issue/modal.ts:23`) sets `target_date: null`. |
| The migration loaders are excluded for free | `~/clickup-exports/scripts/clickup_load*.py` write through raw ORM `objects.create` / `.save()`, never through a serializer. Serializer-layer defaults cannot reach them. D6's first exclusion needs **no code**, only a test asserting it. |
| No plugin seam exists for either surface | `packages/constants` is a sealed `@plane/*` package (`docs/FORK.md` § "Frontend customizations"); the serializers have no hook. Both edits are fenced core-edit exceptions, matching the precedent in `docs/FORK.md` § "Frontend core-edit exceptions". |

## Architecture

**Backend.** A new model-less fork app `apps/api/plane/issue_defaults_ext/` holds every decision as pure, unit-testable helpers. The two core serializers each get a small fenced call into it — the core diff stays under ~15 changed lines per file, which is the rebase-conflict budget that matters (`docs/FORK.md` § "Rebase-conflict budget").

Why the logic cannot live in a Django signal, which would need no core edit at all: a signal sees only the saved model, where an absent `target_date` and an explicit `null` are both `None`. D2 requires telling them apart, and only the serializer can — it has `self.initial_data`.

**Frontend.** A new package `packages/work-item-defaults-ext/` exports one pure helper; `form.tsx` and the quick-add root call it behind fences.

**Scope guard.** `validate()` runs on update too (`app/views/issue/base.py:667` reuses `IssueCreateSerializer` with `partial=True`). Every helper is gated on `self.instance is None` — a plain edit that clears a due date must never have it re-filled.

## Phases

| Phase | File | Deliverable |
|---|---|---|
| 1 | `phase-1.md` | Propagation issues filed in the six sibling repos (before any code) |
| 2 | `phase-2.md` | `issue_defaults_ext` fork app: helpers + unit tests |
| 3 | `phase-3.md` | Wire into the app serializer; intake exclusion; API tests |
| 4 | `phase-4.md` | Wire into the public-API serializer (covers MCP); API tests |
| 5 | `phase-5.md` | `work-item-defaults-ext` package + create-modal prefill |
| 6 | `phase-6.md` | Quick-add prefill (all four layouts) |
| 7 | `phase-7.md` | `docs/FORK.md` + `CLAUDE.md` fork-inventory entries |

Phases 3 and 4 both depend on 2. Phase 6 depends on 5 (shares the package). Phase 7 depends on 3–6. Phase 1 blocks nothing but is done first per D7.

## Risk Assessment

| Risk | Likelihood | Impact | Score | Mitigation |
|---|---|---|---|---|
| The default fires on UPDATE, silently re-filling a due date a user just cleared | 4 | 5 | **20** | `self.instance is None` gate in every helper; a regression test that PATCHes `target_date: null` and asserts it stays null. Phase 3. |
| A migration/bulk writer picks up today's due date, reverting migrated data | 2 | 5 | **10** | Serializer-layer only; loaders use raw ORM. Test asserts `Issue.objects.create()` sets no target date. Phase 2. |
| Timezone mismatch — backend UTC "today" disagrees with the browser's local date | 4 | 2 | 8 | D8: compute from `user.user_timezone`. Test at UTC+7 boundary (23:30 UTC = next day local). Phase 2. |
| Rebase conflict in the two core serializers | 3 | 2 | 6 | Keep each core diff to one fenced call; all logic in the fork app. |
| Project default-assignee precedence silently inverted while refactoring the existing block | 2 | 4 | 8 | The helper absorbs the existing validity check verbatim; a test pins "project default wins over creator". Phase 2. |
| Modal prefill leaks into edit mode, marking a clean form dirty | 3 | 3 | 9 | Gate prefill on `!data?.id`; verify the unsaved-changes prompt does not fire on open-then-close. Phase 5. |

No risk scores ≥ 15 other than the update-path one, which phase 3 blocks on explicitly.

## Timeline

| Phase | Effort | Notes |
|---|---|---|
| 1 — propagation issues | S (~1h) | No code dependency |
| 2 — fork app + helpers | M (~3h) | Critical path start |
| 3 — app serializer wiring | M (~3h) | Depends on 2 |
| 4 — public API wiring | S (~2h) | Depends on 2; parallel with 3 |
| 5 — package + modal prefill | M (~3h) | Depends on 2 for field semantics only |
| 6 — quick-add prefill | S (~2h) | Depends on 5 |
| 7 — docs | S (~1h) | Depends on 3–6 |
| **Total** | **~15h** | Critical path: 2 → 3 → 7 |

## Success criteria

- `POST` with no `assignee_ids` key → assigned to creator (project default absent) or to the project default (present).
- `POST` with `assignee_ids: []` → unassigned. `POST` with `target_date: null` → no due date.
- `PATCH` clearing either field → stays cleared.
- Intake submissions and raw-ORM writes get neither default.
- `start_date` in the future with no `target_date` → `target_date == start_date`, request succeeds.
- Modal opens with the creator chip and today's date filled, both clearable.
- Quick-add creates an item assigned to the creator, due today.
- `python manage.py makemigrations --check --dry-run` clean; `pnpm check` clean.

# Code Review — "Estimated hours" in the Add-work-item modal

**Reviewed:** `git diff e460d3094e..HEAD` on `feat/work-item-modal-estimated-hours`
(4 commits: `606907b4e5`, `a5fe19974d`, `7f827bed27`, `ecb9c25855`)
**Pinned base:** `e460d3094e` · **Reviewed HEAD:** `ecb9c25855`
**Reviewer:** t1k-code-reviewer · **Date:** 2026-08-24
**Verdict:** **PASS with 2 Important findings** (neither blocks runtime correctness). **Score 8/10.**

---

## 1. Acceptance criteria — plan.md Decisions D1–D11

| #   | Decision                                                                            | Verdict  | Evidence                                                                                                                                                                                                                                                                                                                                                                                                                           |
| --- | ----------------------------------------------------------------------------------- | -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| D1  | Update mode live-commits via existing `useWorkloadEstimateEditor`, unchanged timing | **PASS** | `estimated-hours-input.tsx:138` calls `useWorkloadEstimateEditor({workspaceSlug, projectId, issueId})` and wires `value/onFocus/onChange/onBlur/onKeyDown` verbatim. `use-workload-estimate-editor.ts` `COMMIT_DEBOUNCE_MS`, `enqueueCommit`, `debouncedCommit`, flush-on-unmount all untouched — the only hunk is the parse extraction at `:92`.                                                                                  |
| D2  | Create mode holds a draft in React state, writes once after creation                | **PASS** | `base.tsx:74` `useState<string>("")`; `PendingEstimateProvider` at `:469`; the single `workloadStore.updateEstimate(...)` at `:259`. `CreateModeInput` never calls a store. Nothing added to `TIssue`/rhf.                                                                                                                                                                                                                         |
| D3  | Placement: bottom properties row, after `target_date`, before cycle                 | **PASS** | `default-properties.tsx:205–214` sits between the `target_date` `Controller` (ends `:204`) and `{projectDetails?.cycle_view && (` (`:215`). Rendered outside any `Controller`, as specified.                                                                                                                                                                                                                                       |
| D4  | Only the create/update modal, not the inline quick-add row                          | **PASS** | Diff touches no file under `issue-layouts/quick-add/`. `IssueEstimatedHoursInput` has exactly one consumer: `default-properties.tsx:208`.                                                                                                                                                                                                                                                                                          |
| D5  | Field hidden when `isDraft`                                                         | **PASS** | `estimated-hours-input.tsx:56` `if (isDraft \|\| !projectId) return null;` — placed above both branches, no hooks run before it, so no conditional-hook hazard.                                                                                                                                                                                                                                                                    |
| D6  | Save-as-draft with hours warns and drops them; does not block the draft save        | **PASS** | `base.tsx:228` `} else if (parseEstimateHoursInput(pendingHours,{allowEmpty:false}) !== null) {` → one `TOAST_TYPE.WARNING`, then falls through. The `else` binds to the `if (!is_draft_issue)` at `:212`, so it fires only on the draft path. Reachable exactly as designed: the field is visible when the modal is not in draft mode, and `handleClose(saveAsDraft)` at `:158–160` calls `handleCreateIssue(changesMade, true)`. |
| D7  | Estimate PUT runs BEFORE `handleCreateSubWorkItem`                                  | **PASS** | `base.tsx:249–269` (PUT) precedes `:271 await handleCreateSubWorkItem(...)` inside the same `if (response.id && response.project_id)` block.                                                                                                                                                                                                                                                                                       |
| D8  | A failed estimate PUT never fails the create                                        | **PASS** | `base.tsx:257–267` — `try { await ... } catch { setToast(ERROR) }`, no rethrow, no `throw` after. Confirmed necessary: `store.ts:79–82` documents `updateEstimate` **re-throws** on failure. The outer `handleCreateIssue` catch is therefore never reached by an estimate failure, and the success toast + `handleClose` still run.                                                                                               |
| D9  | `parseEstimateHoursInput` is the single SSOT; old inline block GONE                 | **PASS** | `grep -n "trim()" apps/web/core/hooks/store/use-workload-estimate-editor.ts` → **no matches**. The removed 5-line block is transcribed byte-for-byte into `estimateInput.ts:26–34` (same branch order: `trim` → empty+`!allowEmpty`→null → `""?0:Number` → `!isFinite \|\| <0`→null → return). Two consumers only: the hook (`:92`) and `base.tsx` (`:228`, `:256`).                                                               |
| D10 | Parent (`rollup !== null`) renders read-only in update mode                         | **PASS** | `estimated-hours-input.tsx:161` `rollup !== null ?` → `formatRollupHours` + `title={formatRollupTooltip(rollup)}`, same helpers as the spreadsheet cell and the sidebar. `TWorkloadRollup` is an object type (`packages/workload-ext/src/types.ts:108`), so this is behaviourally identical to the existing sites' truthiness check. See Minor-3.                                                                                  |
| D11 | Pending hours reset after successful create AND on close, NOT on project change     | **PASS** | Reset at `base.tsx:296` (post-create, beside `setDescription`/`setChangesMade`) and `:167` (in `handleClose`). No reset added to the `data?.project_id`-keyed `useEffect` (the project-switch effect ending at `:132`), and the value lives outside react-hook-form so the `reset()` on project switch cannot sweep it.                                                                                                            |

**11 / 11 PASS.**

---

## 2. Public-contract stability — all confirmed stable

| Contract                           | Status         | Evidence                                                                                                                    |
| ---------------------------------- | -------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `TIssue` / `@plane/types`          | **untouched**  | Not in `git diff --name-status`.                                                                                            |
| `@plane/constants` (`ETabIndices`) | **untouched**  | Not in the diff. `default-properties.tsx:213` reuses `getIndex("estimate_point")` — the sanctioned workaround from phase-2. |
| Backend / Django                   | **zero files** | `git diff --name-status` lists no path under `apps/api/`. No model, no migration, no endpoint.                              |
| `createIssue()` payload            | **unchanged**  | No diff hunk touches the `createIssue(...)` call or the `payload` construction. The estimate is a separate `PUT`.           |
| `handleUpdateIssue`                | **untouched**  | No diff hunk in that function. No double-PUT risk.                                                                          |

---

## 3. Touchpoint regression walk

### 3.1 `useWorkloadEstimateEditor.commit()` — 3 existing callers

The extraction is behaviour-preserving. The removed block and the new helper body are line-for-line equivalent, in the same order, with the same `allowEmpty` semantics. Everything downstream of the parse (`pendingValueRef` dedupe, `setIsSaving`, the `PARENT_HAS_CHILDREN` backstop, `inFlightRef` serialization, `debouncedCommit`) is untouched.

All three pre-existing callers are unchanged files:

| Caller                                                         | Status      |
| -------------------------------------------------------------- | ----------- |
| `issue-layouts/spreadsheet/columns/estimated-hours-column.tsx` | not in diff |
| `issue-detail/sidebar.tsx`                                     | not in diff |
| `peek-overview/properties.tsx`                                 | not in diff |

**No regression.** Unit tests pin the exact empty/negative/finite semantics (11 cases, incl. the two characterization rows) — the risk register's mitigation for this refactor is real and satisfied.

### 3.2 `base.tsx` `handleCreateIssue` — no payload change

Verified by hunk inspection: the diff adds a `else if` warning branch, a `if (!is_draft_issue) { ... updateEstimate ... }` block, and one `setPendingHours("")`. Nothing between `createIssue(...)` and `if (!response) throw new Error()` (`:210`) moved.

### 3.3 Provider coverage — no `usePendingEstimate` throw path

`usePendingEstimate` throws outside its provider (deliberate, per phase-1). Full consumer graph walked:

```
modal.tsx:55            → CreateUpdateIssueModalBase        (the only consumer)
base.tsx:469            → <PendingEstimateProvider>
  ├─ :471 DraftIssueLayout → draft-issue-layout.tsx:138 → IssueFormRoot
  └─ :473 IssueFormRoot
IssueFormRoot (form.tsx:78) → :496 IssueDefaultProperties   (the only consumer)
IssueDefaultProperties      → :208 IssueEstimatedHoursInput (the only consumer)
```

Every route to `usePendingEstimate` passes through the provider. Grepped across `apps/web` (core + ce + ee) and `packages/` — no second consumer of `IssueFormRoot`, `IssueDefaultProperties`, or `CreateUpdateIssueModalBase` exists. **No crash path.**

### 3.4 `CreateModeInput` makes zero network calls — confirmed

`estimated-hours-input.tsx:96–117` (`CreateModeInput`): the only hook is `usePendingEstimate()` (`:100`). No `useWorkload`, no `useWorkloadEstimate`, no `useWorkloadEstimateEditor`, no service import, no `useEffect`. `onChange` is a bare `setPendingHours(e.target.value)`. **Verified by reading the component, not by trusting the header comment.**

---

## 4. Findings

### Critical (must fix)

**None.**

### Important (fix before merge)

**I-1 — `docs/FORK.md`'s "Every edit is fenced" claim is FALSE for `base.tsx`'s 5 renames.**
`docs/FORK.md:284–285` states _"Every edit is fenced with a `The1Studio fork (SP2 workload)` comment"_, and the Rebase-handling paragraph instructs a resolver to _"re-apply the fork block — each is fenced by a ..."_. `7f827bed27` also renames 5 pre-existing shadowed identifiers in `base.tsx` — `addIssueToCycle(cycleId→targetCycleId)`, `addIssueToModule(moduleId→targetModuleId)`, `handleCycleChange(data→issueData)`, `handleModuleChange(data→issueData)`, and the `for (const moduleId→updatedModuleId)` loop. **None of those lines carries a fence.**

The renames are _justified_, not a drive-by — I verified the claim rather than accepting it. `package.json:34` runs `pnpm exec oxlint --fix --deny-warnings` under `lint-staged`, which lints the whole file; oxlint on the pre-change `base.tsx` reports **5 `eslint(no-shadow)` warnings and 0 errors**, so any staged edit to that file is blocked until they clear. The commit body says exactly this.

The defect is the _documentation gap_, and it is load-bearing: `base.tsx` is a declared conflict point, and on a conflict inside `handleCycleChange`/`handleModuleChange` a resolver following FORK.md's fence-keyed procedure sees no fork marker and will take upstream's side — silently reintroducing 5 deny-warnings and blocking the next commit that touches the file.

**Fix (one line):** extend the new `base.tsx` row's _What_ column in `docs/FORK.md` to name the renames, e.g. _"…; also renames 5 pre-existing shadowed identifiers (`cycleId`/`moduleId`/`data` params) that `oxlint --deny-warnings` flags whole-file — these lines are unfenced and must be re-applied on conflict."_

**I-2 — Phase 4 steps 3 and 4 are not done.**
`gh pr list --head feat/work-item-modal-estimated-hours` → `[]` (no PR), so the propagation table phase-4 § 3 requires _"in the PR description"_ does not exist anywhere. `gh issue list --search "turbo run test in:title"` → `[]`, so the separate CI issue phase-4 § 4 requires (wiring `turbo run test` into `frontend-check`) has not been filed. Phase-4's own success criteria list both as blocking; the propagation assessment itself is sound and is recorded in `plan.md` + `phase-4.md`, so this is bookkeeping, not analysis.

_(`CLAUDE.md`'s `workload/` bullet IS extended per phase-4 § 2 — it does not appear in the diff only because `CLAUDE.md` is gitignored by design.)_

### Minor / Suggestions

**M-1 — 5 unused devDependencies added to `packages/workload-ext/package.json`.**
`@testing-library/jest-dom`, `@testing-library/react`, `@testing-library/user-event`, `@vitejs/plugin-react`, `jsdom`. These were copied verbatim from `cascade-ext` per phase-1 § 5 ("the same vitest devDependencies that package declares") — but `cascade-ext` also ships `vitest.config.ts` **and** `vitest.setup.ts`; `workload-ext` ships neither, and its single test is a pure-node unit test with no DOM. Only `vitest` is actually consumed. Proof: `pnpm --filter @plane/workload-ext test` passes 11/11 with no config file present, so nothing wires jsdom or the React plugin. Cost is 123 lines of `pnpm-lock.yaml` churn plus install weight. **Suggest** dropping the four DOM-related entries and keeping `vitest`; if a component test for `PendingEstimate` is planned, add them back _with_ the config that uses them.

**M-2 — `docs/FORK.md` carries unrelated prettier reformatting.** Two tables (the cascade-ext exception table, the fork-owned-paths table) were re-aligned and one markdown escape changed (`plane-*` → `plane-\*`) beyond the four appended rows. Harmless — `FORK.md` is fork-owned and `plane-classify-path.cjs` reads `forkPaths` from `fork-convention.md`, not from this table — but it enlarges the phase-4 diff.

**M-3 — `rollup !== null` diverges cosmetically from both existing call sites.** `sidebar.tsx:223` and `estimated-hours-column.tsx:82` both use truthiness (`rollup ?`). `TWorkloadRollup` is an object type, so the three are behaviourally identical — but plan D10 asserts the spreadsheet uses `!== null`, which it does not. Either form is fine; pick one for all three so a future reader does not go hunting for a difference that is not there.

**M-4 — `max={10000}` is now a bare literal at three call sites.** Spreadsheet cell, sidebar, and now the modal. `code-conventions.md` § "No Duplicated Logic" says extract at the second occurrence; this is the third. Suggest a `MAX_HOURS_INPUT_ATTR` (or similar) exported from `packages/workload-ext` alongside `parseEstimateHoursInput` — note this is only the browser hint, and does not contradict the helper's deliberate no-clamp policy.

**M-5 — `base.tsx:17`'s fence uses a variant string.** `// The1Studio fork (SP2 workload / work-item modal estimated hours)` does not contain the exact literal `The1Studio fork (SP2 workload)` that FORK.md's rebase procedure names (`grep -cF` → 7 exact of 8 loose in `base.tsx`). The file is still discoverable via its other 7 fences, so this is cosmetic. Same variant in `packages/workload-ext/src/estimateInput.ts` and `PendingEstimate.tsx` (exact=0) — irrelevant there, since those live in a fork-owned package with no rebase conflict surface.

**M-6 — `estimateFetchedRef` never resets on an `issueId` change.** `estimated-hours-input.tsx:146–157` is a faithful transcription of `sidebar.tsx:102–112`, ref guard included, so this is inherited rather than introduced. It is currently safe in the modal: `issueId` moving from `undefined`→defined swaps `CreateModeInput` for `UpdateModeInput` (fresh mount), and closing the modal unmounts the subtree. If a future change ever keeps `UpdateModeInput` mounted across two different work items, the second item's estimate is never fetched and the field renders blank for an item that has hours. Cheap hardening: add `estimateFetchedRef.current = false` on `issueId` change, or `key={issueId}` on `UpdateModeInput`.

### Informational (no action)

- **Every keystroke in the create-mode field re-renders the whole modal.** `pendingHours` lives in `CreateUpdateIssueModalBase`, so a keystroke re-renders `IssueFormRoot`/`DraftIssueLayout` (their `observer` memo bails because `commonIssueModalProps` is a fresh object literal each render). This is _forced by phase-1_ ("There is no internal-`useState` variant of this provider; do not add one") and is _pre-existing in shape_ — `handleFormChange` already sets `changesMade` on every keystroke elsewhere in the form. No new regression.
- **No permission/`disabled` gate on the modal's hours input.** The spreadsheet cell has `disabled={disableUserActions || !projectId}`; `sidebar.tsx:233` (the closer precedent) has none, and `default-properties.tsx` gates none of its dropdowns. The new component matches the sidebar/peek precedent; authorization is enforced server-side on the `PUT`. Not a regression, but worth knowing the client offers no defence-in-depth here.
- **Two toasts on the draft path** (draft-not-saved WARNING + draft-created SUCCESS). Intended per D6.
- **Frontend vitest remains ungated in CI.** Known, documented in `plan.md` § Risk and `phase-4` § 4, explicitly out of scope. Tracked by I-2.

---

## 5. Phase "Do not" list — compliance

| Phase | Prohibition                                                                                   | Status                                                                                                                                                    |
| ----- | --------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1     | Enforce `MAX_HOURS` client-side                                                               | **OK** — helper deliberately does not; the `max={10000}` HTML attribute is a browser hint transcribed from the two existing call sites, not a parse clamp |
| 1     | Change debounce interval / Enter-keeps-focus / flush-on-unmount                               | **OK** — only the parse step changed                                                                                                                      |
| 1     | Put `PendingEstimate` in `apps/web/core/`                                                     | **OK** — `packages/workload-ext/src/PendingEstimate.tsx`                                                                                                  |
| 2     | Add field to `TIssue` / `DEFAULT_WORK_ITEM_FORM_VALUES` / `@plane/types` / `@plane/constants` | **OK** — none in diff                                                                                                                                     |
| 2     | Wire `isSaving` to `disabled`                                                                 | **OK** — not wired; the warning comment is carried at `:179–181`                                                                                          |
| 2     | Add `estimated_hours` to `ETabIndices`                                                        | **OK** — reuses `getIndex("estimate_point")`                                                                                                              |
| 2     | Any create-mode network call                                                                  | **OK** — `CreateModeInput` calls one hook, `usePendingEstimate`                                                                                           |
| 2     | Touch `form.tsx` / `base.tsx` / layout files _in phase 2_                                     | **OK** — `a5fe19974d` (phase 2) touches only the 3 owned paths; `base.tsx` lands in `7f827bed27` (phase 3)                                                |
| 3     | Add hours to the `createIssue` payload                                                        | **OK** — payload untouched                                                                                                                                |
| 3     | Make the create `await` fail on an estimate error                                             | **OK** — non-rethrowing catch                                                                                                                             |
| 3     | Reset pending hours inside `IssueFormRoot`'s `reset(...)`                                     | **OK** — `form.tsx` not in diff                                                                                                                           |
| 3     | Touch `handleUpdateIssue`                                                                     | **OK** — untouched                                                                                                                                        |

**Zero "Do not" violations.**

---

## 6. Verification actually run (not asserted)

| Check                                                      | Result                                            |
| ---------------------------------------------------------- | ------------------------------------------------- |
| `pnpm --filter @plane/workload-ext test`                   | **11 passed / 11**                                |
| `pnpm --filter @plane/workload-ext check:types`            | clean                                             |
| `pnpm --filter web check:types`                            | exit 0                                            |
| `oxlint --deny-warnings` on all 5 changed web files        | 0 warnings, 0 errors                              |
| `oxlint --deny-warnings` on **pre-change** `base.tsx`      | **5 warnings** — proves I-1's renames were forced |
| `grep -n "trim()" use-workload-estimate-editor.ts`         | no matches — D9 SSOT proof                        |
| `grep -cF "The1Studio fork (SP2 workload)"` × 4 core files | 1 / 2 / 1 / 7 — all present (see M-5)             |
| `git diff --name-status` for `apps/api/`                   | none — frontend-only confirmed                    |

Not run: `pnpm turbo run build --filter=web` (SSR prerender) and the 7 manual browser checks in `plan.md` § Verification. Those remain owed before merge.

---

## 7. Security review (OWASP-relevant subset)

Frontend-only diff, no new endpoint, no new auth surface.

- **Injection** — n/a; no query construction, no `dangerouslySetInnerHTML`. `formatRollupTooltip(rollup)` lands in a `title` attribute, React-escaped.
- **Broken access control** — no client-side gate added or removed; the `PUT` reuses the existing `WorkloadEstimate` endpoint, which enforces authorization server-side. See the Informational note on the missing `disabled` gate (matches existing precedent).
- **Sensitive data exposure** — no secrets, no PII, no logging added. The two `catch {}` blocks swallow deliberately and surface a user-visible toast (the create path) or are documented as expected-empty (the fetch effect) — not silent failure hiding a bug.
- **Insufficient logging** — the estimate-failure path raises a named error toast rather than failing silently; acceptable.
- **Vulnerable components** — 5 new devDependencies (M-1); all dev-only, all already present in the lockfile via `cascade-ext`, none reaching the runtime bundle.

No security findings.

---

## Score: 8 / 10

Faithful to every one of the 11 decisions, all four phase "Do not" lists honoured, byte-equivalent refactor of the shared hook with tests written against current behaviour, no crash path, no public-contract drift, no backend surface. Deductions: `docs/FORK.md` makes a fence claim its own diff falsifies (I-1), phase 4's PR-description and CI-issue obligations are outstanding (I-2), and five inert devDependencies plus their lockfile churn ship for no benefit (M-1).

# Phase 1 — `views_ext` Django app: grouped workspace-issues endpoint

**Goal:** Expose `GET /api/views-ext/workspaces/<slug>/issues/` — the workspace-view issue list
with server-side `group_by` / `sub_group_by` / date-range support, so Board, grouped List and
Calendar have data to render. **Zero core Python edits.**

**Contract:** [`plan.md`](plan.md) § Contract — pinned, authoritative. Do not restate or diverge.
**Effort:** M (~3d) · **Blocks:** Phase 2 consumes this at runtime (but may build against the contract in parallel).

---

## Why a new app rather than extending core

`apps/api/plane/app/views/view/base.py` classifies as `core` under
`.claude/scripts/plane-classify-path.cjs` → editing it is a `plane-isolation-audit` violation and
conflicts on every monthly upstream rebase. `docs/FORK.md` § Isolation convention mandates new
Django apps for new backend behaviour. Decision D2 in [`plan.md`](plan.md).

## The template to copy

`apps/api/plane/app/views/workspace/user.py` → `WorkspaceUserProfileIssuesEndpoint`, lines
**~150-260**. It is the _only_ existing endpoint that does cross-project grouped pagination at
workspace scope, which is exactly this endpoint's job. Read it in full before writing anything.

Combine two existing sources — do not invent a third pattern:

| Take from                                                                    | What                                                                                                                                                   |
| ---------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `WorkspaceViewIssuesViewSet` (`app/views/view/base.py:138-250`)              | `_get_project_permission_filters()`, `apply_annotations()`, the `IssueFilterSet` + `ComplexFilterBackend` wiring, `issue_filters()` legacy-filter call |
| `WorkspaceUserProfileIssuesEndpoint` (`app/views/workspace/user.py:150-260`) | The `group_by` / `sub_group_by` branching and the four `self.paginate(...)` call shapes                                                                |

Both already import the shared helper trio — reuse, never reimplement:
`issue_queryset_grouper`, `issue_group_values`, `issue_on_results`.

## Files owned by this phase

```
apps/api/plane/views_ext/__init__.py
apps/api/plane/views_ext/apps.py
apps/api/plane/views_ext/urls.py
apps/api/plane/views_ext/views.py
apps/api/plane/views_ext/tests/__init__.py
apps/api/plane/views_ext/tests/test_grouped_view_issues.py
```

Touch-point appends (append-only, one line each):

```
apps/api/plane/settings/common.py        # touch-point 1 — "plane.views_ext",
apps/api/plane/urls.py                   # touch-point 2 — path("api/views-ext/", include("plane.views_ext.urls")),
.claude/skills/_shared/references/fork-convention.md   # add "views_ext" to the forkApps JSON array
```

**No `models.py`, no `migrations/`.** This app is read-only — it adds no tables and no columns.
`makemigrations --check --dry-run` must stay clean; if it does not, something was added that D2
forbids.

## `forkApps` registration — required, two consequences

Add `"views_ext"` to the `forkApps` array in the fenced JSON block of
`.claude/skills/_shared/references/fork-convention.md`. Per that file's own § Fork-owned
customizations, `forkApps` drives **two** things:

1. `plane-classify-path.cjs` — without it, every file in the app classifies as `core` and the
   isolation audit fails the whole PR.
2. `.claude/scripts/plane-fork-test-paths.py`, which `company-main-ci.yml` uses to select pytest
   paths — without it, this phase's tests **never run in CI** and go green by not existing.

Do not treat this as bookkeeping. Verify both after the edit (see success criteria).

## `group_by` value mapping

The contract's accepted values are server field paths. They must match what the frontend's
`EIssueGroupByToServerOptions` already emits — check that enum in `packages/types` rather than
assuming, and pin the four mappings in a module-level dict in `views.py`:

| UI concept (D3) | Server value   |
| --------------- | -------------- |
| State group     | `state__group` |
| Priority        | `priority`     |
| Project         | `project_id`   |
| Labels          | `labels__id`   |

Anything else ⇒ `400` with a message naming the accepted set. **Never** silently fall back to a
flat list — a Board that quietly renders one column looks like a data problem, not a bad param
(`rules/development-principles.md` § Errors Over Silent Fallbacks).

`state` (individual), `cycle` and `module` are deliberately excluded — they are per-project and
produce ~40 near-duplicate columns across a 12-project workspace. This is decision D3, not an
oversight; note it in a comment so the next reader does not "fix" it.

## Permissions — do not weaken

Carry `_get_project_permission_filters()` across **verbatim**. It enforces the guest-role rules
(`role=5` + `guest_view_all_features`) that keep a guest from seeing work items they should not.
A grouped endpoint that skips it leaks issue titles through group counts even when the rows are
filtered. Re-read it before adapting; do not "simplify".

## Success criteria

- [ ] `GET /api/views-ext/workspaces/<slug>/issues/` with no `group_by` returns a response
      shape-identical to the existing `/api/workspaces/<slug>/issues/`
- [ ] `?group_by=priority` returns `results` as a dict keyed by priority, with `grouped_by: "priority"`
- [ ] `?group_by=state__group&sub_group_by=project_id` returns the sub-grouped shape
- [ ] `?before=&after=` narrows by target date (Phase 4 depends on this; implement it now)
- [ ] `?group_by=bogus` returns `400`, not a flat list
- [ ] A guest with `guest_view_all_features=False` sees only their own created items — verified by test, not by reading the filter
- [ ] `python manage.py check` clean
- [ ] `python manage.py makemigrations --check --dry-run` clean (**no** migrations expected)
- [ ] `node .claude/scripts/plane-classify-path.cjs apps/api/plane/views_ext/views.py` reports `custom-app`
- [ ] `python .claude/scripts/plane-fork-test-paths.py` output includes the `views_ext` test path
- [ ] `plane-isolation-audit` on the working tree: PASS

## Risks

| Risk                                                         | L   | I   | Score | Mitigation                                                                                  |
| ------------------------------------------------------------ | --- | --- | ----- | ------------------------------------------------------------------------------------------- |
| `forkApps` edit forgotten → misclassified + untested         | 3   | 4   | 12    | Two explicit success criteria above, one per consequence                                    |
| Permission filter subtly weakened while adapting             | 2   | 5   | 10    | Copy verbatim; guest test is a success criterion                                            |
| Grouped query slow across 12 projects / 468+ items           | 3   | 3   | 9     | Reuse the profile endpoint's annotate + prefetch chain unchanged; measure before optimising |
| `EIssueGroupByToServerOptions` values differ from assumption | 2   | 3   | 6     | Read the enum; do not assume the table above                                                |

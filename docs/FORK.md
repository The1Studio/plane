# Fork Governance — The1Studio / company-main

This document is the single source of truth for how The1Studio governs its private fork of
[Plane CE](https://github.com/makeplane/plane). Read it in full before making any change to
`company-main` or a feature branch derived from it.

---

## Branch model

| Branch                | Purpose                                              | Derived from                      |
| --------------------- | ---------------------------------------------------- | --------------------------------- |
| `company-main`        | Production branch — the only branch deployed         | upstream **tags** (e.g. `v1.3.1`) |
| `sp1/clickup-migrate` | One-time ClickUp → Plane ETL                         | branches from `company-main`      |
| `sp2/ai-ext`          | AI feature suite (BGE-M3 embeddings, Claude tooling) | branches from `company-main`      |
| `preview`, `master`   | Upstream tracking branches — **untouched**           | never deployed, never edited      |

**Rules:**

- `company-main` is derived from an upstream **tag**, never from `preview` or `master`.
  Production deploys from a tag-derived SHA on `company-main`; no deploy pulls from an
  untagged tip.
- Feature branches (`sp1/clickup-migrate`, `sp2/ai-ext`) branch FROM `company-main`. They are
  never merged directly to `company-main` — instead, changes ride the rebase cycle below.
- When upstream ships a new tag, the monthly rebase is performed on `company-main` (see
  "Rebase-on-tags workflow" below). The result is tagged `company-vX.Y.Z-N` before
  any deploy.

---

## Rebase-on-tags workflow (the monthly survival recipe)

Upstream Plane CE releases approximately monthly (`v1.2.0` Dec 2025 → `v1.3.1` May 2026).
We adopt **selected tags** — not every tag — when the diff is clean and staging smoke passes.
Never rebase onto `preview`/`master` (moving targets that carry unfinished work).

```bash
# 1. Fetch latest upstream tags
git fetch upstream --tags

# 2. Identify the tag to adopt (e.g. v1.4.0)
git tag -l 'v*' | sort -V | tail -10

# 3. Switch to company-main
git checkout company-main

# 4. Rebase onto the new tag
git rebase v1.4.0

# 5. Resolve conflicts — ONLY in the documented touch-points (see §Isolation convention)
#    A conflict OUTSIDE touch-points 1–7 means custom code leaked into core → STOP.
#    See §Conflict recovery + abort path.

# 6. Rebuild and type-check
pnpm install
pnpm check

# 7. Staging: migrate + smoke
#    docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm migrator
#    Run the Phase-5 smoke checklist against the staging stack.

# 8. Tag the result
git tag company-v1.4.0-1   # increment N for re-rebases on the same upstream tag
git push origin company-main --tags
```

**Cadence recommendation:** rebase monthly or when a tag fixes a security issue. Do not skip
more than two upstream tags in a row — the conflict surface grows quickly beyond two monthly
tags.

---

## `git rerere` — auto-replay of repeated conflict resolutions

`git rerere` (Reuse Recorded Resolution) records how you resolved a conflict the first time
and automatically replays that resolution on subsequent rebases. This is the single
highest-leverage tool for fork survival across repeated monthly rebases.

It is **already enabled** on this repo:

```bash
git config rerere.enabled true
git config rerere.autoupdate true
```

How it works: the first time you resolve a conflict in a touch-point file, `git rerere`
records the resolution under `.git/rr-cache/`. On the next rebase, if the same conflict
hunk appears, it is replayed automatically without manual intervention.

**Implication:** after you resolve a touch-point conflict correctly once, every subsequent
monthly rebase on that same touch-point is automatic — no human needed unless upstream
changed the surrounding context significantly. Keep your `.git/rr-cache/` intact; do not
prune it.

---

## Conflict recovery + abort path

When `git rebase <tag>` produces conflicts:

1. **Identify the conflicting file.** Run `git diff --name-only --diff-filter=U` to list
   unresolved files.

2. **If the conflict is in a documented touch-point (1–7 below):** resolve it using the
   rebase-safe approach for that touch-point (see §Isolation convention touch-point table).
   After resolving: `git add <file>` then `git rebase --continue`.

3. **If a touch-point file was renamed or deleted upstream:** STOP. Do not force-resolve.
   Run `git rebase --abort` to restore `company-main` to its pre-rebase state, then
   re-home the customization into the new location upstream chose. This is normal — upstream
   refactors occasionally move files; track-and-relocate is correct; force-resolving against
   a deleted file is not.

4. **If a conflict appears OUTSIDE touch-points 1–7:** this means custom code leaked into
   a core file. Run `git rebase --abort`, locate the out-of-bounds edit, and relocate it
   into a new app/package. Do not resolve-and-continue — the leak will compound with every
   future rebase.

5. **Abort path at any time:**
   ```bash
   git rebase --abort   # restores company-main to its pre-rebase state
   ```
   The abort is safe. No committed history is lost. Diagnose, fix the convention violation,
   then rebase again from step 1.

Per-touch-point recovery notes:

| Touch-point                                            | Conflict likely cause                                                    | Recovery                                                                                           |
| ------------------------------------------------------ | ------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------- |
| 1 — `INSTALLED_APPS`                                   | Upstream added/removed an app in the same block                          | Re-apply our appended lines after the upstream change                                              |
| 2 — `urlpatterns`                                      | Upstream added/restructured url includes                                 | Re-apply our `path("api/ai-ext/", ...)` after upstream's block                                     |
| 3 — `beat_schedule`                                    | Already zero-edit; no conflict expected                                  | If upstream refactored `celery.py` heavily, check autodiscover still applies                       |
| 4 — `base.py` LLM                                      | Claude/Anthropic section was already in-place edited                     | Reapply the `base_url` line + the model-id list if upstream overwrote it                           |
| 5 — `requirements`                                     | Upstream bumped or removed a dep we pinned                               | Re-pin our dep; check for compatibility                                                            |
| 6 — `extended.ts`                                      | Upstream added structure around the empty array                          | Re-append our route entries to the array in its new form                                           |
| 7 — `root.tsx` / `Dockerfile.web` / `Dockerfile.admin` | Upstream changed the title constant/meta or the Dockerfile ARG/ENV block | Re-apply the `process.env.VITE_APP_TITLE \|\|` fallback prefix; empty default keeps upstream title |

---

## Secret hygiene

### The situation (critical — read before taking any action)

The tracked files `deployments/aio/community/variables.env` and
`deployments/cli/community/variables.env` contain values such as:

```
SECRET_KEY=60gp0byfz2…
LIVE_SERVER_SECRET_KEY=…
POSTGRES_PASSWORD=plane
AWS_SECRET_ACCESS_KEY=secret-key
```

These are **upstream public defaults** — they are identical in every public Plane CE clone,
published openly in the makeplane/plane GitHub repository, and **none of them are The1Studio
credentials**. There is nothing to scrub from history and no leak to remediate; these values
were never ours.

### The actual risk — and the only mitigation that matters

If any of these defaults reaches a production deployment, the consequences are severe:

- `SECRET_KEY` default → every session token is forgeable by anyone who knows the default
- `POSTGRES_PASSWORD=plane` → database accessible to anyone guessing the default
- `AWS_SECRET_ACCESS_KEY=secret-key` → MinIO/S3 authentication trivially bypassed

**The only correct mitigation:** always generate fresh secrets at deploy time. Never let a
default reach production. Fresh secrets are generated during the Phase 3 deploy setup
(see `plane-deploy/docs/secrets.md` and `plane-deploy/.env.template`).

### Audit command

To confirm no committed default is wired into the production deploy:

```bash
git grep -iE 'SECRET_KEY|PASSWORD|ACCESS_KEY|TOKEN' $(git ls-files)
```

Every hit should be either: (a) the upstream `variables.env` defaults — known public, not
ours, and not wired into `docker-compose.prod.yml`; or (b) a placeholder (`=your-value-here`,
`=change-me`) in a `.env.example` or template file.

### When history scrub would apply

`git filter-repo` + credential rotation would only be warranted if a **genuine The1Studio
secret** (an actual API key, OAuth client secret, or production DB password) were committed to
this repository. **That has not happened.** If it ever does: (1) rotate the credential
immediately, (2) then scrub history.

---

## Isolation convention (Phase 2 — LOAD-BEARING)

This section codifies the rule that makes rebases survivable. Every SP1 and SP2 customization
MUST follow it. Non-conformance will cause rebase conflicts outside the documented touch-points,
which is the mechanical signal that the rule was violated.

### Backend customizations — NEW Django apps only

New backend code lives in **new Django apps**:

- `apps/api/plane/ai_ext/` — SP2 AI feature suite (embeddings, Claude tooling, AI digest tasks)
- `apps/api/plane/clickup_migrate/` — SP1 ClickUp → Plane ETL
- `apps/api/plane/workload/` — per-issue time estimates (`WorkloadEstimate`) plus
  **workspace-wide work settings** (`WorkloadSettings`: max weekly hours, workdays, week
  start day); powers the spreadsheet/peek/sidebar hours columns, the workspace admin-only
  Work Settings page (`/:workspaceSlug/settings/workload`), and the per-member Workload
  timeline (`/:workspaceSlug/workload`, see § "Workload timeline & workspace-wide work
  settings" below). `WorkloadCapacity` (per-member capacity) was **removed** —
  `migrations/0004_seed_workload_settings_from_capacity.py` +
  `0005_delete_workloadcapacity.py`; the grain is workspace-only from `company-v1.3.1-*`
  onward.
- `apps/api/plane/github_ext/` — GitHub ↔ Plane dev-workflow links (`WorkItemGithubLink`) and
  PR-driven status automation (`StateTransitionConfig`, webhook ingest)
- `apps/api/plane/project_ext/` — project visibility (`network`) over the public API (the core
  `/api/v1/` serializer omits the field, so it is unreachable without this app); plus a
  workspace-admin all-projects list and a workspace-scoped bulk project-member-add endpoint.
  Core's public-API project list only returns projects the caller is a project _member_ of, and
  core's project-member endpoints are gated at _project_ level — a user who is not already in a
  project cannot add anyone to it, including themselves, so a workspace ADMIN has no
  workspace-level path to grant themselves access to a private project they administer. These
  two endpoints are that bootstrap path.
- `apps/api/plane/workspace_ext/` — workspace discovery over the public API
  (`GET /api/v1/users/me/workspaces/`). Every workspace-scoped route takes the slug as a path
  segment, but no core `/api/v1/` route returns the slugs a caller can access, so an API-key
  client cannot bootstrap itself. Guessing does not work either: an unknown slug and a real
  workspace the caller lacks access to both answer `403` with byte-identical bodies. Core's
  `plane.api.views.user` / `plane.api.urls.user` are not touch-points, so the endpoint lives
  here. Returns only workspaces the caller is an _active_ member of. Model-less (read-only over
  core models), so it ships no `migrations/`.
- `apps/api/plane/views_ext/` — grouped/paginated workspace-issues endpoint
  (`GET /api/views-ext/workspaces/<slug>/issues/`) powering the workspace Views tab's multi-layout
  switcher (see § "Views multi-layout switcher" above), plus a second endpoint on the same app
  (`GET /api/views-ext/workspaces/<slug>/user-issues/<user_id>/`) powering the "Your work" profile
  pages' multi-layout switcher (see § "Profile pages multi-layout switcher" below)

Each app is **self-contained**:

- Its own `migrations/` directory. **Never edit `plane/db/migrations/`.**
- Its own `apps.py`, `urls.py`, `tasks.py`, `models.py` as needed.
- Registered via touch-point 1 (one appended line in `INSTALLED_APPS`) and touch-point 2
  (one appended `path(...)` in `urlpatterns`).

Cross-app FK dependencies must pin to a `db` migration name that exists in the **currently
adopted upstream tag**. Re-run `python manage.py makemigrations --check` after every rebase
(the CI gate in `company-main-ci.yml` enforces this).

**DB rule:** no new columns on core models. The core models (`Issue`, `Page`, `Module`,
`State`, `Intake`, `Asset`) already carry `external_source` and `external_id` fields —
these are sufficient for SP1 idempotency (import tracking). New tables (pgvector embeddings,
migration-log tables) live in the new apps.

### Frontend customizations — NEW packages only

New frontend code lives in **new packages** under `packages/`:

- `packages/ai-ext/` — SP2 AI UI components

Packages are consumed from the app workspaces with `workspace:*` version specifiers.
**Never edit `@plane/*` packages in place.** The designed seam for mounting new UI routes is
touch-point 6 (see table below).

### Frontend core-edit exceptions (no upstream seam)

`extendedRoutes` (touch-point 6) only mounts whole **pages**. Upstream Plane has **no plugin
slot** for injecting a single property row into the issue-detail sidebar, nor for adding an
item to the workspace nav menu (the nav arrays live in the sealed `@plane/constants` package,
which we must not edit in place), nor for adding a column to the list/spreadsheet grid (the
column registry is typed to `keyof IIssueDisplayProperties` in `@plane/types`/`@plane/constants`).
The SP2 workload feature therefore carries a set of **minimal, clearly-marked in-place edits**
to core web components. Each is the documented exception for its integration point. Every edit
is fenced with a `The1Studio fork (SP2 workload)` comment.

| File                                                                                                 | What                                                                                                                                                                                                 | Why no seam                                                                                |
| ---------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| `apps/web/core/components/issues/issue-detail/sidebar.tsx`                                           | "Estimated hours" property field (now reads/writes via the shared workload store); also renders the Progress bar (§`workload-progress.md`) alongside it. Positioned next to the Start/Due date rows. | No upstream API to add an issue-property row; must render inside the core properties list  |
| `apps/web/core/components/issues/peek-overview/properties.tsx`                                       | "Estimated hours" property field in the peek/quick-view (reads/writes the shared workload store), placed next to the Start/Due date rows — mirrors the sidebar field                                 | Peek renders its own core property list; no upstream seam to inject an issue-property row  |
| `apps/web/core/components/workspace/sidebar/sidebar-menu-items.tsx`                                  | "Workload" nav link → `/:workspaceSlug/workload`                                                                                                                                                     | Nav items come from `@plane/constants` (sealed package, no edit-in-place)                  |
| `apps/web/core/hooks/store/use-workload-estimate.ts` (NEW)                                           | `useWorkloadEstimate` + `useBulkWorkloadFetch` selector hooks                                                                                                                                        | Package hooks are context-agnostic; selector hooks must read core's `useWorkload()`        |
| `apps/web/core/components/issues/issue-layouts/spreadsheet/columns/estimated-hours-column.tsx` (NEW) | Editable "Estimated hours" grid column (header + body cell)                                                                                                                                          | New file; the column is appended, not registered in the sealed column registry             |
| `apps/web/core/components/issues/issue-layouts/spreadsheet/columns/progress-column.tsx` (NEW)        | Fixed "Progress" grid column (header + body), appended after the Estimated-hours column                                                                                                              | New file; the column is appended, not registered in the sealed column registry             |
| `apps/web/core/components/issues/issue-layouts/spreadsheet/spreadsheet-header.tsx`                   | Appends the fixed `<th>`s after the property loop — Estimated hours, then Progress                                                                                                                   | No registry seam for an always-on column without a `keyof IIssueDisplayProperties` key     |
| `apps/web/core/components/issues/issue-layouts/spreadsheet/issue-row.tsx`                            | Appends the fixed `<td>`s in `IssueRowDetails` — Estimated hours, then Progress                                                                                                                      | Same — body half of the appended columns                                                   |
| `apps/web/core/components/issues/issue-layouts/spreadsheet/spreadsheet-table.tsx`                    | Hosts the page-level `useBulkWorkloadFetch`                                                                                                                                                          | Needs the full visible `issueIds` to warm the store in one request                         |
| `apps/web/ce/components/issues/issue-layouts/additional-properties.tsx`                              | Inline hours pill + Progress pill (list + kanban)                                                                                                                                                    | The `ce/` stub seam (`WorkItemLayoutAdditionalProperties`) is the intended injection point |
| `apps/web/core/components/issues/issue-layouts/list/blocks-list.tsx`                                 | `useBulkWorkloadFetch` warm-up for list groups                                                                                                                                                       | Pill reads the store; the list view must warm it for visible ids                           |
| `apps/web/core/components/issues/issue-layouts/kanban/blocks-list.tsx`                               | `useBulkWorkloadFetch` warm-up for kanban groups                                                                                                                                                     | Same; the kanban pill is accepted in-scope and shares the seam                             |

**Rebase handling:** these files ARE expected conflict points (unlike the abort-on-conflict
rule for everything else). On conflict, re-apply the fork block — each is fenced by a
`The1Studio fork (SP2 workload)` comment — and keep upstream's changes around it. Do NOT abort
the rebase for a conflict confined to this set. Keep each edit as small as possible so the
conflict surface stays trivial.

**`plane-isolation-audit` note:** `packages/workload-ext` uses the `@plane/` npm scope but is
**fork-owned** (not upstream) — editing it is NOT an `@plane/*` violation. Allowlist
`@plane/workload-ext` in the isolation audit so it isn't false-flagged as a sealed-package edit.

### Views multi-layout switcher (workspace Views tab) — fenced `The1Studio fork (views-layouts)`

Adds the List / Board / Calendar / Spreadsheet / Timeline layout switcher to the workspace
**Views** tab (`/:workspaceSlug/workspace-views/:globalViewId`), matching the project Work Items
tab. Backend: new `views_ext` Django app (§ Backend customizations above). Frontend: new
`packages/views-ext/` package (own subsection below) plus a small set of fenced core delegations —
the same "no upstream seam" pattern as the SP2 workload table above, minimised to
`@plane/views-ext` delegations rather than inline fork logic (`docs/FORK.md` core-edit
minimisation rule).

| File                                                                                                                                                                              | What                                                                                                                                                                                                                           | Why no seam                                                                                                                                                                                                                                                                                                                                            |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `apps/web/ce/components/views/helper.tsx`                                                                                                                                         | `GlobalViewLayoutSelection` + `WorkspaceAdditionalLayouts` delegate to `@plane/views-ext` / the new layout roots, replacing the upstream `<></>` stub bodies                                                                   | The `ce/` stub seam — the intended injection point, same class as `additional-properties.tsx` (SP2 workload row above)                                                                                                                                                                                                                                 |
| `apps/web/core/store/issue/workspace/filter.store.ts`                                                                                                                             | `getAppliedFilters` now calls the fork-owned `getGlobalViewQueryParamsByLayout(userFilters?.displayFilters?.layout)` instead of a param builder hardcoded to `SPREADSHEET`/`"my_issues"`                                       | No seam; every sibling store (cycle, module, archived, profile) already derives params from the active layout — upstream never made the global one dynamic                                                                                                                                                                                             |
| `apps/web/core/services/workspace.service.ts`                                                                                                                                     | `getViewIssues` routes global-view issue fetches to `/api/views-ext/workspaces/<slug>/issues/` instead of the ungrouped core `/api/workspaces/<slug>/issues/`                                                                  | No service-layer override point; the core endpoint has no `group_by` support                                                                                                                                                                                                                                                                           |
| `apps/web/core/components/issues/issue-layouts/list/base-list-root.tsx`                                                                                                           | `+ EIssuesStoreType.GLOBAL` in `ListStoreType`                                                                                                                                                                                 | Sealed union type; admitting a sibling of the existing `PROFILE` member (also workspace-level, cross-project)                                                                                                                                                                                                                                          |
| `apps/web/core/components/issues/issue-layouts/kanban/base-kanban-root.tsx`                                                                                                       | `+ EIssuesStoreType.GLOBAL` in `KanbanStoreType`                                                                                                                                                                               | Same                                                                                                                                                                                                                                                                                                                                                   |
| `apps/web/core/store/issue/workspace/issue.store.ts`                                                                                                                              | `WorkspaceIssues.viewFlags.enableIssueCreation` flipped `true` → `false`                                                                                                                                                       | Upstream wired the quick-add button to an `undefined` callback (`useWorkspaceIssueActions` supplies no `quickAddIssue`) — no crash, no type error, it silently did nothing. A workspace-wide view also has no unambiguous target project, so suppressing the button is the correct fix, not a workaround                                               |
| `apps/web/core/hooks/use-group-dragndrop.ts`                                                                                                                                      | `+ EIssuesStoreType.GLOBAL` in the local `DNDStoreType` union                                                                                                                                                                  | Only surfaced when `tsc` failed after the two `ListStoreType`/`KanbanStoreType` widenings above propagated here — not discoverable by reading. Safe: the hook takes `projectId` per-issue rather than from the route, and the global view's group-by set excludes cycle/module, so those branches are unreachable for `GLOBAL`                         |
| `apps/web/core/components/issues/issue-layouts/list/roots/workspace-root.tsx` (NEW)                                                                                               | `WorkspaceListRoot` — GLOBAL-store List root, sibling of the existing `WorkspaceSpreadsheetRoot`                                                                                                                               | New file; no upstream equivalent for a cross-project List layout exists to conflict with                                                                                                                                                                                                                                                               |
| `apps/web/core/components/issues/issue-layouts/kanban/roots/workspace-root.tsx` (NEW)                                                                                             | `WorkspaceKanBanRoot` — GLOBAL-store Board root, same pattern as the List root above                                                                                                                                           | Same                                                                                                                                                                                                                                                                                                                                                   |
| `apps/web/core/components/issues/issue-layouts/calendar/base-calendar-root.tsx`                                                                                                   | `+ EIssuesStoreType.GLOBAL` in `CalendarStoreType`, plus a comment recording the quick-add coupling (below)                                                                                                                    | Sealed union type. Unlike List/Board this union did NOT already contain `PROFILE` — no workspace-level Calendar had ever existed upstream                                                                                                                                                                                                              |
| `apps/web/core/components/issues/issue-layouts/calendar/calendar.tsx`                                                                                                             | `+ IWorkspaceIssuesFilter` in the `issuesFilterStore` prop union                                                                                                                                                               | Sealed prop type. Verified safe before widening: this subtree only ever reads `issuesFilterStore.issueFilters?.displayFilters?.calendar?.…`, always optional-chained — the `mutateFilters`/`resetFilters` that `IWorkspaceIssuesFilter` lacks are never called here                                                                                    |
| `.../calendar/header.tsx`, `.../calendar/day-tile.tsx`, `.../calendar/week-days.tsx`, `.../calendar/dropdowns/months-dropdown.tsx`, `.../calendar/dropdowns/options-dropdown.tsx` | Same one-line `+ IWorkspaceIssuesFilter` prop-union widening, 5 files                                                                                                                                                          | The prop is forwarded down the whole calendar chain, so the union must widen at every hop. Each was read before widening and confirmed identical to `calendar.tsx` above. Type-only — zero logic changed across all five                                                                                                                               |
| `apps/web/core/components/issues/issue-layouts/calendar/roots/workspace-root.tsx` (NEW)                                                                                           | `WorkspaceCalendarRoot` — GLOBAL-store Calendar root                                                                                                                                                                           | New file; same pattern as the List/Board roots above                                                                                                                                                                                                                                                                                                   |
| `apps/web/core/components/issues/issue-layouts/gantt/base-gantt-root.tsx`                                                                                                         | `+ EIssuesStoreType.GLOBAL` in `GanttStoreType`, and the **B3 fix**: `updateBlockDates` branches on the GLOBAL store to resolve each dragged item's own `project_id` from `issueMap` and route through per-issue `updateIssue` | Sealed union + a genuine API-shape mismatch: `updateIssueDates` takes ONE project id for a batch, and it was reading a route `:projectId` that `/workspace-views/:globalViewId` does not have — it threw on the first bar drag. A workspace-wide timeline spans many projects, so no single value is correct. Non-GLOBAL stores fall through unchanged |
| `apps/web/core/components/issues/issue-layouts/gantt/roots/workspace-root.tsx` (NEW)                                                                                              | `WorkspaceGanttRoot` — GLOBAL-store Timeline root (`gantt/roots/` created by this feature)                                                                                                                                     | New file; no upstream equivalent                                                                                                                                                                                                                                                                                                                       |

**Quick-add coupling — read before touching either side.** `calendar/quick-add-issue-actions.tsx:82`
returns `null` without a route `:projectId`, which there is none of on `/workspace-views/`. That is
what keeps Calendar safe — **not** `WorkspaceIssues.viewFlags.enableIssueCreation: false`, because
`calendar.tsx:112-114` reads `viewFlags` from a hardcoded `useIssues(EIssuesStoreType.PROJECT)`
rather than the active store, so that flag never reaches the gate at `calendar.tsx:183`. Quick-add
DOES mount for `GLOBAL` and renders nothing solely because of the null guard. Timeline is different:
its gate reads the real flag, so the flag IS what protects it there. Anyone changing either
mechanism should re-check the other.

**Rebase handling:** these files ARE expected conflict points (unlike the abort-on-conflict rule
for everything else). On conflict, re-apply the fork block — each is fenced by a
`The1Studio fork (views-layouts)` comment — and keep upstream's changes around it. Do NOT abort
the rebase for a conflict confined to this set. The two `(NEW)` root files carry near-zero
rebase-conflict surface (no upstream file to collide with); the reserved Calendar/Timeline rows
above will gain the same treatment once Phases 4/5 land — do not delete this placeholder note in
the interim, and do not abort a rebase over a conflict in those two files either once they exist.

**`plane-isolation-audit` / fork-ownership note:** `packages/views-ext` uses the `@plane/` npm
scope but is **fork-owned** (not upstream) — same clarification as `@plane/workload-ext` above.
Allowlist `@plane/views-ext` so it isn't false-flagged as a sealed-package edit.

**Why `packages/views-ext` carries its own layout-options table:** `@plane/constants`'
`ISSUE_DISPLAY_FILTERS_BY_PAGE.my_issues.layoutOptions` only defines `spreadsheet` and `list` (no
`kanban`/`calendar`/`gantt_chart` entries), and `@plane/*` is sealed — this repo never edits it in
place. `packages/views-ext/src/layout-options.ts` is the fork-owned replacement covering all 5
layouts for the Views tab specifically, modelled on upstream's own `profile_issues` entry (also a
workspace-level, cross-project view). This is a **deliberate, documented duplicate**, not
accidental drift — do not "consolidate" it back into `@plane/constants` without first re-opening
the isolation question it was created to avoid.

### Profile pages multi-layout switcher ("Your work" tabs) — fenced `The1Studio fork (profile-layouts)`

The direct follow-up to the Views tab switcher above: the same List / Board / Calendar /
Spreadsheet / Timeline switcher, now on the **profile** "Your work" pages
(`/:workspaceSlug/profile/:userId/{assigned,created,subscribed}`), which previously offered only
List and Board. Backend: one new endpoint on the _existing_ `views_ext` Django app — no new app,
no touch-point edit (see § Backend customizations above). Frontend: `packages/views-ext/` grows a
`PROFILE_VIEW_*` export set alongside the `GLOBAL_VIEW_*` one (own subsection below) plus a small
set of fenced core edits — same "no upstream seam" pattern as the SP2 workload and Views tables
above.

| File                                                                                                                                                              | What                                                                                                                                                                                                                                                            | Why no seam                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `apps/web/core/components/profile/profile-issues.tsx`                                                                                                             | Hardcoded List/Board ternary replaced by a 5-way `ProfileActiveLayout` dispatcher covering every `EIssueLayoutTypes` value; an unhandled layout renders `null` rather than throwing                                                                             | No `ce/` stub seam exists for the profile page's active-layout switch (unlike the Views tab, which routes through `ce/components/views/helper.tsx`) — the switch is inline in the core page component                                                                                                                                                                                                                                                                                                                                                                      |
| `apps/web/core/components/profile/profile-issues-filter.tsx`                                                                                                      | Switcher's `LayoutSelection` now reads `PROFILE_VIEW_LAYOUTS` (was hardcoded `[LIST, KANBAN]`); the Display dropdown's `layoutDisplayFiltersOptions` now reads `PROFILE_VIEW_ISSUE_LAYOUT_OPTIONS[activeLayout]`                                                | Sealed `@plane/constants` `profile_issues` table only defines `list`/`kanban` — resolves `undefined` for the three added layouts                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| `apps/web/core/services/user.service.ts`                                                                                                                          | `getUserProfileIssues` repointed to `/api/views-ext/workspaces/<slug>/user-issues/<user_id>/`                                                                                                                                                                   | Core's `/api/workspaces/<slug>/user-issues/<user_id>/` ignores `before`/`after` — profile Calendar would fetch unbounded and only look correct at small data sizes                                                                                                                                                                                                                                                                                                                                                                                                         |
| `apps/web/core/store/issue/profile/filter.store.ts`                                                                                                               | `getAppliedFilters` calls the fork-owned `getProfileViewQueryParamsByLayout` instead of core's `handleIssueQueryParamsByLayout(layout, "profile_issues")`                                                                                                       | Sealed `profile_issues` layoutOptions table only covers `list`/`kanban`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `apps/web/core/components/issues/issue-layouts/gantt/base-gantt-root.tsx`                                                                                         | TWO distinct changes: (a) `EIssuesStoreType.PROFILE` admitted to `GanttStoreType`, and the original GLOBAL-only date-drag fallback generalised behind a named `isWorkspaceLevelGanttStore` predicate; (b) the quick-add gate now also requires `enableQuickAdd` | (a) `/profile/:userId/assigned` has no route `:projectId` either, so it hits the identical crash as GLOBAL — naming the predicate means the next workspace-level store inherits the fix instead of reintroducing it. (b) PROFILE sets `enableQuickAdd: false` while `enableIssueCreation: true`; the old ungated condition (list/kanban/spreadsheet already check both flags — Gantt was the outlier) would have rendered a quick-add button wired to `useProfileIssueActions`'s absent `quickAddIssue`. Project stores set `enableQuickAdd: true`, so they are unaffected |
| `apps/web/core/components/issues/issue-layouts/calendar/base-calendar-root.tsx`                                                                                   | `EIssuesStoreType.PROFILE` admitted to `CalendarStoreType`                                                                                                                                                                                                      | Sealed union type. Quick-add is doubly safe here versus GLOBAL: `IProfileIssues.quickAddIssue` is `undefined` at the store level, so `quickAddCallback` is `undefined` before the `quick-add-issue-actions.tsx:82` `!projectId` null guard is even reached                                                                                                                                                                                                                                                                                                                 |
| `apps/web/core/components/issues/issue-layouts/spreadsheet/base-spreadsheet-root.tsx`                                                                             | `EIssuesStoreType.PROFILE` admitted to `SpreadsheetStoreType`                                                                                                                                                                                                   | Sealed union type — Spreadsheet is the layout gaining PROFILE now; List/Board already had it                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| `.../calendar/calendar.tsx`, `.../header.tsx`, `.../day-tile.tsx`, `.../week-days.tsx`, `.../dropdowns/months-dropdown.tsx`, `.../dropdowns/options-dropdown.tsx` | Same one-line `+ IProfileIssuesFilter` `issuesFilterStore` prop-union widening, 6 files — mechanically identical to the `+ IWorkspaceIssuesFilter` widening already in the Views table above, and fenced together with it (`views-layouts / profile-layouts`)   | The prop is forwarded down the whole calendar chain, so the union must widen at every hop; each file only ever reads `.issueFilters?.…`, always optional-chained — type-only, zero logic changed across all six                                                                                                                                                                                                                                                                                                                                                            |
| `apps/web/core/components/issues/issue-layouts/calendar/roots/profile-issues-root.tsx` (NEW)                                                                      | `ProfileIssuesCalendarLayout` — PROFILE-store Calendar root, sibling of the existing List/Board profile roots                                                                                                                                                   | New file; no upstream Calendar layout existed for the profile "Your work" pages                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `apps/web/core/components/issues/issue-layouts/spreadsheet/roots/profile-issues-root.tsx` (NEW)                                                                   | `ProfileIssuesSpreadsheetLayout` — same pattern as the Calendar root above                                                                                                                                                                                      | Same                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| `apps/web/core/components/issues/issue-layouts/gantt/roots/profile-issues-root.tsx` (NEW)                                                                         | `ProfileIssuesGanttLayout` — same pattern; mirrors `gantt/roots/workspace-root.tsx` (`WorkspaceGanttRoot`) for the PROFILE store                                                                                                                                | Same                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |

**Rebase handling:** these files ARE expected conflict points (unlike the abort-on-conflict rule
for everything else). On conflict, re-apply the fork block — each is fenced by a
`The1Studio fork (profile-layouts)` comment (the six calendar prop-widening files carry a combined
`views-layouts / profile-layouts` fence, since both features touch the same union/prop) — and keep
upstream's changes around it. Do NOT abort the rebase for a conflict confined to this set.

**`packages/views-ext` reuse note:** `PROFILE_VIEW_ISSUE_LAYOUT_OPTIONS` and
`GLOBAL_VIEW_ISSUE_LAYOUT_OPTIONS` are both built by the same `buildWorkspaceLevelViewLayoutOptions`
factory in `packages/views-ext/src/layout-options.ts`, parameterized only by their `group_by` field
set (identical for both today). The GLOBAL table's evaluated output was diffed byte-for-byte
against `origin/company-main` and is unchanged by this refactor — the factory extraction is
internal restructuring, not a behavior change to the already-shipped Views tab feature.
`plane-isolation-audit` already allowlists `@plane/views-ext` as fork-owned (see the Views table's
note above); no new allowlist entry is needed.

### Workload timeline & workspace-wide work settings — fenced `The1Studio fork (workspace work settings)` / `The1Studio fork (workload timeline, phase-8.md)`

Replaces per-member `WorkloadCapacity` with a single workspace-wide `WorkloadSettings` row
(max weekly hours, workdays, week start day — admin-only, `/:workspaceSlug/settings/workload`)
and replaces the aggregate Workload **table** with a per-member **timeline** of task bars built
on core's gantt primitives (`plans/260818-workload-workspace-settings/plan.md`, D1–D14). Backend:
existing `workload` app (§ Backend customizations above), no new app. Frontend: new
`apps/web/core/components/workload/timeline/` (composes `GanttChartRoot`, does not fork it —
see the architectural note below) plus a small set of fenced core-edit exceptions, same "no
upstream seam" pattern as the SP2/Views/Profile tables above.

Upstream ships week-start as a **per-user** preference (`User.start_of_the_week`, default
Sunday) read by 8 core web files. This feature makes week-start a **workspace-wide** setting
(D3) with no per-user override, so those 8 reads are swapped for `useWorkSettings()` and the
per-user preference UI is deleted outright rather than left as a dead control.

| File                                                                                                 | What                                                                                                                                                                      | Why no seam                                                                                                                                                   |
| ---------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `apps/web/core/components/dropdowns/date.tsx`                                                        | Week-start read swapped from `useUserProfile().data?.start_of_the_week` to `useWorkSettings(workspaceSlug).workSettings.week_start_day`                                   | No upstream seam to override a per-user preference read with a workspace-scoped one; the field itself (`start_of_the_week`) is core and sealed                |
| `apps/web/core/components/dropdowns/date-range.tsx`                                                  | Same swap, date-range variant                                                                                                                                             | Same                                                                                                                                                          |
| `apps/web/core/components/gantt-chart/chart/root.tsx`                                                | Same swap, in `ChartViewRoot`'s week-column math — the **only** Phase 8 timeline edit to this file (see architectural note below)                                         | Same                                                                                                                                                          |
| `apps/web/core/components/issues/issue-layouts/calendar/week-days.tsx`                               | Same swap, calendar week-day rendering                                                                                                                                    | Same                                                                                                                                                          |
| `apps/web/core/components/issues/issue-layouts/calendar/week-header.tsx`                             | Same swap, calendar week-header labels                                                                                                                                    | Same                                                                                                                                                          |
| `apps/web/core/store/issue/issue_calendar_view.store.ts`                                             | Same swap, 4 call sites building the calendar's week grid                                                                                                                 | Same                                                                                                                                                          |
| `apps/web/core/components/settings/profile/content/pages/preferences/language-and-timezone-list.tsx` | Removes the per-user "start of week" control from the Profile → Preferences page                                                                                          | D3 — no per-user override exists any more; a control left in place would silently do nothing                                                                  |
| `apps/web/core/components/power-k/config/preferences-commands.ts`                                    | Removes the `update_start_of_week` Power-K command                                                                                                                        | Same — the command targeted the deleted preference                                                                                                            |
| `apps/web/core/components/power-k/core/types.ts`                                                     | Removes `"update-start-of-week"` from `TPowerKPageType`                                                                                                                   | Same — sealed union, no seam to shrink it externally                                                                                                          |
| `apps/web/core/components/power-k/ui/modal/constants.ts`                                             | Removes the `"update-start-of-week"` entry from `POWER_K_MODAL_PAGE_DETAILS`                                                                                              | Same                                                                                                                                                          |
| `apps/web/core/components/power-k/ui/pages/preferences/root.tsx`                                     | Removes the `PowerKPreferencesStartOfWeekMenu` import + render branch                                                                                                     | Same                                                                                                                                                          |
| `apps/web/core/components/settings/workspace/sidebar/item-categories.tsx`                            | Appends a "Work settings" nav item to the FEATURES category, admin-only, linking `/settings/workload`                                                                     | Nav items come from the sealed `@plane/constants` `GROUPED_WORKSPACE_SETTINGS` registry (identical reason to the existing `sidebar-menu-items.tsx` row above) |
| `apps/web/core/hooks/store/use-workload-estimate.ts`                                                 | Removes the `useWorkloadCapacity(memberId)` selector                                                                                                                      | Read a store field (`capacities`) that no longer exists once `WorkloadCapacity` is removed — dangling if left in place                                        |
| `apps/web/ce/store/root.store.ts`                                                                    | Wires the new `WorkSettingsStore` into the CE root store                                                                                                                  | The CE root-store composition object has no plugin slot for a new top-level store                                                                             |
| `apps/web/ce/hooks/use-timeline-chart.ts` (Phase 8)                                                  | Widens the timeline-chart-store hook to accept the workload timeline's own `BaseTimeLineStore` instance alongside the existing issue/module ones                          | Sealed union of concrete timeline store types — the workload timeline needs a sibling entry, not a new hook                                                   |
| `apps/web/ce/store/timeline/index.ts` (Phase 8)                                                      | Types the workload timeline's store as the concrete `BaseTimeLineStore`, and documents that block data is pushed in via `updateBlocks` rather than an autorun data source | Same — no upstream store variant for a manually-fed gantt data source existed                                                                                 |
| `apps/web/app/(all)/[workspaceSlug]/(projects)/workload/page.tsx`                                    | Replaced wholesale: renders `WorkloadTimelineRoot` instead of the deleted `WorkloadMatrix` table                                                                          | Existing fork-owned route (not a core file); listed here for completeness since the whole page body changed                                                   |
| `packages/types/src/index.ts`                                                                        | `export * from "./workload"` — barrel export for the new `packages/types/src/workload.ts`                                                                                 | `@plane/types`' barrel is additive-only by convention; a missing re-export would make the new types unreachable from `@plane/types` consumers                 |
| `packages/types/src/base-layouts/gantt/extended.ts`                                                  | **Not a fork exception** — fills the empty, upstream-designed `EXTENDED_GANTT_TIMELINE_TYPE` extension seam with a `WORKLOAD` entry. See the seam note below.             | N/A — using a seam as designed                                                                                                                                |

**Rebase handling:** these files ARE expected conflict points (unlike the abort-on-conflict
rule for everything else). On conflict, re-apply the fork block — each is fenced by a
`The1Studio fork (workspace work settings)` comment (the two Phase 8 `ce/` files above carry
`The1Studio fork (workload timeline, phase-8.md)` instead, since they are timeline-specific
rather than week-start propagation) — and keep upstream's changes around it. Do NOT abort the
rebase for a conflict confined to this set.

**Deletions, not in-place edits.** Two core files were removed wholesale rather than edited —
`apps/web/core/components/power-k/ui/pages/preferences/start-of-week-menu.tsx` and
`apps/web/core/components/profile/start-of-week-preference.tsx` — both dead code once the
per-user week-start preference was removed (D3); every remaining reference to them is the
removal edits already listed in the table above.

**Seam used as designed, not a fork exception.** `packages/types/src/base-layouts/gantt/extended.ts`
shipped upstream as `export const EXTENDED_GANTT_TIMELINE_TYPE = {} as const;` — an intentionally
empty extension point. Filling it with a `WORKLOAD` member is that seam's designed use, not an
in-place edit to sealed logic. Do **not** list a future fill of this same const as a new fork
exception; only list it here if a future feature is ever forced to change the const's _shape_
(not just add a member).

**Architectural note — why the Phase 8 timeline creates almost no rebase-conflict surface.**
The gantt chart has no grouping/swimlane seam (`chart/root.tsx` renders one flat `blockIds`
list). Phase 8 deliberately did **not** fork `ChartViewRoot` to add one: its zoom/pan/pagination
state machine is private, unexported logic internal to that file, and forking it would put the
single highest-conflict-risk file in this repo on a permanent fork track. Instead, the workload
timeline **composes around** `GanttChartRoot` — one gantt instance per assignee swimlane, built
from a flat, assignee-grouped `blockIds` list assembled in
`apps/web/core/components/workload/timeline/` from the Phase 7 per-task API response, fed into a
plain `BaseTimeLineStore` via `updateBlocks` (see `packages/types/.../gantt/extended.ts` above).
The **only** Phase 8 line inside `gantt-chart/chart/root.tsx` is the Phase 5 week-start read
swap already in the table above — Phase 8 itself added zero lines to that file. This is the
single most valuable decision in this feature from a fork-survival standpoint: the timeline UI
tracks upstream gantt changes for free, because it never touches the file upstream is most
likely to change.

**`apps/space` carve-out — deliberately NOT converted.** `apps/space/store/profile.store.ts`
still reads the per-user `start_of_the_week` default (`EStartOfTheWeek.SUNDAY`). This is
intentional, not a missed site: `apps/space` is the public-facing app for shared/published
views and has no workspace-settings access to read a `WorkloadSettings` row from, so there is
nothing to swap it to. A future audit should not treat this as an incomplete propagation.

**`apps/web/core/store/user/profile.store.ts` — deliberately unchanged.** Still supplies
`start_of_the_week: EStartOfTheWeek.SUNDAY` as the **default value** in its initial
`TUserProfile` object. D7 (see `plan.md`) keeps the core `User.start_of_the_week` DB column —
`plane/db/migrations/` is never edited in place — so the TypeScript type keeps the field too.
This is a write of an unused default, never a read; nothing in the web app reads
`profile.start_of_the_week` any more after this feature (all 8 former call sites now read
`useWorkSettings()` instead, per the table above).

**`DEFAULT_WEEK_START_DAY` divergence — deliberate.** The workspace default is **Monday**
(`apps/api/plane/workload/constants.py`), diverging from core's per-user default of **Sunday**.
Today's week buckets are ISO weeks (Monday-start, `aggregation.py` pre-Phase-2), so seeding
Monday is the value that leaves every existing workspace's week columns unchanged on migration —
seeding Sunday would silently shift every historical week boundary by one day.

**`plane-isolation-audit` note:** no new allowlist entry is needed — this feature adds no new
`@plane/`-scoped package; `apps/web/core/components/workload/timeline/` is app-internal (not a
package), and `packages/workload-ext` is already allowlisted per the SP2 workload table above.

**Timeline follow-up (`plans/260818-workload-timeline-fixes/`) — ZERO new core edits.** The
capacity-badge, single-time-control, row-layout and clickable-work-item work adds **no** row to
the table above and **no** new touch-point. Two core edits were considered and deliberately
avoided; both are worth knowing about before anyone reaches for them again:

- **Hiding `GanttChartHeader`'s own Week/Month/Quarter switcher** would have meant threading a
  `hideViewSwitcher` prop through `GanttChartRoot` → `ChartViewRoot` → `GanttChartHeader` —
  three core files and three rebase-conflict points, to remove a control we can simply _adopt_.
  Instead that switcher IS the granularity control now: `WorkloadTimelineRoot` reacts to
  `timelineStore.currentView` and maps it onto `store.granularity`.
- **A taller swimlane header** (name + badge on one line, the Unscheduled/Overdue strip below)
  would have needed per-block heights, but `BLOCK_HEIGHT` is a hardcoded 44px inside core's
  `gantt-chart/blocks/block-row.tsx`. Instead the footer strip is a THIRD BLOCK KIND, so every
  row stays at the shared height and core is untouched. Anyone wanting variable row heights here
  should know the uniform-height constraint was designed around, not overlooked.

The same change makes the `/api/workload/workspaces/<slug>/` response carry `weekly_buckets`,
`weekly_capacity` and `tasks[].project_id`, and makes `periods` span the requested window rather
than only the populated buckets. `total_over` keeps its definition but changes its **value** as a
result — the one silent behavioural change for downstream consumers.

### Fork bugfix exceptions (upstream bugs, fenced, upstream-PR candidates)

Minimal fenced fixes for bugs that exist in upstream itself (verified unfixed at
makeplane/plane `preview` HEAD when added). Each is expected to disappear once upstream
fixes it — on a rebase conflict, check whether upstream's version still has the bug; if
fixed upstream, DROP our hunk.

| File                    | What                                                                                                                                                                                                                                                                                                                           | Fence                                      |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------ |
| `apps/web/app/root.tsx` | `HydrateFallback` mounted-gate — SPA-mode prerender emits an empty `<div />` but the first client render resolved the theme synchronously and rendered the spinner, throwing React #418 (hydration mismatch) on every page load                                                                                                | `The1Studio fork (hydration fix)`          |
| `.oxlintrc.json`        | `overrides` block scoping `unicorn/no-array-sort: off` to `apps/web`/`admin`/`space` — those apps compile with lib:ES2022, so the rule's autofix (`.sort()` → `.toSorted()`, ES2023) produces code tsc rejects, and the lint-staged pre-commit applies it AFTER local typechecks ran (CI went red unseen, incident 2026-07-03) | none (JSON — this table row is the marker) |

### The complete 7 core touch-point inventory

These are the ONLY files that may carry The1Studio edits. A rebase conflict outside this set
means a customization leaked into core — relocate it.

Verified line numbers against the live fork (branch `company-main`, tag base `v1.3.1`):

| #   | File                                                                                                         | Verified line                                                                                                         | Why touched                           | Rebase-safe approach                                                                                                                                                                                                                                                                                              |
| --- | ------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------- | ------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `apps/api/plane/settings/common.py`                                                                          | `INSTALLED_APPS` at line 79                                                                                           | Register new apps                     | Append 1 line per new app at the end of the in-house block (after `"plane.authentication",`, before `# Third-party things`)                                                                                                                                                                                       |
| 2   | `apps/api/plane/urls.py`                                                                                     | `urlpatterns` at line 17                                                                                              | Mount new app URLs                    | Append `path("api/ai-ext/", include("plane.ai_ext.urls")),` after the existing includes                                                                                                                                                                                                                           |
| 3   | `apps/api/plane/celery.py`                                                                                   | `beat_schedule` at line 29; `autodiscover_tasks()` at line 101; `DatabaseScheduler` at line 103                       | SP2 scheduled digest tasks            | **ZERO edit to celery.py** — register `PeriodicTask` rows via `django_celery_beat` `DatabaseScheduler` (already active at line 103) from the new app's `apps.py ready()` or a data migration. `autodiscover_tasks()` at line 101 already picks up any new-app `tasks.py` automatically.                           |
| 4   | `apps/api/plane/app/views/external/base.py`                                                                  | `get_llm_response()` around line 131; `AnthropicProvider.models` around line 54                                       | Claude/Anthropic fix (Phase 4b)       | Prefer a new-app endpoint in `ai_ext` for new AI calls. The in-place edit here is the **documented exception**: the existing core God-mode AI button must keep working. The fix is already applied (commit `4469c63`): `base_url` is set for the anthropic provider branch; current Claude model ids are present. |
| 5   | `apps/api/requirements/base.txt` + `apps/api/Dockerfile.api`                                                 | —                                                                                                                     | New pip dependencies                  | **Avoid** — prefer the OpenAI-compatible gateway path (no new dep). If a dep is unavoidable, pin it in the new app's own requirements fragment and reference it from a prod Dockerfile overlay — never edit `requirements/base.txt` in place.                                                                     |
| 6   | `apps/web/app/routes/extended.ts` + `apps/web/package.json`                                                  | `extendedRoutes: RouteConfigEntry[] = []` at line 9 of `extended.ts`; merged via `mergeRoutes` in `routes.ts` line 17 | Mount AI UI routes                    | **Designed seam** — append route entries to the empty `extendedRoutes` array in `extended.ts`. Never edit `routes/core.ts`. The array is already merged into the app via `mergeRoutes(coreRoutes, extendedRoutes)`.                                                                                               |
| 7   | `apps/web/app/root.tsx`, `apps/admin/app/root.tsx`, `apps/web/Dockerfile.web`, `apps/admin/Dockerfile.admin` | branding constant + meta around `APP_TITLE`                                                                           | White-label branding (VITE_APP_TITLE) | Re-apply the `process.env.VITE_APP_TITLE \|\|` fallback prefix; empty default keeps upstream title                                                                                                                                                                                                                |

### Rebase-conflict budget

A conflict in a file not in this table = a customization leaked outside the documented
touch-points. Abort the rebase (`git rebase --abort`) and relocate the offending edit into
a new app or package before attempting the rebase again.

### Executable isolation probe (Phase 2 gate)

The following procedure proves the append-only pattern is mechanically valid. It requires the
built migrator image and a running database (available on the staging VM), so it is documented
here as a ready-to-run gate and marked as an **operator/staging task** — do not commit the
probe files.

```bash
# 1. Scaffold the throwaway probe app
mkdir -p apps/api/plane/_isolation_probe
cat > apps/api/plane/_isolation_probe/__init__.py << 'EOF'
EOF

cat > apps/api/plane/_isolation_probe/apps.py << 'EOF'
from django.apps import AppConfig

class IsolationProbeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "plane._isolation_probe"
    label = "isolation_probe"
EOF

cat > apps/api/plane/_isolation_probe/urls.py << 'EOF'
from django.urls import path
urlpatterns = []
EOF

# 2. Apply touch-point 1 — append to INSTALLED_APPS (after "plane.authentication",)
#    Add:  "plane._isolation_probe",
# Edit apps/api/plane/settings/common.py manually at line ~95

# 3. Apply touch-point 2 — append to urlpatterns
#    Add:  path("api/_probe/", include("plane._isolation_probe.urls")),
# Edit apps/api/plane/urls.py manually after line ~23

# 4. Run the Django system check inside the migrator container
docker compose --project-directory . -f docker-compose.yml \
  run --rm migrator python manage.py check

# Expected output: "System check identified no issues (0 silenced)."

# 5. Revert ALL probe changes — do not commit probe files
git checkout -- apps/api/plane/settings/common.py apps/api/plane/urls.py
rm -rf apps/api/plane/_isolation_probe
```

Expected result: Django loads cleanly, the URL resolver finds no issues, and after revert the
working tree is clean. This proves that new apps integrate via the documented touch-points
without any core surgery.

---

## CI gates

Two GitHub Actions workflows enforce the fork convention automatically:

- `.github/workflows/company-main-ci.yml` — runs on every push/PR to `company-main`:
  - `python manage.py makemigrations --check` — fails if any migration is missing after rebase.
  - `python manage.py check` — fails if Django's system check fails (import errors, url errors).
  - `pnpm install --frozen-lockfile` + `pnpm check` — fails if frontend type-check breaks.
- `.github/workflows/upstream-sync-check.yml` — weekly cron that checks for new upstream tags
  and writes a job summary when a newer tag is available.

---

## Versioning

After every successful rebase-and-smoke, tag `company-main` with:

```
company-v<upstream-version>-<N>
```

Examples:

- `company-v1.3.1-1` — first adopt of upstream v1.3.1
- `company-v1.3.1-2` — a hotfix on top of v1.3.1 before the next upstream tag
- `company-v1.4.0-1` — first adopt of upstream v1.4.0

Production deploys reference a specific `company-v*` tag, never a branch tip.

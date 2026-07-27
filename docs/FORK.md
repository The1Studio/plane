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

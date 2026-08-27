# Fork Convention — SSOT mirror of `docs/FORK.md`

> **Authoritative source is `docs/FORK.md`.** This file MIRRORS its §Isolation convention for the
> `plane-*` skills to consume. On any conflict, **`docs/FORK.md` wins** — fix this mirror, never the
> reverse. `plane-fork-doctor` diffs this file's touch-point list against `docs/FORK.md` and fails on drift.

The fork survives monthly upstream rebases only if customizations stay isolated. There are exactly
**7 core touch-points** that may carry fork edits. A rebase conflict in any other core file = a leak →
`git rebase --abort` and relocate the edit into a new app/package.

## The 7 touch-points (mirror of `docs/FORK.md` §The complete 7 core touch-point inventory)

| #   | File(s)                                                                                                      | Why touched                           | Rebase-safe approach                                                                                                  |
| --- | ------------------------------------------------------------------------------------------------------------ | ------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| 1   | `apps/api/plane/settings/common.py`                                                                          | Register new apps                     | Append 1 line per app to the in-house `INSTALLED_APPS` block                                                          |
| 2   | `apps/api/plane/urls.py`                                                                                     | Mount new app URLs                    | Append `path("api/<name>/", include("plane.<name>.urls")),` after existing includes                                   |
| 3   | `apps/api/plane/celery.py`                                                                                   | Scheduled tasks                       | **Zero edit** — `autodiscover_tasks()` + `DatabaseScheduler` already pick up new-app `tasks.py` / `PeriodicTask` rows |
| 4   | `apps/api/plane/app/views/external/base.py`                                                                  | Claude/Anthropic God-mode AI          | Documented in-place **exception** — prefer a new `ai_ext` endpoint; the core button must keep working                 |
| 5   | `apps/api/requirements/base.txt`, `apps/api/Dockerfile.api`                                                  | New pip deps                          | **Avoid** — pin in the new app's own requirements fragment + a Dockerfile overlay, never in place                     |
| 6   | `apps/web/app/routes/extended.ts`, `apps/web/package.json`                                                   | Mount UI routes                       | Append entries to the empty `extendedRoutes` array — never edit `routes/core.ts`                                      |
| 7   | `apps/web/app/root.tsx`, `apps/admin/app/root.tsx`, `apps/web/Dockerfile.web`, `apps/admin/Dockerfile.admin` | White-label branding (VITE_APP_TITLE) | Re-apply the `VITE_APP_TITLE` fallback prefix; never rename the constant or remove the upstream fallback string       |

## Core models — NO new columns (new tables only)

`Issue`, `Page`, `Module`, `State`, `Intake`, `Asset` (and any other upstream core model). Add a new
table in your fork app (OneToOne/FK to the core model) instead of a column. Never edit
`apps/api/plane/db/migrations/` or any `@plane/*` package in place.

## Fork-owned customizations

- **Backend** = NEW Django app under `apps/api/plane/<name>/` (owns its `migrations/`, `urls.py`,
  `models.py`, `apps.py`). Current fork apps: `ai_ext`, `clickup_migrate`, `workload`, `github_ext`,
  `project_ext`, `workspace_ext`, `views_ext`, `cascade_ext`, `issue_defaults_ext`, `workload_cache` — keep this list and the `forkApps` array below in sync. `forkApps` also selects which
  apps master CI runs tests for (via `.claude/scripts/plane-fork-test-paths.py`), so an app
  missing from it is both misclassified AND untested.
- **Frontend** = NEW package under `packages/<name>-ext/`, mounted via touch-point 6.
- **Infrastructure** = a path listed in `forkPaths` below, classified `custom-infra`. These are
  files and directories the fork CREATED outright — deploy scripts, its own CI workflows, its plan
  archive, and `docs/FORK.md` itself. They are neither a Django app nor a frontend package, so
  without this list the classifier called them `core — fork edits forbidden, relocate`, which is
  both wrong and self-contradictory: it said that about the very document defining the convention.

  A prefix ending in `/` matches that directory and everything under it; a prefix without one must
  match the path exactly, so a single file can be listed without capturing its siblings.

  **`.claude/` is whitelisted with a carve-out.** Upstream created the directory (`f1d567accc`,
  "Claude Code skills for PR descriptions", #8920) but contributed exactly two files to it —
  `skills/pr-description.md` and `skills/release-notes.md`. Every subdirectory beneath it
  (`scripts/`, `rules/`, `plans/`, `skills/_shared/`, every `skills/plane-*/`) is fork-authored,
  mostly by `5105532b68`. So the directory is listed in `forkPaths` and those two files are named
  in **`forkPathExceptions`**, which is checked first and returns them to `core`. Prefer that shape
  over enumerating fork subdirectories: a new `plane-*` skill is then covered automatically,
  whereas an enumerated list silently misses it.

  Only `deployments/selfhost/` is listed and not `deployments/`
  — the siblings (`cli`, `aio`, `kubernetes`, `swarm`, `r2-proxy`) came from upstream
  `6d01622663` — and why the two fork workflows are named individually rather than whitelisting
  `.github/workflows/`. Verify provenance with `git log --diff-filter=A -- <path>` before adding
  anything here; a too-broad prefix silently grants fork-edit approval to upstream files.

---

## Machine-readable convention (SSOT for `plane-classify-path.cjs`)

The classifier reads the first fenced JSON block below. This block — not an inline literal in the
script — is the single source of truth; deleting it from the script changes nothing because the data lives here.
Keep paths in sync with the table above (the doctor's drift check enforces it).

```json
{
  "touchPoints": [
    { "id": 1, "paths": ["apps/api/plane/settings/common.py"] },
    { "id": 2, "paths": ["apps/api/plane/urls.py"] },
    { "id": 3, "paths": ["apps/api/plane/celery.py"] },
    { "id": 4, "paths": ["apps/api/plane/app/views/external/base.py"] },
    { "id": 5, "paths": ["apps/api/requirements/base.txt", "apps/api/Dockerfile.api"] },
    { "id": 6, "paths": ["apps/web/app/routes/extended.ts", "apps/web/package.json"] },
    {
      "id": 7,
      "paths": [
        "apps/web/app/root.tsx",
        "apps/admin/app/root.tsx",
        "apps/web/Dockerfile.web",
        "apps/admin/Dockerfile.admin"
      ]
    }
  ],
  "forkApps": [
    "ai_ext",
    "clickup_migrate",
    "workload",
    "github_ext",
    "project_ext",
    "workspace_ext",
    "views_ext",
    "cascade_ext",
    "issue_defaults_ext",
    "workload_cache"
  ],
  "forkAppRoot": "apps/api/plane/",
  "forkPackageRoot": "packages/",
  "forkPackageSuffix": "-ext",
  "coreModels": ["Issue", "Page", "Module", "State", "Intake", "Asset"],
  "neverEdit": ["apps/api/plane/db/migrations/", "apps/web/app/routes/core.ts"],
  "forkPaths": [
    ".claude/",
    "deployments/selfhost/",
    "plans/",
    "docs/FORK.md",
    ".github/workflows/master-ci.yml",
    ".github/workflows/deploy-master.yml"
  ],
  "forkPathExceptions": [".claude/skills/pr-description.md", ".claude/skills/release-notes.md"]
}
```

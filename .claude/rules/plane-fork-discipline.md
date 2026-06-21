---
origin: the1studio-plane
repository: The1Studio/plane
module: null
protected: false
---

# Plane Fork Discipline

Auto-loaded guardrails for `company-main`. Full specification: `docs/FORK.md` (SSOT).
Operational tools: `plane-rebase`, `plane-isolation-audit`, `plane-scaffold-feature`,
`plane-propagate`, `plane-fork-doctor` skills.

## Backend customizations

- New code = NEW Django app under `apps/api/plane/<name>/` — owns its own `migrations/`,
  `urls.py`, `models.py`, `apps.py`.
- **Never edit** `apps/api/plane/db/migrations/` or any `@plane/*` package in place.
- Register via touch-point 1 (`INSTALLED_APPS`) + touch-point 2 (`urlpatterns`) only.

## Core model constraint

- **No new columns** on `Issue`, `Page`, `Module`, `State`, `Intake`, `Asset` or any other
  upstream core model. Add a new table in your fork app (OneToOne/FK to the core model).

## Frontend customizations

- New UI code = NEW package under `packages/<name>-ext/`, consumed via `workspace:*`.
- Mount routes via touch-point 6 only: append entries to `extendedRoutes` in
  `apps/web/app/routes/extended.ts`. **Never edit** `apps/web/app/routes/core.ts`.

## The 6 touch-points

Only these files may carry fork edits:

| #   | File(s)                                                                            |
| --- | ---------------------------------------------------------------------------------- |
| 1   | `apps/api/plane/settings/common.py` — `INSTALLED_APPS`                             |
| 2   | `apps/api/plane/urls.py` — `urlpatterns`                                           |
| 3   | `apps/api/plane/celery.py` — **zero edit**; `autodiscover_tasks()` covers new apps |
| 4   | `apps/api/plane/app/views/external/base.py` — documented exception for God-mode AI |
| 5   | `apps/api/requirements/base.txt`, `apps/api/Dockerfile.api` — avoid; use overlay   |
| 6   | `apps/web/app/routes/extended.ts`, `apps/web/package.json` — designed seam         |

A rebase conflict **outside** this set = a customization leaked into core →
`git rebase --abort` and relocate the edit.

## After every rebase

Run `python manage.py makemigrations --check --dry-run` (CI gate: `company-main-ci.yml`
enforces this on every push/PR). Also run `python manage.py check` and `pnpm check`.

## Feature propagation (mandatory)

Every new endpoint, field, or behavior must be propagated before the feature is considered done:
MCP tool in `plane-mcp-server` → SDK bindings in `plane-node-sdk` / `plane-python-sdk` →
`plane-claude-plugin` / docs as relevant → `CLAUDE.md` "Custom features" entry.
Track via issues/PRs in the sibling repos; do not edit them from this repo's PR.

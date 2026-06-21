# Rebase Recipe — Per-Touch-Point Resolution Guide

> **SSOT is `docs/FORK.md` §The complete 6 core touch-point inventory.**
> This file mirrors the "Rebase-safe approach" column and the per-touch-point
> recovery notes from `docs/FORK.md` §Conflict recovery. On any discrepancy,
> `docs/FORK.md` wins — update this mirror, never the reverse.

These recipes apply only when `git rerere` has NOT already auto-replayed the
resolution. If rerere staged the file automatically, verify the result and
`git rebase --continue` — no recipe needed.

---

## Touch-point 1 — `apps/api/plane/settings/common.py`

**Why touched:** `INSTALLED_APPS` registration for fork-owned Django apps.

**Conflict likely cause:** upstream added, removed, or reordered an app entry
in the same `INSTALLED_APPS` block.

**Recipe:**

1. Accept upstream's version of the block as the base.
2. Re-apply the fork's appended lines at the **end of the in-house block**
   (after `"plane.authentication",`, before the `# Third-party things` comment).
   One line per fork app, e.g.:
   ```python
   "plane.ai_ext",
   "plane.workload",
   # "plane.clickup_migrate",  ← ONLY on the sp1/clickup-migrate branch (docs/FORK.md branch model)
   ```
   Re-append **only the fork apps registered on the CURRENT branch** — adding an app whose
   package is absent on this branch fails `python manage.py check`.
3. Do NOT reorder upstream entries; only append fork entries at the designated
   position.
4. `git add apps/api/plane/settings/common.py && git rebase --continue`

---

## Touch-point 2 — `apps/api/plane/urls.py`

**Why touched:** `urlpatterns` — mounting fork app URL namespaces.

**Conflict likely cause:** upstream added new URL includes or restructured the
include block.

**Recipe:**

1. Accept upstream's `urlpatterns` block as the base.
2. Re-append fork route entries **after** upstream's last `path(...)` entry:
   ```python
   path("api/ai-ext/", include("plane.ai_ext.urls")),
   # add other fork apps here as they are registered
   ```
3. Do NOT edit upstream URL entries; only append fork entries at the end.
4. `git add apps/api/plane/urls.py && git rebase --continue`

---

## Touch-point 3 — `apps/api/plane/celery.py`

**Why touched:** historically listed as a touch-point for scheduled tasks; the
fork convention mandates ZERO direct edits.

**Conflict likely cause:** If a conflict appears here, a previous edit violated
the zero-edit rule. Most likely, upstream refactored `celery.py` significantly.

**Recipe:**

1. This file must carry ZERO fork edits. Accept upstream's version entirely:
   ```bash
   git checkout --theirs apps/api/plane/celery.py
   ```
2. Verify that `autodiscover_tasks()` and `DatabaseScheduler` are still present
   in upstream's version (they should be; if they were removed, that is an
   upstream architectural change requiring investigation).
3. Fork scheduled tasks use `PeriodicTask` rows registered from the fork app's
   `apps.py ready()` or a data migration — no celery.py edit needed.
4. `git add apps/api/plane/celery.py && git rebase --continue`
5. After rebase: confirm fork tasks still appear in the Celery beat schedule
   via `django_celery_beat`.

---

## Touch-point 4 — `apps/api/plane/app/views/external/base.py`

**Why touched:** documented in-place exception — the existing core God-mode AI
button's `get_llm_response()` function and `AnthropicProvider.models` list.

**Conflict likely cause:** upstream changed the Anthropic provider logic around
line 131 (`get_llm_response`) or around line 54 (`AnthropicProvider.models`).

**Recipe:**

1. Accept upstream's version as the base.
2. Re-apply the fork's two specific changes from commit `4469c63`:
   - In the Anthropic provider branch: ensure `base_url` is set to the
     OpenAI-compatible gateway value (not upstream's default or None).
   - In `AnthropicProvider.models`: ensure current Claude model IDs are present
     (e.g. `claude-sonnet-4-6`, `claude-opus-4-7`).
3. Prefer minimal edits — only the `base_url` line and model-id list. Every
   other change in `base.py` belongs in `apps/api/plane/ai_ext/` instead.
4. `git add apps/api/plane/app/views/external/base.py && git rebase --continue`

---

## Touch-point 5 — `apps/api/requirements/base.txt` and `apps/api/Dockerfile.api`

**Why touched:** new pip dependencies. The fork convention STRONGLY prefers
avoiding in-place edits here.

**Conflict likely cause:** upstream bumped, removed, or renamed a package that
the fork also pinned in `base.txt`.

**Recipe (preferred — Dockerfile overlay):**

1. Accept upstream's `requirements/base.txt` as the base (take theirs).
2. If the fork pinned a dep that conflicts: move the pin to the fork app's own
   requirements fragment (e.g. `apps/api/plane/ai_ext/requirements.txt`) and
   reference it from a production Dockerfile overlay, not from `base.txt`.
3. `git add apps/api/requirements/base.txt && git rebase --continue`

**Recipe (fallback — if dep is already in base.txt and cannot move):**

1. Re-pin the fork dep after upstream's version of the file, verifying version
   compatibility with whatever upstream changed.
2. Annotate with `# fork-pin: <reason>` so future rebases know it is
   intentional.
3. `git add apps/api/requirements/base.txt && git rebase --continue`

`Dockerfile.api`: same approach — prefer overlay files; if forced, accept
upstream's Dockerfile as base and re-apply only the fork's ADD/RUN lines.

---

## Touch-point 6 — `apps/web/app/routes/extended.ts` and `apps/web/package.json`

**Why touched:** mounting AI UI routes via the designed seam in `extended.ts`.

**Conflict likely cause (extended.ts):** upstream added structure around the
`extendedRoutes` array in `extended.ts`, or changed how `mergeRoutes` is called.

**Recipe (extended.ts):**

1. Accept upstream's version as the base.
2. Locate the `extendedRoutes: RouteConfigEntry[] = [...]` declaration (should
   still be at or near line 9).
3. Re-append the fork's route entries inside the array in its new form.
4. Never edit `apps/web/app/routes/core.ts` — that is a core file.
5. `git add apps/web/app/routes/extended.ts && git rebase --continue`

**Conflict likely cause (package.json):** upstream bumped a workspace dep or
added a new package reference.

**Recipe (package.json):**

1. Accept upstream's `apps/web/package.json` as the base.
2. Re-apply fork workspace references (e.g. `"@plane/ai-ext": "workspace:*"`)
   in the `dependencies` block. Do not restore any package version pin that
   upstream intentionally changed.
3. `git add apps/web/package.json && git rebase --continue`

---

## After all conflicts are resolved

Return to `SKILL.md` Step 6: run `pnpm install && pnpm check`, then Step 7:
`python manage.py makemigrations --check --dry-run && python manage.py check`.
Both must pass before proceeding to HARD-GATE B.

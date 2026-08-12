---
name: plane-scaffold-feature
description: Scaffold an isolated fork feature (new Django app + optional frontend package) by cloning the workload pattern, with append-only touch-point wiring. Use for "scaffold a fork feature", "new Plane app", "add an isolated Django app".
keywords: [scaffold, fork, django-app, feature, workload-pattern, isolation, append-only]
metadata:
  author: the1studio
  version: "1.0.0"
---

# plane-scaffold-feature

Scaffold an isolated fork feature following the workload pattern — a new Django app under
`apps/api/plane/<name>/` and an optional frontend package under `packages/<name>-ext/` —
then wire the 6 touch-points with append-only edits so the result survives upstream rebases.

**Isolation SSOT:** `docs/FORK.md` + `.claude/skills/_shared/references/fork-convention.md`.
**Pattern reference:** `.claude/skills/plane-scaffold-feature/references/workload-pattern.md`.

---

## When to Use

Invoke this skill when the user wants to:

- Scaffold a new fork feature following the workload/ai_ext pattern
- Add an isolated Django app to the Plane fork
- Create a new Plane app without touching core Plane code
- Add a backend feature that needs its own models, views, and URLs
- Create a new fork feature like workload (with or without a frontend package)

Do NOT use this skill to:

- Add columns to core models (`Issue`, `Page`, `Module`, `State`, `Intake`, `Asset`) — that violates `docs/FORK.md`
- Edit existing core Plane source files other than the 6 touch-points
- Modify `apps/api/plane/db/migrations/` or any `@plane/*` package in place

---

## Activation

Activate automatically when the user's request contains any of these phrases:

- "scaffold a fork feature"
- "new Plane app"
- "add an isolated Django app"
- "create a new fork feature like workload"
- "scaffold backend app + frontend package"
- "new Django app for Plane"
- "add a fork feature"

---

## Decision Tree

**Required inputs before starting:**

1. `<name>` — feature name in snake_case (e.g. `sprint_tracker`). Also derive `<Name>` (PascalCase, e.g. `SprintTracker`) for class names.
2. `needs-frontend` — yes/no: does this feature need a `packages/<name>-ext/` frontend package?

If either input is missing, use `AskUserQuestion` to collect both before proceeding.

**Steps (execute in order):**

### Step 1 — Create the backend Django app

Create `apps/api/plane/<name>/` by cloning the workload structure. Each file's exact rename rules are documented in `references/workload-pattern.md`.

Required files:

```
apps/api/plane/<name>/
  __init__.py          # empty
  apps.py              # WorkloadConfig → <Name>Config; name="plane.workload" → name="plane.<name>"; label="workload" → label="<name>"; verbose_name="Workload (The1Studio)" → "<Name> (The1Studio)"
  models.py            # New table(s) only — NO column added to core models (docs/FORK.md DB rule). OneToOne/FK to core models as needed.
  serializers.py       # DRF ModelSerializer(s) for the new model(s)
  views.py             # Thin HTTP layer: parse + validate + permission, defer logic to service.py
  service.py           # ORM/business logic — no HTTP concerns
  urls.py              # App-internal URL patterns (mounted at /api/<name>/ from core urls.py via TP2)
  migrations/
    __init__.py
    0001_initial.py    # Django migration for the new model(s)
  tests/
    __init__.py
    test_<name>_db.py  # DB-level integration tests (pytest + factory-boy)
```

Optional files (include when the feature has public API / aggregation needs):

```
  aggregation.py       # Pure stdlib aggregation logic (no Django imports) — only if complex calc needed
  api_urls.py          # Public /api/v1/ URL patterns — only if public API is needed
  api_views.py         # Public /api/v1/ views (APIKeyAuthentication base) — only if public API is needed
```

**DB rule (FORK.md):** every model is a NEW table. Reference core models via OneToOne/FK only — never add a column to `Issue`, `Page`, `Module`, `State`, `Intake`, or `Asset`.

### Step 2 — (conditional) Create the frontend package

Skip if `needs-frontend = no`.

Create `packages/<name>-ext/` by cloning `packages/workload-ext/`:

```
packages/<name>-ext/
  package.json         # name: "@plane/<name>-ext"; description updated; keep same deps structure
  tsconfig.json        # extends "@plane/typescript-config/react-library.json"; rootDir ./src, outDir ./dist
  src/
    index.ts           # barrel export
    types.ts           # TypeScript types for the feature
    service.ts         # API client calls to the new backend endpoints
    store.ts           # MobX store (if state management needed)
    hooks.ts           # React hooks
    <Name>*.tsx        # React components (PascalCase, one component per file)
```

Workspace dependencies to carry over from workload-ext: `@plane/constants`, `@plane/propel`, `@plane/types`, `mobx`, `mobx-react`, `react`, `react-dom`. Adjust as needed — drop any that are not used by this feature.

### Step 3 — Append-only touch-point wiring

**Before editing each touch-point file, run it through the classifier:**

```bash
node .claude/scripts/plane-classify-path.cjs <path>
```

Verify `category` is `"touch-point"` in the JSON output before writing. If the classifier returns a different category, STOP and report — do not edit the file.

**TP1 — `apps/api/plane/settings/common.py`** (INSTALLED_APPS):

Find the in-house block (the block that contains `"plane.ai_ext"` and `"plane.workload"`).
Append ONE line inside that block:

```python
    "plane.<name>",
```

**TP2 — `apps/api/plane/urls.py`** (urlpatterns):

Find the existing fork-app `include()` lines. Append ONE line after the last existing fork entry:

```python
    path("api/<name>/", include("plane.<name>.urls")),
```

If the feature also has a public API (`api_urls.py` exists), append a second line:

```python
    path("api/v1/<name>/", include("plane.<name>.api_urls")),
```

**TP6 — `apps/web/app/routes/extended.ts`** (extendedRoutes, only if `needs-frontend = yes`):

Find the `extendedRoutes` array. Append a `route(...)` entry for each top-level UI route the feature needs.

```typescript
  route("<path>", () => import("@plane/<name>-ext/...")),
```

Also append `"@plane/<name>-ext": "workspace:*"` to `apps/web/package.json` dependencies (TP6 also covers `apps/web/package.json`).

### Step 4 — Update CLAUDE.md "Custom features"

Open `CLAUDE.md` at the repo root. Find the "Custom features (fork-owned)" section.
Append a one-line entry:

```markdown
- `<name>/` — <one-sentence description of the feature>.
```

### Step 5 — Register in fork-convention.md

Open `.claude/skills/_shared/references/fork-convention.md`.
Find the `"forkApps"` array in the fenced JSON block.
Append `"<name>"` to the array so the classifier (`plane-classify-path.cjs`) recognizes the new app:

```json
"forkApps": ["ai_ext", "clickup_migrate", "workload", "<name>"]
```

This prevents drift: after the next `plane-fork-doctor` run the new app is known, not flagged as unclassified.

**This array also selects which apps company-main CI runs tests for** — `.claude/scripts/plane-fork-test-paths.py`
intersects it with the `tests/` directories on disk to build the pytest invocation. An app missing from
`forkApps` is therefore misclassified as `core` AND its tests never run, while the job still reports
green. The script hard-fails on that combination, so CI will tell you; registering here is the single
action that fixes both. Do NOT add the app path to the workflow by hand — the list is derived.

### Step 6 — Queue propagation TODO

Open (or create) `.claude/plane-propagation-queue.md`.
Append a block at the end:

```markdown
## <name> — <date YYYY-MM-DD>

- Feature: <one-sentence description>
- New endpoints: <list the URL patterns from urls.py / api_urls.py>
- New fields: <list any new fields exposed via serializers>
- Propagation needed: MCP tool in `plane-mcp-server`, SDK bindings in `plane-node-sdk` + `plane-python-sdk`, docs update
```

This queue is consumed by the `plane-propagate` skill (CLAUDE.md standing rule: every new endpoint must reach MCP + SDKs).

### Step 7 — Verify

Run both checks and report results:

```bash
cd apps/api && python manage.py makemigrations --check --dry-run && python manage.py check
```

If `needs-frontend = yes`, also run:

```bash
pnpm check
```

If either check fails, diagnose and fix before reporting the scaffold as complete.

---

## Append-Only Discipline

Every touch-point edit in steps 3–4 is an **append** (add lines at the end of the relevant block).
**Never modify or delete an existing line** in a touch-point file.

This discipline is what makes the fork survive upstream rebases:

- Upstream rebases replay Plane CE commits on top of the fork base. An append at the end of an existing block lands cleanly; a modification to an upstream-owned line creates a conflict that must be manually resolved.
- `docs/FORK.md` mandates this. Each touch-point's annotation in the workload source files reads: "append-only include — FORK.md touch-point N".

**Verification before any touch-point write:**

1. Run `node .claude/scripts/plane-classify-path.cjs <path>` on the target file.
2. Confirm `"category": "touch-point"` in the JSON output.
3. Only then append. Never prepend, never modify, never delete.

If the classifier returns `"category": "core"`, that file is NOT a touch-point and must not be edited. Report and stop.

---

## Verify

After completing all steps, confirm:

- [ ] `apps/api/plane/<name>/apps.py` exists with `name="plane.<name>"` and `label="<name>"`
- [ ] `apps/api/plane/<name>/migrations/0001_initial.py` exists
- [ ] `apps/api/plane/<name>/models.py` has no columns on core models (`Issue`, `Page`, etc.)
- [ ] TP1 (`common.py` INSTALLED_APPS) has `"plane.<name>"` appended in the in-house block
- [ ] TP2 (`urls.py` urlpatterns) has the new `path("api/<name>/", ...)` appended
- [ ] TP6 (`extended.ts` + `apps/web/package.json`) updated if `needs-frontend = yes`
- [ ] `CLAUDE.md` "Custom features" has the new one-line entry
- [ ] `.claude/skills/_shared/references/fork-convention.md` `forkApps` array includes `"<name>"`
- [ ] **CI covers the new tests:** `python3 .claude/scripts/plane-fork-test-paths.py` exits 0 and its
      output includes `plane/<name>` (proves the app is both registered and discoverable — a green CI
      run does NOT prove its tests executed)
- [ ] **Closed-loop classifier check:** `node .claude/scripts/plane-classify-path.cjs apps/api/plane/<name>/models.py` returns `"category": "custom-app"` (proves Step 5 registration took effect; not just that the array text was edited)
- [ ] `.claude/plane-propagation-queue.md` has the new TODO block
- [ ] `python manage.py makemigrations --check --dry-run` exits 0
- [ ] `python manage.py check` exits 0
- [ ] `pnpm check` exits 0 (if `needs-frontend = yes`)

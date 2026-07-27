# Plan — Workload: Estimate-Input Placement + Per-Person Capacity & Overload

**Target:** `The1Studio/plane` @ `company-main` (fork). **Base:** already at upstream `v1.3.1` (no rebase due).
**Created:** 2026-07-25
**Builds on:** the EXISTING fork workload feature (`apps/api/plane/workload/` app + `packages/workload-ext/` package). This is a **delta**, not a rebuild.

## FORK.md compliance (LOAD-BEARING — every task obeys this)
All new backend code → the existing **`plane/workload/` app** (own `migrations/`; NEVER touch `plane/db/migrations/`; NO new columns on core models). All new frontend code → the fork-owned **`@plane/workload-ext`** package. The only core web edits allowed are the **documented fenced touch-points** (issue `sidebar.tsx`, and — if chosen — peek `properties.tsx`), each marked `The1Studio fork (SP2 workload)`. No `@plane/*` sealed-package edits. `makemigrations --check` + isolation audit gated by `company-main-ci.yml`. → **Zero core-model / core-migration edits in this plan.**

---

## Scope — two independent deltas

- **Delta A (frontend-only):** move the existing "Estimated hours" sidebar field to sit **next to the Start date / Due date** rows.
- **Delta B (backend + frontend):** add a **per-person weekly capacity** baseline and an **overload signal** ("over") to the per-person Workload matrix.

They share no files and can ship independently / in parallel.

---

## Delta A — Reposition the Estimated-hours input next to the dates (sidebar + peek)  `[S ~0.4d]`

**Grounded facts** (`apps/web/core/components/issues/issue-detail/sidebar.tsx`, company-main):
- Rows are a flat list of `<SidebarPropertyListItem>` inside the `space-y-2.5` container (line 169). Order today: State → Assignees → Priority → Created-by → **Start date (224-242)** → **Due date (244-268)** → Estimate dropdown (270) → **Estimated-hours workload field (291-320)** → Progress (324).
- The estimate field is fenced: `{/* SP2 workload estimate — fork touch-point exception */}` (291) wrapping `<SidebarPropertyListItem>` (292-320); its state+handlers live at 98-162; reads `useWorkload().estimateData[issueId]?.hours`, writes via `workloadStore.updateEstimate(...)` on blur.
- Row layout wrapper: `common/layout/sidebar/property-list-item.tsx` (30-unit label col + grow control) — the estimate row already matches the date rows visually.

**Task:** relocate the fenced estimate block (291-320) to **immediately after the Due-date row** (`</SidebarPropertyListItem>` at 268) and **before** the Estimate dropdown (270). Keep the fence comments; move the block whole. No logic/handler changes — pure JSX reorder within the same file.

**Task 2 (D-A1 = both):** add the workload Estimated-hours field to **peek** `apps/web/core/components/issues/peek-overview/properties.tsx` next to its date rows (Start 146-164 / Due 166-190), placed right after the Due-date block and before the stock Estimate dropdown (192-209). Peek has **no** workload field today, so this is a NEW fenced touch-point: import `useWorkload` + the estimate control (reuse the sidebar's input pattern / a shared `workload-ext` component if one is extracted), fenced with `The1Studio fork (SP2 workload)`. Reads/writes the same shared workload store (SSOT with sidebar + grid).

**Verify:** in BOTH sidebar and peek, order reads … Start date → Due date → **Estimated hours** → (Estimate dropdown). Field reads/writes via the shared store in both. `pnpm typecheck` green.

---

## Delta B — Per-person capacity + overload

### B1 — Backend: `WorkloadCapacity` model + migration  `[S ~0.5d]`
**Owns:** `apps/api/plane/workload/models.py` — add a second model mirroring `WorkloadEstimate`'s plain-`models.Model` + denormalized-FK pattern (models.py:18-62):
```python
class WorkloadCapacity(models.Model):
    id = UUIDField(pk, default=uuid4)
    member = FK(settings.AUTH_USER_MODEL, CASCADE, related_name="workload_capacities")
    workspace = FK("db.Workspace", CASCADE, related_name="workload_capacities")
    project = FK("db.Project", null=True, blank=True, CASCADE, related_name="workload_capacities")  # null = workspace-wide
    weekly_hours = FloatField(validators=[MinValueValidator(0), MaxValueValidator(MAX_HOURS)])
    created_by / created_at / updated_at   # mirror WorkloadEstimate
    class Meta: db_table="workload_capacities"; constraints=[UniqueConstraint(member, workspace, project)]
```
- Migration `apps/api/plane/workload/migrations/0002_workloadcapacity.py` (latest is `0001_initial`; deps `("workload","0001_initial")`, `("db","0001_initial")`, `swappable_dependency(AUTH_USER_MODEL)`).
- `serializers.py` — add `WorkloadCapacitySerializer` (validate `weekly_hours` ≥ 0 ≤ MAX_HOURS; mirror estimate serializer).

**Verify:** `makemigrations --check` clean; capacity row round-trips; `unique_together(member, workspace, project)` enforced.

### B2 — Backend: capacity CRUD endpoints (app + public /api/v1)  `[S ~0.5d]`
**Owns:** `apps/api/plane/workload/views.py` (shared `capacity_get/put/delete` handlers mirroring `estimate_get/put/delete` at 120-176, `update_or_create` keyed on member+workspace[+project]) + `WorkloadCapacityEndpoint` class (per-verb role gates: PUT/DELETE = ADMIN; GET = ADMIN/MEMBER); `api_views.py` public mirror; `urls.py` + `api_urls.py` add `workspaces/<slug>/workload-capacity/`.
**Verify:** app + `/api/v1` capacity GET/PUT/DELETE work; permission gates enforced; `test_api_routing.py`-style route asserts pass.

### B3 — Backend: capacity proration + overload in the matrix  `[M ~1d]`  ⚠ trickiest
**Owns:**
- `apps/api/plane/workload/aggregation.py` — new **pure** helper `capacity_for_period(weekly_hours, period_key, granularity) -> float` (unit-testable, no ORM; mirrors the pure-cents pattern). Proration per **D-B1 = ÷5 workdays**: day = `weekly/5` if the period date is Mon–Fri else `0`; week = `weekly`; month = `weekly × (workdays_in_calendar_month / 5)`. Add a module docstring noting the calendar-spread vs workday-capacity mismatch (weekend-spanning estimates accrue hours on 0-capacity days).
- `apps/api/plane/workload/service.py` — add `_resolve_capacities(owner_ids, slug, scope)` (mirror `_resolve_owners` at 197-226); in the row-building loop (310-324) inject into each row: `"capacity_buckets": {period: cap}` and `"over": {period: bucket_hours > cap}` (+ a row-level `"total_over": total > sum(caps)`). Response shape (337-345) otherwise unchanged — additive fields only.

**Verify:** a member with weekly capacity 40 and 45h assigned in a week bucket → `over[period]=true`; day/week/month proration correct; members without a capacity row → `capacity_buckets` empty, `over` all false (graceful). `test_aggregation_pure.py` covers proration; `test_workload_db.py` covers injected output.

### B4 — Frontend: thread capacity/over through the package  `[S ~0.5d]`
**Owns (`packages/workload-ext/`):**
- `types.ts` — extend `TWorkloadRow` (3-8) with `capacity_buckets?`, `over?`, `total_over?`; add `TWorkloadCapacity` for CRUD.
- `service.ts` — capacity CRUD methods mirroring `getEstimate`/`putEstimate` (45-94); matrix response flows capacity fields through automatically (`getWorkload` returns response as-is).
- `store.ts` — capacity observable + `updateCapacity` action (mirror `updateEstimate` 338-368).
- `i18n.ts` — add `matrix.capacity`, `matrix.over_capacity` (etc.) to `WORKLOAD_STRINGS` (fork-owned; the ONLY string home).
- App-side hook `apps/web/core/hooks/store/use-workload-estimate.ts` — add a capacity-edit selector hook (FORK.md places selector hooks app-side, not in the package).

**Verify:** `pnpm typecheck` green; capacity fields typed end-to-end.

### B5 — Frontend: render capacity + overload in the matrix  `[M ~1d]`
**Owns:** `packages/workload-ext/src/WorkloadMatrix.tsx`:
- Per-cell hours render (175-179) → conditional over-capacity color (amber/red) when `row.over[period]`.
- Assignee-name cell (174) → per-person weekly-capacity badge ("cap 40h") + an "over" chip when `row.total_over`.
- Optional capacity-edit control (admin) inline or via `WorkloadFilters.tsx`; a "show over-capacity only" toggle in the filter row (46-141).

**Verify:** matrix shows "assigned / cap / over" per person; over buckets colored; scope/granularity switches keep proration correct; points-less/capacity-less members render cleanly (no color, no badge).

---

## Decisions — ALL RESOLVED (confirmed with user 2026-07-25)
- **D-A1 — Peek overview parity → BOTH.** Reposition/add the Estimated-hours field next to the dates in the sidebar **and** peek `properties.tsx` (two fenced touch-points). See Delta A.
- **D-B1 — Capacity proration basis → ÷5 workdays.** Daily cap = weekly/5 (Mon–Fri; weekends = 0). Week bucket = weekly. Month bucket = weekly × (workdays-in-month / 5). ⚠ Estimates spread across **calendar** days (incl. weekends) in `spread_estimate`, so a weekend-spanning issue accrues hours on days with 0 workday-capacity — **document this mismatch** in `aggregation.py` + surface in tests (R2).
- **D-B2 — Capacity scope → workspace-wide per member.** `WorkloadCapacity(member, workspace, project=null)`. `project` FK kept nullable for a future per-project override; v1 always writes `project=null`.
- **D-B3 — Who sets capacity → ADMIN only.** PUT/DELETE gated to ADMIN; GET = ADMIN/MEMBER (all with access view it read-only).
- **D-B4 — Overload display → both.** Per-bucket over-capacity cell coloring **and** a row-level `total_over` chip.

## Risk Assessment
| Risk | L | I | Score | Mitigation |
|------|---|---|-------|------------|
| R1 Month-bucket proration (ISO weeks in a calendar month) miscomputed → wrong "over" | 3 | 4 | **12** | Pure `capacity_for_period` unit tests for edge months (e.g. 2026-12 spanning 2027-W01); document the weeks-in-month rule |
| R2 Proration basis (÷5 vs ÷7) mismatched with estimate spread → confusing overload | 3 | 3 | 9 | D-B1 decision + a documented note in aggregation.py; align tests to the chosen basis |
| R3 Sidebar reorder (Delta A) collides with an upstream change to sidebar.tsx on next tag-rebase | 2 | 2 | 4 | Keep the moved block fenced + minimal (it already IS a touch-point; rerere handles it) |
| R4 Capacity FK to AUTH_USER_MODEL of a removed member | 2 | 2 | 4 | `on_delete=CASCADE` on member; matrix already skips inactive/bot owners |
| R5 isolation-audit false-flags new workload-ext edits | 1 | 2 | 2 | `@plane/workload-ext` already allowlisted in the audit (FORK.md note) |

## Timeline
| Phase | Effort | Notes |
|-------|--------|-------|
| A Reposition estimate field | S (~0.25d) | FE-only, independent |
| B1 Capacity model + migration | S (~0.5d) | — |
| B2 Capacity CRUD endpoints | S (~0.5d) | after B1 |
| B3 Proration + overload (matrix) | M (~1d) | after B1; ⚠ R1/R2 |
| B4 FE thread-through | S (~0.5d) | after B3 contract |
| B5 FE render | M (~1d) | after B4 |
| **Total** | **~3.75d** | Delta A parallel to all of B; critical path B1→B3→B4→B5 |

## Parallel-safe decomposition (for `/t1k:team cook`)
| Owner | Files (zero-overlap) | Depends on |
|-------|----------------------|------------|
| A — Sidebar + peek | `issue-detail/sidebar.tsx`, peek-overview `properties.tsx` (both fenced touch-points) | — |
| B-backend | `workload/{models,serializers,views,api_views,urls,api_urls,aggregation,service}.py`, `workload/migrations/0002_*`, `workload/tests/*` | — |
| B-frontend | `workload-ext/{types,service,store,i18n}.ts`, `workload-ext/WorkloadMatrix.tsx`, `workload-ext/WorkloadFilters.tsx`, app `use-workload-estimate.ts` | B-backend (response contract) |

**Contract (crosses B-backend ↔ B-frontend):** matrix row gains additive fields `capacity_buckets: {period: hours}`, `over: {period: bool}`, `total_over: bool`; capacity CRUD payload `{member, workspace, project|null, weekly_hours}`. Pin before fan-out.

## Cook handoff
`/t1k:team cook .claude/plans/workload-capacity-overload-plan.md`  (Delta A + B-backend run in parallel; B-frontend after the backend contract lands.)

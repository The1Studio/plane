# Plan: Time-Based Estimates + Per-Person Workload (day/week/month)

**Status:** v3 (10-round validated; ready pending 4 product confirmations in §0)
**Target repo:** forked Plane CE `The1Studio/plane` @ `company-main` — `apps/api` (Django) + `apps/web` (Next.js)
**Author:** Claude (with tuha) · **Date:** 2026-06-19

> **v2→v3 (Wave-2 fixes):** RE-ARCHITECTED to a self-contained `plane/workload/` Django app per `docs/FORK.md` (NO core `Issue` column, NO core serializer/migration/`@plane/*` edits). Fixed CRITICAL cross-project leak; exclude bot + inactive-member owners; exclude cancelled/(completed) by default; tolerance-based reconciliation (float drift at response boundary); quantize-on-write; `0` vs null; stand up frontend test infra + add factories + hypothesis; MEMBER privacy policy; throttling; rollout/feature-flag/adoption-precondition; MCP+SDK propagation to sibling repos; DoD checklist.

---

## 0. PRODUCT DECISIONS — CONFIRMED (2026-06-19)

1. **Estimate input location = issue sidebar.** A numeric "Estimated hours" field on the core issue-detail sidebar → an **explicit documented core touch-point exception** beyond FORK.md's 6 (accepted higher rebase cost for better UX). It writes to the app-local estimate endpoint (§4.2) and reads via the app-local GET (estimate lives in the `workload` app table, NOT a core serializer).
2. **State inclusion = exclude `cancelled` + `completed` by DEFAULT** (revised 2026-06-19). Default workload = remaining/planned work (`state__group` in `backlog,unstarted,started`), the correct signal for "spot overload". Cancelled = phantom work; completed = done. The `state_group` param **overrides** the default (e.g. pass `completed` for a historical "what did people carry" view). `issue_objects` still also excludes triage/archived/draft/deleted.
3. **Owner = skip to next active human.** Earliest active, non-bot assignee; skip inactive/bot; none → Unassigned bucket. (As §3.1.)
4. **Privacy = all members see all** (within accessible projects). No per-row self-restriction; the cross-project access-intersection (§4.4) is still enforced.

---

## 1. Locked scope

| Decision          | Choice                                                                                                    |
| ----------------- | --------------------------------------------------------------------------------------------------------- |
| Estimate unit     | Free numeric **hours** (`FloatField`), quantized to 2 dp on write                                         |
| Storage           | **`WorkloadEstimate` table in a NEW `plane/workload/` app** — NOT a core `Issue` column (FORK.md DB rule) |
| Multi-assignee    | **One owner** = earliest active, non-bot assignee                                                         |
| Bucketing         | **Spread evenly across `start_date → target_date`**, clipped to window                                    |
| Capacity baseline | **None** — raw hours per person/period (see §11 product-gap note)                                         |
| Output            | Per-person × {day, week, month}, workspace-scoped tab                                                     |

**Out of scope:** logged/actual time, timesheets, capacity/leave, overload coloring, per-assignee splits, billing, backfill, activity-feed tracking, parent/child estimate roll-up (estimates summed flat per issue).

---

## 2. Architecture & database (re-architected per `docs/FORK.md`)

### 2.1 Why a separate app (non-negotiable)

`docs/FORK.md` "Isolation convention — LOAD-BEARING" + the `company-main-ci.yml` gate require: **new backend code = new Django app; no new columns on core models; never edit `plane/db/migrations/` or `@plane/*`.** Only 6 core touch-points are allowed. Precedent apps: `ai_ext/`, `clickup_migrate/`. → Build `apps/api/plane/workload/`.

### 2.2 New app layout — `apps/api/plane/workload/`

`apps.py`, `models.py`, `serializers.py`, `views.py`, `urls.py`, `aggregation.py`, `migrations/0001_initial.py`, `tests/`.

### 2.3 Model — `WorkloadEstimate` (own table, own migration)

```python
class WorkloadEstimate(ProjectBaseModel):          # inherits workspace/project/created_by/soft-delete
    issue = models.OneToOneField("db.Issue", on_delete=models.CASCADE, related_name="workload_estimate")
    hours = models.FloatField(validators=[MinValueValidator(0), MaxValueValidator(10000)])
    class Meta:
        db_table = "workload_estimates"
        indexes = [models.Index(fields=["project"])]   # table is small (only estimated issues)
```

- `FloatField` (house convention; zero `DecimalField` in codebase). Precision handled in app logic (§3.3) + quantize-on-write (§4.2).
- **OneToOne to core `Issue`** — cross-app FK; pin dependency to a `db` migration that exists in the adopted tag (FORK.md). `on_delete=CASCADE` so deleting an issue removes its estimate.
- Migration lives in `plane/workload/migrations/0001_initial.py` → **never collides with upstream `db` numbering**; the v2 `0122/0123` collision risk is eliminated.
- The table only ever holds estimated issues → inherently the small/selective set; no partial index on the huge `issues` table needed.

### 2.4 Core schema (read-only context, unchanged)

`Issue.start_date`/`target_date` (`issue.py:146-147`, `DateField(null=True)`), `IssueAssignee` (`issue.py:337`, `ordering=("-created_at",)` DESC ⚠️, soft-delete), `IssueManager`=`issue_objects` (excludes triage/archived/draft+deleted). `User.is_bot` (`user.py:115`). `Project.timezone`. **None edited.**

### 2.5 "Spread over range" ≠ GROUP BY (confirmed)

`build_chart.py:153` groups one issue→one bucket and hardcodes `Count` (line 179). Cannot fan hours across days. We build our own `aggregation.py`; `build_chart.py` untouched.

---

## 3. Semantics

### 3.1 Owner — earliest **active non-bot** assignee (explicit ASC subquery)

Model default ordering is DESC → must override. Resolve via correlated `Subquery`/`OuterRef` (NOT the M2M join — that fans one issue into N rows and triple-counts):

```python
earliest = IssueAssignee.objects.filter(
    issue=OuterRef("issue_id"), deleted_at__isnull=True,
    assignee__is_bot=False,
    # active membership: assignee ∈ ProjectMember(project, is_active=True)
).order_by("created_at", "assignee_id")
```

- Exclude `is_bot` (every modern analytics query does; `advance.py:68,75`). Exclude members no longer active on the project (membership removal is soft `is_active=False`, `project/member.py:296`; IssueAssignee rows are NOT cleaned up). **DECISION 0.2:** if earliest is inactive → next active assignee; none → "Unassigned/Former" bucket.
- `owner_id IS NULL` → Unassigned bucket (counted).

### 3.2 Spread rule

`H` = estimate hours. `start`&`target` present, `start≤target` → spread across `[start,target]` inclusive, `N=(target-start).days+1`; **per_day computed on full N, never the clipped window.** `start` missing → all on `target` (N=1). `target` missing → **Unscheduled** bucket. `start>target` (dirty; rejected by core serializer on write but possible via import/partial-update) → single day on `target` + `meta.dirty_date_count`. `H` null/≤0 → excluded (see §3.7).

### 3.3 Distribution — largest-remainder (Hamilton), exact in integer cents

`cents=round(H*100)`; `base=cents//N`; `rem=cents-base*N`; each day gets `base`, first `rem` days +1 cent. `sum(day_cents)==cents` exactly. (Quantize-on-write §4.2 ensures stored `H` already equals `cents/100`, so no write-time precision loss.)

### 3.4 Window clipping

`overlap_start=max(start,date_from)`, `overlap_end=min(target,date_to)`; emit only days in `[overlap_start,overlap_end]` if non-empty; span entirely outside window → contributes 0 to buckets AND 0 to Unscheduled (it has a target).

### 3.5 Reconciliation invariant (tolerance-based — float boundary)

Integer cents are exact, but the API emits float hours and source `H` are float8 → cross-row sums drift ~1e-12. **Invariant:** `abs(sum(buckets)+unscheduled − sum(H)) < 0.005` (half-cent) **for fully-windowed issues**; clipped issues contribute exactly their overlap-day cents. Tests assert tolerance, not exact float equality.

### 3.6 Period keys

day `YYYY-MM-DD`; week ISO via `date.isocalendar()` → `f"{iso_year}-W{iso_week:02d}"` (handles 2026-12-31→`2027-W01`); month `YYYY-MM`. No tz shift of stored dates (calendar arithmetic is tz-independent). "Current period" highlight uses viewing-user tz (workspace route spans multiple project tzs).

### 3.7 Zero vs null

`H=0` (explicit zero) → excluded from buckets; tracked in `meta.zero_estimate_count` separately from `issues_no_estimate` (null). Aggregation filters `hours__gt=0`.

---

## 4. Backend (`apps/api/plane/workload/`)

### 4.1 Model + migration — §2.3. `0001_initial` (atomic). Index in same migration (new small table, not the hot `issues` table → no concurrent-build needed).

### 4.2 Estimate read/write serializer + endpoint (app-local — NOT core serializers)

- `WorkloadEstimateSerializer`: `hours` field with `validate_hours` → reject negative; **quantize to 2 dp** (`round(value,2)`) so stored value == cents/100.
- Endpoints (app-local, no core edit): `GET/PUT workspaces/<str:slug>/projects/<uuid:project_id>/issues/<uuid:issue_id>/workload-estimate/`. Upsert on PUT.
- Permission `@allow_permission([ROLE.ADMIN, ROLE.MEMBER])` (project level). **DECISION 0.4 / GUEST:** estimate write = MEMBER+ only (do not rely on core `creator=True` GUEST path).

### 4.3 Aggregation — `aggregation.py`

`compute_workload(base_qs, granularity, date_from, date_to) -> {periods, rows, unscheduled, meta}`. Driving queryset = `WorkloadEstimate.objects` (small) `.select_related("issue")`, filter `hours__gt=0`, issue alive via `issue__` mirror of `issue_objects` filters (deleted/archived/draft/triage). **State default (DECISION 0.2):** when `state_group` param absent → filter `issue__state__group__in=["backlog","unstarted","started"]` (exclude cancelled + completed). When `state_group` provided → use exactly those groups (override, e.g. historical `completed`). Validate `state_group` values against the allowed group set. Annotate owner (§3.1). Python distribution (§3.3)+clip(§3.4)→sparse buckets. Escape hatch (SQL `date_trunc` overlap math, O(issues×periods) not per-day `generate_series` fan-out) documented, not built; if built, `granularity`→server-side literal map only (no interpolation).

### 4.4 Workload endpoint + URL (app-local, mounted via touch-point 2)

- Routes: `workspaces/<str:slug>/workload/` and `.../projects/<uuid:project_id>/workload/` (exact converters, trailing slash, kwargs `slug`/`project_id` load-bearing for decorator).
- **Permissions:** workspace → `@allow_permission([ADMIN,MEMBER], level="WORKSPACE")`; project → `@allow_permission([ADMIN,MEMBER])` (PROJECT). **GUEST excluded.**
- 🔴 **CRITICAL access fix:** workspace route must **intersect** `project_ids` (and default scope) with the caller's accessible projects:
  `accessible = ProjectMember.objects.filter(member=user, workspace__slug=slug, is_active=True).values_list("project_id", flat=True)` (ADMIN bypass to all). `project_ids` provided → `requested ∩ accessible`; else scope to `project_id__in=accessible`. **Never `workspace__slug` alone** (that leaks per-person load for private projects the caller isn't on). Tests: member-of-P1 querying P2 → empty; member-of-none → empty.
- **DECISION 0.4 privacy = all members see all** within accessible projects → **no** per-row self-restriction. (The cross-project intersection above is the only access boundary.)
- Params: `granularity=day|week|month` (req); `date_from`/`date_to` (req, `date.fromisoformat`); optional `project_ids`/`assignee_ids`/`state_group` (comma-split + `filter_valid_uuids`).
- Validation → `400 {"error":...}`: missing req; bad granularity enum (allow-list); unparseable date; inverted range; span over cap.
- **Span caps:** day≤92, week≤366, month≤730. **Row guard:** unfiltered workspace route, matched count >50,000 → 400 (cheap count). **Throttle:** `ScopedRateThrottle` (Plane has throttle infra) — distribution loop is sync CPU.
- Response: `{granularity,date_from,date_to,periods[],rows[{assignee_id|null,assignee_name,buckets{sparse},total}],unscheduled[{assignee_id,hours}],meta{issues_counted,issues_no_estimate,zero_estimate_count,issues_unscheduled,unscheduled_ratio,dirty_date_count,truncated}}`.
- **Caching + invalidation:** Short-TTL Redis cache (60–300s) keyed by all params, **namespaced per workspace** via a version stamp: `workload:{workspace_id}:v{N}:{param_hash}`. The estimate write endpoint (§4.2) and any issue date/state/assignee/delete change that affects workload **bumps `N`** (`INCR workload:{workspace_id}:version`), instantly orphaning all stale keys for that workspace — so "I just set 8h and the matrix didn't update" cannot happen. TTL is then only a backstop, not the freshness boundary. Bump on: estimate PUT/delete, and (acceptable-coarser) issue `start_date`/`target_date`/`state`/assignee/soft-delete writes — wire via the workload app's signals on `WorkloadEstimate` + an `Issue` post-save signal scoped to the relevant fields (signal lives in the app, no core edit). If wiring the core-issue signal is undesirable, fall back to short TTL (≤60s) for the matrix and **always** bust on estimate writes (the common case). FE may send `Cache-Control: no-cache` to force-refresh after a known mutation.

### 4.5 Tests — `plane/workload/tests/` (harness exists: `pytest.ini`, `conftest.py`, factory-boy)

Add `IssueFactory`, `IssueAssigneeFactory`, `WorkloadEstimateFactory` (missing today — only User/Workspace/Project factories exist). Cases: even spread; single-day; unscheduled; clip partial; **span fully outside window → 0**; null & **`0` excluded**; **earliest active non-bot owner** (verify ASC, skip bot, skip inactive); unassigned; soft-deleted assignee ignored; dirty start>target (+ partial-update inversion); **tolerance reconciliation (10h/3d, 100-issue accumulation)**; ISO week Monday + **year-boundary (2026-12-31)**; month boundary; **leap-year span**; **state default: cancelled + completed excluded when no `state_group`; `state_group=completed` override includes completed; invalid `state_group` → 400**; boundaries **span-cap exact (92/93,366/367,730/731)** + **row-guard exact (50000 pass/50001 fail/0→empty)**; inverted-range/bad-granularity 400; **guest-denied + non-member-denied + cross-project-leak-denied**; tie-break lower assignee_id; sparse reconciliation; cache TTL fresh-after-expiry; quantize-on-write (`H=3.14159`→3.14, `0.005` documented). **Property test (`hypothesis`, add to `requirements/test.txt`):** ∀H∈[0.01,10000],N∈[1,366]: `sum(distribute(H,N))==round(H*100)` and max-min ≤1 cent. EXPLAIN: driving table is small WorkloadEstimate; assert no seq-scan on `issues` via the join; thresholds: <500ms @10k estimates/30d-day-window.

---

## 5. Frontend (`apps/web`) — new package + extendedRoutes seam (no `@plane/*` edits)

### 5.1 Fork-owned package + types

New `packages/workload-ext/` (consumed `workspace:*`). **Do NOT edit `@plane/types`.** Define fork-owned types here: `TWorkloadResponse/Row/Granularity`, and `TIssueWithWorkload = TBaseIssue & { workload_estimate?: { hours: number } }` (intersection, core type untouched).

### 5.2 Route mount (touch-point 6, the ONLY core frontend touch)

Append a workload route entry to the empty `extendedRoutes` array in `apps/web/app/routes/extended.ts` (designed seam, merged via `mergeRoutes`). **Do NOT** edit core `analytics/tabs.tsx`/`analytics.ts`/`routes/core.ts`. → Workload is its own page under the extended seam (workspace-scoped). Project-scoped UI deferred.

### 5.3 Estimate input = issue sidebar (DECISION 0.1 — documented core exception)

- Add a numeric "Estimated hours" field on the core issue-detail sidebar, mirroring the `EstimateDropdown` block at `issue-detail/sidebar.tsx:191-203` (a `SidebarPropertyListItem` + number input). **This edits a core file → an explicit FORK.md touch-point exception** (listed in §6); accept the higher rebase cost.
- It does **not** use core serializers: on change → `PUT` the app-local estimate endpoint (§4.2); on load → `GET` it (or hydrate from the workload package store). Show always (not gated by `areEstimateEnabledByProjectId`, which governs the separate points feature).
- Rebase mitigation: keep the edit a single minimal, greppable hunk; if upstream churns `sidebar.tsx`, re-apply the hunk (it's self-contained).
- **Spreadsheet/board column = explicitly DEFERRED (not in v1).** Showing estimated-hours as a column in the issue list/spreadsheet would require editing core list serialization (`IssueListDetailSerializer.to_representation`, forbidden by FORK.md) or adding a core spreadsheet-column registry entry (`issue-layouts/spreadsheet/columns/index.ts`, another core touch) plus a per-row fetch from the app endpoint. For v1, hours are visible on the **sidebar** (set/read) and in the **workload matrix** (aggregated) only — NOT as a list column. If wanted later, the isolation-compliant path is: a column component in `packages/workload-ext/` that reads from the workload store (batch-fetch estimates for visible issues), registered via one more documented core touch-point. Tracked in §13.

### 5.4 Service + store + hook (in `packages/workload-ext` / app)

`WorkloadService extends APIService` (`super(API_BASE_URL)`, `.then(r=>r?.data).catch(e=>{throw e?.response?.data})`, `/api/workspaces/${slug}/workload/`). MobX store + **register in root store** + `use-workload` hook (if store lives in a fork package, wire via the app's store provider without editing core `root.store.ts` where possible; if registration requires a core edit, that is an additional touch-point to confirm).

### 5.5 Matrix UI

Build in the package; reuse `propel/src/table` primitives (don't hand-roll). Rows=people, cols=periods, cells=hours (sparse), row totals, Unscheduled column, granularity toggle, date-range+project/assignee filters, empty/loading/error. **Day granularity capped ~31–62 cols** (50×366 janks). Empty-state copy references `meta.unscheduled_ratio` ("N issues have no target date").

### 5.6 i18n

Nested **TS** keys (not JSON) — ship strings inside the package or a `workload` namespace; English required, others fall back.

### 5.7 Frontend test infra — DOES NOT EXIST (must stand up)

`apps/web` has **no** vitest/jest/playwright, zero test deps. Either (a) stand up `vitest`+`@testing-library/react`+`jsdom`+`msw` (config + setup file) and write component/service tests, or (b) MVP = manual `chrome-devtools` screenshot smoke only + typecheck/lint, and defer automated FE tests (state explicitly). Recommend (b) for v1 to avoid scope creep; (a) as fast-follow.

---

## 6. Fork-maintainability (aligned to `docs/FORK.md`)

All new code in `plane/workload/` (backend) + `packages/workload-ext/` (frontend). Core touch-points used: **#1** (`INSTALLED_APPS` append `"plane.workload"`), **#2** (`urls.py` append `path("api/", include("plane.workload.urls"))`), **#6** (`extendedRoutes` append for the workload tab).
**Documented exceptions beyond the 6 (accepted, listed here so a rebase conflict is expected not surprising):**

- `apps/web/.../issue-detail/sidebar.tsx` — the estimated-hours input (DECISION 0.1). Single self-contained hunk.
- Root-store registration for the workload store, IF the FE store can't be provided without it (confirm in 5.4; prefer the package's own provider to avoid this).
  No `# fork:` markers (FORK.md uses separation, not annotation). Re-run `makemigrations --check` after rebase (CI gate). FK pins to current adopted `db` migration.

## 7. Phases (`/t1k:cook`)

0. **Confirm §0 decisions** (AskUserQuestion).
1. **App scaffold + model + migration** — `plane/workload/` skeleton, `WorkloadEstimate`, `0001_initial`, register touch-point #1. Verify `makemigrations --check`, migrate scratch DB.
2. **Estimate endpoint** — serializer (quantize), GET/PUT view, urls, touch-point #2. Verify CRUD + quantize tests.
3. **Aggregation + workload endpoint** — `aggregation.py`, view, access-intersection, caps/guard/throttle. Verify §4.5 suite + property tests + EXPLAIN green.
4. **FE package + types + route** — `packages/workload-ext/`, extendedRoutes (#6), service/store/hook. Verify typecheck/lint, page loads.
5. **Estimate input + matrix UI + i18n** (per 0.1). Verify screenshot smoke; FE tests per 5.7.
6. **E2E + reconciliation** — seed via factories, hit **workspace** route, assert matrix + tolerance invariant + EXPLAIN. Both servers run.
7. **MCP + SDK + CLAUDE.md propagation** — §9.

## 8. Verify

Backend `cd apps/api && python manage.py makemigrations --check --dry-run && pytest plane/workload`; `migrate` scratch. FE `pnpm typecheck && pnpm lint`; chrome-devtools screenshot.

## 9. MCP / SDK / docs propagation (standing process — see §12)

Sibling forks in `/mnt/Work/1M/15. Plane/` (all `The1Studio/*`):

- **`plane-mcp-server`** (Python, `plane_mcp/`) — add tools: `set_issue_workload_estimate`, `get_workload` (the new endpoints; generic issue tools won't carry estimate since it's a separate endpoint, not an Issue field). **Action: open issue/PR there.**
- **`plane-node-sdk` / `plane-python-sdk`** — add bindings for the 3 new endpoints. **Action: issue/PR each.**
- **`plane-claude-plugin`** — add a skill/doc entry for the feature.
- **`docs` / `developer-docs`** — API + user docs for estimate + workload.
- **`plane-deploy` / `helm-charts`** — only if a new env var (none planned).
  These are **separate repos** — track via issues; do NOT edit them from this repo's PR (kit-PR boundary).

## 10. Open risks / confirm at cook

§0 decisions; FE test-infra choice (5.7); root-store registration touch-point; avg issue span (Python-vs-SQL aggregation); whether project-scoped FE view is in v1.

## 11. Product-value note (honest gap)

User goal = "spot overload," but locked "no capacity line" means the matrix shows hours **without a reference point** — it answers _who has how many hours when_, not _who is overloaded_. Defensible MVP; the capacity line is the natural v2 that closes the original goal. **Confirm a baseline-less matrix is acceptable for v1.**

## 12. Adoption precondition & rollout

- **Precondition:** the calendar feature is meaningful only if teams populate `target_date`. ClickUp→Plane migrations often lack dates → matrix may be empty day-1. `meta.unscheduled_ratio` makes this self-diagnosing; surface it in the empty state.
- **Day-1:** 100% of existing issues have no estimate (no backfill) → feature populates as hours are entered. Communicate this.
- **Feature flag:** gate the tab/route behind a flag (Plane has flag infra) for staged rollout. Decide on/off default.
- **Discoverability:** where users find the input + tab; admin enablement; help copy.

## 13. Definition of Done

Must-have: app + model + 3 endpoints; access-intersection + guest/cross-project tests green; aggregation correctness + property + tolerance reconciliation green; workspace workload tab renders with real data; estimate settable per 0.1; EXPLAIN no seq-scan on issues; English i18n; rebase touch-points ≤ the listed set; MCP/SDK propagation issues filed. Accepted-deferrals: project-scoped FE view; automated FE tests (if 5.7-b); capacity line; backfill; **spreadsheet/board estimate column** (sidebar + matrix only in v1, §5.3).

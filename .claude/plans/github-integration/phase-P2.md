# Phase P2 — Status Automation

**Goal:** drive Plane work-item state from GitHub PR lifecycle, using a **service-token
internal API call** (NOT raw ORM) so every side-effect (`IssueActivity`, notifications,
outbound webhook) fires. Transitions are governed by `StateTransitionConfig` (global default

- per-project override) and protected by a bot-actor loop guard.

**Effort:** M · **Blocks:** P4 · **Blocked by:** P0, P1.

---

## Transition rules (default; overridable per project)

| GitHub event                                              | Condition                            | Target state (group)                                                           |
| --------------------------------------------------------- | ------------------------------------ | ------------------------------------------------------------------------------ |
| `pull_request` `opened`                                   | PR references a work item (P1 parse) | **In Progress** (`started`)                                                    |
| `pull_request` `ready_for_review` (or `review_requested`) | linked                               | **In Review** (a `started`-group state named/ordered for review; configurable) |
| `pull_request` `closed` + `merged=true`                   | linked via a **closing word** (P1)   | **Done** (`completed`)                                                         |

Done-state resolution: `State.objects.filter(project_id=, group="completed").first()`
(`StateGroup` enum `db/models/state.py:14-20`). "In Progress"/"In Review" map to configured
state names per project, falling back to the first `started`-group state.

---

## Deliverables / file ownership

| File                                                        | Purpose                                                                                                                                                                                     |
| ----------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `github_ext/models.py` (+`StateTransitionConfig` finalized) | `scope ∈ {global, project}`, `project` FK null, `rules` JSON mapping event→state-name. Project row overrides global. (Table already declared in P0's 0001; if fields change, add `0002_*`.) |
| `github_ext/services/state_transition.py`                   | Resolve config (project override → global) → resolve target state → **call internal API** with service token.                                                                               |
| `github_ext/bgtasks/transition_task.py`                     | `@shared_task` consuming PR events from dispatch; applies transition; loop-guard.                                                                                                           |
| `github_ext/views/config.py`                                | CRUD for `StateTransitionConfig` (get/set global + per-project) — mirrors `ai_ext/views/config.py` permission pattern (`allow_permission([ROLE.ADMIN])`). Feeds P4 MCP tools.               |
| `github_ext/urls.py` (append)                               | mount config endpoints under the existing `api/github/` prefix (no new core touch-point).                                                                                                   |
| `github_ext/tests/{test_transition,test_config}.py`         | Transition + config tests.                                                                                                                                                                  |

---

## Concrete steps

1. **`StateTransitionConfig` resolve:** `resolve_config(project_id)` = project-scope row if
   present else global row else built-in default table above. Return the event→state-name map.
2. **Service-token transition (trap #4 fix — the core of P2):**
   - Provision a **bot user + service `APIToken`** (`is_service=True`, workspace-bound) —
     reuse `WorkspaceIntegration.actor` + `api_token` FK slots (`db/models/integration/base.py`)
     or create in `services/state_transition.py` bootstrap. Store the token reference in
     `GithubInstallation.config` / `WorkspaceIntegration.config` JSON (**no new column**).
   - Apply the state change with an **HTTP PATCH to Plane's own internal work-item API**
     (`PATCH /api/workspaces/<slug>/projects/<pid>/issues/<iid>/`) carrying header
     `X-Api-Key: <service token>`. This routes through `api_authentication.py:24-52`, gets
     `ServiceTokenRateThrottle`, and fires `IssueActivity` + notifications + outbound webhook
     for free. **NEVER `issue.save()` inside `github_ext`.**
   - Alternative documented in the brainstorm (manual `issue_activity.delay` +
     `model_activity.delay`) is the fallback ONLY if the internal-API call is infeasible; MVP
     uses the API path.
3. **Bot-actor loop guard:** the internal-API PATCH is performed by the bot user → its resulting
   outbound webhook (and any GitHub echo) is tagged with the bot actor. `transition_task` (and
   P0 dispatch) **drop any event whose originating actor == our bot / carries our provenance
   stamp**. Prevents: our Done-transition → outbound webhook → GitHub → inbound → re-transition.
4. **Config CRUD (`views/config.py`):** `GET/PUT /api/github/config/` (global, admin-only) and
   `GET/PUT /api/github/projects/<pid>/config/` (project override). Validate state names exist
   in the project. These endpoints are what P4 exposes via MCP (`get/set StateTransitionConfig`).
5. **Wire dispatch → transition_task** for `pull_request` events (P0 left these as no-ops).

---

## Risk assessment (P2-local)

| Risk                                                                        | L   | I   | Score  | Mitigation                                                                                                                                                                 |
| --------------------------------------------------------------------------- | --- | --- | ------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Raw `issue.save()` silently skips activity/notify/webhook (trap #4)**     | 3   | 5   | **15** | Service-token internal-API PATCH ONLY. Code-review + grep gate forbids `.save(` on core issue in `github_ext`. Test asserts an `IssueActivity` row exists post-transition. |
| **Echo loop** (our transition → webhook → GitHub → inbound → re-transition) | 3   | 4   | 12     | Bot-actor guard drops self-originated events; provenance stamp on transition. Test simulates the echo and asserts no second transition.                                    |
| Target state missing in project (no `completed`-group state)                | 2   | 3   | 6      | Resolve `.first()`; if null → log + skip (no crash), surface in config validation.                                                                                         |
| Config override ambiguity (both global + project match)                     | 2   | 2   | 4      | Deterministic precedence: project row wins; documented + tested.                                                                                                           |
| Service token leaked / over-scoped                                          | 2   | 5   | 10     | Bot user least-privilege, workspace-bound, `is_service=True`; token stored in config JSON only, never logged.                                                              |
| Rate-limit / API failure mid-transition                                     | 2   | 3   | 6      | Celery `max_retries=2` + backoff; failed transition logged, no partial state.                                                                                              |

**Risk ≥ 15 (trap #4) mitigation is mandatory before P2 starts** — the service-token path is
the phase's central design, gated by a test asserting `IssueActivity` creation.

---

## Test list (`pytest plane/github_ext`)

- PR `opened` linked → issue moves to In Progress **and** an `IssueActivity` row was created
  (proves side-effects fired — the trap #4 gate).
- PR `ready_for_review` → In Review.
- PR `closed merged=true` with `Fixes PROJ-1` → Done (`completed` group).
- PR `closed merged=false` → **no** transition.
- Merged PR **without** a closing word → no Done transition (only closing-word merges close).
- **Echo guard:** an inbound event whose actor == bot → dropped, no transition.
- Config: project override beats global; PUT validates state name exists; admin-only enforced.
- Missing `completed` state in project → skip, logged, no exception.

## Gates

- `plane-isolation-audit` clean (P2 adds no core touch-point — config endpoints mount under
  the P0 `api/github/` include).
- `makemigrations --check --dry-run` (only if `StateTransitionConfig` fields changed → `0002_*`).
- `python manage.py check`.
- `pytest plane/github_ext`.

## Rollback

Transitions are API calls — reverting = stop enqueuing `transition_task`. Config rows are
additive; `StateTransitionConfig` delete is clean. Bot user/token can be deactivated
(`is_active=False`) without schema change.

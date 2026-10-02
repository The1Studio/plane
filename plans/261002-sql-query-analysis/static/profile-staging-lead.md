# Staging SQL profile — workspace `cocos` (sv-2 / plane-staging-app)

Captured by the lead on 2026-10-02 against the live staging stack (`plane-staging-app-api-1`, image tag `staging` @ `9025c0a9f0`).
Method: Django test client + `CaptureQueriesContext`, real data (5 workspaces, 109 projects, 6906 issues). Raw: `profile.json`, `profile-duplicates.json`, `profile-workload.json`, `profile-transcript.txt`.

## Per-endpoint ranking (45 probed, 26 HTTP 200)

| status | queries | dup | sql_ms | wall_ms | KB | endpoint |
|---:|---:|---:|---:|---:|---:|---|
| 200 | 1009 | 932 | 242 | 1869.7 | 783 | `/api/workspaces/cocos/issues/` |
| 200 | 13 | 0 | 113 | 151.5 | 9 | `/api/workspaces/cocos/default-analytics/` |
| 200 | 6 | 0 | 100 | 257.6 | 306 | `/api/workspaces/cocos/modules/` |
| 200 | 4 | 0 | 36 | 94.8 | 2 | `/api/workspaces/cocos/projects/37270556-e1a2-4622-a1a1-b8eaf628e17` |
| 200 | 9 | 0 | 27 | 140.1 | 19 | `/api/workspaces/cocos/projects/37270556-e1a2-4622-a1a1-b8eaf628e17` |
| 200 | 11 | 0 | 25 | 57.4 | 0 | `/api/workspaces/cocos/advance-analytics/` |
| 200 | 4 | 0 | 24 | 47.9 | 8 | `/api/workspaces/cocos/project-stats/` |
| 200 | 10 | 0 | 20 | 50.3 | 0 | `/api/workspaces/cocos/advance-analytics-charts/` |
| 200 | 4 | 0 | 19 | 37.4 | 8 | `/api/workspaces/cocos/advance-analytics-stats/` |
| 200 | 6 | 0 | 14 | 27.5 | 38 | `/api/workspaces/cocos/projects/` |
| 404 | 7 | 0 | 13 | 42.1 | - | `/api/workspaces/cocos/projects/37270556-e1a2-4622-a1a1-b8eaf628e17` |
| 200 | 6 | 1 | 12 | 34 | 0 | `/api/workspaces/cocos/projects/37270556-e1a2-4622-a1a1-b8eaf628e17` |
| 200 | 8 | 0 | 12 | 34.8 | 0 | `/api/workspaces/cocos/projects/37270556-e1a2-4622-a1a1-b8eaf628e17` |
| 200 | 4 | 0 | 11 | 22.5 | 0 | `/api/workspaces/cocos/cycles/` |
| 200 | 4 | 0 | 11 | 47.4 | 0 | `/api/workspaces/cocos/projects/37270556-e1a2-4622-a1a1-b8eaf628e17` |
| 200 | 4 | 0 | 8 | 22.8 | 1 | `/api/workspaces/cocos/projects/37270556-e1a2-4622-a1a1-b8eaf628e17` |
| 200 | 5 | 0 | 7 | 28.4 | 57 | `/api/workspaces/cocos/members/` |
| 200 | 4 | 0 | 7 | 29.3 | 80 | `/api/workspaces/cocos/states/` |
| 200 | 4 | 0 | 6 | 26.1 | 1 | `/api/workspaces/cocos/projects/37270556-e1a2-4622-a1a1-b8eaf628e17` |
| 200 | 4 | 0 | 6 | 17.4 | 0 | `/api/workspaces/cocos/projects/37270556-e1a2-4622-a1a1-b8eaf628e17` |
| 200 | 4 | 0 | 5 | 14.9 | 0 | `/api/workspaces/cocos/projects/37270556-e1a2-4622-a1a1-b8eaf628e17` |
| 400 | 3 | 0 | 4 | 9.2 | - | `/api/workspaces/cocos/analytics/` |

## Dominant defect — per-issue `states` N+1 (UPSTREAM, not fork-fixable)

`/api/workspaces/cocos/issues/` executed **1009 statements, only 77 distinct** — undefined duplicates — in 3678.5 ms.
Every repeated statement is `SELECT ... FROM "states" WHERE ...` — one lookup per serialized issue instead of a joined/prefetched state.

| repeats | statement |
|---:|---|
| x97 | `SELECT "states"."created_at", "states"."updated_at", "states"."created_by_id", "states"."updated_by_id", "states"."deleted_at", "states"."id", "states` |
| x82 | `SELECT "states"."created_at", "states"."updated_at", "states"."created_by_id", "states"."updated_by_id", "states"."deleted_at", "states"."id", "states` |
| x78 | `SELECT "states"."created_at", "states"."updated_at", "states"."created_by_id", "states"."updated_by_id", "states"."deleted_at", "states"."id", "states` |
| x58 | `SELECT "states"."created_at", "states"."updated_at", "states"."created_by_id", "states"."updated_by_id", "states"."deleted_at", "states"."id", "states` |
| x46 | `SELECT "states"."created_at", "states"."updated_at", "states"."created_by_id", "states"."updated_by_id", "states"."deleted_at", "states"."id", "states` |
| x42 | `SELECT "states"."created_at", "states"."updated_at", "states"."created_by_id", "states"."updated_by_id", "states"."deleted_at", "states"."id", "states` |

This route is mounted by core `plane.app.urls` (`plane/urls.py:18`), i.e. **upstream** — `docs/FORK.md` forbids editing it, so it is reported, not fixed.

## Fork-owned workload endpoints

| endpoint | status | queries | dup | sql_ms | wall_ms | KB |
|---|---:|---:|---:|---:|---:|---:|
| `/api/workspaces/cocos/workload/?granularity=week&date_from=2026-08` | 200 | 14 | 1 | 142 | 2852.3 | 478 |
| `/api/workspaces/cocos/workload/?granularity=day&date_from=2026-09-` | 200 | 14 | 1 | 104 | 204.2 | 149 |
| `/api/workspaces/cocos/projects/37270556-e1a2-4622-a1a1-b8eaf628e171/workload/?granularity=week&date_from=2026-08` | 200 | 14 | 1 | 24 | 52 | 23 |
| `/api/workspaces/cocos/workload-rollups/` | 400 | 3 | 0 | 3 | 8.3 | 0 |

The workspace workload response (490 KB, weekly/Oct window) spends 142 ms in SQL but 2852.3 ms wall — the cost is Python-side materialization/aggregation, not SQL. The only duplicate is the `workspace_members` admin EXISTS, issued twice (matches the workload lane's finding 1).

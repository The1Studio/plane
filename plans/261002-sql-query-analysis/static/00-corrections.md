# Corrections — verified against source by the lead

These override the lane reports below where they conflict. `/home/frostbun/Projects/plane/plane` at `9025c0a9f0`.

## CORRECTION 1 — `fork-views-ext.md` top finding #1 is a FALSE POSITIVE. Do not rank it.

The report claims `views_ext/views.py:172-174`:

```python
.prefetch_related(Prefetch("issue_assignee", queryset=IssueAssignee.objects.all()))
.prefetch_related(Prefetch("label_issue", queryset=IssueLabel.objects.all()))
.prefetch_related(Prefetch("issue_module", queryset=ModuleIssue.objects.all()))
```

performs an unscoped global table scan, cost O(total tenant rows).

That is wrong. Django constrains every reverse-FK `Prefetch` queryset to the parent
instances. Verified in the pinned interpreter:

```
apps/api/.venv-profile/lib/python3.12/site-packages/django/db/models/fields/related_descriptors.py:299-301
            queryset = _filter_prefetch_queryset(
                queryset._next_is_sticky(), self.query_field_name, instances
            )
:94-96
def _filter_prefetch_queryset(queryset, field_name, instances):
    predicate = Q(**{f"{field_name}__in": instances})
```

So the executed SQL carries `WHERE issue_id IN (<parent ids>)`; the explicit
`queryset=...objects.all()` is redundant, not a full-table scan. Real cost is
O(page size), as intended.

Consequence for synthesis: drop this item from the ranked fix list entirely. It is
**not** an optimization opportunity, and any change to those three lines is cosmetic.
Randomly re-ranking other findings into the top slot is not a substitute — rank the
remaining items on their own measured/estimated merit.

## CORRECTION 2 — scope of what can actually be changed

The apply phase may modify ONLY fork-owned code: the Django apps `ai_ext`,
`cascade_ext`, `clickup_migrate`, `github_ext`, `issue_defaults_ext`, `project_ext`,
`views_ext`, `workload`, `workload_cache`, `workspace_ext` (and their own
`migrations/`), plus `packages/*-ext`. Everything under `apps/api/plane/app/**`,
`apps/api/plane/api/`, `apps/api/plane/db/`, `apps/api/plane/space/`,
`apps/api/plane/utils/`, `apps/api/plane/authentication/`, `apps/api/plane/license/`,
`apps/api/plane/bgtasks/`, and `apps/api/plane/db/migrations/` is UPSTREAM and must be
reported only, never edited (`docs/FORK.md`).

Rank the fork-safe items above equivalent upstream ones, and mark every upstream-only
finding `fork-safe: no` in the final report.

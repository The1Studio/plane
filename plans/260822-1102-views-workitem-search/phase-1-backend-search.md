# Phase 1 — Backend `search` parameter on the Views endpoint

**Parent plan:** [`plan.md`](plan.md) · **Depends on:** nothing · **Parallel-safe with:** Phase 2

## Goal

`GET /api/views-ext/workspaces/<slug>/issues/` accepts a `search` query parameter and narrows its
result set by work-item name, work-item number, and project identifier — before pagination, after
permission scoping.

## Pinned contract (do not rename or re-interpret)

```
Query parameter name:  search
Type:                  string
Semantics:             empty or absent  ->  no filtering applied
Match:                 plane.utils.issue_search.search_issues(query, queryset)
Applied:               after permission scoping, before pagination
```

Phase 2 emits this exact parameter name from the client. It is the only thing the two lanes share.

## File ownership

This phase owns these paths and no others:

- `apps/api/plane/views_ext/views.py`
- `apps/api/plane/views_ext/tests/test_grouped_view_issues.py`

## Prior art — reuse, do not reimplement

`apps/api/plane/utils/issue_search.py:14-24` already implements exactly the match rule D2 asks for:

```python
def search_issues(query, queryset):
    fields = ["name", "sequence_id", "project__identifier"]
    q = Q()
    for field in fields:
        if field == "sequence_id" and len(query) <= 20:
            sequences = re.findall(r"\b\d+\b", query)
            for sequence_id in sequences:
                q |= Q(**{"sequence_id": sequence_id})
        else:
            q |= Q(**{f"{field}__icontains": query})
    return queryset.filter(q).distinct()
```

Three core call sites already use it (`app/views/search/issue.py:28`, and the same Q inlined in
`app/views/search/base.py:87-91` and `api/views/issue.py:2227-2236`). Import it; do not write a new
`Q()`. Matching core here is what makes `PLANE-79` behave the same in this box as in the command
palette.

## Implementation

### 1.1 — Add the search helper and call site (~1h)

In `apps/api/plane/views_ext/views.py`:

1. Import the helper alongside the existing `plane.utils` imports:
   `from plane.utils.issue_search import search_issues`.
2. Add a module-level helper next to the other module-level helpers
   (`parse_date_range` at `:101`, `apply_issue_annotations` at `:129`):

   ```python
   def apply_issue_search(queryset, request):
       """The1Studio fork (views-search) — narrow by work-item name / number / project identifier.

       An empty or absent `search` is NOT a filter: it returns the queryset untouched. Never
       let a blank box become a hidden exclusion.
       """
       query = request.query_params.get("search", "").strip()
       if not query:
           return queryset
       return search_issues(query, queryset)
   ```

3. Call it inside `GroupedWorkspaceViewIssuesEndpoint.get`, **after** the permission filter is
   applied (`views.py:284`) and **before** `issue_queryset_grouper` (`views.py:294`).

**Why a module-level helper rather than an inline two-liner:** the sibling
`GroupedWorkspaceUserProfileIssuesEndpoint` (`views.py:349`) is the out-of-scope profile-pages
surface. Extracting now means adopting it there later is one call, not a copy — but do **not** wire
it into the profile endpoint in this phase (see plan.md § "Deliberately not in scope").

### 1.2 — Order-of-operations check (~30m)

Confirm by reading, and record the finding in the PR description:

- `search_issues` ends in `.distinct()`. Verify this does not conflict with the annotations applied
  by `apply_issue_annotations` (`views.py:129-167`) or with the `GroupedOffsetPaginator` count
  queries. If `.distinct()` interacts badly with the grouping annotations, the fix is to place the
  search call **before** `apply_issue_annotations`, not to drop `.distinct()` — dropping it
  reintroduces duplicate rows when a query matches both `name` and `project__identifier`.
- Confirm the search is applied to the queryset the paginator counts from, not only the one it
  slices — otherwise `total_count` reports the unsearched total and the UI shows a wrong count
  beside a correct list.

### 1.3 — Tests (~1.5h)

Append a `SearchTests(TransactionTestCase)` class to
`apps/api/plane/views_ext/tests/test_grouped_view_issues.py`, using that file's existing helpers
(`_user`, `_ws`, `_wmember`, `_project`, `_pmember`, `_state`, `_issue`) and its
`APIClient` + `force_authenticate` style. Do not introduce pytest — this app's suite is
`TransactionTestCase`.

Required assertions:

| Test                                 | Asserts                                                                                                     |
| ------------------------------------ | ----------------------------------------------------------------------------------------------------------- |
| `test_absent_search_unfiltered`      | No `search` param returns every visible item                                                                |
| `test_empty_search_unfiltered`       | `?search=` and `?search=%20` return **the same set** as no param — the "no filter means no filtering" guard |
| `test_matches_name_substring`        | Case-insensitive partial name match                                                                         |
| `test_matches_sequence_id`           | `?search=79` finds the item whose `sequence_id` is 79                                                       |
| `test_matches_project_identifier`    | `?search=PLANE` returns that project's items                                                                |
| `test_matches_full_identifier`       | `?search=PLANE-79` finds that item (the D2 headline behavior)                                               |
| `test_no_match_returns_empty`        | A term matching nothing returns an empty `results`, not an error and not everything                         |
| `test_respects_permission_scope`     | A guest who cannot see project B gets no B rows even when the term matches a B item                         |
| `test_total_count_reflects_search`   | `total_count` in the envelope is the **searched** total, not the unsearched one (guards 1.2)                |
| `test_search_composes_with_group_by` | `?search=…&group_by=priority` returns grouped results, each group filtered                                  |

`test_respects_permission_scope` is the one that must not be skipped: search runs on an
already-scoped queryset today, and this test is what keeps it that way if the call site ever moves.

## Success criteria

- [ ] `cd apps/api && python manage.py check` clean
- [ ] `cd apps/api && python -m pytest plane/views_ext/tests/ -q` — zero failures, all 10 new tests present and passing
- [ ] `cd apps/api && python manage.py makemigrations --check --dry-run` reports no changes
- [ ] `git diff --name-only` for this phase touches only the two files listed under File ownership
- [ ] The profile endpoint (`views.py:349`) is unchanged

## Notes

- `views_ext` is already listed in `forkApps`
  (`.claude/skills/_shared/references/fork-convention.md:65`), so the new tests are already selected
  by `company-main-ci.yml`. No registry edit is needed — unlike a brand-new fork app.
- No model, no migration, no core Python file is touched by this phase.

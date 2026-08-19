# Phase 1 — Backend: alphabetical row order, `Unassigned` pinned first

**Effort:** S (~2h) · **Depends on:** nothing · **Blocks:** phase 3

## Goal

`assemble_workload` returns `rows` ordered `Unassigned` first, then every other
member ascending by `assignee_name`, case-insensitively. The busiest-first
(`-total`) ordering is removed, not made optional (plan D2).

## Files owned

- `apps/api/plane/workload/service.py`
- `apps/api/plane/workload/tests/test_task_rows.py`
- `apps/web/core/components/workload/timeline/blocks.ts` — **docstring only**, see step 3

## Steps

1. **Replace the sort** at `service.py:516`:

   ```python
   rows.sort(key=lambda r: (r["assignee_id"] is not None, r["assignee_name"].casefold()))
   ```

   `assignee_id is None` sorts `False` before `True`, which pins the `Unassigned`
   row first without special-casing the display name — a real member literally
   named "Unassigned" would still sort under U rather than stealing the pinned
   slot. `casefold()` (not `lower()`) so non-ASCII display names compare the way
   the reader expects.

   Replace the sort's rationale comment with one stating the new rule and that
   `Unassigned` is pinned by id, not by name.

2. **Add a regression test** in `tests/test_task_rows.py`. That module is a
   `TransactionTestCase` suite driving real `compute_workload` calls against
   Postgres with explicit ORM fixtures — follow that style (its helpers already
   build workspaces, members and issues; do not introduce a mocked variant
   alongside them). Assert:
   - the `assignee_id is None` row is `rows[0]`;
   - the remaining `assignee_name` values equal their own `casefold`-sorted copy;
   - a high-`total` member with a late-alphabet name sorts _after_ a low-`total`
     member with an early-alphabet name (this is the assertion that would have
     passed under the old sort only by accident, so build the fixture so the two
     orders genuinely differ).

3. **Correct the stale docstring** in
   `apps/web/core/components/workload/timeline/blocks.ts` — `buildWorkloadBlocks`
   currently says rows arrive "already sorted server-side by `-total,
assignee_name` — service.py `rows.sort`". Update it to the new rule. No logic
   changes: the builder consumes `data.rows` in order and is agnostic to what
   that order means.

## Verification

```bash
cd apps/api && python manage.py check
# workload module tests — see memory note backend-test-db-isolation for the
# interpreter pin / pgvector / per-runner Postgres setup
pytest plane/workload/tests/test_task_rows.py -q
```

## Success criteria

- `rows[0]["assignee_id"] is None` whenever an unassigned bucket exists.
- Remaining rows are `casefold`-ascending by `assignee_name`.
- No `total`-derived term remains in the sort key.
- New test fails against the pre-change sort (verify by stashing the service.py
  edit once — a test that passes both ways proves nothing).

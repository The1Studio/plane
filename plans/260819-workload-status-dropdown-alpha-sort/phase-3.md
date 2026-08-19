# Phase 3 — Propagation

**Effort:** S (~0.5h) · **Depends on:** phase 1

## Goal

Satisfy the standing propagation rule in `CLAUDE.md`: a behaviour change to a
fork-owned endpoint reaches the downstream sibling repos before the feature is
done.

## Files owned

- `CLAUDE.md` (this repo)
- An **issue** on `The1Studio/plane-mcp-server` — never an edit from this repo's PR

## Steps

1. **`CLAUDE.md`** — extend the `workload/` bullet under "Custom features
   (fork-owned)" with one clause: workload rows are returned `Unassigned`-first
   then alphabetical by assignee name, replacing the previous busiest-first order.

2. **`plane-mcp-server` issue.** `plane_mcp/tools/workload.py:107` documents the
   row shape (`rows[{assignee_id, assignee_name, buckets, total}]`) but makes no
   ordering claim, so nothing there is _wrong_ today — the issue asks for the new
   ordering to be stated explicitly in `get_workload`'s docstring, so an agent
   reading the tool description knows the first row is the unassigned bucket and
   not the busiest member. Reference this plan and the `service.py` change.

3. **SDKs** — `plane-node-sdk` / `plane-python-sdk` carry no workload row-order
   contract; no change. State that explicitly in the issue rather than leaving it
   unmentioned.

## Success criteria

- `CLAUDE.md` workload bullet mentions the ordering.
- An issue URL exists on `The1Studio/plane-mcp-server`.
- No sibling repo is edited from this repo's PR.

# Phase 3 — Documentation + verification

**Plane:** [PLANE-83](https://plane.the1studio.org/infrastructure/projects/2eae4e83-f715-4e4b-8753-cdc289bbe37f/issues/244963da-b3dd-4a11-abe0-f1a579559348) — 1h

**Effort:** S (1h) · **Depends on:** phases 1–2

## Ownership

- `docs/FORK.md` — one new row in § "Frontend core-edit exceptions (no upstream seam)"
- `CLAUDE.md` — one clause on the existing `workload/` bullet

## Steps

1. **`docs/FORK.md`** — add a row for the new hook, immediately after the existing
   `use-workload-estimate.ts` row so the two selector/editor hooks read together:

   | File                                                              | What                                                                                                               | Why no seam                                                                                                          |
   | ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------- |
   | `apps/web/core/hooks/store/use-workload-estimate-editor.ts` (NEW) | `useWorkloadEstimateEditor` — the shared debounce/Enter/blur commit lifecycle behind every "Estimated hours" input | Same as the selector hook: a `packages/workload-ext` hook is context-agnostic and cannot read core's `useWorkload()` |

   The three component rows already exist and their descriptions stay accurate — no edit needed
   there.

2. **`CLAUDE.md`** — extend the `workload/` bullet's description of the estimate inputs with
   the new commit timing: _"the inputs commit 800 ms after typing stops, on Enter (focus
   retained), or on blur; an empty field commits as 0 only on Enter or blur."_ This is the
   behavior an API/UI consumer would otherwise have to discover by experiment.

3. **No sibling-repo propagation.** Record explicitly in the PR description that the standing
   propagation rule was evaluated and does not apply: no endpoint, field, or response shape
   changed, so `plane-mcp-server`, `plane-node-sdk`, `plane-python-sdk`, and
   `plane-claude-plugin` need nothing. Silence here would read as an oversight rather than a
   decision.

4. **Verify.**
   - `pnpm check` (repo-wide lint + typecheck).
   - `python manage.py check` and `makemigrations --check --dry-run` in `apps/api` — expected
     to be no-ops for a frontend-only change; run them anyway so the CI gate is not the first
     thing to find out.
   - `plane-isolation-audit` — confirms the new hook file lands inside the allowlisted
     core-edit set and that no `@plane/*` upstream package was touched.

## Success criteria

- `pnpm check` green.
- `plane-isolation-audit` reports no new violation.
- `docs/FORK.md` and `CLAUDE.md` both describe behavior that matches what phases 1–2 shipped.

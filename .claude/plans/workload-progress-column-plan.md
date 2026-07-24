# Plan — Visual progress column + bar (match ClickUp look) in list/spreadsheet + item sidebar

**Status:** Draft — awaiting go-ahead.
**Owner:** company-main fork
**Feature:** Surface **progress** as a visual **bar + %** on every work item, in the
spreadsheet grid (own column), the list/kanban pill, and the item-detail sidebar — matching
the ClickUp "progress" column the team is used to. Extends the existing SP2 workload feature
(hours estimate + parent rollup).

## Locked decisions (from user)
1. **Match the ClickUp look** — visual bar + %, not just text. Both grid columns AND item sidebar.
2. **Leaf progress = state-group derived** (client-side, no backend): `completed → 100%`,
   `started → 50%`, `unstarted → 0%`, `backlog → 0%`, `cancelled → excluded (no bar / dash)`.
3. **Parent progress = existing hours-weighted rollup** (`TWorkloadRollup.percent`, already served
   by `GET /workload-rollups/`). A parent shows the rollup %, a leaf shows the state-derived %.

## Key architectural finding — this is FRONTEND-ONLY
- Every issue's `state_id` is already in the grid row + sidebar; `IState.group` (`@plane/types`)
  gives the state group via the existing states store. Leaf progress is a pure client-side map.
- Parent progress already comes from the backend rollup (`rollup.percent`, 0..1).
- ⇒ **No new API field, no new endpoint, no core model column, no migration.** The progress
  value is a display derivation over data the frontend already holds. Backend untouched.

## Fork-isolation (docs/FORK.md)
- **No `@plane/*` edits.** The state-group→% map, the `<ProgressBar>` component, and the
  progress selector live in `packages/workload-ext` (fork-owned, npm-scoped but ours).
- **Core edits = documented fork exceptions only**, same fenced pattern the hours column already
  uses (`The1Studio fork (SP2 workload)`), in the SAME spreadsheet files that already carry
  fork fences. A NEW fixed-append "Progress" column reuses the exact mechanism proven by the
  hours column (fixed append after the `spreadsheetColumnsList` loop → no `IIssueDisplayProperties`
  key needed → no `@plane/types` edit).
- No backend touch-points. `makemigrations --check` unaffected.

## Semantics (SSOT — one helper in workload-ext)
`leafProgress(stateGroup): number | null`
- `completed → 1.0` · `started → 0.5` · `unstarted → 0` · `backlog → 0` · `cancelled → null`
- `null` ⇒ render a dash / empty cell (no bar), consistent with cancelled being excluded from
  the hours rollup too.

`resolveProgress(issue, rollup, stateGroup): number | null`
- `rollup` present (is_parent) → `rollup.percent`
- else → `leafProgress(stateGroup)`
- One function, used by grid column + list pill + sidebar (no drift).

## Phases

### P1 — workload-ext primitives (fork-owned package)
- `packages/workload-ext/src/progress.ts` — `leafProgress()`, `resolveProgress()`, and a
  `toDisplayPercent()` reuse from i18n. Pure, unit-testable.
- `packages/workload-ext/src/ProgressBar.tsx` — the blue bar + `%` label (matches screenshot:
  filled track + right-aligned percent; dash when null). Theme-aware, width = `percent`.
- i18n strings for the progress label + a11y aria-label.
- Build the package (`tsdown`) so `dist/` is current for consumers.

### P2 — Spreadsheet "Progress" column (new fixed-append column)
- `columns/progress-column.tsx` (NEW) — `ProgressHeaderCell` + `ProgressBodyCell`, mirroring
  `estimated-hours-column.tsx`. Body cell reads `issue`, its rollup (from the workload store),
  and the state group (states store) → `resolveProgress` → `<ProgressBar>`.
- Wire fixed-append in `spreadsheet-header.tsx` + `issue-row.tsx` (append AFTER the existing
  Estimated-hours fixed column — two fork columns now, both documented exceptions).
- Rename/keep the hours column header to read like "Time estimate" if the team wants parity
  (optional; default keep "Estimated hours").

### P3 — Item-detail sidebar progress row
- In `issue-detail/sidebar.tsx`, add a **Progress** `SidebarPropertyListItem` (its own row, below
  the Estimated-hours field) rendering `<ProgressBar>` via `resolveProgress`. The existing hours
  field stays as-is (parent still shows `Σ Xh · Y%` text OR we drop the `· Y%` from the hours
  field now that progress has its own row — decide in review; default: keep hours field numeric,
  move % to the new Progress row for a clean split).

### P4 — List + Kanban pill (CE seam)
- Extend `ce/.../additional-properties.tsx` to render a compact `<ProgressBar variant="pill">`
  next to the hours pill, so list rows + kanban cards show progress too (same seam already used
  for the hours pill; shared with kanban by design — accept, as with hours).

### P5 — (Optional) footer hours total
- The screenshot shows a `421 h` total. If wanted, add a spreadsheet footer summing visible
  estimate hours (frontend aggregate; no backend). Flag: only if the team relies on it — default
  **defer** unless requested.

### P6 — Verify + ship
- `pnpm --filter web typecheck && pnpm --filter web lint` green; build workload-ext.
- Unit tests for `leafProgress`/`resolveProgress` (workload-ext).
- Browser E2E on `localhost:20080`: a completed leaf shows a full bar/100%, a started leaf ~50%,
  a backlog leaf 0%, a cancelled leaf a dash; a parent shows its hours-weighted rollup %; the
  Progress column and sidebar row both render; no console errors. (Needs a login.)
- `plane-isolation-audit` clean (only documented SP2 fences touched); `pnpm check`.
- Commits split by surface; push a feature branch → PR to company-main.

### P7 — Propagation (standing rule)
- Because leaf progress is a **frontend display derivation** with **no new API surface**, there
  is nothing new for the SDKs/MCP to bind. Update only: `CLAUDE.md` "Custom features" line +
  a short note in docs describing the state-group→% mapping (so consumers understand the UI %).
- If the team later wants progress in the API for reporting, that's a separate follow-up
  (server-side leaf-progress field) — out of scope here.

## Definition of Done
- Progress renders as a visual bar + % on every non-cancelled task in the spreadsheet column,
  the list/kanban pill, and the item sidebar; cancelled shows a dash.
- Leaf % follows the locked state-group map; parent % is the existing hours-weighted rollup.
- No `@plane/*` edits; core edits are documented FORK.md exceptions only; no backend/migration.
- typecheck/lint/build green; workload-ext unit tests green; isolation audit clean.
- `CLAUDE.md` + docs note the progress semantics.

## Open items to confirm in review (non-blocking)
- Keep `Σ Xh · Y%` in the hours field, or move % entirely to the new Progress row? (default: split)
- Include the footer hours total now (P5) or defer? (default: defer)
- "started → 50%" is a placeholder for the single in-progress group; if the team wants finer
  buckets (e.g. per named state) that's a small extension of `leafProgress`.

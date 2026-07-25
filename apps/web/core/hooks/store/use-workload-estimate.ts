/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 *
 * The1Studio fork (SP2 workload) — documented core-edit exception.
 * Listed in docs/FORK.md "Frontend core-edit exceptions".
 *
 * Selector hooks for per-issue workload estimates.  Lives in core so they can
 * call useWorkload() (the singleton store accessed via StoreContext), which
 * package hooks cannot do (they are context-agnostic).
 */

import { useEffect, useRef, useState } from "react";
import { reaction } from "mobx";
import type { TWorkloadRollup } from "@plane/workload-ext";
import { useWorkload } from "./use-workload";

// ── Per-issue selector ────────────────────────────────────────────────────────

/**
 * Returns the estimated hours and (when the issue is a parent) the computed
 * rollup for a single issue from the shared workload store.
 *
 * `hours` is `null` when no leaf estimate exists (either not yet fetched, the
 * backend has no record, or the issue is a parent — parents never carry a
 * leaf `hours` value). `rollup` presence is the parent signal: a non-null
 * `rollup` means this issue is a parent and its estimate field must render
 * read-only (plan §P4 item 5). The caller is responsible for triggering a
 * fetch (e.g. via useBulkWorkloadFetch, or fetchEstimate for a single issue)
 * before this hook will return non-null values.
 */
export function useWorkloadEstimate(issueId: string): { hours: number | null; rollup: TWorkloadRollup | null } {
  const store = useWorkload();
  const entry = store.estimateData[issueId];
  const rollup = store.rollupData[issueId] ?? null;
  return { hours: entry?.hours ?? null, rollup };
}

/**
 * Returns a member's workspace-wide weekly capacity (hours) from the shared
 * workload store. `null` when the member has no capacity row set, or when
 * `memberId` itself is null (e.g. an unassigned row). Pure selector — the
 * caller is responsible for triggering `store.fetchCapacities` (WorkloadMatrix
 * does this on mount).
 */
export function useWorkloadCapacity(memberId: string | null): number | null {
  const store = useWorkload();
  if (!memberId) return null;
  return store.capacities[memberId] ?? null;
}

// ── Bulk fetch effect ─────────────────────────────────────────────────────────

/**
 * Effect hook that triggers a single bulk fetch for all `issueIds` whose
 * estimates (and rollups) are not yet in the store. The estimates fetch is
 * guarded so it does not refire on every render — it only re-runs when the
 * stable join of issueIds changes (or workspaceSlug changes). The rollups
 * fetch additionally refires whenever the store's rollupInvalidationVersion
 * bumps (after a successful updateEstimate/deleteEstimate elsewhere) — see
 * plan §P4 item 3 "Invalidation".
 *
 * Intended usage: call once in the component that owns a page of rows (e.g.
 * SpreadsheetTable or a list-view container) passing the full set of visible
 * issue IDs.  The store deduplicates internally; repeated calls are cheap.
 */
export function useBulkWorkloadFetch(workspaceSlug: string, issueIds: string[]): void {
  const store = useWorkload();

  // Build a stable join-string key so the effect only fires when the actual
  // set of ids changes, not on every array identity change (common with derived
  // selectors that create a new array each render). Sort is on a copy — no mutation.
  // NOTE: .sort() on the spread copy, NOT .toSorted() — the repo tsconfig lib
  // predates ES2023, so tsc rejects toSorted (oxlint --fix rewrites it back if
  // allowed, which is how a type error once reached the branch unnoticed).
  // oxlint-disable-next-line unicorn/no-array-sort
  const joinedIds = [...issueIds].sort().join(",");

  // Track the previous values so we can skip the redundant estimates fetch
  // when nothing changed.
  const prevKey = useRef<string>("");
  const prevSlug = useRef<string>("");

  // Subscribe to the store's rollup-invalidation counter via a direct mobx
  // `reaction` rather than relying on the calling component being wrapped in
  // `observer` — list/blocks-list.tsx (a caller) is a plain function
  // component, so an observable read here would otherwise never trigger a
  // re-render there. Mirroring the value into local React state makes it a
  // normal effect dependency regardless of the caller's observer status.
  const [rollupInvalidationVersion, setRollupInvalidationVersion] = useState(store.rollupInvalidationVersion);
  useEffect(() => reaction(() => store.rollupInvalidationVersion, setRollupInvalidationVersion), [store]);

  useEffect(() => {
    if (!workspaceSlug || issueIds.length === 0) return;

    const isSameRequest = joinedIds === prevKey.current && workspaceSlug === prevSlug.current;
    prevKey.current = joinedIds;
    prevSlug.current = workspaceSlug;

    // Estimates: unchanged dedup semantics — skip when nothing changed.
    if (!isSameRequest) {
      store.fetchEstimatesBulk(workspaceSlug, issueIds).catch(() => {
        // Errors are written to store.error; no local handling needed.
      });
    }

    // Rollups: dispatched every time this effect runs (id/slug change OR a
    // rollupInvalidationVersion bump). fetchRollups no-ops per id already in
    // its own dedup set, so this is cheap when nothing actually changed.
    store.fetchRollups(workspaceSlug, issueIds).catch(() => {
      // Errors are written to store.rollupError; no local handling needed.
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceSlug, joinedIds, store, rollupInvalidationVersion]);
}

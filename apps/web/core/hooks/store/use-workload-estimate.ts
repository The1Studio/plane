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

import { useEffect, useRef } from "react";
import { useWorkload } from "./use-workload";

// ── Per-issue selector ────────────────────────────────────────────────────────

/**
 * Returns the estimated hours for a single issue from the shared workload store.
 *
 * Returns `null` when no estimate exists (either not yet fetched or the backend
 * has no record).  The caller is responsible for triggering a fetch (e.g. via
 * useBulkWorkloadFetch) before this hook will return a non-null value.
 */
export function useWorkloadEstimate(issueId: string): { hours: number | null } {
  const store = useWorkload();
  const entry = store.estimateData[issueId];
  return { hours: entry?.hours ?? null };
}

// ── Bulk fetch effect ─────────────────────────────────────────────────────────

/**
 * Effect hook that triggers a single bulk fetch for all `issueIds` whose
 * estimates are not yet in the store.  The effect is guarded so it does not
 * refire on every render — it only re-runs when the stable join of issueIds
 * changes (or workspaceSlug changes).
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
  const joinedIds = [...issueIds].sort().join(",");

  // Track the previous values so we can skip the fetch when nothing changed.
  const prevKey = useRef<string>("");
  const prevSlug = useRef<string>("");

  useEffect(() => {
    if (!workspaceSlug || issueIds.length === 0) return;

    // Skip if both slug and id-set are unchanged since the last run.
    if (joinedIds === prevKey.current && workspaceSlug === prevSlug.current) return;

    prevKey.current = joinedIds;
    prevSlug.current = workspaceSlug;

    // Fire-and-forget; the store handles deduplication and error state.
    store.fetchEstimatesBulk(workspaceSlug, issueIds).catch(() => {
      // Errors are written to store.error; no local handling needed.
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceSlug, joinedIds, store]);
}

import { useEffect } from "react";
import type { IWorkloadStore } from "./store";

/**
 * useWorkloadStore
 *
 * Thin pass-through — the store must be provided externally (via the app's
 * own React context or a module-level singleton). This avoids shipping a
 * React context inside the package itself, keeping the package context-agnostic.
 *
 * Usage:
 *   const store = useWorkloadStore(myStoreInstance);
 *   store.fetchWorkload(slug);
 */
export function useWorkloadStore(store: IWorkloadStore): IWorkloadStore {
  return store;
}

/**
 * useWorkloadData
 *
 * Calls `store.fetchWorkload` whenever `workspaceSlug` changes.
 * Wrap this in the component that owns the workload view; the store
 * is wired externally so the hook stays portable.
 *
 * Usage:
 *   useWorkloadData(store, workspaceSlug);
 */
export function useWorkloadData(store: IWorkloadStore, workspaceSlug: string): void {
  useEffect(() => {
    if (!workspaceSlug) return;
    store.fetchWorkload(workspaceSlug);
  }, [store, workspaceSlug]);
}

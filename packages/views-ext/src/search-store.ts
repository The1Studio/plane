// The1Studio fork (views-search)
//
// Ephemeral, per-view search-term store for the workspace Views tab. Resolves D3 (plan.md):
// the term must survive layout switches within one saved view but must NOT be persisted
// (no localStorage) or shared across views — an in-memory observable keyed by view id gives
// exactly that lifetime.
//
// Deliberately dumb: it holds a string and nothing else. No fetch, no service call, no
// reference to any issue store — the re-fetch on term change is Phase 3's job
// (plan.md § D4), and a store reference here would create a circular store dependency.
// Instantiated once from the root store (apps/web/ce/store/root.store.ts).

import { action, makeObservable, observable } from "mobx";

export interface IViewsSearchStore {
  /**
   * The active search term for `key`, or `""` when none has been set. Never returns
   * `undefined` — the consumer treats empty as "no filter" and must not need a null check.
   *
   * `key` is an OPAQUE STRING, not necessarily a view id. The workspace Views tab passes a bare
   * `globalViewId`; the project-scoped lists (Project Work Items, Module, Cycle, Project Views)
   * pass a composite `"<EIssuesStoreType>:<entityId>"` so that, say, a module and a cycle that
   * happened to share an id could never collide. Any caller-chosen scheme works as long as it is
   * stable for the surface and distinct across surfaces — the store never parses it.
   */
  getSearchQuery(key: string): string;
  setSearchQuery(key: string, query: string): void;
  clearSearchQuery(key: string): void;
}

export class ViewsSearchStore implements IViewsSearchStore {
  // observables
  /** Keyed by view id so switching between two saved views never carries a term across. */
  searchQueries: Record<string, string> = {};

  constructor() {
    makeObservable(this, {
      searchQueries: observable,
      setSearchQuery: action,
      clearSearchQuery: action,
    });
  }

  // computed-style read (kept as a method, matching IViewsSearchStore)
  getSearchQuery = (viewId: string): string => this.searchQueries[viewId] ?? "";

  // actions
  setSearchQuery(viewId: string, query: string): void {
    this.searchQueries[viewId] = query;
  }

  clearSearchQuery(viewId: string): void {
    delete this.searchQueries[viewId];
  }
}

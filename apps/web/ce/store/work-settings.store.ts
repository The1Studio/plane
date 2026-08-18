/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 *
 * The1Studio fork (workspace work settings) — new file.
 *
 * MobX-side counterpart to `useWorkSettings()`
 * (apps/web/core/hooks/store/use-work-settings.ts). React components read the
 * workspace work settings (max weekly hours, workdays, first day of week) via
 * that hook directly. `issue_calendar_view.store.ts` (Phase 5) is a MobX
 * store, not a component, so it cannot call a hook — this store exists
 * SOLELY to give that non-component consumer the same read path. Do not add
 * new component-side consumers here; use `useWorkSettings()` instead so
 * there remains exactly one fetch/PUT implementation.
 */

import { action, computed, makeObservable, observable, reaction, runInAction } from "mobx";
import type { TWorkSettings } from "@plane/types";
import { DEFAULT_WORK_SETTINGS } from "@/hooks/store/use-work-settings";
import type { RootStore } from "./root.store";

export interface IWorkSettingsStore {
  /** Never `undefined` — DEFAULT_WORK_SETTINGS until the first fetch resolves. */
  workSettings: TWorkSettings;
  /** Convenience accessor — mirrors `workSettings.week_start_day`. */
  weekStartDay: number;
  /** Fetches (once per slug; call again to force a refetch) the workspace's work settings. */
  fetchWorkSettings: (workspaceSlug: string) => Promise<void>;
}

export class WorkSettingsStore implements IWorkSettingsStore {
  workSettings: TWorkSettings = DEFAULT_WORK_SETTINGS;

  private rootStore: RootStore;
  /** Slug this store has already fetched (or is fetching) for — avoids a redundant re-fetch on every reaction fire. */
  private _fetchedForSlug: string | undefined;

  constructor(_rootStore: RootStore) {
    makeObservable(this, {
      workSettings: observable.ref,
      weekStartDay: computed,
      fetchWorkSettings: action,
    });

    this.rootStore = _rootStore;

    // Keep work settings current as the active workspace changes (including
    // the initial value once the router has resolved a slug).
    reaction(
      () => this.rootStore.router.workspaceSlug,
      (workspaceSlug) => {
        if (workspaceSlug) void this.fetchWorkSettings(workspaceSlug);
      },
      { fireImmediately: true }
    );
  }

  get weekStartDay(): number {
    return this.workSettings.week_start_day;
  }

  fetchWorkSettings = async (workspaceSlug: string): Promise<void> => {
    if (this._fetchedForSlug === workspaceSlug) return;
    this._fetchedForSlug = workspaceSlug;
    try {
      const res = await fetch(`/api/workspaces/${workspaceSlug}/work-settings/`, { credentials: "include" });
      if (!res.ok) return;
      const data = (await res.json()) as TWorkSettings;
      runInAction(() => {
        this.workSettings = data;
      });
    } catch {
      // Network/server failure — keep the last-known-good (or default)
      // workSettings, and allow a retry (e.g. on the next workspace switch
      // back to this slug) rather than getting stuck permanently unfetched.
      this._fetchedForSlug = undefined;
    }
  };
}

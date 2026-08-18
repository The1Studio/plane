/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 *
 * The1Studio fork (workspace work settings) — new file.
 *
 * Single read path for the workspace-wide work settings (max weekly hours,
 * workdays, first day of week) — see plans/260818-workload-workspace-settings/phase-4.md.
 * Consumed by the workspace settings page (this phase) AND, per plan.md, by
 * eight core web components in Phase 5 that currently read the per-user
 * `start_of_the_week` preference. Every one of those call sites goes through
 * THIS hook so there is exactly one place that knows the API shape.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { TWorkSettings } from "@plane/types";

const API_BASE = "/api";

/**
 * Mirrors apps/api/plane/workload/constants.py DEFAULT_* verbatim
 * (phase-0.md "Defaults"). Used as the hook's initial value and as the
 * fallback the hook NEVER falls away from — a consumer never sees
 * `undefined`, only these defaults while the first fetch is in flight.
 */
export const DEFAULT_WORK_SETTINGS: TWorkSettings = {
  max_weekly_hours: 40.0,
  workdays: [1, 2, 3, 4, 5],
  week_start_day: 1,
};

function workSettingsUrl(workspaceSlug: string): string {
  return `${API_BASE}/workspaces/${workspaceSlug}/work-settings/`;
}

/** Parses a DRF error body into one human-readable string, verbatim where possible. */
async function parseErrorResponse(res: Response): Promise<string> {
  const raw = await res.text();
  try {
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    if (parsed && typeof parsed === "object") {
      if (typeof parsed.error === "string") return parsed.error;
      // Serializer validation errors: { field: ["message", ...], ... }
      const messages = Object.entries(parsed).flatMap(([field, value]) => {
        const values = Array.isArray(value) ? value : [value];
        return values.map((v) => `${field}: ${String(v)}`);
      });
      if (messages.length > 0) return messages.join(" · ");
    }
  } catch {
    // Non-JSON error body — fall back to the raw text below.
  }
  return raw || `Request failed with status ${res.status}`;
}

export interface IUseWorkSettings {
  /** Never `undefined` — DEFAULT_WORK_SETTINGS until the first fetch resolves. */
  workSettings: TWorkSettings;
  /** True only for the initial GET; a subsequent PUT does not toggle this. */
  isLoading: boolean;
  /** Set when the GET fails; cleared on the next successful GET. */
  error: string | null;
  /**
   * Issues the PUT with `partial` merged onto the current snapshot.
   *
   * NOTE — the backend serializer requires ALL THREE fields on every PUT
   * (`WorkloadSettingsSerializer` is instantiated without `partial=True`,
   * apps/api/plane/workload/views.py `settings_put`). This function accepts
   * a partial update for caller convenience but always sends the full
   * merged object — callers do not need to know this.
   *
   * Resolves with the server's echoed (canonical, quantized) settings on
   * success. Rejects with the server's error text verbatim on a 4xx/5xx —
   * callers surface it directly rather than replacing it with their own copy.
   * Admin-gating is the caller's responsibility; this function does not check.
   */
  updateWorkSettings: (partial: Partial<TWorkSettings>) => Promise<TWorkSettings>;
  /** True while a PUT is in flight. */
  isUpdating: boolean;
}

export function useWorkSettings(workspaceSlug: string | undefined): IUseWorkSettings {
  const [workSettings, setWorkSettings] = useState<TWorkSettings>(DEFAULT_WORK_SETTINGS);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isUpdating, setIsUpdating] = useState(false);
  // Mirrors the latest workSettings without adding it as an effect dependency,
  // so updateWorkSettings always merges onto the freshest snapshot.
  const workSettingsRef = useRef(workSettings);
  workSettingsRef.current = workSettings;

  useEffect(() => {
    if (!workspaceSlug) return;
    let cancelled = false;

    async function load() {
      setIsLoading(true);
      setError(null);
      try {
        const res = await fetch(workSettingsUrl(workspaceSlug as string), { credentials: "include" });
        if (!res.ok) throw new Error(await parseErrorResponse(res));
        const data = (await res.json()) as TWorkSettings;
        if (cancelled) return;
        setWorkSettings(data);
      } catch (err: unknown) {
        if (cancelled) return;
        // GET never 404s (phase-0.md contract) — a rejection here is a real
        // network/server failure. Keep the last-known-good (or default)
        // workSettings rather than clearing it, so consumers never branch
        // on absence.
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }

    void load();

    return () => {
      cancelled = true;
    };
  }, [workspaceSlug]);

  const updateWorkSettings = useCallback(
    async (partial: Partial<TWorkSettings>): Promise<TWorkSettings> => {
      if (!workspaceSlug) {
        throw new Error("updateWorkSettings called with no workspaceSlug");
      }
      const merged: TWorkSettings = { ...workSettingsRef.current, ...partial };

      setIsUpdating(true);
      try {
        const res = await fetch(workSettingsUrl(workspaceSlug), {
          method: "PUT",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(merged),
        });
        if (!res.ok) throw new Error(await parseErrorResponse(res));
        const data = (await res.json()) as TWorkSettings;
        setWorkSettings(data);
        return data;
      } finally {
        setIsUpdating(false);
      }
    },
    [workspaceSlug]
  );

  return { workSettings, isLoading, error, updateWorkSettings, isUpdating };
}

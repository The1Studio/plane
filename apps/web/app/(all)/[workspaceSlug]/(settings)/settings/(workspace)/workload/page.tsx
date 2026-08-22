/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 *
 * The1Studio fork (workspace work settings) — new file.
 * Admin-only workspace settings page for the three workload work-settings
 * values (max daily hours, workdays, first day of week). See
 * plans/260818-workload-workspace-settings/phase-4.md.
 */

import { useEffect, useState } from "react";
import { observer } from "mobx-react";
import { useParams } from "react-router";
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import { Button } from "@plane/propel/button";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import type { TWorkSettings } from "@plane/types";
import { CustomSelect, Input } from "@plane/ui";
import { cn } from "@plane/utils";
// components
import { NotAuthorizedView } from "@/components/auth-screens/not-authorized-view";
import { PageHead } from "@/components/core/page-title";
import { SettingsContentWrapper } from "@/components/settings/content-wrapper";
import { SettingsHeading } from "@/components/settings/heading";
// hooks
import { useWorkSettings } from "@/hooks/store/use-work-settings";
import { useWorkspace } from "@/hooks/store/use-workspace";
import { useUserPermissions } from "@/hooks/store/user";
// local imports
import { WorkloadWorkSettingsHeader } from "./header";

const MAX_DAILY_HOURS_CEILING = 10000;

/** EStartOfTheWeek numbering (packages/types/src/users.ts) — SUNDAY = 0 .. SATURDAY = 6. */
const DAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const DAY_LABELS_FULL = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

function WorkloadWorkSettingsPage() {
  // params
  const { workspaceSlug } = useParams();
  const slug = workspaceSlug?.toString();
  // store hooks
  const { allowPermissions, workspaceUserInfo } = useUserPermissions();
  const { currentWorkspace } = useWorkspace();
  const { workSettings, isLoading, error, updateWorkSettings, isUpdating } = useWorkSettings(slug);

  // derived values
  const isAdmin = allowPermissions([EUserPermissions.ADMIN], EUserPermissionsLevel.WORKSPACE);
  const pageTitle = currentWorkspace?.name ? `${currentWorkspace.name} - Work settings` : undefined;

  // draft state — hydrated once from the first successful GET, then owned by the form.
  const [draft, setDraft] = useState<TWorkSettings>(workSettings);
  const [hasHydrated, setHasHydrated] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    if (!isLoading && !hasHydrated) {
      setDraft(workSettings);
      setHasHydrated(true);
    }
    // Only re-hydrate once — after that, the draft is form-owned so the admin's
    // in-progress edits are never clobbered by a background re-render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLoading, hasHydrated]);

  // validation — mirrors WorkloadSettingsSerializer (apps/api/plane/workload/serializers.py) verbatim.
  const isValidMaxHours =
    typeof draft.max_daily_hours === "number" &&
    !Number.isNaN(draft.max_daily_hours) &&
    draft.max_daily_hours >= 0 &&
    draft.max_daily_hours <= MAX_DAILY_HOURS_CEILING;
  const isValidWorkdays = draft.workdays.length > 0;
  const isValid = isValidMaxHours && isValidWorkdays;

  function toggleWorkday(day: number) {
    setSaveError(null);
    setDraft((prev) => {
      const isSelected = prev.workdays.includes(day);
      const nextWorkdays = isSelected
        ? prev.workdays.filter((d) => d !== day)
        : [...prev.workdays, day].sort((a, b) => a - b);
      return { ...prev, workdays: nextWorkdays };
    });
  }

  async function handleSave() {
    if (!isValid || !slug) return;
    setSaveError(null);
    try {
      const saved = await updateWorkSettings(draft);
      setDraft(saved);
      setToast({ type: TOAST_TYPE.SUCCESS, title: "Success!", message: "Work settings updated." });
    } catch (err: unknown) {
      // Surface the server's 400 text verbatim — do not replace it with a generic copy.
      setSaveError(err instanceof Error ? err.message : String(err));
    }
  }

  if (workspaceUserInfo && !isAdmin) {
    return <NotAuthorizedView section="settings" className="h-auto" />;
  }

  // Workday toggles are ordered starting at the currently-selected week_start_day,
  // wrapping around — not hardcoded Sunday-first (phase-4.md).
  const orderedDays = Array.from({ length: 7 }, (_, i) => (draft.week_start_day + i) % 7);

  return (
    <SettingsContentWrapper header={<WorkloadWorkSettingsHeader />}>
      <PageHead title={pageTitle} />
      <div className={cn("flex w-full flex-col gap-y-6", { "opacity-60": isLoading })}>
        <SettingsHeading
          title="Work settings"
          description="Configure the daily hour cap, workdays, and first day of the week used by workload capacity and the calendar across this workspace."
        />

        {error && <div className="rounded-md bg-danger-subtle px-3 py-2 text-13 text-danger-primary">{error}</div>}

        <div className="flex flex-col gap-2">
          <h4 className="text-body-sm-medium text-tertiary">Max daily hours</h4>
          <Input
            type="number"
            min={0}
            step={0.5}
            value={draft.max_daily_hours}
            onChange={(e) => setDraft((prev) => ({ ...prev, max_daily_hours: Number(e.target.value) }))}
            className="w-32"
            disabled={isUpdating}
            hasError={!isValidMaxHours}
          />
          {!isValidMaxHours && (
            <span className="text-13 text-danger-primary">
              Must be a number between 0 and {MAX_DAILY_HOURS_CEILING}.
            </span>
          )}
        </div>

        <div className="flex flex-col gap-2">
          <h4 className="text-body-sm-medium text-tertiary">Workdays</h4>
          <div className="flex flex-wrap items-center gap-1.5">
            {orderedDays.map((day) => {
              const isSelected = draft.workdays.includes(day);
              return (
                <button
                  key={day}
                  type="button"
                  aria-pressed={isSelected}
                  disabled={isUpdating}
                  onClick={() => toggleWorkday(day)}
                  className={cn(
                    "rounded-md border px-2.5 py-1 text-13 transition-colors",
                    isSelected
                      ? "border-accent-subtle bg-accent-subtle text-accent-primary"
                      : "border-subtle text-tertiary hover:bg-layer-transparent-hover"
                  )}
                >
                  {DAY_LABELS[day]}
                </button>
              );
            })}
          </div>
          {!isValidWorkdays && <span className="text-13 text-danger-primary">Select at least one workday.</span>}
        </div>

        <div className="flex flex-col gap-2">
          <h4 className="text-body-sm-medium text-tertiary">First day of week</h4>
          <CustomSelect
            value={draft.week_start_day}
            onChange={(value: number) => setDraft((prev) => ({ ...prev, week_start_day: value }))}
            label={DAY_LABELS_FULL[draft.week_start_day] ?? DAY_LABELS_FULL[0]}
            buttonClassName="border border-subtle bg-layer-2 !shadow-none !rounded-md w-48"
            input
            disabled={isUpdating}
          >
            {DAY_LABELS_FULL.map((label, day) => (
              <CustomSelect.Option key={label} value={day}>
                {label}
              </CustomSelect.Option>
            ))}
          </CustomSelect>
        </div>

        {saveError && (
          <div className="rounded-md bg-danger-subtle px-3 py-2 text-13 text-danger-primary">{saveError}</div>
        )}

        <div>
          <Button variant="primary" onClick={handleSave} disabled={!isValid || isUpdating} loading={isUpdating}>
            Save changes
          </Button>
        </div>
      </div>
    </SettingsContentWrapper>
  );
}

export default observer(WorkloadWorkSettingsPage);

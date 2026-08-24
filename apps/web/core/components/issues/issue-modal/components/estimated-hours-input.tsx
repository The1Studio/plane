/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 *
 * The1Studio fork (SP2 workload / work-item modal estimated hours) —
 * documented core-edit exception. Listed in docs/FORK.md "Frontend core-edit
 * exceptions".
 *
 * "Estimated hours" control for the Add-work-item modal's properties row.
 * Two sibling components, not one conditional body: `useWorkloadEstimateEditor`
 * needs an `issueId`, which does not exist in create mode, and a hook cannot
 * be called conditionally. `IssueEstimatedHoursInput` picks which sibling to
 * render on `!!issueId`, so each sibling's own hooks are always called
 * unconditionally.
 *
 *   - CreateModeInput — no network. Holds the draft in `PendingEstimateProvider`
 *     (see `packages/workload-ext/src/PendingEstimate.tsx`); the value is
 *     written once the work item exists, by base.tsx (phase 3).
 *   - UpdateModeInput — live-commit via `useWorkloadEstimateEditor`, mirroring
 *     `issue-layouts/spreadsheet/columns/estimated-hours-column.tsx`'s
 *     `EstimatedHoursBodyCell` (parse/commit/rollup-read-only behavior).
 */

import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import { observer } from "mobx-react";
import { Clock } from "lucide-react";
// workload i18n + context (fork-owned — no @plane/i18n / @plane/types edit)
import { formatRollupHours, formatRollupTooltip, usePendingEstimate, wlt } from "@plane/workload-ext";
// hooks
import { useWorkload } from "@/hooks/store/use-workload";
import { useWorkloadEstimate } from "@/hooks/store/use-workload-estimate";
import { useWorkloadEstimateEditor } from "@/hooks/store/use-workload-estimate-editor";

type TIssueEstimatedHoursInputProps = {
  /** Work item id — undefined in create mode. */
  issueId: string | undefined;
  projectId: string | null;
  workspaceSlug: string;
  /** True when the modal is in draft mode; the whole control is hidden. */
  isDraft: boolean;
  tabIndex?: number;
};

/**
 * Entry point rendered from `default-properties.tsx`. Hidden for a draft (no
 * `db.Issue` row to FK a `WorkloadEstimate` against — D5) and when there is no
 * project yet (the estimate write path needs one either way).
 */
export const IssueEstimatedHoursInput = observer(function IssueEstimatedHoursInput(
  props: TIssueEstimatedHoursInputProps
) {
  const { issueId, projectId, workspaceSlug, isDraft, tabIndex } = props;

  if (isDraft || !projectId) return null;

  return issueId ? (
    <UpdateModeInput issueId={issueId} projectId={projectId} workspaceSlug={workspaceSlug} tabIndex={tabIndex} />
  ) : (
    <CreateModeInput tabIndex={tabIndex} />
  );
});

// ── Shared shell ────────────────────────────────────────────────────────────

/**
 * Visual shell shared by both modes so they render as one control that sits
 * flush with the neighbouring date/cycle dropdowns in the properties row.
 * Styled like `buttonVariant="border-with-text"` (see
 * `core/components/dropdowns/buttons.tsx`'s `BorderButton`) without pulling in
 * the dropdown button machinery, since this control is not a dropdown.
 */
function EstimatedHoursPill(props: { children: ReactNode }) {
  return (
    <div className="h-7">
      <div className="flex h-full w-fit items-center gap-1 rounded-sm border-[0.5px] border-strong px-2 py-0.5 text-caption-sm-regular">
        <Clock className="h-3 w-3 flex-shrink-0 text-secondary" />
        {props.children}
      </div>
    </div>
  );
}

// ── Create mode — no network ────────────────────────────────────────────────

type TCreateModeInputProps = {
  tabIndex?: number;
};

/**
 * No network at all: writes straight through to the pending-estimate draft.
 * Parsing and the eventual PUT both happen once, at create time, in base.tsx
 * (phase 3) — this component only ever holds a raw string.
 */
const CreateModeInput = observer(function CreateModeInput(props: TCreateModeInputProps) {
  const { tabIndex } = props;
  const { pendingHours, setPendingHours } = usePendingEstimate();

  return (
    <EstimatedHoursPill>
      <input
        type="text"
        inputMode="decimal"
        tabIndex={tabIndex}
        value={pendingHours}
        onChange={(e) => setPendingHours(e.target.value)}
        placeholder={wlt("estimate.placeholder")}
        aria-label={wlt("estimate.label")}
        // Fixed width so a long in-progress number does not reflow the
        // properties row — see the plan's "Shared shell" note.
        className="w-20 bg-transparent text-caption-sm-regular text-primary outline-none placeholder:text-placeholder"
      />
    </EstimatedHoursPill>
  );
});

// ── Update mode — live-commit ───────────────────────────────────────────────

type TUpdateModeInputProps = {
  issueId: string;
  projectId: string;
  workspaceSlug: string;
  tabIndex?: number;
};

/**
 * Live-commit, mirroring `EstimatedHoursBodyCell`: 800 ms after typing stops,
 * on Enter (keeping focus), or on blur — see
 * `hooks/store/use-workload-estimate-editor.ts`. A parent (non-null rollup)
 * renders read-only, exactly as the spreadsheet cell does.
 */
const UpdateModeInput = observer(function UpdateModeInput(props: TUpdateModeInputProps) {
  const { issueId, projectId, workspaceSlug, tabIndex } = props;

  const workloadStore = useWorkload();
  const { rollup } = useWorkloadEstimate(issueId);
  const estimate = useWorkloadEstimateEditor({ workspaceSlug, projectId, issueId });

  // Transcribed from issue-detail/sidebar.tsx:102-112. Required, not optional:
  // useWorkloadEstimate is a pure selector, and the modal may open from a
  // surface that never warmed the store — without this fetch the field would
  // render empty for an item that actually has hours. The single GET
  // populates estimateData AND rollupData, which also feeds the parent check
  // below.
  const estimateFetchedRef = useRef(false);
  useEffect(() => {
    if (!workspaceSlug || !projectId || !issueId || estimateFetchedRef.current) return;
    estimateFetchedRef.current = true;
    void (async () => {
      try {
        await workloadStore.fetchEstimate(workspaceSlug, projectId, issueId);
      } catch {
        // silently ignore — estimate may not exist
      }
    })();
  }, [workspaceSlug, projectId, issueId, workloadStore]);

  return (
    <EstimatedHoursPill>
      {rollup !== null ? (
        // Parent work item — read-only rollup summary, same as the
        // spreadsheet cell and the issue-detail sidebar (D10).
        <span className="w-20 truncate text-caption-sm-regular text-secondary" title={formatRollupTooltip(rollup)}>
          {formatRollupHours(rollup)}
        </span>
      ) : (
        <input
          type="number"
          min={0}
          max={10000}
          step={0.5}
          tabIndex={tabIndex}
          value={estimate.value}
          onFocus={estimate.onFocus}
          onChange={estimate.onChange}
          onBlur={estimate.onBlur}
          onKeyDown={estimate.onKeyDown}
          // NOTE: `estimate.isSaving` must NOT appear here. Saves fire while
          // the user is still typing; disabling on save drops DOM focus and
          // swallows the next keystrokes — see use-workload-estimate-editor.ts.
          placeholder={wlt("estimate.placeholder")}
          aria-label={wlt("estimate.label")}
          // Fixed width so a long number does not reflow the properties row.
          className="w-20 bg-transparent text-caption-sm-regular text-primary outline-none placeholder:text-placeholder"
        />
      )}
      {estimate.isSaving && (
        <span className="shrink-0 text-caption-sm-regular text-secondary">{wlt("common.saving")}</span>
      )}
    </EstimatedHoursPill>
  );
});

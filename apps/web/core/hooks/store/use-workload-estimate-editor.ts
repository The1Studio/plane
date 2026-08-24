/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 *
 * The1Studio fork (SP2 workload) — documented core-edit exception.
 * Listed in docs/FORK.md "Frontend core-edit exceptions".
 *
 * The shared edit lifecycle behind every "Estimated hours" input (spreadsheet
 * cell, peek panel, issue-detail sidebar).  Lives in core alongside
 * use-workload-estimate.ts and for the same reason: it must call useWorkload(),
 * which a context-agnostic package hook cannot do.
 *
 * Commit timing:
 *   - 800 ms after the last keystroke ("stopped typing"),
 *   - immediately on Enter, keeping focus so the value can be corrected,
 *   - immediately on blur, as the final safety net.
 *
 * An empty field is NEVER auto-committed — clearing the field to retype must
 * not write a 0.  Empty commits as 0 only on an explicit Enter or blur.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { debounce } from "lodash-es";
import { setToast, TOAST_TYPE } from "@plane/propel/toast";
import {
  PARENT_HAS_CHILDREN_ERROR_CODE,
  parseEstimateHoursInput,
  WorkloadEstimateApiError,
  wlt,
} from "@plane/workload-ext";
import { useWorkloadEstimate } from "./use-workload-estimate";
import { useWorkload } from "./use-workload";

/** Idle time after the last keystroke before an edit is committed. */
const COMMIT_DEBOUNCE_MS = 800;

type TEstimateEditorArgs = {
  workspaceSlug: string | undefined;
  projectId: string | null | undefined;
  issueId: string;
};

type TEstimateEditor = {
  /** Controlled input value — the draft while focused, the store value when idle. */
  value: string;
  /**
   * Drives the "Saving…" label ONLY.  Never wire this to the input's `disabled`
   * attribute: under debounced saving that disables the field mid-keystroke,
   * which drops DOM focus and swallows whatever the user types next.
   */
  isSaving: boolean;
  onFocus: () => void;
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onBlur: () => void;
  onKeyDown: (e: React.KeyboardEvent<HTMLInputElement>) => void;
};

export function useWorkloadEstimateEditor(args: TEstimateEditorArgs): TEstimateEditor {
  const { workspaceSlug, projectId, issueId } = args;

  const store = useWorkload();
  const { hours } = useWorkloadEstimate(issueId);

  // The draft is a string, not `number | ""`: a number-typed draft cannot hold
  // the intermediate "12." a user types on the way to 12.5.
  const [draft, setDraft] = useState<string>("");
  const [isFocused, setIsFocused] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  /**
   * Value of the most recent commit ATTEMPT, set before the await so a blur
   * firing right behind a debounced save cannot re-send the same number while
   * the first PUT is still open.  Reset on focus, and on failure so a retry is
   * allowed.
   */
  const pendingValueRef = useRef<number | null>(null);

  /**
   * Serializes writes.  Two debounced saves can overlap (type → pause → save A
   * → type → pause → save B while A is still open); the store assigns
   * `estimateData[issueId]` unconditionally on success, so an out-of-order
   * resolution would leave the older value in place.  Its `_writeEpoch` guard
   * covers bulk GETs, not PUT-vs-PUT ordering.
   */
  const inFlightRef = useRef<Promise<void>>(Promise.resolve());

  const commit = useCallback(
    async (raw: string, options: { allowEmpty: boolean }): Promise<void> => {
      if (!workspaceSlug || !projectId) return;

      const parsed = parseEstimateHoursInput(raw, { allowEmpty: options.allowEmpty });
      if (parsed === null) return;

      // Skip a value already stored or already in flight.
      if (parsed === (pendingValueRef.current ?? hours ?? 0)) return;
      pendingValueRef.current = parsed;

      setIsSaving(true);
      try {
        await store.updateEstimate(workspaceSlug, projectId, issueId, parsed);
      } catch (err) {
        // Allow a retry of the same value now that this attempt failed.
        pendingValueRef.current = null;
        // 400 UX backstop: a sub-issue was likely added concurrently, so the
        // backend now considers this issue a parent.  Refetch its rollup (which
        // flips the field read-only) and explain why the edit didn't apply.
        if (err instanceof WorkloadEstimateApiError && err.errorCode === PARENT_HAS_CHILDREN_ERROR_CODE) {
          void store.forceRefetchRollup(workspaceSlug, issueId);
          setToast({
            type: TOAST_TYPE.ERROR,
            title: wlt("estimate.parent_has_children_toast_title"),
            message: wlt("estimate.parent_has_children_toast_message"),
          });
        }
      } finally {
        setIsSaving(false);
      }
    },
    [workspaceSlug, projectId, issueId, hours, store]
  );

  /** Queue a commit behind whatever write is already open. */
  const enqueueCommit = useCallback(
    (raw: string, options: { allowEmpty: boolean }) => {
      inFlightRef.current = inFlightRef.current.then(() => commit(raw, options)).catch(() => {});
    },
    [commit]
  );

  // Keep the debounced callback pointed at the latest closure so it never fires
  // against stale props (same shape as hooks/use-auto-save.tsx).
  const enqueueCommitRef = useRef(enqueueCommit);
  enqueueCommitRef.current = enqueueCommit;

  const debouncedCommit = useMemo(
    () => debounce((raw: string) => enqueueCommitRef.current(raw, { allowEmpty: false }), COMMIT_DEBOUNCE_MS),
    []
  );

  // Flush rather than cancel on unmount: closing the peek panel without a blur
  // must not discard a pending edit.
  useEffect(() => () => debouncedCommit.flush(), [debouncedCommit]);

  const onFocus = useCallback(() => {
    setDraft(hours !== null ? String(hours) : "");
    pendingValueRef.current = null;
    setIsFocused(true);
  }, [hours]);

  const onChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const raw = e.target.value;
      setDraft(raw);
      debouncedCommit(raw);
    },
    [debouncedCommit]
  );

  const onBlur = useCallback(() => {
    debouncedCommit.cancel();
    setIsFocused(false);
    enqueueCommit(draft, { allowEmpty: true });
  }, [debouncedCommit, enqueueCommit, draft]);

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key !== "Enter") return;
      // Commit now and keep focus, so the value can be corrected without
      // re-clicking the field.
      e.preventDefault();
      debouncedCommit.cancel();
      enqueueCommit(e.currentTarget.value, { allowEmpty: true });
    },
    [debouncedCommit, enqueueCommit]
  );

  return {
    // Draft while the user is editing; otherwise the live store value, so an
    // edit made in the grid shows in the panel without reopening it.
    value: isFocused ? draft : hours !== null ? String(hours) : "",
    isSaving,
    onFocus,
    onChange,
    onBlur,
    onKeyDown,
  };
}

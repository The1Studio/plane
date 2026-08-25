/**
 * The1Studio fork (work-item creation defaults) — the project-change reset.
 *
 * Upstream's `getUpdateFormDataForReset` rebuilds the create form from
 * `DEFAULT_WORK_ITEM_FORM_VALUES` and carries forward exactly five fields:
 * name, description_html, priority, start_date, target_date. `assignee_ids` is
 * not among them, so switching project inside the create modal emptied the
 * assignee chip and never restored the fork's prefill.
 *
 * It lives in the sealed `@plane/utils` package (docs/FORK.md § "Frontend
 * customizations"), so this wraps it rather than patching it — which also keeps
 * the date carry-forward it owns pinned by a test in fork-owned code.
 *
 * Contract: plans/260825-workitem-defaults-project-change/phase-1.md
 */

import type { TIssue } from "@plane/types";
import { getUpdateFormDataForReset } from "@plane/utils";

import type { TCreationAssigneeContext } from "./creation-defaults";
import { resolveCreationAssigneeIds } from "./creation-defaults";

/**
 * The create form's new values after the project changed.
 *
 * Everything upstream carries across is carried across untouched — including
 * both dates, and including a `target_date` the user deliberately CLEARED,
 * which is never re-filled with today. Only `assignee_ids` is re-resolved, for
 * the newly chosen project.
 *
 * `ctx.currentAssigneeIds` defaults to the form's own value, so a caller that
 * already holds `formValues` does not have to spell the selection out twice.
 */
export const getProjectChangeFormReset = (
  projectId: string | null | undefined,
  formValues: Partial<TIssue>,
  ctx: TCreationAssigneeContext
): Partial<TIssue> => ({
  ...getUpdateFormDataForReset(projectId, formValues),
  assignee_ids: resolveCreationAssigneeIds({
    ...ctx,
    currentAssigneeIds: ctx.currentAssigneeIds ?? formValues.assignee_ids,
  }),
});

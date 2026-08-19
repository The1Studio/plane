// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
//
// The1Studio fork (workload timeline) — the click target shared by a task's
// sidebar label and its chart bar. Both open the work-item peek panel.
//
// Why `setPeekIssue` directly rather than `useIssuePeekOverviewRedirection`:
// that hook's `handleRedirection` takes a `TIssue`, and the workload response
// is not an issue list — it carries a compact per-task payload with no
// `TIssue` anywhere. Everything the peek panel actually needs from it is
// `{ workspaceSlug, projectId, issueId }`, which is precisely what the hook
// forwards to `setPeekIssue` (hooks/use-issue-peek-overview-redirection.tsx).
// Fetching the whole issue just to hand three ids back would add a request per
// click for nothing — the peek panel self-fetches on open.
//
// `ControlLink` is what preserves cmd/ctrl/middle-click to the full work-item
// page: it intercepts a plain left click and lets every modified click fall
// through to the `href`. Same affordance as core's own gantt layout
// (issues/issue-layouts/gantt/blocks.tsx).

import { observer } from "mobx-react";
import type { TWorkloadTask } from "@plane/workload-ext";
import { ControlLink } from "@plane/ui";
import { generateWorkItemLink } from "@plane/utils";
import { useIssueDetail } from "@/hooks/store/use-issue-detail";
import { useProject } from "@/hooks/store/use-project";

type Props = {
  task: TWorkloadTask;
  workspaceSlug: string;
  className?: string;
  children: React.ReactNode;
};

export const WorkloadTaskLink = observer(function WorkloadTaskLink({
  task,
  workspaceSlug,
  className,
  children,
}: Props) {
  const { setPeekIssue } = useIssueDetail();
  const { getProjectIdentifierById } = useProject();

  const projectIdentifier = getProjectIdentifierById(task.project_id);
  const href = generateWorkItemLink({
    workspaceSlug,
    projectId: task.project_id,
    issueId: task.id,
    projectIdentifier,
    // `task.identifier` is "<PROJECT>-<sequence_id>"; take the number from the
    // LAST hyphen, since a project identifier may itself contain one.
    sequenceId: Number(task.identifier.slice(task.identifier.lastIndexOf("-") + 1)) || undefined,
  });

  const handleClick = (event: React.MouseEvent<HTMLAnchorElement>) => {
    // The bar sits inside `ChartDraggable`, and the surrounding `BlockRow`
    // owns hover/active state — let neither see this click.
    event.stopPropagation();
    setPeekIssue({ workspaceSlug, projectId: task.project_id, issueId: task.id });
  };

  return (
    <ControlLink href={href} onClick={handleClick} className={className}>
      {children}
    </ControlLink>
  );
});

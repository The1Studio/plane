/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// types
import type { TTimelineType } from "@plane/types";
import { GANTT_TIMELINE_TYPE } from "@plane/types";
// Plane-web

import type { IBaseTimelineStore } from "@/plane-web/store/timeline/base-timeline.store";
import type { ITimelineStore } from "../store/timeline";

export const getTimelineStore = (
  timelineStore: ITimelineStore,
  /* The1Studio fork (workload timeline, phase-8.md) — widened from
   * `TTimelineTypeCore` to `TTimelineType` so the WORKLOAD member (added to
   * `EXTENDED_GANTT_TIMELINE_TYPE`) type-checks here. */
  timelineType: TTimelineType
): IBaseTimelineStore => {
  if (timelineType === GANTT_TIMELINE_TYPE.ISSUE) {
    return timelineStore.issuesTimeLineStore as IBaseTimelineStore;
  }
  if (timelineType === GANTT_TIMELINE_TYPE.MODULE) {
    return timelineStore.modulesTimeLineStore as IBaseTimelineStore;
  }
  if (timelineType === GANTT_TIMELINE_TYPE.PROJECT) {
    return timelineStore.projectTimeLineStore;
  }
  if (timelineType === GANTT_TIMELINE_TYPE.GROUPED) {
    return timelineStore.groupedTimeLineStore;
  }
  /* The1Studio fork (workload timeline, phase-8.md) */
  if (timelineType === GANTT_TIMELINE_TYPE.WORKLOAD) {
    return timelineStore.workloadTimeLineStore;
  }
  throw new Error(`Unknown timeline type: ${timelineType}`);
};

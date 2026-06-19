/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// store
import { WorkloadStore } from "@plane/workload-ext";
import type { IWorkloadStore } from "@plane/workload-ext";
import { CoreRootStore } from "@/store/root.store";
import type { ITimelineStore } from "./timeline";
import { TimeLineStore } from "./timeline";

export class RootStore extends CoreRootStore {
  timelineStore: ITimelineStore;
  workloadStore: IWorkloadStore;

  constructor() {
    super();

    this.timelineStore = new TimeLineStore(this);
    this.workloadStore = new WorkloadStore();
  }
}

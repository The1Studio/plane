/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { RootStore } from "@/plane-web/store/root.store";
import { IssuesTimeLineStore } from "@/store/timeline/issues-timeline.store";
import type { IIssuesTimeLineStore } from "@/store/timeline/issues-timeline.store";
import { ModulesTimeLineStore } from "@/store/timeline/modules-timeline.store";
import type { IModulesTimeLineStore } from "@/store/timeline/modules-timeline.store";
import { BaseTimeLineStore } from "./base-timeline.store";
import type { IBaseTimelineStore } from "./base-timeline.store";

export interface ITimelineStore {
  issuesTimeLineStore: IIssuesTimeLineStore;
  modulesTimeLineStore: IModulesTimeLineStore;
  projectTimeLineStore: IBaseTimelineStore;
  groupedTimeLineStore: IBaseTimelineStore;
  /* The1Studio fork (workload timeline, phase-8.md) — typed as the CONCRETE
   * class (not `IBaseTimelineStore`) because the workload timeline root calls
   * `updateBlocks()` directly, which is public on `BaseTimeLineStore` but not
   * part of the `IBaseTimelineStore` interface (only the ISSUE/MODULE
   * subclasses call it internally via their own autorun). */
  workloadTimeLineStore: BaseTimeLineStore;
}

export class TimeLineStore implements ITimelineStore {
  issuesTimeLineStore: IIssuesTimeLineStore;
  modulesTimeLineStore: IModulesTimeLineStore;
  projectTimeLineStore: IBaseTimelineStore;
  groupedTimeLineStore: IBaseTimelineStore;
  /* The1Studio fork (workload timeline, phase-8.md) */
  workloadTimeLineStore: BaseTimeLineStore;

  constructor(rootStore: RootStore) {
    this.issuesTimeLineStore = new IssuesTimeLineStore(rootStore);
    this.modulesTimeLineStore = new ModulesTimeLineStore(rootStore);
    // Dummy store
    this.projectTimeLineStore = new BaseTimeLineStore(rootStore);
    this.groupedTimeLineStore = new BaseTimeLineStore(rootStore);
    /* The1Studio fork (workload timeline, phase-8.md) — block data is pushed in
     * directly by the workload timeline root via `updateBlocks`, not by an
     * internal autorun (there is no single MobX issue/module store to read
     * from — the source is the workload API response held in @plane/workload-ext's
     * own store). */
    this.workloadTimeLineStore = new BaseTimeLineStore(rootStore);
  }
}

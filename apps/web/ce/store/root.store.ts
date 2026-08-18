/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// store
import { makeObservable, observable } from "mobx";
import { WorkloadStore } from "@plane/workload-ext";
import type { IWorkloadStore } from "@plane/workload-ext";
import { CoreRootStore } from "@/store/root.store";
import type { ITimelineStore } from "./timeline";
import { TimeLineStore } from "./timeline";
/* The1Studio fork (workspace work settings) */
import type { IWorkSettingsStore } from "./work-settings.store";
/* The1Studio fork (workspace work settings) */
import { WorkSettingsStore } from "./work-settings.store";

export class RootStore extends CoreRootStore {
  timelineStore: ITimelineStore;
  workloadStore: IWorkloadStore;
  /* The1Studio fork (workspace work settings) */
  workSettingsStore: IWorkSettingsStore;

  constructor() {
    super();

    /* The1Studio fork (workspace work settings) */
    // `workSettingsStore` MUST be observable. CoreRootStore's own constructor
    // (invoked by super() above) builds CalendarStore, whose constructor reads
    // the week-start day and registers a reaction on it -- all BEFORE the line
    // below has run, so it observes `undefined`. Without observability MobX
    // would register that reaction with zero dependencies and it could never
    // fire again, leaving the calendar pinned to the fallback week start even
    // after the real setting loads. Declaring it observable makes the
    // assignment below a tracked change that wakes the reaction.
    makeObservable(this, {
      workSettingsStore: observable.ref,
    });

    this.timelineStore = new TimeLineStore(this);
    this.workloadStore = new WorkloadStore();
    /* The1Studio fork (workspace work settings) */
    this.workSettingsStore = new WorkSettingsStore(this);
  }
}

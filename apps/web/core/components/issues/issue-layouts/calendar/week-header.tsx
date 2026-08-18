/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { EStartOfTheWeek } from "@plane/types";
import { getOrderedDays } from "@plane/utils";
import { DAYS_LIST } from "@/constants/calendar";
// helpers
// hooks
/* The1Studio fork (workspace work settings) */
import { useParams } from "next/navigation";
/* The1Studio fork (workspace work settings) */
import { useWorkSettings } from "@/hooks/store/use-work-settings";

type Props = {
  isLoading: boolean;
  showWeekends: boolean;
};

export const CalendarWeekHeader = observer(function CalendarWeekHeader(props: Props) {
  const { isLoading, showWeekends } = props;
  // hooks
  /* The1Studio fork (workspace work settings) */
  const { workspaceSlug } = useParams();
  /* The1Studio fork (workspace work settings) */
  const { workSettings } = useWorkSettings(workspaceSlug?.toString());
  /* The1Studio fork (workspace work settings) */
  const startOfWeek = workSettings.week_start_day as EStartOfTheWeek;

  // derived
  const orderedDays = getOrderedDays(Object.values(DAYS_LIST), (item) => item.value, startOfWeek);

  return (
    <div
      className={`relative sticky top-0 z-[1] grid divide-subtle-1 text-13 font-medium md:divide-x-[0.5px] ${
        showWeekends ? "grid-cols-7" : "grid-cols-5"
      }`}
    >
      {isLoading && (
        <div className="absolute h-[1.5px] w-3/4 animate-[bar-loader_2s_linear_infinite] bg-accent-primary" />
      )}
      {orderedDays.map((day) => {
        if (!showWeekends && (day.value === EStartOfTheWeek.SUNDAY || day.value === EStartOfTheWeek.SATURDAY))
          return null;

        return (
          <div key={day.shortTitle} className="flex h-11 items-center justify-center bg-layer-1 px-4 md:justify-end">
            {day.shortTitle}
          </div>
        );
      })}
    </div>
  );
});

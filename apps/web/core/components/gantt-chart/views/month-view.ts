/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { cloneDeep, uniqBy } from "lodash-es";
// plane imports
import { EStartOfTheWeek } from "@plane/types";
import type { ChartDataType } from "@plane/types";
// local imports
import { months } from "../data";
import { getNumberOfDaysBetweenTwoDates, getNumberOfDaysInMonth } from "./helpers";
import type { IWeekBlock } from "./week-view";
import { getWeeksBetweenTwoDates } from "./week-view";

export interface IMonthBlock {
  today: boolean;
  month: number;
  days: number;
  monthData: {
    key: number;
    shortTitle: string;
    title: string;
  };
  title: string;
  year: number;
}

export interface IMonthView {
  months: IMonthBlock[];
  weeks: IWeekBlock[];
}

/**
 * Generate Month Chart data
 * @param monthPayload
 * @param side
 * @param targetDate
 * @param startOfWeek
 * @returns
 *
 * The1Studio fork (workspace work settings) — `startOfWeek` was previously
 * accepted by the week view alone. `ChartViewRoot` has always passed it to
 * every view's `generateChart` (chart/root.tsx), but this one dropped it, so
 * the month view's week sub-columns fell back to the `EStartOfTheWeek.SUNDAY`
 * default of `getWeeksBetweenTwoDates` no matter what the workspace had
 * configured. The workload timeline's capacity heat cells are positioned by
 * their true calendar dates, and the API buckets those weeks by the workspace's
 * `week_start_day` (default MONDAY — `plane/workload/constants.py`), so at
 * month zoom every cell sat one or more days out of step with the week column
 * drawn under it. Threading the parameter through is the ninth site of the
 * per-user → workspace-wide week-start conversion documented in docs/FORK.md;
 * the other eight were converted, this one was missed because it had a silent
 * default rather than a read to swap.
 */
const generateMonthChart = (
  monthPayload: ChartDataType,
  side: null | "left" | "right",
  targetDate?: Date,
  startOfWeek: EStartOfTheWeek = EStartOfTheWeek.SUNDAY
) => {
  let renderState = cloneDeep(monthPayload);

  const range: number = renderState.data.approxFilterRange || 6;
  let filteredDates: IMonthView = { months: [], weeks: [] };
  let minusDate: Date = new Date();
  let plusDate: Date = new Date();

  let startDate = new Date();
  let endDate = new Date();

  // if side is null generate months on both side of current date
  if (side === null) {
    const currentDate = renderState.data.currentDate;

    minusDate = new Date(currentDate.getFullYear(), currentDate.getMonth() - range, currentDate.getDate());
    plusDate = new Date(currentDate.getFullYear(), currentDate.getMonth() + range, currentDate.getDate());

    if (minusDate && plusDate) filteredDates = getMonthsViewBetweenTwoDates(minusDate, plusDate, startOfWeek);

    startDate = filteredDates.weeks[0]?.startDate;
    endDate = filteredDates.weeks[filteredDates.weeks.length - 1]?.endDate;
    renderState = {
      ...renderState,
      data: {
        ...renderState.data,
        startDate,
        endDate,
      },
    };
  }
  // When side is left, generate more months on the left side of the start date
  else if (side === "left") {
    const chartStartDate = renderState.data.startDate;
    const currentDate = targetDate ? targetDate : chartStartDate;

    minusDate = new Date(currentDate.getFullYear(), currentDate.getMonth() - range, 1);
    plusDate = new Date(chartStartDate.getFullYear(), chartStartDate.getMonth(), chartStartDate.getDate() - 1);

    if (minusDate && plusDate) filteredDates = getMonthsViewBetweenTwoDates(minusDate, plusDate, startOfWeek);

    startDate = filteredDates.weeks[0]?.startDate;
    endDate = new Date(chartStartDate.getFullYear(), chartStartDate.getMonth(), chartStartDate.getDate() - 1);
    renderState = {
      ...renderState,
      data: { ...renderState.data, startDate },
    };
  }
  // When side is right, generate more months on the right side of the end date
  else if (side === "right") {
    const chartEndDate = renderState.data.endDate;
    const currentDate = targetDate ? targetDate : chartEndDate;

    minusDate = new Date(chartEndDate.getFullYear(), chartEndDate.getMonth(), chartEndDate.getDate() + 1);
    plusDate = new Date(currentDate.getFullYear(), currentDate.getMonth() + range, 1);

    if (minusDate && plusDate) filteredDates = getMonthsViewBetweenTwoDates(minusDate, plusDate, startOfWeek);

    startDate = new Date(chartEndDate.getFullYear(), chartEndDate.getMonth(), chartEndDate.getDate() + 1);
    endDate = filteredDates.weeks[filteredDates.weeks.length - 1]?.endDate;
    renderState = {
      ...renderState,
      data: { ...renderState.data, endDate: filteredDates.weeks[filteredDates.weeks.length - 1]?.endDate },
    };
  }

  const days = Math.abs(getNumberOfDaysBetweenTwoDates(startDate, endDate)) + 1;
  const scrollWidth = days * monthPayload.data.dayWidth;

  return { state: renderState, payload: filteredDates, scrollWidth: scrollWidth };
};

/**
 * Get Month View data between two dates, i.e., Months and Weeks between two dates
 * @param startDate
 * @param endDate
 * @returns
 */
const getMonthsViewBetweenTwoDates = (
  startDate: Date,
  endDate: Date,
  startOfWeek: EStartOfTheWeek = EStartOfTheWeek.SUNDAY
): IMonthView => ({
  months: getMonthsBetweenTwoDates(startDate, endDate),
  weeks: getWeeksBetweenTwoDates(startDate, endDate, false, startOfWeek),
});

/**
 * generate array of months between two dates
 * @param startDate
 * @param endDate
 * @returns
 */
export const getMonthsBetweenTwoDates = (startDate: Date, endDate: Date): IMonthBlock[] => {
  const monthBlocks = [];

  const startYear = startDate.getFullYear();
  const startMonth = startDate.getMonth();

  const today = new Date();
  const todayMonth = today.getMonth();
  const todayYear = today.getFullYear();

  const currentDate = new Date(startYear, startMonth);

  // oxlint-disable-next-line no-unmodified-loop-condition -- pre-existing warning, unrelated to this change (husky lint-staged runs --deny-warnings on the whole file)
  while (currentDate <= endDate) {
    const currentYear = currentDate.getFullYear();
    const currentMonth = currentDate.getMonth();

    monthBlocks.push({
      year: currentYear,
      month: currentMonth,
      monthData: months[currentMonth],
      title: `${months[currentMonth].title} ${currentYear}`,
      days: getNumberOfDaysInMonth(currentMonth, currentYear),
      today: todayMonth === currentMonth && todayYear === currentYear,
    });

    currentDate.setMonth(currentDate.getMonth() + 1);
  }

  return monthBlocks;
};

/**
 * Merge two MonthView data payloads
 * @param a
 * @param b
 * @returns
 */
const mergeMonthRenderPayloads = (a: IMonthView, b: IMonthView): IMonthView => ({
  months: uniqBy([...a.months, ...b.months], (monthBlock) => `${monthBlock.month}_${monthBlock.year}`),
  weeks: uniqBy(
    [...a.weeks, ...b.weeks],
    (weekBlock) => `${weekBlock.startDate.getTime()}_${weekBlock.endDate.getTime()}`
  ),
});

export const monthView = {
  generateChart: generateMonthChart,
  mergeRenderPayloads: mergeMonthRenderPayloads,
};

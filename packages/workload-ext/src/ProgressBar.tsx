/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 *
 * Fork-owned progress bar for the SP2 workload feature — a filled track + a
 * right-aligned percent label, matching the source (ClickUp) progress column.
 * Shared by the spreadsheet Progress column, the list/kanban pill, and the
 * item-detail sidebar (one component ⇒ no visual drift across surfaces).
 *
 * `value` is a 0..1 fraction, or null ⇒ render a dash (no bar). Theme-aware
 * via Plane's design tokens; the fill uses the accent color like the rest of
 * the app's progress affordances.
 */

import React from "react";

import { toProgressPercent } from "./progress";

type ProgressBarVariant = "grid" | "pill";

export type TProgressBarProps = {
  /** Progress as a 0..1 fraction, or null to render a dash (no bar). */
  value: number | null;
  /** `grid` (default) = full-width bar for the spreadsheet/sidebar; `pill` = compact for cards. */
  variant?: ProgressBarVariant;
  /** Accessible label prefix, e.g. "Progress". */
  ariaLabel?: string;
};

export function ProgressBar({ value, variant = "grid", ariaLabel = "Progress" }: TProgressBarProps) {
  // Null = no meaningful progress (cancelled / stateless leaf, or 0-hour
  // parent) — a dash, never a 0%-filled bar.
  if (value === null || value === undefined) {
    return <span className="text-secondary">—</span>;
  }

  const percent = toProgressPercent(value);
  const clamped = Math.max(0, Math.min(100, percent));
  const isPill = variant === "pill";

  return (
    <div
      className={`flex items-center ${isPill ? "gap-1.5" : "w-full gap-2"}`}
      role="progressbar"
      aria-valuenow={clamped}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={`${ariaLabel}: ${clamped}%`}
    >
      <div className={`overflow-hidden rounded-full bg-layer-3 ${isPill ? "h-1.5 w-10" : "h-2 w-full max-w-40"}`}>
        <div
          className="h-full rounded-full bg-accent-primary transition-[width] duration-200"
          style={{ width: `${clamped}%` }}
        />
      </div>
      <span className={`shrink-0 text-secondary tabular-nums ${isPill ? "text-caption-sm-regular" : "text-13"}`}>
        {clamped}%
      </span>
    </div>
  );
}

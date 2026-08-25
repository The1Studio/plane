// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
//
// The1Studio fork (workload timeline) — resolve the colour a task bar is
// painted with, from the state the work item is actually in.
//
// Why this is a module and not three lines inside the component: it is a pure
// function over two strings with a fallback chain that has to hold against
// values the UI cannot control, and that is exactly the shape that belongs in
// a unit test rather than in a render path. `barLabel.ts` and `progress.ts`
// in this package are here for the same reason.

import { STATE_GROUPS } from "@plane/constants";
import type { TStateGroups } from "@plane/types";

/**
 * Last-resort fill when neither the state's own colour nor its group's colour
 * is available.
 *
 * A literal rather than a Tailwind class: the caller sets this via
 * `style={{ backgroundColor }}`, because a per-state colour cannot be a class
 * name — there is no finite set of them to compile. Every branch of this
 * module therefore has to return a CSS colour string, including this one.
 */
export const FALLBACK_BAR_COLOR = "#3f76ff";

/**
 * The colour to paint a task bar with.
 *
 * Three steps, in order:
 *
 * 1. **The state's own colour.** This is the answer in every real case, and
 *    it is what makes two custom `started` states distinguishable — the whole
 *    reason the five-group palette was not enough.
 * 2. **The state group's colour.** Reached when `state_color` is blank.
 *    `State.color` is `CharField(max_length=255)` server-side with no hex
 *    validation, so blank is a value the database genuinely permits, and a
 *    client one release behind a server that has not yet shipped the field
 *    lands here too.
 * 3. **`FALLBACK_BAR_COLOR`.** Reached only for a `state_group` outside the
 *    five known groups — `triage`, which `_base_queryset` excludes from the
 *    workload query entirely, or a group added upstream after this was
 *    written. A guard, not a path.
 *
 * The returned string is passed straight to `style={{ backgroundColor }}` /
 * `style={{ borderColor }}` and is **never parsed**. That is deliberate: the
 * value is an opaque CSS colour, so `#fa0`, `rgb(…)` and a named colour all
 * work, and no format assumption can rot. It is also why the fill uses core's
 * overlay technique for contrast rather than computing an alpha — see
 * `WorkloadTimelineChartBlock`.
 *
 * An invalid value is the one case nothing here can catch: React will hand it
 * to the browser, which drops it, and the bar renders unfilled. That is a
 * server-side data problem, not something a colour resolver can repair, and
 * inventing a "looks like a colour" regex here would reject valid CSS while
 * still not catching every invalid string.
 */
export function stateBarColor(task: { state_color?: string | null; state_group?: string | null }): string {
  const own = task.state_color?.trim();
  if (own) return own;

  const group = task.state_group as TStateGroups | undefined;
  const groupColor = group ? STATE_GROUPS[group]?.color : undefined;
  if (groupColor) return groupColor;

  return FALLBACK_BAR_COLOR;
}

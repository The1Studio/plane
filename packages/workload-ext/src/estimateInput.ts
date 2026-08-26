/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
/**
 * The1Studio fork (SP2 workload / work-item modal estimated hours) — fork-owned.
 * Listed in docs/FORK.md "Frontend core-edit exceptions" alongside the rest of
 * `packages/workload-ext`.
 */

/**
 * Parse a raw "Estimated hours" input string into a committable number.
 *
 * SSOT for every hours input in the fork — the modal's create-mode field and
 * `useWorkloadEstimateEditor`'s commit step both call this, so the two paths
 * cannot drift on what counts as a valid number.
 *
 * Returns `null` when the raw value must NOT be committed:
 *   - empty and `allowEmpty` is false (clearing the field to retype must never
 *     write a 0),
 *   - not a finite number,
 *   - negative.
 * An empty string with `allowEmpty: true` parses to 0 — an explicit Enter or
 * blur is how a user clears an estimate.
 *
 * The upper bound (MAX_HOURS) is deliberately NOT enforced here: it is the
 * server's, and `WorkloadEstimateSerializer.validate_hours` returns a real
 * error for it. Silently clamping client-side would hide a typo.
 */
export function parseEstimateHoursInput(raw: string, options: { allowEmpty: boolean }): number | null {
  const trimmed = raw.trim();
  // Never auto-save an empty field; only an explicit Enter/blur commits 0.
  if (trimmed === "" && !options.allowEmpty) return null;

  const parsed = trimmed === "" ? 0 : Number(trimmed);
  if (!Number.isFinite(parsed) || parsed < 0) return null;

  return parsed;
}

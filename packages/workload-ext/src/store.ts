/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { action, computed, makeObservable, observable, runInAction } from "mobx";
import { MAX_SPAN_DAYS, daysBetween, shiftDate } from "./dateRange";
import { mergeWorkloadResponses, normalizeRanges, snapRangeToPeriods, subtractRanges } from "./merge";
import type { TDateRange } from "./merge";
import { WorkloadService } from "./service";
import type {
  TWorkloadEstimate,
  TWorkloadFilters,
  TWorkloadGranularity,
  TWorkloadResponse,
  TWorkloadRollup,
  TWorkloadRow,
  TWorkloadTask,
} from "./types";

// ── Helpers ──────────────────────────────────────────────────────────────────

/**
 * Today as a local-calendar `YYYY-MM-DD` string, for the client-side `overdue`
 * recompute in `patchTaskDates`. Same local-parse idiom as `dateRange.ts`'s
 * `shiftDate`/`periodDateRange` — this is a display-only approximation good
 * until the background refetch (triggered by the same patch) lands the
 * server's own workspace-timezone `overdue` value; see `_resolve_today` in
 * `apps/api/plane/workload/service.py`.
 */
function todayDateString(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/**
 * Mirrors `_TERMINAL_STATE_GROUPS` in `apps/api/plane/workload/service.py` —
 * a task in either group is done/abandoned and can never be flagged overdue,
 * however far in the past its `target_date` sits.
 */
const TERMINAL_STATE_GROUPS = new Set(["completed", "cancelled"]);

/**
 * A task's dates as they were immediately before `patchTaskDates` rewrote
 * them, plus the id they belong to — enough for `rollbackTaskDates` (or a
 * future phase 4) to restore the pre-patch state on a rejected write.
 * `target_date` is non-null here because a task with no `target_date` is
 * never drawn on the timeline and is therefore never draggable (plan D8) —
 * there is no dateless state to snapshot.
 */
export type TTaskDatesSnapshot = {
  issueId: string;
  start_date: string | null;
  target_date: string;
};

// ── Interface ─────────────────────────────────────────────────────────────────

export interface IWorkloadStore {
  // observables
  granularity: TWorkloadGranularity;
  /**
   * Date spans already fetched at the CURRENT granularity + filters, normalized
   * and non-overlapping. There is no date-range picker any more: the chart's
   * viewport asks for what it needs and this records what has been answered.
   */
  loadedRanges: TDateRange[];
  /**
   * Bumped by `resetCoverage`. The timeline watches it to reload the viewport
   * after a filter or zoom change — those do not scroll, so the scroll-settle
   * path that normally drives loading would never fire on its own.
   */
  coverageVersion: number;
  selectedProjectIds: string[];
  selectedAssigneeIds: string[];
  selectedStateGroups: string[];
  workloadData: TWorkloadResponse | null;
  estimateData: Record<string, TWorkloadEstimate | null>; // keyed by issueId
  /**
   * Computed rollup per issueId. `null` means the id has been fetched (via
   * either the single-issue GET or the bulk rollups endpoint) and is
   * confirmed NOT a parent — mirrors the estimateData null-recording
   * convention so a subsequent read never re-triggers a redundant fetch.
   * Presence of a non-null entry is the parent signal (plan §P4 item 3).
   */
  rollupData: Record<string, TWorkloadRollup | null>;
  isLoading: boolean;
  error: string | null;
  /**
   * Error state for the rollup fetch path — kept independent from `error`
   * (the estimate fetch/write path) so one failing request never clobbers
   * the other's error state (plan §P4 item 3).
   */
  rollupError: string | null;
  /**
   * Bumped whenever a successful updateEstimate/deleteEstimate invalidates
   * rollupData. Consumers (e.g. useBulkWorkloadFetch) can `reaction()` on
   * this to trigger a refetch even outside an `observer`-wrapped component.
   */
  rollupInvalidationVersion: number;

  // computed
  maxColumns: number;

  // actions
  setGranularity: (g: TWorkloadGranularity) => void;
  setProjectIds: (ids: string[]) => void;
  setAssigneeIds: (ids: string[]) => void;
  setStateGroups: (groups: string[]) => void;
  /**
   * Load `range` if any of it is missing, merging the result into what is held.
   * Idempotent and safe to call on every scroll settle — a fully covered range
   * issues no request.
   */
  ensureRange: (workspaceSlug: string, range: TDateRange, weekStartDay: number) => Promise<void>;
  /**
   * Drops every loaded range AND blanks `workloadData` — used when a filter
   * or granularity change means the cache describes a query nobody is asking
   * any more. The board flashes empty while the viewport refetches; see
   * `invalidateCoverage` for the non-blanking sibling.
   */
  resetCoverage: () => void;
  /**
   * Drops the loaded-range cache and bumps `coverageVersion` WITHOUT blanking
   * `workloadData` — the timeline's `coverageVersion` effect refetches the
   * viewport and folds the server's truth in on top of what is already on
   * screen, so nothing flashes empty. The soft counterpart to `resetCoverage`,
   * for a caller who knows the visible data MAY be stale (a task's dates,
   * assignee, or state changed somewhere outside this store's own writes —
   * e.g. an edit made through the peek panel) but holds no local snapshot of
   * its own to patch in directly, the way `patchTaskDates` does.
   */
  invalidateCoverage: () => void;
  fetchEstimate: (workspaceSlug: string, projectId: string, issueId: string) => Promise<void>;
  fetchEstimatesBulk: (workspaceSlug: string, issueIds: string[]) => Promise<void>;
  /** Updates the estimate for `issueId`. Re-throws on failure (e.g. a typed
   *  `WorkloadEstimateApiError` with `errorCode === PARENT_HAS_CHILDREN_ERROR_CODE`)
   *  after recording `error`, so callers can run the 400 UX backstop. */
  updateEstimate: (workspaceSlug: string, projectId: string, issueId: string, hours: number) => Promise<void>;
  deleteEstimate: (workspaceSlug: string, projectId: string, issueId: string) => Promise<void>;
  /** Bulk-fetches rollups for ids not already in the rollup dedup set. */
  fetchRollups: (workspaceSlug: string, issueIds: string[]) => Promise<void>;
  /** Bypasses the rollup dedup set for a single id — used by the 400 UX
   *  backstop when a PUT is rejected with PARENT_HAS_CHILDREN. */
  forceRefetchRollup: (workspaceSlug: string, issueId: string) => Promise<void>;
  /**
   * Rewrites `issueId`'s dates in the client cache — every occurrence of it,
   * since a task shared across assignees appears on one row per assignee
   * (plan risk "shared-assignee task patched on one row only") — and returns
   * a snapshot of what the dates were before the patch, so a caller (the
   * write path added in a later phase) can roll back on a rejected PATCH.
   * Recomputes `overdue`; deliberately leaves `buckets`, `capacity_buckets`,
   * `over`, `total`, and `month_buckets` untouched (see the `patchTaskDates`
   * method body for why). Invalidates coverage WITHOUT blanking the board —
   * see D11 — so the timeline's own `coverageVersion` effect refetches the
   * viewport and folds the server's truth back in.
   */
  patchTaskDates: (issueId: string, dates: { start_date: string | null; target_date: string }) => TTaskDatesSnapshot;
  /**
   * Restores a task's dates (every occurrence) from a snapshot returned by
   * `patchTaskDates` — the rollback path for a write the backend rejected
   * (D10). The bar snapping back to its pre-drag position is the visible
   * signal that the write did not land.
   */
  rollbackTaskDates: (snapshot: TTaskDatesSnapshot) => void;
}

// ── Store ─────────────────────────────────────────────────────────────────────

export class WorkloadStore implements IWorkloadStore {
  // observables
  /**
   * Must agree with the timeline's DEFAULT zoom, because that zoom is the only
   * granularity control (WorkloadTimelineRoot's VIEW_TO_GRANULARITY).
   * `BaseTimeLineStore` defaults `currentView` to `"week"`, whose columns are
   * per-day — so `"day"` is the matching bucketing.
   */
  granularity: TWorkloadGranularity = "day";
  loadedRanges: TDateRange[] = [];
  coverageVersion: number = 0;
  selectedProjectIds: string[] = [];
  selectedAssigneeIds: string[] = [];
  selectedStateGroups: string[] = [];
  workloadData: TWorkloadResponse | null = null;
  estimateData: Record<string, TWorkloadEstimate | null> = {};
  rollupData: Record<string, TWorkloadRollup | null> = {};
  isLoading: boolean = false;
  error: string | null = null;
  rollupError: string | null = null;
  /**
   * Bumped whenever a successful updateEstimate/deleteEstimate invalidates
   * rollupData. `useBulkWorkloadFetch` (apps/web) subscribes to this via a
   * direct mobx `reaction` so it can trigger a rollup refetch even when the
   * calling component isn't wrapped in `observer` (e.g. list/blocks-list.tsx).
   */
  rollupInvalidationVersion: number = 0;

  private readonly service: WorkloadService;
  /**
   * Issue IDs whose estimate is already in estimateData (fetched via either the
   * single-issue or bulk endpoint) OR currently in-flight.  Used to avoid
   * redundant bulk requests on repeated renders.
   */
  private readonly _fetchedIds: Set<string> = new Set();
  /**
   * Issue IDs whose rollup is already in rollupData OR currently in-flight.
   * Deliberately SEPARATE from `_fetchedIds` — the estimate fetch marks every
   * requested id, so reusing that set would permanently skip the rollup
   * fetch for issues whose estimate was already fetched (plan §P4 item 3).
   */
  private readonly _fetchedRollupIds: Set<string> = new Set();
  /**
   * Issue IDs with a locally-initiated write that has not yet been confirmed
   * by the backend (PUT/DELETE in-flight).  A bulk GET response MUST NOT
   * overwrite entries in this set — the optimistic local write takes precedence.
   */
  private readonly _dirtyIds: Set<string> = new Set();
  /**
   * Monotonic write-generation counter.  Incremented at the START of every
   * write (updateEstimate / deleteEstimate) and again on confirmed success.
   * Allows fetchEstimatesBulk to detect a write that STARTED after the bulk
   * request was issued but RESOLVED before the bulk response arrived — closing
   * the race window that the dirty-set alone cannot cover once `finally` clears
   * the dirty flag.
   *
   * Invariant: if `_lastWriteEpoch[id] >= startEpoch` (the epoch captured when
   * the bulk fetch began), a write touched that id after the bulk request was
   * fired, so the bulk result must be discarded for that id.
   */
  private _writeEpoch: number = 0;
  private readonly _lastWriteEpoch: Record<string, number> = {};
  /**
   * Spans currently being fetched, subtracted alongside `loadedRanges` so two
   * scroll settles in quick succession never request the same dates twice.
   */
  private readonly _inFlight = new Map<string, TDateRange>();
  /**
   * The workspace `ensureRange` was last called for — `null` until the first
   * call, so a fresh store never self-invalidates against nothing. This
   * store is a SINGLETON (`useWorkload`'s own doc comment), so it survives a
   * workspace switch untouched; the React component that reads it can too,
   * unmounting and remounting through an intermediate route rather than
   * merely re-rendering with a new `workspaceSlug` prop — which makes ANY
   * component-lifecycle-scoped "did the prop change" check (a `useRef`
   * compared across renders) unreliable: a fresh mount's ref starts already
   * equal to the current value, so the comparison never fires even though
   * this store's `loadedRanges`/`workloadData` are still the PREVIOUS
   * workspace's. Tracking the workspace HERE, checked on every `ensureRange`
   * call regardless of how that call was triggered, is what makes the
   * invalidation correct independent of whatever the caller's own React
   * lifecycle happened to do.
   */
  private _lastWorkspaceSlug: string | null = null;

  constructor() {
    // No default window, and no picker to set one. The chart's viewport is the
    // range: `ensureRange` is called with whatever the reader has scrolled to,
    // and `loadedRanges` accumulates what has been answered.
    //
    // The window this replaced ran `today .. today + 12 weeks`, i.e. forward
    // only, which silently hid anyone whose scheduled work had already
    // happened — an assignee reaches `rows` only via in-window hours or
    // genuinely unscheduled work, so somebody whose every task was scheduled
    // AND finished was not a `0h` row but no row at all. Observed live: 71
    // tasks and 216.5h rendering nothing, because the latest target date was
    // one day before the window opened. A viewport-driven range cannot
    // reproduce that: you are always loading what you are looking at.
    this.service = new WorkloadService();

    makeObservable(this, {
      granularity: observable,
      loadedRanges: observable,
      coverageVersion: observable,
      selectedProjectIds: observable,
      selectedAssigneeIds: observable,
      selectedStateGroups: observable,
      workloadData: observable,
      estimateData: observable,
      rollupData: observable,
      isLoading: observable,
      error: observable,
      rollupError: observable,
      rollupInvalidationVersion: observable,

      maxColumns: computed,

      setGranularity: action,
      resetCoverage: action,
      invalidateCoverage: action,
      setProjectIds: action,
      setAssigneeIds: action,
      setStateGroups: action,
      ensureRange: action,
      fetchEstimate: action,
      fetchEstimatesBulk: action,
      updateEstimate: action,
      deleteEstimate: action,
      fetchRollups: action,
      forceRefetchRollup: action,
      patchTaskDates: action,
      rollbackTaskDates: action,
    });
  }

  // ── Computed ───────────────────────────────────────────────────────────────

  get maxColumns(): number {
    const caps: Record<TWorkloadGranularity, number> = {
      day: 62,
      week: 52,
      month: 24,
    };
    return caps[this.granularity];
  }

  // ── Actions ────────────────────────────────────────────────────────────────

  /**
   * Changing any of the four inputs below makes every cached range describe a
   * query that is no longer being asked — different bucketing, or a different
   * slice of work — so each one drops the cache rather than trying to reconcile
   * it. The next viewport settle refetches what is on screen.
   */
  setGranularity(g: TWorkloadGranularity): void {
    if (g === this.granularity) return;
    this.granularity = g;
    this.resetCoverage();
  }

  setProjectIds(ids: string[]): void {
    this.selectedProjectIds = ids;
    this.resetCoverage();
  }

  setAssigneeIds(ids: string[]): void {
    this.selectedAssigneeIds = ids;
    this.resetCoverage();
  }

  setStateGroups(groups: string[]): void {
    this.selectedStateGroups = groups;
    this.resetCoverage();
  }

  resetCoverage(): void {
    this.loadedRanges = [];
    this.workloadData = null;
    this._inFlight.clear();
    this.coverageVersion += 1;
  }

  invalidateCoverage(): void {
    // Clearing `loadedRanges` makes the next `ensureRange` treat the viewport
    // as an unfetched gap (`gaps.length === 0` short-circuit no longer
    // applies), and bumping `coverageVersion` both discards any response
    // already in flight (`_fetchGap`'s `requestedVersion` check) and fires
    // the timeline's own `coverageVersion` effect, which re-syncs the
    // viewport with no new React-side wiring needed. Deliberately does NOT
    // touch `workloadData` or `_inFlight` — see the interface doc comment.
    this.loadedRanges = [];
    this.coverageVersion += 1;
  }

  patchTaskDates(issueId: string, dates: { start_date: string | null; target_date: string }): TTaskDatesSnapshot {
    const snapshot = this._applyTaskDates(issueId, dates);
    // Invalidate WITHOUT blanking (D11) — resetCoverage's `workloadData = null`
    // would flash the whole board empty on every drag.
    this.invalidateCoverage();
    return snapshot ?? { issueId, start_date: dates.start_date, target_date: dates.target_date };
  }

  rollbackTaskDates(snapshot: TTaskDatesSnapshot): void {
    this._applyTaskDates(snapshot.issueId, { start_date: snapshot.start_date, target_date: snapshot.target_date });
    // No second `loadedRanges` clear needed: `patchTaskDates` already cleared
    // it, and whatever refetch that triggered either already landed (its
    // dates now match this rollback) or is still in flight and will be
    // discarded by the version bump below — either way a later viewport sync
    // re-fetches cleanly. See phase-1 spec's `rollbackTaskDates` note.
    this.coverageVersion += 1;
  }

  /**
   * Shared body for `patchTaskDates`/`rollbackTaskDates`: rewrite `issueId`'s
   * dates on EVERY row that carries it (a shared task appears once per
   * assignee's row) and recompute that task's `overdue` flag, returning the
   * pre-patch dates from the first occurrence found. Returns `null` when
   * `workloadData` hasn't loaded yet or carries no occurrence of `issueId` —
   * both mean there is nothing to patch.
   *
   * Replaces `workloadData` with a new top-level object, and gives only the
   * CHANGED rows new object identity (`data.rows.map` returns the original
   * row reference for every row without a match) — the `blockIds` memo in
   * `WorkloadTimelineRoot.tsx` keys on `store.workloadData`, so an in-place
   * mutation would never re-run `packTasksIntoLanes` and the bar would not
   * repack, while an unnecessarily-new reference on an untouched row would
   * bust memoization for swimlanes nothing changed in.
   *
   * Deliberately does NOT recompute `buckets`, `month_buckets`,
   * `capacity_buckets`, `over`, or `total` — those are aggregates the server
   * computes from `apps/api/plane/workload/aggregation.py`, and the refetch
   * this triggers (see `patchTaskDates`) supplies them; recomputing here
   * would mean keeping a second implementation of that arithmetic in step.
   */
  private _applyTaskDates(
    issueId: string,
    dates: { start_date: string | null; target_date: string }
  ): TTaskDatesSnapshot | null {
    const data = this.workloadData;
    if (!data) return null;

    let snapshot: TTaskDatesSnapshot | null = null;
    const today = todayDateString();

    const rows: TWorkloadRow[] = data.rows.map((row) => {
      let changed = false;
      const tasks: TWorkloadTask[] = row.tasks.map((task) => {
        if (task.id !== issueId) return task;
        if (!snapshot) {
          // `target_date` is non-null here per this task's own doc comment —
          // a task with no target date is never drawn, so it cannot be the
          // one a drag/resize is patching.
          snapshot = { issueId, start_date: task.start_date, target_date: task.target_date as string };
        }
        changed = true;
        const overdue = dates.target_date < today && !TERMINAL_STATE_GROUPS.has(task.state_group);
        return { ...task, start_date: dates.start_date, target_date: dates.target_date, overdue };
      });
      return changed ? { ...row, tasks } : row;
    });

    if (!snapshot) return null;
    this.workloadData = { ...data, rows };
    return snapshot;
  }

  async ensureRange(workspaceSlug: string, range: TDateRange, weekStartDay: number): Promise<void> {
    // Self-invalidate on a workspace change BEFORE anything else below reads
    // `loadedRanges`/`selectedProjectIds`/`selectedAssigneeIds` — see
    // `_lastWorkspaceSlug`'s own doc comment for why this lives here rather
    // than in a caller's `useEffect`. Project/assignee ids are workspace-
    // scoped UUIDs; carrying them over would silently filter the new
    // workspace's request down to entities that don't exist there, which
    // presents identically to "nothing reloaded" (an empty board, no error).
    if (this._lastWorkspaceSlug !== null && this._lastWorkspaceSlug !== workspaceSlug) {
      this.selectedProjectIds = [];
      this.selectedAssigneeIds = [];
      this.resetCoverage();
    }
    this._lastWorkspaceSlug = workspaceSlug;

    // Snap OUTWARD to whole periods before anything else. This is what lets the
    // merge be a key union instead of an addition: a period key can then only
    // ever be produced by one fetch, so re-requesting can never double-count
    // (see merge.ts's header).
    const want = snapRangeToPeriods(range, this.granularity, weekStartDay);

    // Only the parts nobody has asked for yet — this is the whole point of
    // keeping `loadedRanges`. Panning back over seen dates issues no request.
    const gaps = subtractRanges(want, [...this.loadedRanges, ...this._inFlight.values()]);
    if (gaps.length === 0) return;

    await Promise.all(gaps.map((gap) => this._fetchGap(workspaceSlug, gap)));
  }

  /**
   * Fetch ONE contiguous missing span and fold it in.
   *
   * The span is capped at the API's own limit for this granularity
   * (`MAX_SPAN_DAYS`, mirroring `_SPAN_CAPS` in views.py) because the server
   * answers an over-long range with a 400 rather than a truncation. When a gap
   * exceeds the cap the near edge is taken and the rest is left for the next
   * settle — jumping a long way loads progressively rather than failing.
   */
  private async _fetchGap(workspaceSlug: string, gap: TDateRange): Promise<void> {
    const cap = MAX_SPAN_DAYS[this.granularity];
    const capped: TDateRange =
      daysBetween(gap.from, gap.to) > cap ? { from: gap.from, to: shiftDate(gap.from, cap) } : gap;

    // Recorded BEFORE awaiting so a second scroll settle mid-flight subtracts
    // this span too, instead of racing a duplicate request for it.
    this._inFlight.set(this._inFlightKey(capped), capped);

    const filters: TWorkloadFilters = {
      granularity: this.granularity,
      date_from: capped.from,
      date_to: capped.to,
      ...(this.selectedProjectIds.length > 0 && { project_ids: this.selectedProjectIds }),
      ...(this.selectedAssigneeIds.length > 0 && { assignee_ids: this.selectedAssigneeIds }),
      ...(this.selectedStateGroups.length > 0 && { state_group: this.selectedStateGroups }),
    };
    const requestedGranularity = this.granularity;
    // Captured with it: a FILTER change clears the cache without touching
    // granularity, so the granularity guard below cannot see it on its own and
    // a response already in flight would merge into a cache that no longer
    // describes the same query.
    const requestedVersion = this.coverageVersion;

    runInAction(() => {
      this.isLoading = true;
      this.error = null;
    });

    try {
      const data = await this.service.getWorkload(workspaceSlug, filters);
      runInAction(() => {
        // A zoom or filter change while this was in flight already cleared the
        // cache; folding a stale response in would reintroduce buckets for a
        // query nobody is asking any more, which renders as plausible-looking
        // wrong numbers rather than as an error.
        if (requestedGranularity !== this.granularity || requestedVersion !== this.coverageVersion) return;
        this.workloadData = mergeWorkloadResponses(this.workloadData, data);
        this.loadedRanges = normalizeRanges([...this.loadedRanges, capped]);
      });
    } catch (err) {
      runInAction(() => {
        this.error = err instanceof Error ? err.message : String(err);
      });
    } finally {
      runInAction(() => {
        this._inFlight.delete(this._inFlightKey(capped));
        this.isLoading = this._inFlight.size > 0;
      });
    }
  }

  private _inFlightKey(range: TDateRange): string {
    return `${range.from}..${range.to}`;
  }

  async fetchEstimate(workspaceSlug: string, projectId: string, issueId: string): Promise<void> {
    // Mark as fetched upfront so concurrent bulk calls don't also request it.
    this._fetchedIds.add(issueId);
    try {
      const { estimate, rollup } = await this.service.getEstimate(workspaceSlug, projectId, issueId);
      runInAction(() => {
        this.estimateData[issueId] = estimate;
        // The single-GET response carries the rollup inline (for a parent) —
        // write it here too since the sidebar path doesn't use the bulk
        // rollup fetch (plan §P4 item 3).
        this.rollupData[issueId] = rollup;
        this._fetchedRollupIds.add(issueId);
      });
    } catch (err) {
      // Remove from fetched so a retry is allowed.
      this._fetchedIds.delete(issueId);
      runInAction(() => {
        this.error = err instanceof Error ? err.message : String(err);
      });
    }
  }

  /**
   * Bulk-fetch estimated hours for many issues at once.
   *
   * Only requests IDs not already fetched/in-flight (_fetchedIds).
   *
   * Merge rule — two-layer guard:
   * 1. Dirty-set check: skip any id currently in _dirtyIds (write in-flight).
   * 2. Epoch check: skip any id whose _lastWriteEpoch >= startEpoch (a write
   *    started AFTER this bulk request was fired but resolved before we got
   *    here — the dirty-set is already cleared by `finally`, so we use the
   *    epoch to detect that reorder window).
   */
  async fetchEstimatesBulk(workspaceSlug: string, issueIds: string[]): Promise<void> {
    // Filter to IDs not already fetched or in-flight.
    const missing = issueIds.filter((id) => !this._fetchedIds.has(id));
    if (missing.length === 0) return;

    // Snapshot the current epoch BEFORE the await so we can detect any write
    // that starts (or completes) while this request is in-flight.
    const startEpoch = this._writeEpoch;

    // Mark in-flight upfront to guard against concurrent duplicate calls.
    for (const id of missing) this._fetchedIds.add(id);

    try {
      const hoursMap = await this.service.getEstimatesBulk(workspaceSlug, missing);
      runInAction(() => {
        for (const id of missing) {
          // Layer 1: dirty-set — write is currently in-flight.
          if (this._dirtyIds.has(id)) continue;
          // Layer 2: epoch — a write started after us already settled; its
          // confirmed value is in estimateData and must not be overwritten.
          if ((this._lastWriteEpoch[id] ?? 0) >= startEpoch) continue;

          if (Object.prototype.hasOwnProperty.call(hoursMap, id)) {
            // Backend returned an estimate for this ID — store a minimal
            // TWorkloadEstimate-compatible shape (hours is the field consumers read).
            const existing = this.estimateData[id];
            if (existing) {
              // Preserve the full object if already present; only update hours.
              this.estimateData[id] = { ...existing, hours: hoursMap[id] };
            } else {
              // No prior entry — create a lightweight stub.  The full object
              // (with id/issue/created_at/updated_at) will replace this when
              // the user edits and the PUT response comes back.
              this.estimateData[id] = {
                id: "",
                issue: id,
                hours: hoursMap[id],
                created_at: "",
                updated_at: "",
              } satisfies TWorkloadEstimate;
            }
          } else {
            // Backend has no estimate for this issue — explicitly record null
            // so subsequent reads don't trigger another fetch.
            this.estimateData[id] = null;
          }
        }
      });
    } catch (err) {
      // On failure, un-mark so retries are allowed.
      for (const id of missing) this._fetchedIds.delete(id);
      runInAction(() => {
        this.error = err instanceof Error ? err.message : String(err);
      });
    }
  }

  async updateEstimate(workspaceSlug: string, projectId: string, issueId: string, hours: number): Promise<void> {
    // Bump epoch at START so any bulk GET already in-flight (startEpoch < this)
    // will discard its result for this id once it resolves.
    this._lastWriteEpoch[issueId] = ++this._writeEpoch;
    // Mark dirty so bulk GETs that haven't snapshotted startEpoch yet also skip.
    this._dirtyIds.add(issueId);
    this._fetchedIds.add(issueId); // prevent bulk re-fetch while PUT is in-flight
    try {
      const estimate = await this.service.putEstimate(workspaceSlug, projectId, issueId, hours);
      runInAction(() => {
        this.estimateData[issueId] = estimate;
        // Bump epoch again on confirmed success so the epoch test stays current
        // after dirty is cleared in `finally`.
        this._lastWriteEpoch[issueId] = ++this._writeEpoch;
        this._invalidateRollups();
      });
    } catch (err) {
      runInAction(() => {
        this.error = err instanceof Error ? err.message : String(err);
      });
      // Re-throw (after recording `error`) so callers — sidebar.tsx and
      // estimated-hours-column.tsx — can detect a typed WorkloadEstimateApiError
      // with errorCode === PARENT_HAS_CHILDREN_ERROR_CODE and run the 400 UX
      // backstop (refetch that id's rollup + toast). Plan §P4 item 4.
      throw err;
    } finally {
      // Clear dirty regardless of success or failure — epoch guard now covers
      // the post-settlement window for any bulk GET fired before this write.
      this._dirtyIds.delete(issueId);
    }
  }

  async deleteEstimate(workspaceSlug: string, projectId: string, issueId: string): Promise<void> {
    // Same epoch + dirty-set guard as updateEstimate — a concurrent bulk GET
    // must not resurrect a just-deleted estimate.
    this._lastWriteEpoch[issueId] = ++this._writeEpoch;
    this._dirtyIds.add(issueId);
    try {
      await this.service.deleteEstimate(workspaceSlug, projectId, issueId);
      runInAction(() => {
        this.estimateData[issueId] = null;
        this._lastWriteEpoch[issueId] = ++this._writeEpoch;
        this._invalidateRollups();
      });
    } catch (err) {
      runInAction(() => {
        this.error = err instanceof Error ? err.message : String(err);
      });
    } finally {
      this._dirtyIds.delete(issueId);
    }
  }

  /**
   * Bulk-fetch rollups for many issues at once.
   *
   * Only requests IDs not already fetched/in-flight (_fetchedRollupIds).
   * IDs with no rollup (non-parents) are recorded as `null` — mirrors the
   * estimate path's null-recording so a subsequent read doesn't retrigger a
   * fetch. Independent try/catch from fetchEstimatesBulk: a rollup failure
   * only ever touches _fetchedRollupIds/rollupError (plan §P4 item 3).
   */
  async fetchRollups(workspaceSlug: string, issueIds: string[]): Promise<void> {
    const missing = issueIds.filter((id) => !this._fetchedRollupIds.has(id));
    if (missing.length === 0) return;

    for (const id of missing) this._fetchedRollupIds.add(id);

    try {
      const rollupMap = await this.service.getRollupsBulk(workspaceSlug, missing);
      runInAction(() => {
        for (const id of missing) {
          this.rollupData[id] = Object.prototype.hasOwnProperty.call(rollupMap, id) ? rollupMap[id] : null;
        }
      });
    } catch (err) {
      // On failure, un-mark so retries are allowed.
      for (const id of missing) this._fetchedRollupIds.delete(id);
      runInAction(() => {
        this.rollupError = err instanceof Error ? err.message : String(err);
      });
    }
  }

  /**
   * Force a single id's rollup to be re-fetched, bypassing the dedup set.
   * Used by the 400 UX backstop: a PUT rejected with PARENT_HAS_CHILDREN
   * means the backend now considers this issue a parent, but its id may
   * already be marked fetched (previously recorded as a leaf / null rollup).
   */
  async forceRefetchRollup(workspaceSlug: string, issueId: string): Promise<void> {
    this._fetchedRollupIds.delete(issueId);
    await this.fetchRollups(workspaceSlug, [issueId]);
  }

  /**
   * Clears the rollup dedup set and bumps the invalidation version so the
   * next `useBulkWorkloadFetch` (any currently-mounted page) refires and
   * picks up fresh rollups. A single hours edit can change every ancestor's
   * rollup up the parent chain; the store has no ancestry graph to target
   * the affected ids precisely, so this invalidates broadly — one extra bulk
   * request per edit (plan §P4 item 3). Must be called from within
   * `runInAction` (both call sites already are).
   *
   * ACCEPTED v1 LIMITATION (plan §P4 item 3): this store only invalidates on
   * a successful updateEstimate/deleteEstimate. Adding or removing a
   * sub-issue (changing the parent/child relationship itself, not an
   * estimate value) happens through the core issue-parent flow, which this
   * store has no hook into — so a rollup can go stale until the next full
   * page reload or an edit that happens to touch the affected issue's own
   * hours. Not fixed in this pass; documented per plan.
   */
  private _invalidateRollups(): void {
    this._fetchedRollupIds.clear();
    this.rollupInvalidationVersion++;
  }
}

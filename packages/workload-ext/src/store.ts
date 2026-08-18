import { action, computed, makeObservable, observable, runInAction } from "mobx";
import { WorkloadService } from "./service";
import type {
  TWorkloadEstimate,
  TWorkloadFilters,
  TWorkloadGranularity,
  TWorkloadResponse,
  TWorkloadRollup,
} from "./types";

// ── Helpers ──────────────────────────────────────────────────────────────────

/** Format a Date as YYYY-MM-DD (local timezone). */
function toDateString(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/** Add `weeks` weeks to a date and return a new Date. */
function addWeeks(d: Date, weeks: number): Date {
  const result = new Date(d);
  result.setDate(result.getDate() + weeks * 7);
  return result;
}

// ── Interface ─────────────────────────────────────────────────────────────────

export interface IWorkloadStore {
  // observables
  granularity: TWorkloadGranularity;
  dateFrom: string;
  dateTo: string;
  selectedProjectIds: string[];
  selectedAssigneeIds: string[];
  selectedStateGroups: string[];
  workloadData: TWorkloadResponse | null;
  estimateData: Record<string, TWorkloadEstimate | null>; // keyed by issueId
  /** Client-side matrix filter — when true, the matrix renders only rows with `total_over`. */
  showOverCapacityOnly: boolean;
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
  setDateRange: (from: string, to: string) => void;
  setProjectIds: (ids: string[]) => void;
  setAssigneeIds: (ids: string[]) => void;
  setStateGroups: (groups: string[]) => void;
  setShowOverCapacityOnly: (value: boolean) => void;
  fetchWorkload: (workspaceSlug: string) => Promise<void>;
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
}

// ── Store ─────────────────────────────────────────────────────────────────────

export class WorkloadStore implements IWorkloadStore {
  // observables
  granularity: TWorkloadGranularity = "week";
  dateFrom: string;
  dateTo: string;
  selectedProjectIds: string[] = [];
  selectedAssigneeIds: string[] = [];
  selectedStateGroups: string[] = [];
  workloadData: TWorkloadResponse | null = null;
  estimateData: Record<string, TWorkloadEstimate | null> = {};
  showOverCapacityOnly: boolean = false;
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

  constructor() {
    const today = new Date();
    this.dateFrom = toDateString(today);
    this.dateTo = toDateString(addWeeks(today, 12));
    this.service = new WorkloadService();

    makeObservable(this, {
      granularity: observable,
      dateFrom: observable,
      dateTo: observable,
      selectedProjectIds: observable,
      selectedAssigneeIds: observable,
      selectedStateGroups: observable,
      workloadData: observable,
      estimateData: observable,
      showOverCapacityOnly: observable,
      rollupData: observable,
      isLoading: observable,
      error: observable,
      rollupError: observable,
      rollupInvalidationVersion: observable,

      maxColumns: computed,

      setGranularity: action,
      setDateRange: action,
      setProjectIds: action,
      setAssigneeIds: action,
      setStateGroups: action,
      setShowOverCapacityOnly: action,
      fetchWorkload: action,
      fetchEstimate: action,
      fetchEstimatesBulk: action,
      updateEstimate: action,
      deleteEstimate: action,
      fetchRollups: action,
      forceRefetchRollup: action,
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

  setGranularity(g: TWorkloadGranularity): void {
    this.granularity = g;
  }

  setDateRange(from: string, to: string): void {
    this.dateFrom = from;
    this.dateTo = to;
  }

  setProjectIds(ids: string[]): void {
    this.selectedProjectIds = ids;
  }

  setAssigneeIds(ids: string[]): void {
    this.selectedAssigneeIds = ids;
  }

  setStateGroups(groups: string[]): void {
    this.selectedStateGroups = groups;
  }

  setShowOverCapacityOnly(value: boolean): void {
    this.showOverCapacityOnly = value;
  }

  async fetchWorkload(workspaceSlug: string): Promise<void> {
    const filters: TWorkloadFilters = {
      granularity: this.granularity,
      date_from: this.dateFrom,
      date_to: this.dateTo,
      ...(this.selectedProjectIds.length > 0 && { project_ids: this.selectedProjectIds }),
      ...(this.selectedAssigneeIds.length > 0 && { assignee_ids: this.selectedAssigneeIds }),
      ...(this.selectedStateGroups.length > 0 && { state_group: this.selectedStateGroups }),
    };

    runInAction(() => {
      this.isLoading = true;
      this.error = null;
    });

    try {
      const data = await this.service.getWorkload(workspaceSlug, filters);
      runInAction(() => {
        this.workloadData = data;
        this.isLoading = false;
      });
    } catch (err) {
      runInAction(() => {
        this.error = err instanceof Error ? err.message : String(err);
        this.isLoading = false;
      });
    }
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

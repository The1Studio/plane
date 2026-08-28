/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { action, makeObservable, observable } from "mobx";
import type { TCascadeDescendant, TCascadeItem, TCascadeStateGroup, TModuleCascadeSummary } from "./types";

/**
 * Everything the modal needs to render one issue-subject confirmation. Fetching this (the
 * preview call) is Phase 3's job, not this store's — Phase 3 checks the preview for a non-empty
 * eligible set (Decision 3) before ever calling `requestCascade`, so the modal is never opened
 * empty. Deliberately carries NO `kind` discriminant — `requestCascade` is the only place that
 * ever needs to know it is the issue subject, and adding one here would be a breaking change to
 * every existing call site for no reader benefit.
 */
export interface TCascadeConfirmRequest {
  /** Display-only context for the modal header — never sent back to the server by this store. */
  parentIdentifier: string;
  targetGroup: TCascadeStateGroup;
  descendants: TCascadeDescendant[];
}

/**
 * The module-subject counterpart (plan.md M3). `summary` / `overCap` / `cap` are display-only —
 * carried straight from the preview response into the modal's summary header and refusal mode.
 */
export interface TModuleCascadeConfirmRequest {
  moduleName: string;
  targetGroup: TCascadeStateGroup;
  items: TCascadeItem[];
  summary: TModuleCascadeSummary;
  overCap: boolean;
  cap: number;
}

/**
 * `pendingRequest`'s actual stored shape — one MobX-observable field, two subjects, chosen by
 * `kind`. Widening `pendingRequest` in place (rather than adding a second store) is deliberate:
 * `CascadeConfirmModal` is one component, and a second store would need a second mount point in
 * `apps/web/app/root.tsx`, which Phase 2 does not own.
 */
export type TCascadeConfirmSubject =
  | ({ kind: "issue" } & TCascadeConfirmRequest)
  | ({ kind: "module" } & TModuleCascadeConfirmRequest);

export type TCascadeConfirmResult = { cascade: false } | { cascade: true; childIds: string[] };

export interface ICascadeConfirmStore {
  pendingRequest: TCascadeConfirmSubject | null;
  /** Ids of eligible rows currently ticked, whichever subject is pending. Ineligible rows are
   *  never members — and an over-cap module request starts with this empty (M4). */
  checkedIds: Set<string>;
  requestCascade: (request: TCascadeConfirmRequest) => Promise<TCascadeConfirmResult>;
  requestModuleCascade: (request: TModuleCascadeConfirmRequest) => Promise<TCascadeConfirmResult>;
  toggleChild: (id: string) => void;
  confirmOnlyParent: () => void;
  confirmCascade: () => void;
}

/**
 * Holds the pending cascade-confirmation request and the promise resolver for it. Opens the
 * modal by setting `pendingRequest`; resolves the promise once the user picks a button. Holds no
 * UI logic — `CascadeConfirmModal` reads this store and calls its actions; the actual PATCH /
 * cascade-apply call is Phase 3's, using the resolved `{ cascade, childIds }`.
 */
export class CascadeConfirmStore implements ICascadeConfirmStore {
  pendingRequest: TCascadeConfirmSubject | null = null;
  checkedIds: Set<string> = new Set();

  private _resolve: ((result: TCascadeConfirmResult) => void) | null = null;

  constructor() {
    makeObservable(this, {
      pendingRequest: observable,
      checkedIds: observable,
      requestCascade: action,
      requestModuleCascade: action,
      toggleChild: action,
      confirmOnlyParent: action,
      confirmCascade: action,
    });
  }

  requestCascade(request: TCascadeConfirmRequest): Promise<TCascadeConfirmResult> {
    // A prior pending request left unresolved (shouldn't happen — one modal at a time) resolves
    // as "do not cascade" rather than leaving its caller awaiting forever.
    this._resolvePending({ cascade: false });
    this.pendingRequest = { kind: "issue", ...request };
    this.checkedIds = new Set(request.descendants.filter((d) => d.eligible).map((d) => d.id));
    return new Promise<TCascadeConfirmResult>((resolve) => {
      this._resolve = resolve;
    });
  }

  /**
   * The module-subject counterpart of `requestCascade`. When `request.overCap` is true (M4) the
   * checked set starts and stays empty — the modal renders refusal mode with no list and no
   * cascade button, so `checkedIds` is never read there, but leaving it non-empty would be a trap
   * for the next reader who adds a code path that does read it.
   */
  requestModuleCascade(request: TModuleCascadeConfirmRequest): Promise<TCascadeConfirmResult> {
    this._resolvePending({ cascade: false });
    this.pendingRequest = { kind: "module", ...request };
    this.checkedIds = request.overCap ? new Set() : new Set(request.items.filter((i) => i.eligible).map((i) => i.id));
    return new Promise<TCascadeConfirmResult>((resolve) => {
      this._resolve = resolve;
    });
  }

  toggleChild(id: string): void {
    if (!this.pendingRequest) return;
    const row = this._rows().find((r) => r.id === id);
    if (!row || !row.eligible) return; // ineligible rows are never toggleable (Decision 8)
    if (this.checkedIds.has(id)) this.checkedIds.delete(id);
    else this.checkedIds.add(id);
  }

  /**
   * "Only change this item" / "Only change this module" — the default action (Decision 2, M3).
   * Also what a modal dismissal (Escape key / backdrop click, via `ModalCore`'s `handleClose`)
   * resolves to: closing without an explicit choice gets the same safe default as a stray Enter
   * would. Subject-agnostic — the modal itself renders the button label for whichever subject is
   * pending.
   */
  confirmOnlyParent(): void {
    this._resolvePending({ cascade: false });
    this._clear();
  }

  confirmCascade(): void {
    this._resolvePending({ cascade: true, childIds: Array.from(this.checkedIds) });
    this._clear();
  }

  /** The eligible/ineligible row set for whichever subject is pending — issue `descendants` or
   *  module `items`. `TCascadeItem` is a strict superset of `TCascadeDescendant`, so this is a
   *  plain narrowing read, not a projection. */
  private _rows(): readonly TCascadeDescendant[] {
    if (!this.pendingRequest) return [];
    return this.pendingRequest.kind === "issue" ? this.pendingRequest.descendants : this.pendingRequest.items;
  }

  private _resolvePending(result: TCascadeConfirmResult): void {
    if (!this._resolve) return;
    this._resolve(result);
    this._resolve = null;
  }

  private _clear(): void {
    this.pendingRequest = null;
    this.checkedIds = new Set();
  }
}

/**
 * Shared singleton. Lives here rather than in apps/web so that `root.tsx` (the
 * modal mount) and `base-issues.store.ts` (the guard) can both reach it without
 * importing each other — instantiating it inside the store module made root.tsx
 * pull the whole store graph into the SSR entry, producing a circular import and
 * a "Cannot access 'BaseIssuesStore' before initialization" TDZ crash at
 * prerender. Mirrors the existing `cascadeService` singleton in cascade-service.ts.
 */
export const cascadeConfirmStore = new CascadeConfirmStore();

/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { action, makeObservable, observable } from "mobx";
import type { TCascadeDescendant, TCascadeStateGroup } from "./types";

/**
 * Everything the modal needs to render one confirmation. Fetching this (the preview call) is
 * Phase 3's job, not this store's — Phase 3 checks the preview for a non-empty eligible set
 * (Decision 3) before ever calling `requestCascade`, so the modal is never opened empty.
 */
export interface TCascadeConfirmRequest {
  /** Display-only context for the modal header — never sent back to the server by this store. */
  parentIdentifier: string;
  targetGroup: TCascadeStateGroup;
  descendants: TCascadeDescendant[];
}

export type TCascadeConfirmResult = { cascade: false } | { cascade: true; childIds: string[] };

export interface ICascadeConfirmStore {
  pendingRequest: TCascadeConfirmRequest | null;
  /** Ids of eligible descendant rows currently ticked. Ineligible rows are never members. */
  checkedIds: Set<string>;
  requestCascade: (request: TCascadeConfirmRequest) => Promise<TCascadeConfirmResult>;
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
  pendingRequest: TCascadeConfirmRequest | null = null;
  checkedIds: Set<string> = new Set();

  private _resolve: ((result: TCascadeConfirmResult) => void) | null = null;

  constructor() {
    makeObservable(this, {
      pendingRequest: observable,
      checkedIds: observable,
      requestCascade: action,
      toggleChild: action,
      confirmOnlyParent: action,
      confirmCascade: action,
    });
  }

  requestCascade(request: TCascadeConfirmRequest): Promise<TCascadeConfirmResult> {
    // A prior pending request left unresolved (shouldn't happen — one modal at a time) resolves
    // as "do not cascade" rather than leaving its caller awaiting forever.
    this._resolvePending({ cascade: false });
    this.pendingRequest = request;
    this.checkedIds = new Set(request.descendants.filter((d) => d.eligible).map((d) => d.id));
    return new Promise<TCascadeConfirmResult>((resolve) => {
      this._resolve = resolve;
    });
  }

  toggleChild(id: string): void {
    if (!this.pendingRequest) return;
    const row = this.pendingRequest.descendants.find((d) => d.id === id);
    if (!row || !row.eligible) return; // ineligible rows are never toggleable (Decision 8)
    if (this.checkedIds.has(id)) this.checkedIds.delete(id);
    else this.checkedIds.add(id);
  }

  /**
   * "Only change this item" — the default action (Decision 2). Also what a modal dismissal
   * (Escape key / backdrop click, via `ModalCore`'s `handleClose`) resolves to: closing without
   * an explicit choice gets the same safe default as a stray Enter would.
   */
  confirmOnlyParent(): void {
    this._resolvePending({ cascade: false });
    this._clear();
  }

  confirmCascade(): void {
    this._resolvePending({ cascade: true, childIds: Array.from(this.checkedIds) });
    this._clear();
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

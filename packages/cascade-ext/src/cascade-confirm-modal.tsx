/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { observer } from "mobx-react";
import { useEffect, useRef, useState } from "react";
import { Button } from "@plane/propel/button";
import { Checkbox, EModalPosition, EModalWidth, ModalCore } from "@plane/ui";
import type { CascadeConfirmStore, TCascadeConfirmSubject } from "./cascade-confirm-store";
import { CASCADE_LIST_CONTROL_STRINGS, CASCADE_STRINGS, MODULE_CASCADE_STRINGS } from "./strings";
import type { TCascadeDescendant } from "./types";

export interface CascadeConfirmModalProps {
  store: CascadeConfirmStore;
}

/** Indentation per nesting level (Modal requirement 5) — matches the sub-issues list widget's
 *  own `spacingLeft` convention (base 10px, +22px per depth). */
const INDENT_BASE_PX = 10;
const INDENT_PER_DEPTH_PX = 22;

/**
 * Above this row count the list starts collapsed behind a "Show all N items" disclosure
 * (plan.md M3). At or below it — every realistic issue cascade — the list renders exactly as
 * the shipped modal always has, so this is not a behavior change for that flow.
 */
const LIST_COLLAPSE_THRESHOLD = 15;

/** One checkbox row — identical markup for an issue descendant or a module item, since
 *  `TCascadeItem` is a superset of `TCascadeDescendant` and the row never reads the extra
 *  `is_module_member` field. */
function CascadeRow(props: { row: TCascadeDescendant; store: CascadeConfirmStore }) {
  const { row, store } = props;
  return (
    <li
      className="flex items-center gap-2"
      style={{ paddingLeft: `${INDENT_BASE_PX + row.depth * INDENT_PER_DEPTH_PX}px` }}
    >
      <Checkbox
        checked={row.eligible && store.checkedIds.has(row.id)}
        disabled={!row.eligible}
        onChange={() => store.toggleChild(row.id)}
        aria-label={CASCADE_STRINGS.rowCheckboxLabel(row.identifier)}
      />
      <span className="flex flex-col text-13">
        <span>
          <span className="text-secondary">{row.identifier}</span> {row.name}
        </span>
        <span className="text-12 text-secondary">
          {row.eligible ? CASCADE_STRINGS.currentState(row.state_name) : CASCADE_STRINGS.ineligibleReason(row.reason)}
        </span>
      </span>
    </li>
  );
}

/**
 * Confirmation modal for cascading a parent's terminal state to its sub-items (issue #54) or a
 * module's terminal status to its work items (plan.md M3 — same modal, a summary header and a
 * collapsible list added on top). Built on `@plane/ui`'s `ModalCore` — no hand-rolled dialog, no
 * bespoke focus trap.
 */
export const CascadeConfirmModal = observer(function CascadeConfirmModal(props: CascadeConfirmModalProps) {
  const { store } = props;
  const request: TCascadeConfirmSubject | null = store.pendingRequest;
  const onlyParentButtonRef = useRef<HTMLButtonElement>(null);
  const [isExpanded, setIsExpanded] = useState(false);

  // Decision 2 (the single most load-bearing detail in this modal): "Only change this item /
  // module" must hold initial focus so a stray Enter never cascades, for EITHER subject and in
  // refusal mode alike. `ModalCore` doesn't thread a headlessUI `initialFocus` ref through to its
  // `Dialog`, and this component is a DESCENDANT of Dialog's own FocusTrap, so a plain `useEffect`
  // here runs and calls `.focus()` BEFORE FocusTrap's own initial-focus effect (parents run after
  // children in the same commit) — and that effect defers its actual "focus the first focusable
  // element" default to a microtask, which then overrides whatever this effect just set. A
  // `setTimeout` (a macrotask) is guaranteed to run only after every microtask — including that
  // deferred one — has drained, so it reliably runs last regardless of how many effect levels sit
  // between this component and the trap. The cost is one animation frame's worth of default focus
  // before this overrides it, imperceptible to a real user and not a race a synchronous effect can
  // win here.
  useEffect(() => {
    if (!request) return;
    const timeoutId = setTimeout(() => onlyParentButtonRef.current?.focus(), 0);
    return () => clearTimeout(timeoutId);
  }, [request]);

  // A fresh `pendingRequest` is a new object every time (`requestCascade` / `requestModuleCascade`
  // never mutate the previous one), so re-collapsing on it means a second confirmation for a
  // different subject never inherits an expanded list left open by the first.
  useEffect(() => {
    setIsExpanded(false);
  }, [request]);

  if (!request) {
    // `ModalCore.children` is a required prop (`packages/ui/src/modals/modal-core.tsx`) — `null`
    // renders nothing, matching `{request && (...)}`'s old falsy-child behavior when closed.
    return (
      <ModalCore
        isOpen={false}
        handleClose={() => store.confirmOnlyParent()}
        position={EModalPosition.CENTER}
        width={EModalWidth.XL}
      >
        {null}
      </ModalCore>
    );
  }

  const isModule = request.kind === "module";
  const refusalMode = isModule && request.overCap;
  const rows: readonly TCascadeDescendant[] = isModule ? request.items : request.descendants;
  const showDisclosure = !refusalMode && rows.length > LIST_COLLAPSE_THRESHOLD;
  const visibleRows = refusalMode ? [] : showDisclosure && !isExpanded ? [] : rows;
  const eligibleRows = rows.filter((row) => row.eligible);

  const title = isModule ? MODULE_CASCADE_STRINGS.title : CASCADE_STRINGS.title;
  const onlyButtonLabel = isModule ? MODULE_CASCADE_STRINGS.onlyModuleButton : CASCADE_STRINGS.onlyParentButton;
  const cascadeButtonLabel = isModule ? MODULE_CASCADE_STRINGS.cascadeModuleButton : CASCADE_STRINGS.cascadeButton;

  const selectAll = () => {
    for (const row of eligibleRows) if (!store.checkedIds.has(row.id)) store.toggleChild(row.id);
  };
  const selectNone = () => {
    for (const row of eligibleRows) if (store.checkedIds.has(row.id)) store.toggleChild(row.id);
  };

  return (
    <ModalCore
      isOpen={Boolean(request)}
      handleClose={() => store.confirmOnlyParent()}
      position={EModalPosition.CENTER}
      width={EModalWidth.XL}
    >
      <div className="p-5">
        <h3 className="text-16 font-medium">{title}</h3>

        {refusalMode ? (
          // Refusal mode (M4): no list, no checkboxes, no "Change work items too" button — the
          // module's own status write still happens via `confirmOnlyParent` below.
          <p className="mt-1 text-13 text-secondary">
            {MODULE_CASCADE_STRINGS.overCapBody(request.summary.total_live, request.cap)}
          </p>
        ) : (
          <>
            <p className="mt-1 text-13 text-secondary">
              {isModule
                ? MODULE_CASCADE_STRINGS.description(request.moduleName, request.targetGroup)
                : CASCADE_STRINGS.description(request.parentIdentifier, request.targetGroup)}
            </p>
            {isModule && (
              <p className="mt-1 text-13 text-secondary">
                {MODULE_CASCADE_STRINGS.summary(request.summary, request.targetGroup)}
              </p>
            )}

            {showDisclosure && (
              <div className="mt-4 flex items-center gap-3 text-13">
                <button type="button" className="text-secondary underline" onClick={selectAll}>
                  {CASCADE_LIST_CONTROL_STRINGS.selectAll}
                </button>
                <button type="button" className="text-secondary underline" onClick={selectNone}>
                  {CASCADE_LIST_CONTROL_STRINGS.selectNone}
                </button>
                <button
                  type="button"
                  className="ml-auto text-secondary underline"
                  onClick={() => setIsExpanded((prev) => !prev)}
                >
                  {isExpanded
                    ? CASCADE_LIST_CONTROL_STRINGS.showLess
                    : CASCADE_LIST_CONTROL_STRINGS.showAllItems(rows.length)}
                </button>
              </div>
            )}

            {visibleRows.length > 0 && (
              <ul className={`flex max-h-80 flex-col gap-1 overflow-y-auto ${showDisclosure ? "mt-2" : "mt-4"}`}>
                {visibleRows.map((row) => (
                  <CascadeRow key={row.id} row={row} store={store} />
                ))}
              </ul>
            )}
          </>
        )}
      </div>
      <div className="flex flex-col-reverse gap-2 border-t-[0.5px] border-subtle px-5 py-4 sm:flex-row sm:justify-end">
        <Button ref={onlyParentButtonRef} variant="secondary" onClick={() => store.confirmOnlyParent()}>
          {onlyButtonLabel}
        </Button>
        {!refusalMode && (
          <Button variant="primary" onClick={() => store.confirmCascade()}>
            {cascadeButtonLabel}
          </Button>
        )}
      </div>
    </ModalCore>
  );
});

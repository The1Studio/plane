import { observer } from "mobx-react";
import { useEffect, useRef } from "react";
import { Button } from "@plane/propel/button";
import { Checkbox, EModalPosition, EModalWidth, ModalCore } from "@plane/ui";
import type { CascadeConfirmStore } from "./cascade-confirm-store";
import { CASCADE_STRINGS } from "./strings";

export interface CascadeConfirmModalProps {
  store: CascadeConfirmStore;
}

/** Indentation per nesting level (Modal requirement 5) — matches the sub-issues list widget's
 *  own `spacingLeft` convention (base 10px, +22px per depth). */
const INDENT_BASE_PX = 10;
const INDENT_PER_DEPTH_PX = 22;

/**
 * Confirmation modal for cascading a parent's terminal state to its sub-items (issue #54).
 * Built on `@plane/ui`'s `ModalCore` — no hand-rolled dialog, no bespoke focus trap.
 */
export const CascadeConfirmModal = observer(function CascadeConfirmModal(props: CascadeConfirmModalProps) {
  const { store } = props;
  const request = store.pendingRequest;
  const onlyParentButtonRef = useRef<HTMLButtonElement>(null);

  // Decision 2 (the single most load-bearing detail in this modal): "Only change this item"
  // must hold initial focus so a stray Enter never cascades. `ModalCore` doesn't thread a
  // headlessUI `initialFocus` ref through to its `Dialog`, and this component is a DESCENDANT of
  // Dialog's own FocusTrap, so a plain `useEffect` here runs and calls `.focus()` BEFORE
  // FocusTrap's own initial-focus effect (parents run after children in the same commit) — and
  // that effect defers its actual "focus the first focusable element" default to a microtask,
  // which then overrides whatever this effect just set. A `setTimeout` (a macrotask) is
  // guaranteed to run only after every microtask — including that deferred one — has drained, so
  // it reliably runs last regardless of how many effect levels sit between this component and
  // the trap. The cost is one animation frame's worth of default focus before this overrides it,
  // imperceptible to a real user and not a race a synchronous effect can win here.
  useEffect(() => {
    if (!request) return;
    const timeoutId = setTimeout(() => onlyParentButtonRef.current?.focus(), 0);
    return () => clearTimeout(timeoutId);
  }, [request]);

  return (
    <ModalCore
      isOpen={Boolean(request)}
      handleClose={() => store.confirmOnlyParent()}
      position={EModalPosition.CENTER}
      width={EModalWidth.XL}
    >
      {request && (
        <>
          <div className="p-5">
            <h3 className="text-16 font-medium">{CASCADE_STRINGS.title}</h3>
            <p className="mt-1 text-13 text-secondary">
              {CASCADE_STRINGS.description(request.parentIdentifier, request.targetGroup)}
            </p>
            <ul className="mt-4 flex max-h-80 flex-col gap-1 overflow-y-auto">
              {request.descendants.map((descendant) => (
                <li
                  key={descendant.id}
                  className="flex items-center gap-2"
                  style={{ paddingLeft: `${INDENT_BASE_PX + descendant.depth * INDENT_PER_DEPTH_PX}px` }}
                >
                  <Checkbox
                    checked={descendant.eligible && store.checkedIds.has(descendant.id)}
                    disabled={!descendant.eligible}
                    onChange={() => store.toggleChild(descendant.id)}
                    aria-label={CASCADE_STRINGS.rowCheckboxLabel(descendant.identifier)}
                  />
                  <span className="flex flex-col text-13">
                    <span>
                      <span className="text-secondary">{descendant.identifier}</span> {descendant.name}
                    </span>
                    <span className="text-12 text-secondary">
                      {descendant.eligible
                        ? CASCADE_STRINGS.currentState(descendant.state_name)
                        : CASCADE_STRINGS.ineligibleReason(descendant.reason)}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          </div>
          <div className="flex flex-col-reverse gap-2 border-t-[0.5px] border-subtle px-5 py-4 sm:flex-row sm:justify-end">
            <Button ref={onlyParentButtonRef} variant="secondary" onClick={() => store.confirmOnlyParent()}>
              {CASCADE_STRINGS.onlyParentButton}
            </Button>
            <Button variant="primary" onClick={() => store.confirmCascade()}>
              {CASCADE_STRINGS.cascadeButton}
            </Button>
          </div>
        </>
      )}
    </ModalCore>
  );
});

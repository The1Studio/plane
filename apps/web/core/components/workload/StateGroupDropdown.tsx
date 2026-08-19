// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
//
// The1Studio fork (workload timeline) — multi-select dropdown over the five
// work-item state GROUPS (backlog / unstarted / started / completed /
// cancelled).
//
// Why it lives here and not in `packages/workload-ext`: the toolbar's Members
// and Projects controls are Plane's own dropdowns, injected by the host page
// because the package's dependency set (@plane/propel, @plane/constants,
// @plane/types) cannot reach `@/hooks/use-dropdown`, `@plane/ui`'s
// `ComboDropDown`, or `@/components/dropdowns/buttons`. Building the status
// control inside the package would produce an approximation of that chrome
// rather than the chrome itself, and the three controls would drift apart on
// the next upstream restyle. So it is composed here from the same parts and
// handed down through `WorkloadToolbar`'s `stateFilterSlot`.
//
// Modelled on `@/components/dropdowns/project/base.tsx`. Three deliberate
// divergences from it, each noted at its site below.

import { useRef, useState } from "react";
import { usePopper } from "react-popper";
import { Combobox } from "@headlessui/react";
import { STATE_GROUPS } from "@plane/constants";
import { CheckIcon, ChevronDownIcon, StateGroupIcon } from "@plane/propel/icons";
import type { TStateGroups } from "@plane/types";
import { ComboDropDown } from "@plane/ui";
import { cn } from "@plane/utils";
import { useDropdown } from "@/hooks/use-dropdown";
import { DropdownButton } from "../dropdowns/buttons";
import { BUTTON_VARIANTS_WITH_TEXT } from "../dropdowns/constants";
import type { TDropdownProps } from "../dropdowns/types";

type Props = TDropdownProps & {
  dropdownArrow?: boolean;
  dropdownArrowClassName?: string;
  onChange: (val: string[]) => void;
  onClose?: () => void;
  value: string[];
};

const STATE_GROUP_OPTIONS = Object.values(STATE_GROUPS);

/**
 * `0` selected reads as the placeholder ("Status"), `1` as that group's own
 * label, `n>1` as a count — mirrors `getDisplayName` in the project dropdown so
 * the three toolbar controls read alike.
 */
function getDisplayName(value: string[], placeholder: string): string {
  if (value.length === 0) return placeholder;
  if (value.length === 1) {
    const group = STATE_GROUP_OPTIONS.find((g) => g.key === value[0]);
    return group?.label ?? placeholder;
  }
  return `${value.length} statuses`;
}

export function StateGroupDropdown(props: Props) {
  const {
    buttonClassName,
    buttonContainerClassName,
    buttonVariant,
    className = "",
    disabled = false,
    dropdownArrow = false,
    dropdownArrowClassName = "",
    hideIcon = false,
    onChange,
    onClose,
    placeholder = "Status",
    placement,
    showTooltip = false,
    tabIndex,
    value,
  } = props;
  // refs
  const dropdownRef = useRef<HTMLDivElement | null>(null);
  // popper-js refs
  const [referenceElement, setReferenceElement] = useState<HTMLButtonElement | null>(null);
  const [popperElement, setPopperElement] = useState<HTMLDivElement | null>(null);
  // states
  const [isOpen, setIsOpen] = useState(false);
  // popper-js init
  const { styles, attributes } = usePopper(referenceElement, popperElement, {
    placement: placement ?? "bottom-start",
    modifiers: [{ name: "preventOverflow", options: { padding: 12 } }],
  });

  // DIVERGENCE 1 — no search input. Five fixed options fit without scrolling,
  // so `useDropdown` is driven with a permanently empty query and no
  // `Combobox.Input` is rendered; a search box over five rows is noise.
  const { handleKeyDown, handleOnClick } = useDropdown({
    dropdownRef,
    inputRef: useRef<HTMLInputElement | null>(null),
    isOpen,
    onClose,
    query: "",
    setIsOpen,
    setQuery: () => {},
  });

  // DIVERGENCE 2 — no `sortBySelectedFirst`. With a five-row non-scrolling
  // list, re-ordering on select makes options jump under the cursor and buys
  // nothing; the fixed backlog→cancelled order is also the lifecycle order,
  // which is worth more here than selection grouping.

  // DIVERGENCE 3 — no `observer` wrapper and no store hook. `STATE_GROUPS` is
  // a constant, so unlike ProjectDropdown/MemberDropdown this is a plain
  // controlled input with no MobX subscription to make.

  const comboButton = (
    <button
      ref={setReferenceElement}
      type="button"
      className={cn(
        "clickable block h-full max-w-full outline-none",
        { "cursor-not-allowed text-secondary": disabled, "cursor-pointer": !disabled },
        buttonContainerClassName
      )}
      onClick={handleOnClick}
      disabled={disabled}
    >
      <DropdownButton
        className={buttonClassName}
        isActive={isOpen}
        tooltipHeading="Status"
        tooltipContent={value.length ? getDisplayName(value, placeholder) : placeholder}
        showTooltip={showTooltip}
        variant={buttonVariant}
      >
        {!hideIcon && (
          <div className="flex items-center gap-0.5">
            {value.length > 0 ? (
              value.map((groupKey) => <StateGroupIcon key={groupKey} stateGroup={groupKey as TStateGroups} />)
            ) : (
              <StateGroupIcon stateGroup="backlog" className="text-tertiary" />
            )}
          </div>
        )}
        {BUTTON_VARIANTS_WITH_TEXT.includes(buttonVariant) && (
          <span className="max-w-40 truncate">{getDisplayName(value, placeholder)}</span>
        )}
        {dropdownArrow && (
          <ChevronDownIcon className={cn("h-2.5 w-2.5 flex-shrink-0", dropdownArrowClassName)} aria-hidden="true" />
        )}
      </DropdownButton>
    </button>
  );

  return (
    // `no-static-element-interactions` reads `as="div"` + `onKeyDown` as a bare
    // interactive div. It is not: `ComboDropDown` renders a headless-ui
    // `Combobox`, which supplies its own `role`/ARIA wiring, and `handleKeyDown`
    // only adds Escape-to-close on top. The same warning fires on
    // `dropdowns/project/base.tsx`, which this is modelled on; lint-staged runs
    // oxlint with `--deny-warnings`, so it has to be silenced at the site rather
    // than left as ambient noise.
    // eslint-disable-next-line jsx-a11y/no-static-element-interactions
    <ComboDropDown
      as="div"
      ref={dropdownRef}
      tabIndex={tabIndex}
      className={cn("h-full", className)}
      value={value}
      onChange={onChange}
      disabled={disabled}
      onKeyDown={handleKeyDown}
      button={comboButton}
      multiple
    >
      {isOpen && (
        <Combobox.Options className="fixed z-10" static>
          <div
            className="my-1 w-48 rounded-sm border-[0.5px] border-strong bg-surface-1 px-2 py-2.5 text-11 shadow-raised-200 focus:outline-none"
            ref={setPopperElement}
            style={styles.popper}
            {...attributes.popper}
          >
            <div className="space-y-1">
              {STATE_GROUP_OPTIONS.map((group) => (
                <Combobox.Option
                  key={group.key}
                  value={group.key}
                  className={({ active, selected }) =>
                    `flex w-full cursor-pointer items-center justify-between gap-2 truncate rounded-sm px-1 py-1.5 select-none ${
                      active ? "bg-layer-transparent-hover" : ""
                    } ${selected ? "text-primary" : "text-secondary"}`
                  }
                >
                  {({ selected }) => (
                    <>
                      <span className="flex flex-grow items-center gap-2 truncate">
                        <StateGroupIcon stateGroup={group.key} />
                        <span className="flex-grow truncate">{group.label}</span>
                      </span>
                      {selected && <CheckIcon className="h-3.5 w-3.5 flex-shrink-0" />}
                    </>
                  )}
                </Combobox.Option>
              ))}
            </div>
          </div>
        </Combobox.Options>
      )}
    </ComboDropDown>
  );
}

/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
// The1Studio fork (views-search). Deliberately parallel to core's `PageSearchInput`
// (`apps/web/core/components/pages/list/search-input.tsx`), which implements the same interaction.
// It is not reused because a file under `packages/` cannot import from `apps/web/core/` — that
// package-graph edge does not exist — and because its placeholder is hardcoded to "Search pages".
// See plan.md § D6. Do not "de-duplicate" these without first resolving the dependency direction.
//
// Presentational and fully controlled: no store import, no fetch, no debounce. Phase 3 owns all
// three (plan.md § D4), keeping this component renderable in isolation and free of the store cycle.

import { useRef, useState } from "react";
import { useOutsideClickDetector } from "@plane/hooks";
import { IconButton } from "@plane/propel/icon-button";
import { CloseIcon, SearchIcon } from "@plane/propel/icons";
import { cn } from "@plane/utils";

type Props = {
  searchQuery: string;
  updateSearchQuery: (val: string) => void;
  placeholder?: string;
};

export function WorkItemSearchInput(props: Props) {
  const { searchQuery, updateSearchQuery, placeholder = "Search work items" } = props;
  // states
  const [isSearchOpen, setIsSearchOpen] = useState(false);
  // refs
  const inputRef = useRef<HTMLInputElement>(null);

  // outside click collapses only when the term is empty, so clicking into the
  // list does not lose an active search
  useOutsideClickDetector(inputRef, () => {
    if (isSearchOpen && searchQuery.trim() === "") setIsSearchOpen(false);
  });

  const handleInputKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Escape") {
      if (searchQuery && searchQuery.trim() !== "") updateSearchQuery("");
      else {
        setIsSearchOpen(false);
        inputRef.current?.blur();
      }
    }
  };

  return (
    <div className="flex">
      {!isSearchOpen && (
        <IconButton
          variant="ghost"
          size="lg"
          className="my-auto -mr-1 shrink-0"
          onClick={() => {
            setIsSearchOpen(true);
            inputRef.current?.focus();
          }}
          icon={SearchIcon}
        />
      )}
      <div
        className={cn(
          "flex w-0 items-center justify-start overflow-hidden rounded-md border border-transparent text-placeholder opacity-0 transition-[width] ease-linear",
          {
            "w-64 border-subtle px-2.5 py-1.5 opacity-100": isSearchOpen,
          }
        )}
      >
        <SearchIcon className="h-3.5 w-3.5" />
        <input
          ref={inputRef}
          className="ml-2 w-full max-w-[234px] border-none bg-transparent text-13 text-primary placeholder:text-placeholder focus:outline-none"
          placeholder={placeholder}
          value={searchQuery}
          onChange={(e) => updateSearchQuery(e.target.value)}
          onKeyDown={handleInputKeyDown}
        />
        {isSearchOpen && (
          <button
            type="button"
            className="grid place-items-center"
            onClick={() => {
              updateSearchQuery("");
              setIsSearchOpen(false);
            }}
          >
            <CloseIcon className="h-3 w-3" />
          </button>
        )}
      </div>
    </div>
  );
}

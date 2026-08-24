/**
 * The1Studio fork (SP2 workload / work-item modal estimated hours) — fork-owned.
 * Listed in docs/FORK.md "Frontend core-edit exceptions" alongside the rest of
 * `packages/workload-ext`.
 *
 * Holds the "Estimated hours" draft for a work item that does not exist yet
 * (create mode of the Add-work-item modal). There is no network write until
 * the item has an id — see `use-workload-estimate-editor.ts` for the update
 * mode, which goes through a live PUT instead and never touches this context.
 *
 * The provider is a controlled carrier, not a state owner: `pendingHours` /
 * `setPendingHours` are owned one level up (`CreateUpdateIssueModalBase`),
 * which needs to read the value on create and reset it on close/"create more".
 */

import { createContext, useContext, useMemo } from "react";
import type { ReactNode } from "react";

export type TPendingEstimateContext = {
  /** Raw draft string for a work item that does not exist yet. "" means untouched. */
  pendingHours: string;
  setPendingHours: (raw: string) => void;
};

type TPendingEstimateProviderProps = TPendingEstimateContext & { children: ReactNode };

const PendingEstimateContext = createContext<TPendingEstimateContext | null>(null);

export function PendingEstimateProvider(props: TPendingEstimateProviderProps) {
  const { pendingHours, setPendingHours, children } = props;

  const value = useMemo<TPendingEstimateContext>(
    () => ({ pendingHours, setPendingHours }),
    [pendingHours, setPendingHours]
  );

  return <PendingEstimateContext.Provider value={value}>{children}</PendingEstimateContext.Provider>;
}

/**
 * Throws when used outside `PendingEstimateProvider` — a silent no-op context
 * would make a mis-wired provider look like "the field just doesn't save".
 */
export function usePendingEstimate(): TPendingEstimateContext {
  const context = useContext(PendingEstimateContext);
  if (context === null) {
    throw new Error("usePendingEstimate must be used within a PendingEstimateProvider");
  }
  return context;
}

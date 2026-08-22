import type { TIssue } from "@plane/types";
import type { TCascadeStateGroup } from "./types";

const TERMINAL_GROUPS: ReadonlySet<TCascadeStateGroup> = new Set(["completed", "cancelled"]);

export interface TShouldPromptCascadeArgs {
  data: Partial<TIssue>;
  subIssuesCount: number;
  getStateGroupById: (id: string) => string | undefined;
}

/**
 * The guard that keeps the common case free (plan.md § Flow, step 2). Returns the terminal
 * group the parent is about to enter ONLY when a `state_id` is present in `data`, that state's
 * group is one of the two terminal groups, AND the issue actually has sub-issues. Otherwise
 * `null` — no preview request, no modal.
 *
 * This runs before any network call and must stay synchronous and cheap: a Done click on a
 * leaf — the overwhelmingly common case — must cost exactly zero extra requests.
 *
 * Resolved by GROUP, never by state NAME. States are renameable per project (Decision 7 / issue
 * #54's own report), so comparing against a literal state label is exactly the bug this feature
 * exists to avoid reintroducing — `getStateGroupById` is the only source of truth here.
 */
export function shouldPromptCascade(args: TShouldPromptCascadeArgs): TCascadeStateGroup | null {
  const { data, subIssuesCount, getStateGroupById } = args;
  if (subIssuesCount <= 0) return null;
  if (!data.state_id) return null;
  const group = getStateGroupById(data.state_id);
  if (!group) return null;
  if (!TERMINAL_GROUPS.has(group as TCascadeStateGroup)) return null;
  return group as TCascadeStateGroup;
}

import { describe, expect, it } from "vitest";
import { shouldPromptCascade } from "../should-prompt-cascade";

const STATE_GROUPS: Record<string, string> = {
  "state-unstarted": "unstarted",
  "state-started": "started",
  "state-completed": "completed",
  "state-cancelled": "cancelled",
  // A state renamed from "Done" to "Shipped" — same id, same group, different label. Proves
  // resolution goes through the group lookup and never touches a name string.
  "state-shipped": "completed",
};

const getStateGroupById = (id: string): string | undefined => STATE_GROUPS[id];

describe("shouldPromptCascade", () => {
  it("returns null when state_id is absent", () => {
    expect(shouldPromptCascade({ data: {}, subIssuesCount: 3, getStateGroupById })).toBeNull();
  });

  it("returns null for a non-terminal group (started)", () => {
    expect(
      shouldPromptCascade({ data: { state_id: "state-started" }, subIssuesCount: 3, getStateGroupById })
    ).toBeNull();
  });

  it("returns null when subIssuesCount is 0", () => {
    expect(
      shouldPromptCascade({ data: { state_id: "state-completed" }, subIssuesCount: 0, getStateGroupById })
    ).toBeNull();
  });

  it("returns 'completed' for a terminal completed move with children", () => {
    expect(shouldPromptCascade({ data: { state_id: "state-completed" }, subIssuesCount: 1, getStateGroupById })).toBe(
      "completed"
    );
  });

  it("returns 'cancelled' for a terminal cancelled move with children", () => {
    expect(shouldPromptCascade({ data: { state_id: "state-cancelled" }, subIssuesCount: 1, getStateGroupById })).toBe(
      "cancelled"
    );
  });

  it("resolves by group, not name — a state renamed Done -> Shipped still reads as completed", () => {
    expect(shouldPromptCascade({ data: { state_id: "state-shipped" }, subIssuesCount: 1, getStateGroupById })).toBe(
      "completed"
    );
  });

  it("returns null when the state id is unknown to the lookup", () => {
    expect(
      shouldPromptCascade({ data: { state_id: "state-does-not-exist" }, subIssuesCount: 1, getStateGroupById })
    ).toBeNull();
  });
});

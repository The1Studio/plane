/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { describe, expect, it } from "vitest";
import { shouldPromptCascade, shouldPromptModuleCascade } from "../should-prompt-cascade";

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

describe("shouldPromptModuleCascade", () => {
  it("returns 'completed' for a terminal completed move with live issues", () => {
    expect(shouldPromptModuleCascade({ data: { status: "completed" }, totalIssues: 47 })).toBe("completed");
  });

  it("returns 'cancelled' for a terminal cancelled move with live issues", () => {
    expect(shouldPromptModuleCascade({ data: { status: "cancelled" }, totalIssues: 1 })).toBe("cancelled");
  });

  it("returns null for a non-terminal status (in-progress)", () => {
    expect(shouldPromptModuleCascade({ data: { status: "in-progress" }, totalIssues: 47 })).toBeNull();
  });

  it("returns null when total_issues is 0", () => {
    expect(shouldPromptModuleCascade({ data: { status: "completed" }, totalIssues: 0 })).toBeNull();
  });

  // The load-bearing case (plan risk row "Modal fires on the create/update modal's whole-object
  // save"): a payload that doesn't carry `status` at all — e.g. a name-only edit on an already
  // -completed module — must never fire a preview request.
  it("returns null when the payload carries no status at all", () => {
    expect(shouldPromptModuleCascade({ data: { name: "Renamed" }, totalIssues: 47 })).toBeNull();
  });

  // The server decides whether re-saving the same status is a no-op (M7) — the client-side guard
  // has no memory of the module's PREVIOUS status and must not try to infer "unchanged" itself.
  it("fires even when the posted status equals the module's current status", () => {
    expect(shouldPromptModuleCascade({ data: { status: "completed" }, totalIssues: 5 })).toBe("completed");
  });

  // M6's correctness hole, pinned directly: the guard must NOT subtract completed/cancelled
  // counts from total_issues to decide whether to fire. Those three counts cover direct module
  // members only, while the cascade also walks each member's descendant subtree (M2) — so even a
  // module whose direct members are ALL terminal must still prompt when total_issues > 0.
  it("still fires when every direct member is already terminal, because total_issues alone gates it", () => {
    expect(
      shouldPromptModuleCascade({
        data: { status: "completed", completed_issues: 10, cancelled_issues: 0 },
        totalIssues: 10,
      })
    ).toBe("completed");
  });
});

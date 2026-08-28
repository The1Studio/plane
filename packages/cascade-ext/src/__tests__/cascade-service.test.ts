/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CascadeApiError, CascadeService } from "../cascade-service";

const WORKSPACE = "plane";
const PROJECT = "project-1";
const MODULE = "module-1";

function okResponse(body: unknown) {
  return { ok: true, status: 200, json: () => Promise.resolve(body), text: () => Promise.resolve("") };
}

describe("CascadeService — module endpoints", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  // The TRAP this test exists to pin: cascade-ext mounts at `/api/cascade-ext/`, OUTSIDE
  // `/api/v1` — a base-URL regression here would silently 404 in production while every mocked
  // unit test elsewhere kept passing.
  it("getModulePreview hits /api/cascade-ext/…/modules/…, never /api/v1/…", async () => {
    fetchMock.mockResolvedValueOnce(
      okResponse({
        target_group: "completed",
        depth_capped: false,
        over_cap: false,
        cap: 100,
        summary: { total_live: 0, eligible: 0, ineligible: 0, already_terminal: 0 },
        items: [],
      })
    );
    const service = new CascadeService();

    await service.getModulePreview(WORKSPACE, PROJECT, MODULE, "completed");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(
      `/api/cascade-ext/workspaces/${WORKSPACE}/projects/${PROJECT}/modules/${MODULE}/cascade-preview/?status=completed`
    );
    expect(url.startsWith("/api/v1")).toBe(false);
  });

  it("getModulePreview sends 'status', never 'group', as the query param", async () => {
    fetchMock.mockResolvedValueOnce(
      okResponse({
        target_group: "cancelled",
        depth_capped: false,
        over_cap: false,
        cap: 100,
        summary: { total_live: 0, eligible: 0, ineligible: 0, already_terminal: 0 },
        items: [],
      })
    );
    const service = new CascadeService();

    await service.getModulePreview(WORKSPACE, PROJECT, MODULE, "cancelled");

    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toContain("status=cancelled");
    expect(url).not.toContain("group=");
  });

  it("getModulePreview raises CascadeApiError on a non-2xx response", async () => {
    fetchMock.mockResolvedValueOnce({ ok: false, status: 400, text: () => Promise.resolve("archived module") });
    const service = new CascadeService();

    await expect(service.getModulePreview(WORKSPACE, PROJECT, MODULE, "completed")).rejects.toMatchObject({
      name: "CascadeApiError",
      status: 400,
    });
  });

  it("applyModuleCascade posts to /api/cascade-ext/…/modules/…/cascade-apply/", async () => {
    fetchMock.mockResolvedValueOnce(okResponse({ module: MODULE, status: "completed", updated: ["a"], rejected: [] }));
    const service = new CascadeService();

    await service.applyModuleCascade(WORKSPACE, PROJECT, MODULE, "completed", ["a"]);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`/api/cascade-ext/workspaces/${WORKSPACE}/projects/${PROJECT}/modules/${MODULE}/cascade-apply/`);
    expect(url.startsWith("/api/v1")).toBe(false);
    expect(init.method).toBe("POST");
  });

  it("applyModuleCascade always sends item_ids as an explicit array — never omits the key", async () => {
    fetchMock.mockResolvedValueOnce(okResponse({ module: MODULE, status: "completed", updated: [], rejected: [] }));
    const service = new CascadeService();

    await service.applyModuleCascade(WORKSPACE, PROJECT, MODULE, "completed", []);

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(init.body as string) as { status: string; item_ids: unknown };
    expect(body).toEqual({ status: "completed", item_ids: [] });
    expect(Array.isArray(body.item_ids)).toBe(true);
  });

  it("applyModuleCascade raises CascadeApiError on a non-2xx response", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 400,
      text: () => Promise.resolve("cascade exceeds MAX_MODULE_CASCADE_ITEMS"),
    });
    const service = new CascadeService();

    await expect(service.applyModuleCascade(WORKSPACE, PROJECT, MODULE, "completed", [])).rejects.toBeInstanceOf(
      CascadeApiError
    );
  });
});

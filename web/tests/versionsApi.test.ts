import { afterEach, describe, expect, it, vi } from "vitest";

import { purgeFromTrash, listTrash, restoreFromTrash } from "../src/api/trash";
import { downloadVersion, listVersions, restoreVersion } from "../src/api/versions";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

interface RecordedCall {
  url: string;
  method: string;
}

function stubFetch(handler: (url: string, method: string) => Response) {
  const calls: RecordedCall[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    calls.push({ url, method });
    return handler(url, method);
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("versions api", () => {
  it("lists a file's versions", async () => {
    const calls = stubFetch(() => jsonResponse({ file_id: "f1", versions: [] }));

    const result = await listVersions("f1");

    expect(result.versions).toEqual([]);
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toMatch(/\/api\/files\/f1\/versions$/);
    expect(calls[0].method).toBe("GET");
  });

  it("restores a version with a POST and no body", async () => {
    const calls = stubFetch(() => jsonResponse({ id: "v3", version_number: 3 }, 201));

    const result = await restoreVersion("f1", "v1");

    expect(result.version_number).toBe(3);
    expect(calls[0].url).toMatch(/\/api\/files\/f1\/versions\/v1\/restore$/);
    expect(calls[0].method).toBe("POST");
  });

  it("surfaces the server's message when a restore is rejected", async () => {
    stubFetch(() => jsonResponse({ detail: "that version is already the current version" }, 409));

    await expect(restoreVersion("f1", "v2")).rejects.toMatchObject({
      status: 409,
      message: "that version is already the current version",
    });
  });

  it("downloads a specific version through an authenticated fetch", async () => {
    const calls = stubFetch(() => new Response("old bytes", { status: 200 }));
    // jsdom has no URL.createObjectURL
    vi.stubGlobal("URL", Object.assign(URL, {
      createObjectURL: vi.fn(() => "blob:fake"),
      revokeObjectURL: vi.fn(),
    }));
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    await downloadVersion("f1", "v1", "notes.txt");

    expect(calls[0].url).toMatch(/\/api\/files\/f1\/versions\/v1\/download$/);
    expect(clickSpy).toHaveBeenCalledTimes(1);
  });

  it("throws when a version download fails", async () => {
    stubFetch(() => new Response("nope", { status: 500 }));

    await expect(downloadVersion("f1", "v1", "notes.txt")).rejects.toThrow(/status 500/);
  });
});

describe("trash api", () => {
  it("lists the trash", async () => {
    const calls = stubFetch(() => jsonResponse({ files: [{ id: "f1", name: "a.txt" }] }));

    const result = await listTrash();

    expect(result.files[0].name).toBe("a.txt");
    expect(calls[0].url).toMatch(/\/api\/trash$/);
  });

  it("restores a trashed file with a POST", async () => {
    const calls = stubFetch(() => jsonResponse({ id: "f1", name: "a (restored).txt" }));

    const restored = await restoreFromTrash("f1");

    expect(restored.name).toBe("a (restored).txt");
    expect(calls[0]).toMatchObject({ method: "POST" });
    expect(calls[0].url).toMatch(/\/api\/trash\/f1\/restore$/);
  });

  it("permanently deletes with a DELETE and tolerates the empty 204 body", async () => {
    const calls = stubFetch(() => new Response(null, { status: 204 }));

    await expect(purgeFromTrash("f1")).resolves.toBeUndefined();

    expect(calls[0]).toMatchObject({ method: "DELETE" });
    expect(calls[0].url).toMatch(/\/api\/trash\/f1$/);
  });
});

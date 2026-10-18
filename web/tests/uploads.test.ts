import { afterEach, describe, expect, it, vi } from "vitest";

import { resumeUpload, ResumableUploadError } from "../src/api/uploads";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("resumeUpload", () => {
  it("only (re)sends chunks the session status says are missing", async () => {
    const file = new File([new Uint8Array(25)], "big.bin");
    const requests: string[] = [];

    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      requests.push(url);

      if (url.endsWith("/api/uploads/upload-1")) {
        return jsonResponse({
          id: "upload-1",
          file_name: "big.bin",
          file_size: 25,
          chunk_size: 10,
          total_chunks: 3,
          status: "pending",
          created_at: "2026-01-01T00:00:00Z",
          expires_at: "2026-01-02T00:00:00Z",
          received_chunk_indices: [0],
          missing_chunk_indices: [1, 2],
        });
      }
      if (url.includes("/chunks/")) {
        const index = Number(url.split("/chunks/")[1]);
        return jsonResponse({ index, received: true, received_count: index + 1, total_chunks: 3 });
      }
      if (url.endsWith("/complete")) {
        return jsonResponse({
          id: "file-1",
          owner_id: "owner-1",
          folder_id: null,
          name: "big.bin",
          mime_type: null,
          size: 25,
          content_hash: "abc123",
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        });
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const progress: number[] = [];
    const result = await resumeUpload("upload-1", file, (fraction) => progress.push(fraction));

    expect(result.id).toBe("file-1");
    // Chunk 0 was already received — only 1 and 2 should have been sent.
    const chunkRequests = requests.filter((url) => url.includes("/chunks/"));
    expect(chunkRequests.some((url) => url.endsWith("/chunks/1"))).toBe(true);
    expect(chunkRequests.some((url) => url.endsWith("/chunks/2"))).toBe(true);
    expect(chunkRequests.some((url) => url.endsWith("/chunks/0"))).toBe(false);
    // Progress starts from what was already done (1/3) and ends at 1.
    expect(progress[0]).toBeCloseTo(1 / 3);
    expect(progress[progress.length - 1]).toBe(1);
  });

  it("sends several chunks at once, never more than three, and sends every one", async () => {
    const chunks = 8;
    const file = new File([new Uint8Array(chunks * 10)], "wide.bin");
    let active = 0;
    let peak = 0;
    const sent = new Set<number>();

    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/uploads/upload-3")) {
        return jsonResponse({
          id: "upload-3",
          file_name: "wide.bin",
          file_size: chunks * 10,
          chunk_size: 10,
          total_chunks: chunks,
          status: "pending",
          created_at: "2026-01-01T00:00:00Z",
          expires_at: "2026-01-02T00:00:00Z",
          received_chunk_indices: [],
          missing_chunk_indices: Array.from({ length: chunks }, (_, i) => i),
        });
      }
      if (url.includes("/chunks/")) {
        const index = Number(url.split("/chunks/")[1]);
        active += 1;
        peak = Math.max(peak, active);
        await new Promise((resolve) => setTimeout(resolve, 10));
        active -= 1;
        sent.add(index);
        return jsonResponse({ index, received: true, received_count: sent.size, total_chunks: chunks });
      }
      if (url.endsWith("/complete")) {
        return jsonResponse({ id: "file-3", name: "wide.bin", size: chunks * 10 });
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const progress: number[] = [];
    await resumeUpload("upload-3", file, (fraction) => progress.push(fraction));

    expect(sent.size).toBe(chunks);
    expect(peak).toBeGreaterThan(1);
    expect(peak).toBeLessThanOrEqual(3);
    expect(progress[progress.length - 1]).toBe(1);
  });

  it("throws a ResumableUploadError carrying the session id when a chunk keeps failing", async () => {
    const file = new File([new Uint8Array(10)], "small.bin");

    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/uploads/upload-2")) {
        return jsonResponse({
          id: "upload-2",
          file_name: "small.bin",
          file_size: 10,
          chunk_size: 10,
          total_chunks: 1,
          status: "pending",
          created_at: "2026-01-01T00:00:00Z",
          expires_at: "2026-01-02T00:00:00Z",
          received_chunk_indices: [],
          missing_chunk_indices: [0],
        });
      }
      if (url.includes("/chunks/")) {
        return jsonResponse({ detail: "engine unreachable" }, 502);
      }
      throw new Error(`unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(resumeUpload("upload-2", file)).rejects.toBeInstanceOf(ResumableUploadError);
  });
});

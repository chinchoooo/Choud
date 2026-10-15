import { describe, expect, it } from "vitest";

import { formatEta, formatSpeed } from "../src/lib/format";
import { etaSeconds, isTransientFailure, retryDelayMs, smoothSpeed, summarize } from "../src/uploads/queueMath";

describe("queue math", () => {
  it("smooths speed instead of jumping to each sample", () => {
    expect(smoothSpeed(0, 1000)).toBe(1000); // the first sample is taken as is
    expect(smoothSpeed(1000, 2000)).toBeCloseTo(1300);
  });

  it("estimates time left only when the speed is known", () => {
    expect(etaSeconds(1000, 100)).toBe(10);
    expect(etaSeconds(1000, 0)).toBeNull();
    expect(etaSeconds(0, 0)).toBe(0);
  });

  it("backs off 2s, 5s, then 15s", () => {
    expect([1, 2, 3, 9].map(retryDelayMs)).toEqual([2000, 5000, 15000, 15000]);
  });

  it("retries network failures and 5xx but not client errors like a full quota", () => {
    expect(isTransientFailure(new Error("network"))).toBe(true);
    expect(isTransientFailure(Object.assign(new Error("x"), { status: 503 }))).toBe(true);
    expect(isTransientFailure(Object.assign(new Error("x"), { status: 429 }))).toBe(true);
    expect(isTransientFailure(Object.assign(new Error("quota"), { status: 413 }))).toBe(false);
    expect(isTransientFailure(Object.assign(new Error("x"), { status: 401 }))).toBe(false);
  });

  it("summarizes a mixed queue", () => {
    const summary = summarize([
      { status: "done", size: 100, loaded: 100, speed: 0 },
      { status: "uploading", size: 200, loaded: 50, speed: 25 },
      { status: "queued", size: 100, loaded: 0, speed: 0 },
      { status: "error", size: 100, loaded: 10, speed: 0 },
      { status: "cancelled", size: 999, loaded: 0, speed: 0 },
    ]);
    expect(summary).toMatchObject({
      total: 4,
      done: 1,
      failed: 1,
      uploading: 1,
      waiting: 1,
      bytesTotal: 500,
      bytesLoaded: 160,
      speed: 25,
      busy: true,
    });
    expect(summary.etaSeconds).toBeCloseTo((500 - 160) / 25);
  });

  it("is not busy once everything has finished", () => {
    const summary = summarize([{ status: "done", size: 10, loaded: 10, speed: 0 }]);
    expect(summary.busy).toBe(false);
    expect(summary.etaSeconds).toBe(0);
  });
});

describe("speed and ETA formatting", () => {
  it("formats speed", () => {
    expect(formatSpeed(0)).toBe("—");
    expect(formatSpeed(2048)).toBe("2.0 KB/s");
  });

  it("formats durations", () => {
    expect(formatEta(null)).toBe("—");
    expect(formatEta(42)).toBe("42s");
    expect(formatEta(185)).toBe("3m 05s");
    expect(formatEta(4320)).toBe("1h 12m");
  });
});

import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { UploadPanel } from "../src/components/UploadPanel";
import type { UploadItem } from "../src/uploads/UploadContext";

const state = vi.hoisted(() => ({ items: [] as UploadItem[] }));

vi.mock("../src/uploads/UploadContext", async () => {
  const queue = await import("../src/uploads/queueMath");
  return {
    useUploads: () => ({
      items: state.items,
      summary: queue.summarize(state.items),
      enqueue: vi.fn(),
      cancel: vi.fn(),
      retry: vi.fn(),
      cancelAll: vi.fn(),
      clearFinished: vi.fn(),
    }),
  };
});

function item(overrides: Partial<UploadItem>): UploadItem {
  return {
    id: "u1",
    name: "photo.jpg",
    size: 1000,
    folderId: null,
    destination: "My files",
    status: "queued",
    loaded: 0,
    speed: 0,
    attempts: 0,
    ...overrides,
  };
}

describe("UploadPanel", () => {
  it("renders nothing when the queue is empty", () => {
    state.items = [];
    const { container } = render(<UploadPanel />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows overall progress, speed and each file in queue order", () => {
    state.items = [
      item({ id: "a", name: "waiting-1.jpg", status: "queued" }),
      item({ id: "b", name: "active.mp4", size: 2_000_000, loaded: 1_000_000, speed: 500_000, status: "uploading" }),
      item({ id: "c", name: "waiting-2.jpg", status: "queued" }),
      item({ id: "d", name: "finished.png", status: "done", loaded: 1000 }),
    ];
    render(<UploadPanel />);

    expect(screen.getByText("Uploading 2 of 4")).toBeInTheDocument();
    const rows = within(screen.getByRole("list")).getAllByRole("listitem");
    expect(rows.map((row) => within(row).getByTitle(/\.(jpg|mp4|png)$/).textContent)).toEqual([
      "active.mp4",
      "waiting-1.jpg",
      "waiting-2.jpg",
      "finished.png",
    ]);
    expect(within(rows[0]).getByText(/488\.3 KB\/s/)).toBeInTheDocument();
    expect(within(rows[0]).getByText(/2s left/)).toBeInTheDocument();
    expect(within(rows[1]).getByText(/Waiting - #1 in line/)).toBeInTheDocument();
    expect(within(rows[2]).getByText(/Waiting - #2 in line/)).toBeInTheDocument();
    expect(within(rows[3]).getByText(/Uploaded/)).toBeInTheDocument();
  });

  it("shows the reason and a Retry button for a failed upload", () => {
    state.items = [item({ status: "error", error: "storage quota exceeded", loaded: 0 })];
    render(<UploadPanel />);
    expect(screen.getByText("storage quota exceeded")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(screen.getByText("0 uploaded, 1 failed")).toBeInTheDocument();
  });
});

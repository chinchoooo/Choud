import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { FileViewer } from "../src/components/FileViewer";
import type { FileResponse } from "../src/types/files";

vi.mock("../src/media/MediaContext", () => ({
  useMedia: () => ({
    ready: true,
    contentUrl: (id: string) => `http://media.test/${id}/content`,
    thumbUrl: (id: string) => `http://media.test/${id}/thumb`,
  }),
}));
vi.mock("../src/api/files", () => ({ downloadFile: vi.fn().mockResolvedValue(undefined) }));

function file(overrides: Partial<FileResponse>): FileResponse {
  return {
    id: "f1",
    owner_id: "u",
    folder_id: null,
    name: "a.png",
    mime_type: "image/png",
    size: 1234,
    content_hash: "abc",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
    ...overrides,
  };
}

const noop = () => {};

afterEach(() => vi.restoreAllMocks());

describe("FileViewer", () => {
  it("shows images with the built-in viewer", () => {
    render(<FileViewer files={[file({})]} index={0} onIndexChange={noop} onClose={noop} />);
    expect(screen.getByRole("img", { name: "a.png" })).toHaveAttribute("src", "http://media.test/f1/content");
  });

  it("plays video and audio in the page", () => {
    const { container, rerender } = render(
      <FileViewer
        files={[file({ id: "v", name: "a.mp4", mime_type: "video/mp4" })]}
        index={0}
        onIndexChange={noop}
        onClose={noop}
      />,
    );
    expect(container.querySelector("video")).toHaveAttribute("src", "http://media.test/v/content");
    rerender(
      <FileViewer
        files={[file({ id: "s", name: "a.mp3", mime_type: "audio/mpeg" })]}
        index={0}
        onIndexChange={noop}
        onClose={noop}
      />,
    );
    expect(container.querySelector("audio")).toHaveAttribute("src", "http://media.test/s/content");
  });

  it("shows PDFs in a frame", () => {
    render(
      <FileViewer
        files={[file({ name: "a.pdf", mime_type: "application/pdf" })]}
        index={0}
        onIndexChange={noop}
        onClose={noop}
      />,
    );
    expect(document.querySelector("iframe")).toHaveAttribute("src", "http://media.test/f1/content");
  });

  it("shows text as escaped text, never as markup", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("<img src=x onerror=alert(1)>hello", { status: 200 }),
    );
    const { container } = render(
      <FileViewer
        files={[file({ name: "evil.html", mime_type: "text/html", size: 40 })]}
        index={0}
        onIndexChange={noop}
        onClose={noop}
      />,
    );
    await waitFor(() => expect(container.querySelector("pre")).not.toBeNull());
    expect(container.querySelector("pre")?.textContent).toContain("<img src=x onerror=alert(1)>");
    expect(container.querySelector("pre img")).toBeNull();
  });

  it("offers a download when there is no preview", () => {
    render(
      <FileViewer
        files={[file({ name: "a.zip", mime_type: "application/zip" })]}
        index={0}
        onIndexChange={noop}
        onClose={noop}
      />,
    );
    expect(screen.getByText(/no preview for this type/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /download a\.zip/i })).toBeInTheDocument();
  });

  it("closes with Escape and moves with the arrow keys", () => {
    const onClose = vi.fn();
    const onIndexChange = vi.fn();
    render(
      <FileViewer
        files={[file({ id: "1", name: "1.png" }), file({ id: "2", name: "2.png" }), file({ id: "3", name: "3.png" })]}
        index={1}
        onIndexChange={onIndexChange}
        onClose={onClose}
      />,
    );
    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(onIndexChange).toHaveBeenLastCalledWith(2);
    fireEvent.keyDown(window, { key: "ArrowLeft" });
    expect(onIndexChange).toHaveBeenLastCalledWith(0);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });

  it("has no previous button on the first file and no next on the last", () => {
    const two = [file({ id: "1" }), file({ id: "2" })];
    const { rerender } = render(<FileViewer files={two} index={0} onIndexChange={noop} onClose={noop} />);
    expect(screen.queryByLabelText("Previous file")).toBeNull();
    expect(screen.getByLabelText("Next file")).toBeInTheDocument();
    rerender(<FileViewer files={two} index={1} onIndexChange={noop} onClose={noop} />);
    expect(screen.queryByLabelText("Next file")).toBeNull();
  });

  it("toggles the favorite and shows details", () => {
    const onToggle = vi.fn();
    render(
      <FileViewer
        files={[file({ is_favorite: false, folder_path: "Trips/Italy" })]}
        index={0}
        onIndexChange={noop}
        onClose={noop}
        onToggleFavorite={onToggle}
      />,
    );
    fireEvent.click(screen.getByLabelText("Add to favorites"));
    expect(onToggle).toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Info" }));
    expect(screen.getByText("Trips/Italy")).toBeInTheDocument();
    expect(screen.getByText("abc")).toBeInTheDocument();
  });
});

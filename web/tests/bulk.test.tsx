import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { BulkBar } from "../src/components/BulkBar";
import { FileCollection } from "../src/components/FileCollection";
import { MediaProvider } from "../src/media/MediaContext";
import type { FileResponse, FolderResponse } from "../src/types/files";

const file = (id: string, name: string): FileResponse =>
  ({
    id,
    name,
    size: 10,
    mime_type: "text/plain",
    updated_at: "2026-10-18T00:00:00Z",
    created_at: "2026-10-18T00:00:00Z",
    is_favorite: false,
    folder_path: "",
  }) as unknown as FileResponse;

const folder = { id: "d1", name: "Trip", updated_at: "2026-10-18T00:00:00Z" } as unknown as FolderResponse;

function renderCollection(selection?: React.ComponentProps<typeof FileCollection>["selection"]) {
  return render(
    <MediaProvider>
      <FileCollection
        folders={[folder]}
        files={[file("f1", "a.txt"), file("f2", "b.txt")]}
        mode="list"
        empty="empty"
        onOpenFile={() => {}}
        onToggleFavorite={() => {}}
        onDownload={() => {}}
        fileMenu={() => []}
        selection={selection}
      />
    </MediaProvider>,
  );
}

describe("selection in the file list", () => {
  it("shows no checkboxes unless selecting", () => {
    renderCollection();
    expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
  });

  it("toggles files and folders independently", () => {
    const toggleFile = vi.fn();
    const toggleFolder = vi.fn();
    renderCollection({ files: new Set(["f2"]), folders: new Set(), toggleFile, toggleFolder });

    expect(screen.getAllByRole("checkbox")).toHaveLength(3);
    expect(screen.getByLabelText("Select b.txt")).toBeChecked();
    expect(screen.getByLabelText("Select a.txt")).not.toBeChecked();
    fireEvent.click(screen.getByLabelText("Select a.txt"));
    fireEvent.click(screen.getByLabelText("Select folder Trip"));
    expect(toggleFile).toHaveBeenCalledWith("f1");
    expect(toggleFolder).toHaveBeenCalledWith("d1");
  });
});

describe("BulkBar", () => {
  const handlers = () => ({
    onSelectAll: vi.fn(),
    onDownload: vi.fn(),
    onMove: vi.fn(),
    onTrash: vi.fn(),
    onClear: vi.fn(),
  });

  it("disables the actions until something is selected", () => {
    render(<BulkBar count={0} total={3} busy={false} message={null} {...handlers()} />);
    expect(screen.getByText("Nothing selected")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /download \.zip/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /move to/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /delete/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Select all" })).toBeEnabled();
  });

  it("runs the chosen action and reports the outcome", () => {
    const h = handlers();
    render(<BulkBar count={2} total={2} busy={false} message="Move: 2 done." {...h} />);
    expect(screen.getByText("2 selected")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Select none" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /download \.zip/i }));
    fireEvent.click(screen.getByRole("button", { name: /move to/i }));
    fireEvent.click(screen.getByRole("button", { name: /delete/i }));
    fireEvent.click(screen.getByRole("button", { name: /done/i }));
    expect(h.onDownload).toHaveBeenCalled();
    expect(h.onMove).toHaveBeenCalled();
    expect(h.onTrash).toHaveBeenCalled();
    expect(h.onClear).toHaveBeenCalled();
    expect(screen.getByRole("status")).toHaveTextContent("Move: 2 done.");
  });

  it("locks the actions while busy", () => {
    render(<BulkBar count={2} total={5} busy message={null} {...handlers()} />);
    expect(screen.getByRole("button", { name: /delete/i })).toBeDisabled();
  });
});

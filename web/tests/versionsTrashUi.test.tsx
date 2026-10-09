import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { VersionHistory } from "../src/components/VersionHistory";
import { Trash } from "../src/pages/Trash";
import type { FileResponse } from "../src/types/files";
import type { VersionResponse } from "../src/types/versions";

const versionsApi = vi.hoisted(() => ({
  listVersions: vi.fn(),
  restoreVersion: vi.fn(),
  downloadVersion: vi.fn(),
}));
const trashApi = vi.hoisted(() => ({
  listTrash: vi.fn(),
  restoreFromTrash: vi.fn(),
  purgeFromTrash: vi.fn(),
}));

vi.mock("../src/api/versions", () => versionsApi);
vi.mock("../src/api/trash", () => trashApi);

function renderWithProviders(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

const file: FileResponse = {
  id: "file-1",
  owner_id: "user-1",
  folder_id: null,
  name: "notes.txt",
  mime_type: "text/plain",
  size: 20,
  content_hash: "h2",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-02T00:00:00Z",
};

function version(number: number, overrides: Partial<VersionResponse> = {}): VersionResponse {
  return {
    id: `v${number}`,
    file_id: "file-1",
    version_number: number,
    content_hash: `h${number}`,
    size: 10 * number,
    restored_from_version: null,
    created_by: "user-1",
    created_at: "2026-01-0" + number + "T00:00:00Z",
    is_current: false,
    ...overrides,
  };
}

beforeEach(() => {
  vi.spyOn(window, "alert").mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
  Object.values(versionsApi).forEach((fn) => fn.mockReset());
  Object.values(trashApi).forEach((fn) => fn.mockReset());
});

describe("VersionHistory", () => {
  it("lists versions, marks the current one, and only offers Restore on older ones", async () => {
    versionsApi.listVersions.mockResolvedValue({
      file_id: "file-1",
      versions: [version(3, { is_current: true, restored_from_version: 1 }), version(2), version(1)],
    });

    renderWithProviders(<VersionHistory file={file} />);

    const list = await screen.findByRole("list", { name: /versions of notes\.txt/i });
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(3);
    expect(within(rows[0]).getByText("current")).toBeInTheDocument();
    expect(within(rows[0]).getByText(/restored from v1/i)).toBeInTheDocument();
    expect(within(rows[0]).queryByRole("button", { name: "Restore" })).not.toBeInTheDocument();
    expect(within(rows[1]).getByRole("button", { name: "Restore" })).toBeInTheDocument();
    expect(within(rows[2]).getByRole("button", { name: "Restore" })).toBeInTheDocument();
  });

  it("restores a version only after the person confirms", async () => {
    versionsApi.listVersions.mockResolvedValue({
      file_id: "file-1",
      versions: [version(2, { is_current: true }), version(1)],
    });
    versionsApi.restoreVersion.mockResolvedValue(version(3, { is_current: true }));
    const confirmSpy = vi.spyOn(window, "confirm");
    renderWithProviders(<VersionHistory file={file} />);
    const list = await screen.findByRole("list", { name: /versions of/i });
    const restoreButton = within(within(list).getAllByRole("listitem")[1]).getByRole("button", {
      name: "Restore",
    });

    confirmSpy.mockReturnValueOnce(false);
    fireEvent.click(restoreButton);
    expect(versionsApi.restoreVersion).not.toHaveBeenCalled();

    confirmSpy.mockReturnValueOnce(true);
    fireEvent.click(restoreButton);
    await waitFor(() => expect(versionsApi.restoreVersion).toHaveBeenCalledWith("file-1", "v1"));
  });

  it("downloads the chosen version under the file's name", async () => {
    versionsApi.listVersions.mockResolvedValue({
      file_id: "file-1",
      versions: [version(2, { is_current: true }), version(1)],
    });
    versionsApi.downloadVersion.mockResolvedValue(undefined);
    renderWithProviders(<VersionHistory file={file} />);
    const list = await screen.findByRole("list", { name: /versions of/i });

    fireEvent.click(
      within(within(list).getAllByRole("listitem")[1]).getByRole("button", { name: "Download" }),
    );

    await waitFor(() =>
      expect(versionsApi.downloadVersion).toHaveBeenCalledWith("file-1", "v1", "notes.txt"),
    );
  });

  it("shows an error message when the history can't be loaded", async () => {
    versionsApi.listVersions.mockRejectedValue(new Error("boom"));

    renderWithProviders(<VersionHistory file={file} />);

    expect(await screen.findByText(/could not load the version history/i)).toBeInTheDocument();
  });
});

describe("Trash page", () => {
  const trashed = {
    id: "file-9",
    name: "old.pdf",
    folder_id: null,
    mime_type: "application/pdf",
    size: 2048,
    content_hash: "h",
    deleted_at: "2026-02-01T00:00:00Z",
  };

  it("shows an empty state", async () => {
    trashApi.listTrash.mockResolvedValue({ files: [] });

    renderWithProviders(<Trash />);

    expect(await screen.findByText(/the trash is empty/i)).toBeInTheDocument();
  });

  it("lists trashed files and restores one", async () => {
    trashApi.listTrash.mockResolvedValue({ files: [trashed] });
    trashApi.restoreFromTrash.mockResolvedValue({ ...file, id: "file-9", name: "old.pdf" });
    renderWithProviders(<Trash />);

    expect(await screen.findByText(/old\.pdf/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Restore" }));

    await waitFor(() => expect(trashApi.restoreFromTrash).toHaveBeenCalledWith("file-9"));
    expect(window.alert).not.toHaveBeenCalled(); // same name, nothing to tell the person
  });

  it("tells the person when a restore had to rename the file", async () => {
    trashApi.listTrash.mockResolvedValue({ files: [trashed] });
    trashApi.restoreFromTrash.mockResolvedValue({
      ...file,
      id: "file-9",
      name: "old (restored).pdf",
    });
    renderWithProviders(<Trash />);
    await screen.findByText(/old\.pdf/);

    fireEvent.click(screen.getByRole("button", { name: "Restore" }));

    await waitFor(() =>
      expect(window.alert).toHaveBeenCalledWith(expect.stringContaining("old (restored).pdf")),
    );
  });

  it("permanently deletes only after the person confirms", async () => {
    trashApi.listTrash.mockResolvedValue({ files: [trashed] });
    trashApi.purgeFromTrash.mockResolvedValue(undefined);
    const confirmSpy = vi.spyOn(window, "confirm");
    renderWithProviders(<Trash />);
    await screen.findByText(/old\.pdf/);

    confirmSpy.mockReturnValueOnce(false);
    fireEvent.click(screen.getByRole("button", { name: "Delete forever" }));
    expect(trashApi.purgeFromTrash).not.toHaveBeenCalled();

    confirmSpy.mockReturnValueOnce(true);
    fireEvent.click(screen.getByRole("button", { name: "Delete forever" }));
    await waitFor(() => expect(trashApi.purgeFromTrash).toHaveBeenCalledWith("file-9"));
  });

  it("links back to the files page", async () => {
    trashApi.listTrash.mockResolvedValue({ files: [] });

    renderWithProviders(<Trash />);

    expect(await screen.findByRole("link", { name: /back to files/i })).toHaveAttribute(
      "href",
      "/files",
    );
  });
});

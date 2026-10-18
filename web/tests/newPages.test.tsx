import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../src/api/client";
import { ShareDialog } from "../src/components/ShareDialog";
import { Rewind } from "../src/pages/Rewind";
import { Server } from "../src/pages/Server";
import { Space } from "../src/pages/Space";
import { ThemeProvider } from "../src/theme/ThemeContext";

const rewind = vi.hoisted(() => ({ browsePast: vi.fn(), restorePastFile: vi.fn(), restorePastTree: vi.fn() }));
const insights = vi.hoisted(() => ({
  getSpace: vi.fn(),
  pruneVersions: vi.fn(),
  getServerStatus: vi.fn(),
  getSecurityLog: vi.fn(),
}));
const shares = vi.hoisted(() => ({ createShare: vi.fn() }));

vi.mock("../src/api/rewind", () => rewind);
vi.mock("../src/api/insights", () => insights);
vi.mock("../src/api/shares", async () => {
  const actual = await vi.importActual<typeof import("../src/api/shares")>("../src/api/shares");
  return { ...actual, ...shares };
});

afterEach(() => {
  vi.restoreAllMocks();
  [rewind, insights, shares].forEach((group) => Object.values(group).forEach((fn) => fn.mockReset()));
});

function renderPage(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <MemoryRouter>{ui}</MemoryRouter>
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

const past = {
  at: "2026-10-17T10:00:00Z",
  folder_id: null,
  folder_name: null,
  folders: [{ id: "d1", name: "Work" }],
  files: [
    { id: "f1", name: "a.txt", mime_type: "text/plain", size: 10, version_number: 1, version_at: "2026-10-01T00:00:00Z", changed: true, trashed: false },
    { id: "f2", name: "b.txt", mime_type: "text/plain", size: 5, version_number: 2, version_at: "2026-10-02T00:00:00Z", changed: false, trashed: false },
  ],
};
const report = { dry_run: true, restored_content: 1, undeleted: 1, unchanged: 3, newer_untouched: 2, files: ["a.txt"] };

describe("Rewind", () => {
  it("shows the past, only offers 'Put back' for files that differ, and previews before restoring", async () => {
    rewind.browsePast.mockResolvedValue(past);
    rewind.restorePastTree.mockResolvedValue(report);
    rewind.restorePastFile.mockResolvedValue({ ...report, dry_run: false });
    renderPage(<Rewind />);

    expect(await screen.findByText("a.txt")).toBeInTheDocument();
    expect(screen.getByText("changed since")).toBeInTheDocument();
    const buttons = screen.getAllByRole("button", { name: "Put back" });
    expect(buttons[0]).toBeEnabled(); // a.txt differs
    expect(buttons[1]).toBeDisabled(); // b.txt is already as it was

    fireEvent.click(buttons[0]);
    await waitFor(() => expect(rewind.restorePastFile).toHaveBeenCalledWith("f1", expect.any(String)));

    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(await screen.findByText(/would change 2 file/)).toBeInTheDocument();
    expect(rewind.restorePastTree).toHaveBeenCalledWith(null, expect.any(String), true);
    fireEvent.click(screen.getByRole("button", { name: "Put everything back" }));
    await screen.findByText("Put everything back?");
    const confirm = screen.getAllByRole("button", { name: "Put back" });
    fireEvent.click(confirm[confirm.length - 1]); // the dialog's button comes last
    await waitFor(() => expect(rewind.restorePastTree).toHaveBeenCalledWith(null, expect.any(String), false));
  });

  it("refuses a time in the future", async () => {
    rewind.browsePast.mockResolvedValue(past);
    renderPage(<Rewind />);
    await screen.findByText("a.txt");
    const input = screen.getByLabelText(/go back to/i);
    fireEvent.change(input, { target: { value: "2999-01-01T00:00" } });
    expect(screen.getByText("Choose a time in the past.")).toBeInTheDocument();
  });
});

describe("Storage", () => {
  const space = {
    quota_bytes: 1000,
    logical_bytes: 300,
    stored_bytes: 200,
    dedup_saved_bytes: 100,
    current_bytes: 150,
    trash_bytes: 0,
    history_bytes: 50,
    by_type: { Photos: 100, Documents: 50 },
    biggest: [{ id: "f1", name: "huge.bin", size: 99 }],
    duplicates: [{ size: 10, copies: 2, files: [{ id: "a", name: "x.txt" }, { id: "b", name: "y.txt" }] }],
    duplicate_files: 1,
  };

  it("explains where the space went and previews pruning before it deletes anything", async () => {
    insights.getSpace.mockResolvedValue(space);
    insights.pruneVersions.mockResolvedValue({ dry_run: true, versions_removed: 3, bytes_freed: 40, files_affected: 2 });
    renderPage(<Space />);

    expect(await screen.findByText("Saved by deduplication")).toBeInTheDocument();
    expect(screen.getByText("huge.bin")).toBeInTheDocument();
    expect(screen.getByText(/x\.txt, y\.txt/)).toBeInTheDocument();

    const cleanup = within(screen.getByLabelText("Clean up old versions"));
    fireEvent.click(cleanup.getByRole("button", { name: "Preview" }));
    expect(await screen.findByText(/remove 3 version/)).toBeInTheDocument();
    expect(insights.pruneVersions).toHaveBeenCalledWith(5, true);
    fireEvent.click(screen.getByRole("button", { name: "Remove them" }));
    insights.pruneVersions.mockResolvedValue({ dry_run: false, versions_removed: 3, bytes_freed: 40, files_affected: 2 });
    fireEvent.click(await screen.findByRole("button", { name: "Remove" }));
    await waitFor(() => expect(insights.pruneVersions).toHaveBeenCalledWith(5, false));
  });
});

describe("Server", () => {
  it("shows the machine's state to the administrator", async () => {
    insights.getServerStatus.mockResolvedValue({
      disk_total_bytes: 1000,
      disk_free_bytes: 400,
      users: 2,
      files: 10,
      versions: 12,
      logical_bytes: 500,
      stored_bytes: 300,
      uploads_in_progress: 1,
      index_pending: 4,
      index_failed: 2,
      registration_mode: "invite",
      gc_delete_enabled: false,
    });
    renderPage(<Server />);
    expect(await screen.findByText(/60% used/)).toBeInTheDocument();
    expect(screen.getByText("invite")).toBeInTheDocument();
    expect(screen.getByText("report only")).toBeInTheDocument();
  });

  it("says plainly when you are not the administrator", async () => {
    insights.getServerStatus.mockRejectedValue(new ApiError(403, "Only the administrator can do this"));
    renderPage(<Server />);
    expect(await screen.findByText(/only the administrator/i)).toBeInTheDocument();
  });
});

describe("Share dialog options", () => {
  it("offers a file request for folders and hides download limits for it", async () => {
    shares.createShare.mockResolvedValue({
      id: "s",
      kind: "folder",
      target_id: "d1",
      target_name: "Requests",
      token: "t",
      url_path: "/s/t",
      label: null,
      has_password: false,
      permission: "drop",
      max_downloads: null,
      expires_at: null,
      created_at: "2026-10-18T00:00:00Z",
      download_count: 0,
      last_accessed_at: null,
      active: true,
    });
    renderPage(<ShareDialog target={{ kind: "folder", id: "d1", name: "Requests" }} onClose={() => {}} />);
    expect(screen.getByLabelText(/stops working after/i)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/people with the link can/i), { target: { value: "drop" } });
    expect(screen.queryByLabelText(/stops working after/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Create link" }));
    await waitFor(() =>
      expect(shares.createShare).toHaveBeenCalledWith(expect.objectContaining({ folderId: "d1", permission: "drop" })),
    );
    expect(await screen.findByText(/send files into the folder/i)).toBeInTheDocument();
  });

  it("makes a one-time link for a file", async () => {
    shares.createShare.mockResolvedValue({ permission: "view", token: "t", url_path: "/s/t", has_password: false, expires_at: null });
    renderPage(<ShareDialog target={{ kind: "file", id: "f1", name: "a.txt" }} onClose={() => {}} />);
    expect(screen.queryByRole("option", { name: /file request/i })).not.toBeInTheDocument(); // folders only
    fireEvent.change(screen.getByLabelText(/stops working after/i), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "Create link" }));
    await waitFor(() =>
      expect(shares.createShare).toHaveBeenCalledWith(expect.objectContaining({ fileId: "f1", maxDownloads: 1 })),
    );
  });
});

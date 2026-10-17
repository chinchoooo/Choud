import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ShareDialog } from "../src/components/ShareDialog";
import { Shares } from "../src/pages/Shares";
import type { Share } from "../src/api/shares";
import { shareUrl } from "../src/api/shares";

const api = vi.hoisted(() => ({
  createShare: vi.fn(),
  listShares: vi.fn(),
  revokeShare: vi.fn(),
}));

vi.mock("../src/api/shares", async () => {
  const actual = await vi.importActual<typeof import("../src/api/shares")>("../src/api/shares");
  return { ...actual, ...api };
});

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const share: Share = {
  id: "s1",
  kind: "file",
  target_id: "f1",
  target_name: "report.pdf",
  token: "tok",
  url_path: "/s/tok",
  label: null,
  has_password: true,
  expires_at: null,
  created_at: "2026-10-18T00:00:00Z",
  download_count: 3,
  last_accessed_at: null,
  active: true,
};

afterEach(() => {
  vi.restoreAllMocks();
  Object.values(api).forEach((fn) => fn.mockReset());
});

describe("shareUrl", () => {
  it("puts the link on this site's own origin", () => {
    expect(shareUrl({ url_path: "/s/abc" }, "https://cloud.example.com")).toBe(
      "https://cloud.example.com/s/abc",
    );
  });
});

describe("ShareDialog", () => {
  it("creates a link with the chosen expiry and password, then shows it to copy", async () => {
    api.createShare.mockResolvedValue(share);
    renderWithClient(<ShareDialog target={{ kind: "file", id: "f1", name: "report.pdf" }} onClose={() => {}} />);

    fireEvent.change(screen.getByLabelText(/link works for/i), { target: { value: "24" } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: "hunter22" } });
    fireEvent.click(screen.getByRole("button", { name: "Create link" }));

    await waitFor(() =>
      expect(api.createShare).toHaveBeenCalledWith({
        fileId: "f1",
        expiresInHours: 24,
        password: "hunter22",
      }),
    );
    const field = (await screen.findByLabelText("Share link")) as HTMLInputElement;
    expect(field.value).toBe(`${window.location.origin}/s/tok`);
    expect(screen.getByRole("button", { name: "Copy link" })).toBeInTheDocument();
  });

  it("shares a folder by folder id, with no expiry by default", async () => {
    api.createShare.mockResolvedValue({ ...share, kind: "folder", has_password: false });
    renderWithClient(<ShareDialog target={{ kind: "folder", id: "d1", name: "Trip" }} onClose={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Create link" }));
    await waitFor(() =>
      expect(api.createShare).toHaveBeenCalledWith({ folderId: "d1", expiresInHours: null, password: undefined }),
    );
  });

  it("will not create a link with a too-short password", () => {
    renderWithClient(<ShareDialog target={{ kind: "file", id: "f1", name: "a.txt" }} onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: "abc" } });
    expect(screen.getByText(/at least 4 characters/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create link" })).toBeDisabled();
  });

  it("says what went wrong when the server refuses", async () => {
    const { ApiError } = await import("../src/api/client");
    api.createShare.mockRejectedValue(new ApiError(404, "file not found"));
    renderWithClient(<ShareDialog target={{ kind: "file", id: "f1", name: "a.txt" }} onClose={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Create link" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("file not found");
  });
});

describe("Shared links page", () => {
  it("lists links and shows their state", async () => {
    api.listShares.mockResolvedValue([share]);
    renderWithClient(<Shares />);
    expect(await screen.findByText("report.pdf")).toBeInTheDocument();
    expect(screen.getByText(/never expires/)).toBeInTheDocument();
    expect(screen.getByText(/password/)).toBeInTheDocument();
    expect(screen.getByText(/3 downloads/)).toBeInTheDocument();
  });

  it("explains how to make the first link when there are none", async () => {
    api.listShares.mockResolvedValue([]);
    renderWithClient(<Shares />);
    expect(await screen.findByText(/no links yet/i)).toBeInTheDocument();
  });

  it("revokes only after confirmation", async () => {
    api.listShares.mockResolvedValue([share]);
    api.revokeShare.mockResolvedValue(undefined);
    renderWithClient(<Shares />);
    fireEvent.click(await screen.findByRole("button", { name: "Revoke" }));
    expect(api.revokeShare).not.toHaveBeenCalled(); // the confirmation dialog comes first
    fireEvent.click(screen.getAllByRole("button", { name: "Revoke" }).at(-1)!);
    await waitFor(() => expect(api.revokeShare).toHaveBeenCalledWith("s1"));
  });
});

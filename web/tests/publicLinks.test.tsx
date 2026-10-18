import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ShareDialog } from "../src/components/ShareDialog";
import { Server } from "../src/pages/Server";
import { ThemeProvider } from "../src/theme/ThemeContext";

const instance = vi.hoisted(() => ({
  getInstance: vi.fn(),
  setPublicLinks: vi.fn(),
  checkPublicLinks: vi.fn(),
  revokeAllShares: vi.fn(),
}));
const insights = vi.hoisted(() => ({ getServerStatus: vi.fn() }));
const shares = vi.hoisted(() => ({ createShare: vi.fn() }));

vi.mock("../src/api/instance", () => instance);
vi.mock("../src/api/insights", () => insights);
vi.mock("../src/api/shares", async () => {
  const actual = await vi.importActual<typeof import("../src/api/shares")>("../src/api/shares");
  return { ...actual, ...shares };
});

afterEach(() => {
  [instance, insights, shares].forEach((group) => Object.values(group).forEach((fn) => fn.mockReset()));
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

const status = {
  disk_total_bytes: 1000,
  disk_free_bytes: 400,
  users: 1,
  files: 1,
  versions: 1,
  logical_bytes: 1,
  stored_bytes: 1,
  uploads_in_progress: 0,
  index_pending: 0,
  index_failed: 0,
  registration_mode: "invite",
  gc_delete_enabled: false,
};

describe("Public links panel", () => {
  it("explains how to turn links on when no public address is set", async () => {
    insights.getServerStatus.mockResolvedValue(status);
    instance.getInstance.mockResolvedValue({
      version: "0.5.0",
      public_base_url: null,
      public_status: "not_configured",
      public_door_mode: "shares",
      is_admin: true,
    });
    renderPage(<Server />);
    expect(await screen.findByText(/Not set up/)).toBeInTheDocument();
    expect(screen.getByText("scripts/enable-public-links.sh")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Pause public links/ })).not.toBeInTheDocument();
  });

  it("pauses and resumes public links with the kill switch", async () => {
    insights.getServerStatus.mockResolvedValue(status);
    const ready = {
      version: "0.5.0",
      public_base_url: "https://x.example.net",
      public_status: "ready" as const,
      public_door_mode: "shares",
      is_admin: true,
    };
    instance.getInstance.mockResolvedValue(ready);
    instance.setPublicLinks.mockResolvedValue({ ...ready, public_status: "paused" });
    renderPage(<Server />);
    fireEvent.click(await screen.findByRole("button", { name: "Pause public links" }));
    await waitFor(() => expect(instance.setPublicLinks).toHaveBeenCalledWith(false));
    expect(await screen.findByText(/Paused/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Resume public links" })).toBeInTheDocument();
  });

  it("reports what the outside check found", async () => {
    insights.getServerStatus.mockResolvedValue(status);
    instance.getInstance.mockResolvedValue({
      version: "0.5.0",
      public_base_url: "https://x.example.net",
      public_status: "ready",
      public_door_mode: "shares",
      is_admin: true,
    });
    instance.checkPublicLinks.mockResolvedValue({ ok: false, detail: "The public address answered 502.", door: null, client_ip: null });
    renderPage(<Server />);
    fireEvent.click(await screen.findByRole("button", { name: "Check from outside" }));
    expect(await screen.findByText(/answered 502/)).toBeInTheDocument();
  });
});

describe("Share dialog honesty", () => {
  it("says the link is private-network only when no public address is set", async () => {
    shares.createShare.mockResolvedValue({
      id: "s",
      kind: "file",
      token: "t",
      url_path: "/s/t",
      public_url: null,
      public_status: "not_configured",
      permission: "view",
      has_password: false,
      expires_at: null,
    });
    renderPage(<ShareDialog target={{ kind: "file", id: "f", name: "a.txt" }} onClose={() => {}} />);
    fireEvent.click(await screen.findByRole("button", { name: /create link/i }));
    expect(await screen.findByText(/only works for people on your network/i)).toBeInTheDocument();
  });
});

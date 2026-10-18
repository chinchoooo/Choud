import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../src/api/client";
import { AuthProvider, useAuth } from "../src/auth/AuthContext";

const api = vi.hoisted(() => ({ fetchMe: vi.fn() }));
vi.mock("../src/api/auth", async () => {
  const actual = await vi.importActual<typeof import("../src/api/auth")>("../src/api/auth");
  return { ...actual, ...api };
});

function Probe() {
  const { user, isLoading, bootError } = useAuth();
  return (
    <div>
      <span data-testid="state">{isLoading ? "loading" : user ? "signed-in" : "signed-out"}</span>
      <span data-testid="error">{bootError ?? ""}</span>
    </div>
  );
}

function renderProbe() {
  return render(
    <AuthProvider>
      <Probe />
    </AuthProvider>,
  );
}

beforeEach(() => {
  localStorage.clear();
  api.fetchMe.mockReset();
});

describe("startup and the saved login", () => {
  it("is signed out at once when there is no saved login", async () => {
    renderProbe();
    await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("signed-out"));
    expect(api.fetchMe).not.toHaveBeenCalled();
  });

  it("signs in with a valid saved login", async () => {
    localStorage.setItem("personal_cloud_access_token", "a");
    localStorage.setItem("personal_cloud_refresh_token", "r");
    api.fetchMe.mockResolvedValue({ id: "1", email: "a@b.co" });
    renderProbe();
    await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("signed-in"));
  });

  it("drops a login the server says is invalid", async () => {
    localStorage.setItem("personal_cloud_access_token", "a");
    localStorage.setItem("personal_cloud_refresh_token", "r");
    api.fetchMe.mockRejectedValue(new ApiError(401, "Invalid or expired token"));
    renderProbe();
    await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("signed-out"));
    expect(localStorage.getItem("personal_cloud_access_token")).toBeNull();
  });

  it("keeps the saved login and reports an outage instead of signing you out", async () => {
    localStorage.setItem("personal_cloud_access_token", "a");
    localStorage.setItem("personal_cloud_refresh_token", "r");
    api.fetchMe.mockRejectedValue(new TypeError("Failed to fetch"));
    renderProbe();
    await waitFor(() => expect(screen.getByTestId("error")).toHaveTextContent(/could not reach the server/i));
    expect(localStorage.getItem("personal_cloud_access_token")).toBe("a");
  });
});

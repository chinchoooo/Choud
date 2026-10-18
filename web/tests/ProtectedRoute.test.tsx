import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProtectedRoute } from "../src/components/ProtectedRoute";
import { ThemeProvider } from "../src/theme/ThemeContext";

const useAuthMock = vi.fn();
const useHealthMock = vi.fn();

vi.mock("../src/auth/AuthContext", () => ({
  useAuth: () => useAuthMock(),
}));
vi.mock("../src/hooks/useHealth", () => ({
  useHealth: () => useHealthMock(),
}));

const healthy = { isError: false, isSuccess: true, data: { status: "healthy" }, refetch: vi.fn() };
const waiting = { isError: false, isSuccess: false, data: undefined, refetch: vi.fn() };
const down = { isError: true, isSuccess: false, data: undefined, refetch: vi.fn() };

function renderAt(initialPath: string) {
  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route path="/login" element={<div>Login page</div>} />
          <Route element={<ProtectedRoute />}>
            <Route path="/files" element={<div>Files page</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </ThemeProvider>,
  );
}

beforeEach(() => {
  useHealthMock.mockReturnValue(healthy);
});

describe("ProtectedRoute", () => {
  it("redirects to /login when there is no user", () => {
    useAuthMock.mockReturnValue({ user: null, isLoading: false, bootError: null });
    renderAt("/files");
    expect(screen.getByText("Login page")).toBeInTheDocument();
  });

  it("renders the protected route when a user is present", () => {
    useAuthMock.mockReturnValue({ user: { id: "1" }, isLoading: false, bootError: null });
    renderAt("/files");
    expect(screen.getByText("Files page")).toBeInTheDocument();
  });
});

describe("startup screen", () => {
  it("shows each step's real state while the login is being checked", () => {
    useHealthMock.mockReturnValue(waiting);
    useAuthMock.mockReturnValue({ user: null, isLoading: true, bootError: null });
    renderAt("/files");

    expect(screen.getByRole("status", { name: /starting choud/i })).toBeInTheDocument();
    expect(screen.getByText("Reaching the server")).toBeInTheDocument();
    expect(screen.getByText("Checking your login")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: /startup progress/i })).toHaveAttribute("aria-valuenow", "0");
  });

  it("moves forward as steps really finish", () => {
    useAuthMock.mockReturnValue({ user: null, isLoading: true, bootError: null });
    renderAt("/files"); // the server answered, the login check is still running
    expect(screen.getByRole("progressbar", { name: /startup progress/i })).toHaveAttribute("aria-valuenow", "1");
  });

  it("says what is wrong and offers a retry when the server cannot be reached", () => {
    const retryBoot = vi.fn();
    useHealthMock.mockReturnValue(down);
    useAuthMock.mockReturnValue({
      user: null,
      isLoading: false,
      bootError: "Could not reach the server to check your login.",
      retryBoot,
    });
    renderAt("/files");

    expect(screen.getByText(/no answer yet/i)).toBeInTheDocument();
    expect(screen.getByText(/could not reach the server to check your login/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(retryBoot).toHaveBeenCalled();
    expect(down.refetch).toHaveBeenCalled();
    expect(screen.queryByText("Login page")).not.toBeInTheDocument(); // not signed out because of an outage
  });

  it("notes a degraded but running server without blocking", () => {
    useHealthMock.mockReturnValue({ ...healthy, data: { status: "degraded" } });
    useAuthMock.mockReturnValue({ user: null, isLoading: true, bootError: null });
    renderAt("/files");
    expect(screen.getByText(/running, but degraded/i)).toBeInTheDocument();
  });
});

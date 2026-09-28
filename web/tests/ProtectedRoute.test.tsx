import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { ProtectedRoute } from "../src/components/ProtectedRoute";

const useAuthMock = vi.fn();

vi.mock("../src/auth/AuthContext", () => ({
  useAuth: () => useAuthMock(),
}));

function renderAt(initialPath: string) {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/login" element={<div>Login page</div>} />
        <Route element={<ProtectedRoute />}>
          <Route path="/files" element={<div>Files page</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("ProtectedRoute", () => {
  it("shows a loading state while auth is resolving", () => {
    useAuthMock.mockReturnValue({ user: null, isLoading: true });

    renderAt("/files");

    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });

  it("redirects to /login when there is no user", () => {
    useAuthMock.mockReturnValue({ user: null, isLoading: false });

    renderAt("/files");

    expect(screen.getByText("Login page")).toBeInTheDocument();
  });

  it("renders the protected route when a user is present", () => {
    useAuthMock.mockReturnValue({ user: { id: "1" }, isLoading: false });

    renderAt("/files");

    expect(screen.getByText("Files page")).toBeInTheDocument();
  });
});

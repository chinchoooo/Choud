import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../src/api/client";
import { Login } from "../src/pages/Login";
import { Security } from "../src/pages/Security";
import { ThemeProvider } from "../src/theme/ThemeContext";

const auth = vi.hoisted(() => ({ login: vi.fn() }));
const api = vi.hoisted(() => ({
  getTwoFactorStatus: vi.fn(),
  startTwoFactor: vi.fn(),
  enableTwoFactor: vi.fn(),
  newRecoveryCodes: vi.fn(),
  disableTwoFactor: vi.fn(),
}));

vi.mock("../src/auth/AuthContext", () => ({ useAuth: () => ({ login: auth.login }) }));
vi.mock("../src/api/twofactor", () => api);

afterEach(() => {
  vi.restoreAllMocks();
  Object.values(api).forEach((fn) => fn.mockReset());
  auth.login.mockReset();
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

describe("Login with two-factor", () => {
  it("asks for the code only when the server says it is needed, then sends it", async () => {
    auth.login
      .mockRejectedValueOnce(new ApiError(401, "two_factor_required"))
      .mockResolvedValueOnce(undefined);
    renderPage(<Login />);
    expect(screen.queryByLabelText(/two-factor code/i)).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "a@b.co" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "password123" } });
    fireEvent.click(screen.getByRole("button", { name: "Log in" }));

    const code = await screen.findByLabelText(/two-factor code/i);
    expect(screen.queryByText("two_factor_required")).not.toBeInTheDocument();
    fireEvent.change(code, { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Log in" }));
    await waitFor(() => expect(auth.login).toHaveBeenLastCalledWith("a@b.co", "password123", "123456"));
  });
});

describe("Security page", () => {
  it("walks through turning it on and shows the recovery codes once", async () => {
    api.getTwoFactorStatus.mockResolvedValue({ enabled: false, recovery_codes_left: 0 });
    api.startTwoFactor.mockResolvedValue({
      secret: "JBSWY3DPEHPK3PXP",
      otpauth_uri: "otpauth://totp/Choud:a%40b.co?secret=JBSWY3DPEHPK3PXP&issuer=Choud",
    });
    api.enableTwoFactor.mockResolvedValue({ recovery_codes: ["abcde-fghjk", "mnpqr-stuvw"] });
    renderPage(<Security />);

    fireEvent.click(await screen.findByRole("button", { name: /turn on two-factor/i }));
    expect(await screen.findByRole("img", { name: /qr code/i })).toBeInTheDocument();
    expect(screen.getByText("JBSWY3DPEHPK3PXP")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/6-digit code/i), { target: { value: "654321" } });
    fireEvent.click(screen.getByRole("button", { name: /confirm and turn on/i }));
    await waitFor(() => expect(api.enableTwoFactor).toHaveBeenCalledWith("654321"));

    const list = await screen.findByLabelText("Recovery codes");
    expect(list).toHaveTextContent("abcde-fghjk");
    fireEvent.click(screen.getByRole("button", { name: /i have saved them/i }));
    expect(screen.queryByLabelText("Recovery codes")).not.toBeInTheDocument();
  });

  it("needs the password and a code to turn it off", async () => {
    api.getTwoFactorStatus.mockResolvedValue({ enabled: true, recovery_codes_left: 7 });
    api.disableTwoFactor.mockResolvedValue(undefined);
    renderPage(<Security />);

    expect(await screen.findByText(/7 recovery code/)).toBeInTheDocument();
    const off = screen.getByRole("button", { name: "Turn off" });
    expect(off).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/current code/i), { target: { value: "111222" } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: "secret-pass" } });
    expect(off).toBeEnabled();
    fireEvent.click(off);
    await waitFor(() => expect(api.disableTwoFactor).toHaveBeenCalledWith("secret-pass", "111222"));
  });
});

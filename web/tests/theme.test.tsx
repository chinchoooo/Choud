import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { THEMES, ThemeProvider, initialTheme, isThemeId, useTheme } from "../src/theme/ThemeContext";

function Probe() {
  const { theme, setTheme } = useTheme();
  return (
    <div>
      <span data-testid="theme">{theme}</span>
      <button onClick={() => setTheme("dark")}>pick dark</button>
    </div>
  );
}

beforeEach(() => localStorage.clear());
afterEach(() => document.documentElement.removeAttribute("data-theme"));

describe("themes", () => {
  it("offers the two retro (monospace black and white) themes", () => {
    expect(THEMES.map((t) => t.id)).toEqual(["light", "dark", "retro", "retro-paper"]);
  });

  it("validates theme ids", () => {
    expect(isThemeId("retro")).toBe(true);
    expect(isThemeId("neon")).toBe(false);
  });

  it("applies and remembers the chosen theme", () => {
    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );
    expect(screen.getByTestId("theme")).toHaveTextContent("retro"); // the default look
    act(() => screen.getByText("pick dark").click());
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(localStorage.getItem("personal_cloud_theme")).toBe("dark");
    expect(initialTheme()).toBe("dark");
  });

  it("ignores a corrupt saved value", () => {
    localStorage.setItem("personal_cloud_theme", "<script>");
    expect(initialTheme()).toBe("retro");
  });
});

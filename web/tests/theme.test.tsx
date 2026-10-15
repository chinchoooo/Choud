import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { THEMES, ThemeProvider, initialTheme, isThemeId, useTheme } from "../src/theme/ThemeContext";

function Probe() {
  const { theme, setTheme } = useTheme();
  return (
    <div>
      <span data-testid="theme">{theme}</span>
      <button onClick={() => setTheme("retro")}>retro</button>
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
    act(() => screen.getByText("retro").click());
    expect(document.documentElement.getAttribute("data-theme")).toBe("retro");
    expect(localStorage.getItem("personal_cloud_theme")).toBe("retro");
    expect(initialTheme()).toBe("retro");
  });

  it("ignores a corrupt saved value", () => {
    localStorage.setItem("personal_cloud_theme", "<script>");
    expect(["light", "dark"]).toContain(initialTheme());
  });
});

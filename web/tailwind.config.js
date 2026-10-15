/** @type {import('tailwindcss').Config} */

// Every colour is a CSS variable (see src/index.css), so a theme is just a different
// set of values: light, dark, and the two retro (monospace, black & white) themes all
// share the same class names.
const scale = (name) =>
  Object.fromEntries(
    [50, 100, 200, 300, 400, 500, 600, 700, 800, 900].map((step) => [
      step,
      `rgb(var(--${name}-${step}) / <alpha-value>)`,
    ]),
  );

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    fontFamily: {
      sans: ["var(--font)"],
      mono: ["var(--font-mono)"],
    },
    borderRadius: {
      none: "0",
      sm: "var(--radius-sm)",
      DEFAULT: "var(--radius)",
      md: "var(--radius)",
      lg: "var(--radius-lg)",
      xl: "var(--radius-lg)",
      "2xl": "var(--radius-lg)",
      full: "9999px",
    },
    extend: {
      colors: {
        white: "rgb(var(--c-white) / <alpha-value>)",
        black: "rgb(var(--c-black) / <alpha-value>)",
        gray: scale("g"),
        red: scale("r"),
        amber: scale("a"),
        green: scale("n"),
        blue: scale("b"),
      },
    },
  },
  plugins: [],
};

import logoDark from "../assets/brand/choud-logo-dark.png";
import logoLight from "../assets/brand/choud-logo-light.png";
import markDark from "../assets/brand/choud-mark-dark.png";
import markLight from "../assets/brand/choud-mark-light.png";
import { useTheme } from "../theme/ThemeContext";

/** The dark artwork (white on transparent) belongs on dark surfaces, the light artwork on light ones. */
const DARK_SURFACES = new Set(["dark", "retro"]);

interface Props {
  /** "mark" is the cloud-and-folder; "full" adds the pixel "Choud" wordmark and underline. */
  variant?: "mark" | "full";
  /** The height of the mark, or the width of the full logo, in pixels. */
  size?: number;
  className?: string;
}

/** The Choud logo from the brand sheet, switching artwork with the active theme. Decorative: the name sits beside it. */
export function Logo({ variant = "mark", size = 28, className = "" }: Props) {
  const { theme } = useTheme();
  const dark = DARK_SURFACES.has(theme);
  if (variant === "full") {
    return (
      <img
        src={dark ? logoDark : logoLight}
        alt=""
        width={size}
        height={Math.round((size * 647) / 720)}
        className={`shrink-0 ${className}`}
      />
    );
  }
  return (
    <img
      src={dark ? markDark : markLight}
      alt=""
      height={size}
      width={Math.round(size * 1.66)}
      className={`shrink-0 ${className}`}
    />
  );
}

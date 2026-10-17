import iconDark from "../assets/brand/choud-icon-dark.svg";
import iconLight from "../assets/brand/choud-icon-light.svg";
import logoDark from "../assets/brand/choud-logo-dark.svg";
import logoLight from "../assets/brand/choud-logo-light.svg";
import { useTheme } from "../theme/ThemeContext";

/** The dark artwork (white on black) belongs on dark surfaces, the light artwork on light ones. */
const DARK_SURFACES = new Set(["dark", "retro"]);

interface Props {
  /** "mark" is the small cloud-folder icon; "full" is the detailed logo with the wordmark. */
  variant?: "mark" | "full";
  size?: number;
  className?: string;
}

/** The Choud logo, switching artwork with the active theme. Decorative: the name sits beside it. */
export function Logo({ variant = "mark", size = 28, className = "" }: Props) {
  const { theme } = useTheme();
  const dark = DARK_SURFACES.has(theme);
  const src = variant === "full" ? (dark ? logoDark : logoLight) : dark ? iconDark : iconLight;
  return (
    <img
      src={src}
      alt=""
      width={size}
      height={size}
      className={`shrink-0 border border-gray-300 ${className}`}
      style={{ imageRendering: "pixelated" }}
    />
  );
}

# Choud brand assets (monochrome)

## Included
- `choud-logo-dark.svg`: white logo on black for dark surfaces.
- `choud-logo-light.svg`: black logo on white for light surfaces.
- `choud-icon-dark.svg` / `choud-icon-light.svg`: square app icon variants.
- `choud-favicon.svg`: compact monochrome favicon.
- `choud-loading-screen.html`: responsive CRT-inspired loading screen prototype with animated progress.

## Brand tokens
- Black: `#000000`
- White: `#FFFFFF`
- Secondary line: `#333333`
- Typography: monospace / pixel-inspired; preserve high legibility for UI text.

## Agent implementation notes
- Use SVG assets directly where supported. Export PNGs from the SVGs at required platform sizes if needed.
- The HTML loading screen is a prototype. Its progress animation is illustrative, not connected to real initialization. Replace the timer with actual app state/progress before shipping.
- Keep scanlines subtle and disable/reduce motion when `prefers-reduced-motion: reduce` applies.
- Keep the detailed logo for splash/branding and use the icon-only mark for favicons and small app icons.

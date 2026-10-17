# Branding (Choud)

Strict monochrome (black `#000000`, white `#FFFFFF`, secondary line `#333333`), retro-terminal
feel, pixel-art cloud-folder mark. The supplied kit lives in [`choud-brand-assets/`](../choud-brand-assets)
and is the source of truth: nothing is redrawn, everything below is derived from those SVGs by
[`scripts/brand/build_assets.py`](../scripts/brand/build_assets.py).

```bash
python scripts/brand/build_assets.py          # regenerate (needs Pillow and Chrome/Edge)
python scripts/brand/build_assets.py --check  # CI-style: fail if the committed assets are stale
```

## Done

| Where | What | Source |
| --- | --- | --- |
| Web favicon | `web/public/favicon.svg` (the supplied file, byte for byte) | `choud-favicon.svg` |
| Web fallbacks | `favicon-16/32.png` (dot-free variant, crisp small), `apple-touch-icon.png`, `icon-192/512.png`, `manifest.webmanifest`, `theme-color` black | favicon / icon-dark |
| Web logos | `web/src/assets/brand/choud-{logo,icon}-{dark,light}.svg` (copies, ready to import) | the four SVGs |
| Android launcher | adaptive icon: black background, mark ported to a VectorDrawable and scaled into the safe zone, plus a themed (monochrome) layer | `choud-icon-dark.svg` |
| Android status bar | `ic_stat_choud` at 24-96 px, alpha only, dot-free so it stays legible | favicon |
| Android logos | `choud_logo_dark/light.png` (512 px, rendered from the SVGs) and `ic_choud_mark.xml` | logo SVGs / icon |
| Android launch window | black with the mark (`choud_splash.xml`) | icon |
| Names | web title, Android app label and notification title are "Choud" | |

Light vs dark: `choud-logo-dark` (white on black) belongs on dark surfaces (`retro`, `dark`),
`choud-logo-light` on light ones (`retro-paper`, `light`).

## Framework-specific adaptations

- **Android has no SVG support.** Shapes (rects and paths) are converted to VectorDrawables by the
  script; logos that contain the `<text>` wordmark ship as PNGs rendered by Chrome from the SVG,
  because VectorDrawable cannot draw text.
- **Adaptive icons are cropped to a shape**, and the supplied cloud fills ~84% of its box, so the
  launcher foreground is the same artwork scaled by 1.12 dp per grid unit (farthest point of the
  cloud stays inside the 66 dp safe circle). The website icons use the artwork unscaled.
- **Tiny sizes:** below ~48 px the 1.6-unit dither dots turn into noise, so the 16/32 px favicons
  and the status-bar icon are rendered from the same SVG with only those dots removed.
- **Wordmark font:** the supplied logos set "Choud" in `font-family="monospace"`, so it is drawn in
  the device's own monospace font. The PNG logos fix it at export time.

## Known issues in the supplied kit (left as supplied)

- In both detailed logos the top of the "Choud" wordmark touches the bottom edge of the folder
  outline (text baseline y=57, folder bottom y=52). Worth a nudge in the source SVG.

## Not done yet (parked while Milestone 2 takes priority)

- A branded loading screen (`choud-loading-screen.html` is a prototype with a timer; it must be
  driven by real startup state, not that timer): React boot overlay for the web app tied to
  session / server health / media token / storage queries, and an equivalent Android view tied to
  the first facts / health check. Steps and progress must be real, with reduced-motion respected.
- A theme-aware `<Logo>` (web and Android) and the logo on the login pages.
- Making the retro theme the default for new installs.

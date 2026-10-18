# Branding (Choud)

Strict monochrome (black `#000000`, white `#FFFFFF`), retro-terminal feel, a dithered pixel-art
cloud with a folder, and a chunky pixel "Choud" wordmark with an underline.

The **brand sheet** is the source of truth: [`choud-brand-assets/brand-sheet.png`](../choud-brand-assets/brand-sheet.png)
shows the logo (light and dark), the app icons, the favicons and the five retro loading screens.
Everything the apps use is cut out of it by one script, so there is a single place to change:

```bash
python scripts/brand/from_sheet.py            # regenerate every logo and icon (needs Pillow)
python scripts/brand/from_sheet.py --check    # fail if the committed assets are stale
```

(The older SVG kit in `choud-brand-assets/*.svg` is a simplified drawing of the same idea and is no
longer used by the apps.)

## What the script makes

The art is turned into a clean one-colour mask (so one file serves every theme), enlarged and
re-sharpened so the pixel edges stay crisp, then written at the sizes each platform needs.

| Where | What |
| --- | --- |
| Android, in the app | `choud_logo_full.png` (cloud, folder, wordmark), `ic_choud_mark.png` (cloud and folder), `choud_wordmark.png`: white masks the app tints to the current theme's ink colour, so they look right in all four themes |
| Android, launcher | adaptive icon: black background, the mark scaled into the safe zone as the foreground, plus a themed (monochrome) layer; `ic_stat_choud` for notifications |
| Android, launch window | black with the mark (`choud_splash.xml`, `choud_splash_icon.xml`) |
| Web logos | `web/src/assets/brand/choud-{logo,mark,icon}-{dark,light}.png`; the `Logo` component picks the dark art (white) on dark and retro-black themes, the light art on the others |
| Web icons | `web/public/` `icon-192/512.png`, `apple-touch-icon.png`, `favicon-16/32.png`, referenced by `manifest.webmanifest` and `index.html` |

## The loading screen

The sheet's loading frames (logo, one line of status text, an outlined bar filled with solid
blocks, a "Ready." at the end) are built natively, not shown as pictures, so every line and every
block is something that really happened:

- **Android:** `LoadingScreen` + `BlockBar`. Shown after signing in, and on the first start when the
  phone has no copy of the library yet, with the steps reach the server, check the login, sync the
  photos, fetch the first thumbnails, ready. Later starts skip it and open instantly.
- **Web:** `BootScreen` shows the same logo and block bar for its start-up checks.

## Where the look lives in the Android app

The app has no stock Android widgets in anything you touch. Buttons, text fields, switches, list
rows, bottom sheets, full-screen pages, the toast, the seek bar and play/pause controls, the progress
bars and the scroll handle are all drawn by the app in the web app's style: bordered boxes with square
corners in the retro themes, colours inverted while pressed, a heavier border on the field that has
focus. (Only things the phone itself owns, such as the permission prompts and the system share sheet,
look like Android.) The pieces are `Ui.kt` (button, field, logos), `Kit.kt` (rows, switch, group,
banner, top bar, scroll style), `Sheet.kt` (sheets and pages), `Player.kt` (seek bar and player bar)
and `LoadingScreen.kt`.

## Names

Web title, Android app label and notification title are "Choud".

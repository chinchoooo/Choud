# Changelog

All notable changes to Choud. Each release on GitHub has fuller notes and upgrade steps; this file is the
short version. Versions follow `MAJOR.MINOR.PATCH`; until 1.0 the minor number can include changes that
need a server update (always noted).

## 0.5.1

- The logo, wordmark, app icon, favicons and loading screen come from the brand sheet, on Android and the
  web (one script, `scripts/brand/from_sheet.py`, makes them all).
- Android: a loading screen driven by the real start-up steps; every control is the app's own (button,
  text field, message pill, audio and video controls, seek bar, scroll handle); no stock dialogs or
  toasts remain.
- `scripts/enable-public-links.sh` checks the public address the way the internet reaches it (public DNS)
  and gained `--no-verify`.

## 0.5.0

- **Fast photos on slow links:** the phone keeps the whole library in a local database (delta sync, `304`
  when nothing changed), blurry ThumbHash placeholders, WebP thumbnails on stable cacheable URLs, a batch
  thumbnail endpoint, and a daily warm-up on Wi-Fi while charging. Photos that are only on the phone
  appear in the same timeline. Pinch to resize the grid.
- **Public share links in one command:** `scripts/enable-public-links.sh` (Tailscale Funnel or a
  Cloudflare Tunnel), a pause switch and "revoke all" for administrators, `GET /api/instance`,
  `GET /s/_health`. The phone and web app say whether a link works from outside, and the phone can send
  the file itself instead.
- **Android:** own sheets, pages and switches instead of stock dialogs; a settings hub; a viewer with an
  action bar; search; upload and share into Choud from other apps; new folder and rename; screens for
  trash, shared links, storage and sign-in history; lazy tabs and a faster start.
- `scripts/netcheck.sh` finds Wi-Fi power saving and relayed Tailscale paths; `docs/mobile-perf.md`.
- **Needs a server update** (migrations 0016 and 0017).

## 0.4.2 and 0.4.1

- Android redesign: app bar and bottom navigation, long-press multi-select with share, save, keep offline,
  star, move and delete, fast thumbnail loading with a disk cache, a clean launch screen and icon.
- The phone tries a private address first and falls back to a public one; an optional public door that
  serves the whole app (`PUBLIC_DOOR_MODE=full`).
- Public share links via `PUBLIC_BASE_URL`; photo dates repaired from file names and EXIF.
- Responses are compressed; thumbnails are made ahead of time in the background.

## 0.4.0

- **Rewind** (restore any folder to an earlier moment), **Vault** (files sealed in the browser),
  **file requests**, one-time links, a storage report with safe clean-up, "on this day" memories,
  sign-in history, an administrator server view.
- Multi-select, zip download, folder upload, strict browser security headers, encrypted backups.
- Migrations 0014 and 0015.

## 0.3.0

- Search inside files, two-factor login with recovery codes, edit links, invites and a registration lock,
  desktop backup mode. Migrations 0007 to 0013.

## 0.2.1

- Android no longer re-uploads everything after a reinstall.

## 0.2.0

- Android app (camera-roll backup, browsing, built-in viewers, four themes), the Windows desktop client,
  an upload queue with speed and time left, photo timeline, favorites, activity, thumbnails, storage usage
  and quota, stricter upload limits.

## Before 0.2.0

Phases 1 to 10 of the roadmap ([`docs/roadmap.md`](docs/roadmap.md)): authentication, folders and files,
the C++ content-addressed storage engine, chunked and resumable uploads, versioning and trash, the desktop
sync client with offline mode and conflict copies, the production deployment stack and operator scripts.

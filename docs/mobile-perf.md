# Phone app: speed

Why photos feel fast (or slow) from anywhere, what the app does about it, and how to measure.

## The short version

Opening your photos over a 100-200 ms link is slow for one reason: **round trips**. Fetching 40
thumbnails one by one costs 40 trips; each trip first has to find a path (DNS, TCP, TLS), then ask,
then wait. The app attacks that from five sides:

| Technique | What it removes |
| --- | --- |
| **The library lives on the phone** (`LibraryDb`, from `GET /api/library/index`) | Waiting for the list. Every month paints at once from the phone's own database, offline too. A refresh asks only what changed since the last one: usually a bodyless `304` (about 30 ms), otherwise a few rows |
| **ThumbHash placeholders** (about 25 bytes per photo, inside the index) | Grey boxes. A cell shows a blurry version of the photo the instant it exists |
| **Batched thumbnails** (`POST /api/media/thumbs`, 24 at a time) | 24 round trips become 1. The visible cells are gathered for one frame, then fetched together |
| **WebP thumbnails on stable URLs** (`/api/thumbs/{id}?v=hash`, `immutable`) | About a third fewer bytes, and a thumbnail is fetched once, ever: the URL only changes when the picture does |
| **One shared HTTP client** | A fresh TCP and TLS handshake for every request. One connection pool is reused by lists, thumbnails and downloads |

And three that are about the **start**: the app opens straight into the screen (the server and login
are checked in the background), a tab is only built when you first open it, and the login tokens are
the only thing kept in the slow-to-open encrypted store.

Also: the phone refreshes the library and the newest thumbnails once a day on Wi-Fi while charging
(**More > Keep photos ready**), so Photos is instant even when you open it on a bad connection.

## The network is the biggest factor

Everything above makes the app need fewer trips. A trip itself should still be short. Run on the
server:

```bash
scripts/netcheck.sh my-phone     # the phone's Tailscale name
```

Typical findings:

- **Wi-Fi power saving on the server laptop.** The default on most Linux distributions. Every reply
  waits for the radio to wake up, so a same-room ping is 90 ms instead of 3 ms. The script prints the
  commands to turn it off for good (or use Ethernet).
- **Tailscale using a relay (DERP) instead of a direct path.** Adds 50-200 ms. `tailscale ping`
  tells you which one you have; on the same Wi-Fi it should say `direct` and answer in a few ms.

In the app, **More > Test connection** shows the median round trip and which address it used.

## Budgets

Measured on an Android 14 emulator (x86, software graphics), release build with R8. A real phone is
several times faster than the emulator for everything CPU-bound.

| What | Budget | Measured |
| --- | --- | --- |
| Work done in `onCreate` (the part we control) | under 100 ms | 43-115 ms (was 320 ms) |
| Cold start to first frame (`am start -W`) | under 500 ms on a phone | about 1.0-1.5 s on the emulator, which is dominated by the emulator's own process start |
| Open Photos, painted from the phone's database | no network | yes; verified with the server off |
| Refresh when nothing changed | one tiny request | `304` in about 30 ms |
| Thumbnails for a full screen | one request | one batch request (24 cells), about 150 ms on a local link |
| Release APK | under 6 MB | 0.7 MB |

Record new numbers here when something changes.

## How to measure

```bash
android/tools/perf.sh start 5        # cold start, median of 5 runs
android/tools/perf.sh jank           # scroll the grid 10 times, print janky-frame stats
android/tools/perf.sh net slow       # emulator only: 150 ms delay, 4 Mbps (and `normal` to reset)
android/tools/perf.sh log            # the app's own request log with per-call timings
```

The app logs every request with its time to **More > Diagnostics** (and `adb logcat -s ChoudPerf`
prints `onCreate` time). Over a real link, compare the first Photos screen with the phone on Wi-Fi
and then on mobile data through Tailscale.

## What is not done yet

- Thumbnails larger than 256 px are not pre-generated for the whole library (only the grid size).
- No predictive fast-scroll thumb with a date label.
- HTTP/2 to the server needs HTTPS in front (`tailscale serve --https`); today the phone talks plain
  HTTP/1.1 over Tailscale's own encrypted tunnel, with keep-alive.

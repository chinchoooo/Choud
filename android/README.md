# Personal Cloud — Android app (Phase 18a, first slice)

One-way **camera-roll backup** (phone → server) that runs in the background.
Spec and rationale: [`../docs/mobile.md`](../docs/mobile.md).

## What it does

- Log in (server URL, email, password); tokens are kept in
  `EncryptedSharedPreferences` (Android Keystore) and refreshed on any `401`.
- Backs up photos and videos under `DCIM/` to
  `Phone Backups/<phone name>/<Camera|subfolder>/` — a per-device folder, so two
  phones with `IMG_0001.jpg` never collide.
- Uploads are **create-only** (`base_version_id=none`). On a name clash: same
  bytes → already backed up (counted done); different bytes → uploaded as
  `name.conflict-YYYY-MM-DD.ext`. Nothing is ever overwritten.
- Files over 20 MiB use the resumable chunked API; the session id is persisted,
  so a killed upload resumes with only the missing chunks.
- WorkManager runs it hourly (Wi-Fi + charging by default, switchable in the UI);
  "Back up now" runs it immediately on any connection. A notification shows
  progress while it runs.
- It **never deletes anything on the phone** and never downloads into the camera roll.

## Build and test

Needs the Android SDK (platform 34) and a JDK 17+ (Android Studio's bundled JBR works).

```bash
cd android
echo "sdk.dir=/path/to/Android/Sdk" > local.properties
./gradlew testDebugUnitTest assembleDebug
# APK: app/build/outputs/apk/debug/app-debug.apk
```

Install with `adb install -r app/build/outputs/apk/debug/app-debug.apk`, open the
app, log in with the server URL as reachable from the phone (LAN or Tailscale
address), and grant the media/notification permissions.

## Layout

| File | Role |
| --- | --- |
| `Logic.kt` | Pure decisions: remote folder, conflict names, chunk math (unit-tested) |
| `Api.kt` | HTTP client, port of `client/cloudsync/api.py` (tested against a mock server) |
| `Store.kt` | Encrypted settings + SQLite table of what is already backed up |
| `Backup.kt` | MediaStore scan and the per-file upload / clash handling |
| `SyncWorker.kt` | WorkManager job, constraints, foreground notification |
| `MainActivity.kt` | Plain login + status screen |

## Not done yet

- **Never run on a real phone or emulator** — only unit tests (11) and a debug build
  have been verified. Do a real run before trusting it.
- Backed-up files are not re-uploaded if edited afterwards (a photo edited in place
  keeps its MediaStore id and is treated as done).
- Only `DCIM/`; no other folders (needs Storage Access Framework), no two-way sync
  (port `client/cloudsync/reconciler.py` and its test table), no browse/download (18b).
- Plain `http://` is allowed (`usesCleartextTraffic`) because the server is typically
  on a LAN/Tailscale; use `https://` if you can.
- No battery-optimisation exemption prompt; without it Android may delay the job.
- Original capture time is not sent (see `docs/mobile.md`, problem 5).

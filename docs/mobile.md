# Phone sync (Phases 16 and 18a)

**Goal (Milestone 1):** pick folders on your phone (camera roll, Downloads,
Documents, …), and have them sync with the server **in the background**, without
the app being open — the same thing the desktop client does, on a phone.

**Status:** the *server* side is ready. **Platform decided: Android (Kotlin).**
Build-order steps 1-5 (login, status screen, camera-roll backup, WorkManager
scheduling, resumable chunked uploads) exist in [`android/`](../android/README.md)
— unit-tested and building, but **not yet run on a real phone/emulator**. Steps
6-7 (two-way folder sync, browse/download) are not built. This page remains the
spec.

## What the server already provides

Everything a phone client needs exists and is tested (the desktop client uses
the same calls — read `client/cloudsync/api.py` as the reference client):

| Need | Endpoint | Notes |
| --- | --- | --- |
| Log in, stay logged in | `POST /api/auth/login`, `/refresh` | Short access token (15 min), refresh token (7 days). Refresh on any `401`. Store tokens in the Android Keystore / iOS Keychain. |
| See what is on the server | `GET /api/sync/snapshot` | Whole tree with paths, hashes, `version_id`. Send the last `ETag` as `If-None-Match`: unchanged tree = bodyless `304`, so polling is cheap on mobile data. |
| Create folders | `POST /api/sync/folders` | Idempotent nested path. |
| Upload a small file | `POST /api/files/upload` | Multipart. |
| Upload a large file / video | `POST /api/uploads` → `POST /api/uploads/{id}/chunks/{i}` → `POST /api/uploads/{id}/complete` | **Resumable**: `GET /api/uploads/{id}` says which chunks are missing, so an upload the OS killed resumes with only the rest. Persist the session id. |
| Don't overwrite someone else's edit | `base_version_id` on upload and delete | `409 {"code":"version_conflict"}` when the file changed since the version you started from; `base_version_id=none` = create-only. |
| Download | `GET /api/files/{id}/download` | Stream to a temp file, verify SHA-256, then move into place. |
| Delete safely | `DELETE /api/files/{id}?base_version_id=` | Goes to the server trash; recoverable. |

## The sync algorithm is the same

Reuse the desktop design unchanged — three views per path (local, remote, base),
the decision table in `client/cloudsync/reconciler.py`, conflict copies named
`name.conflict-YYYY-MM-DD.ext`, deletes to a recoverable trash, "an edit always
beats a delete". The table is pure logic with no I/O: port it as-is and port its
test table with it. The things that differ on a phone are below.

## Phone-specific problems (decide these before writing code)

### 1. Photos: two phones, same file name — silent data merging

Cameras number files `IMG_0001.jpg`. If two phones both upload
`Camera/IMG_0001.jpg`, the server's "same name in the same folder = new
version" rule would make one photo a *version* of the other. Nothing is lost
(both are kept as versions) but they look like one photo with two edits.

**Do this:** back photos up into a per-device folder:
`Phone Backups/<device name>/Camera/IMG_0001.jpg`, and upload with
`base_version_id=none` so a clash is a `409` that the app turns into a conflict
copy rather than a surprise version. Treat camera-roll backup as **one-way
(phone → server)** by default: do not download other devices' photos into the
camera roll, and **never delete from the phone because a server file vanished**.

### 2. Background execution is the hard part

| | Android | iOS |
| --- | --- | --- |
| Periodic background work | WorkManager periodic work (≥ 15 min), constraints: unmetered network, charging, battery not low | `BGTaskScheduler` (`BGAppRefreshTask` ~30 s, `BGProcessingTask` minutes, system decides *when*) |
| Reacting to new photos | `ContentObserver` on MediaStore + a one-off WorkManager job | Photos library change observer, only while the app runs; otherwise PHPhotoLibrary background delivery is not guaranteed |
| Long uploads | Foreground service (visible notification) or WorkManager expedited work | Background `URLSession` upload tasks keep running after the app is suspended |
| Reality check | Works well if the user exempts the app from battery optimisation | The OS decides; "always syncs within minutes" is **not** achievable. Expect syncs when charging overnight on Wi-Fi |

Consequences for the design: keep every sync step **resumable and idempotent**
(the server already is), do the work in short slices, persist state after each
file, and make "open the app and pull to refresh" a first-class way to catch up.

### 3. Storage access

- **Android 11+ (scoped storage):** camera roll through **MediaStore**; other
  folders through the Storage Access Framework (the user picks a folder once and
  grants a persistent URI). No raw file paths.
- **iOS:** the photo library through **PhotoKit**; files through the document
  picker with security-scoped bookmarks. The app cannot watch arbitrary folders.

So "connect to folders on my phone" realistically means: *camera roll + folders
the user explicitly grants*, and on iOS the second is limited.

### 4. Cellular data and battery

Default to **Wi-Fi + charging only** for uploads; make cellular opt-in with a
size cap. Use the snapshot `ETag` so idle polling costs a few hundred bytes.

### 5. Original timestamps

The server records upload time, not the photo's capture time. The web gallery
(Phase 17) will want the original date. Plan: add an optional `modified_at` form
field to uploads and expose it in the snapshot; until then the date is only in
the file's EXIF data (which is preserved, since bytes are stored untouched).

## Decision needed: which phone?

Background folder sync needs platform APIs that cross-platform frameworks wrap
unevenly.

| Option | Pros | Cons |
| --- | --- | --- |
| **Android only, Kotlin** (recommended if you have Android) | Best background story (WorkManager, foreground services); the algorithm ports directly (Kotlin ≈ the Python); realistic to get real background sync | Android only |
| **iOS only, Swift** | Native PhotoKit + background URLSession | iOS background limits cap how "live" it can feel; needs a Mac + Apple developer account to run on a real device |
| **Both, native twice** | Best result on both | Two codebases |
| **Both, Flutter / React Native + native modules** | One UI codebase | The background sync part is native code on each platform anyway, so the saving is mostly the UI; Expo's managed workflow is too restrictive for this |
| **Stopgap: the Python client under Termux (Android)** | Works today, no app to build | Not a product: needs Termux, a scheduler, battery-optimisation exemptions; **untested** |

**Recommendation:** tell me the phone. If Android → build 18a in Kotlin
(WorkManager + MediaStore + SAF), reusing this spec. If iOS → build in Swift and
set expectations about background timing. Do not start a cross-platform
framework for this feature.

## Suggested build order for 18a

1. Login + settings (server URL, account) with tokens in the secure store.
2. Pick folders; show a sync status screen (pending, errors, last run).
3. One-way **camera-roll backup** into `Phone Backups/<device>/Camera/` —
   the feature that lets you stop paying for a photo cloud.
4. Background scheduling (WorkManager / BGTaskScheduler) with Wi-Fi + charging
   constraints.
5. Resumable chunked uploads for videos.
6. Two-way sync for chosen folders (port `reconciler.py` + its test table).
7. Browse/download on demand (this is 18b, Milestone 2).

## What would be tested

The server contract is already covered by the backend and client suites. The app
needs its own tests for: the ported decision table, resume after a killed
upload, token refresh, name-collision handling, and the "never delete the
phone's file because the server lost it" rule.

# Releases and downloads

Downloadable builds live on the repository's **Releases** page (GitHub → the repo → Releases).
Each release carries:

| File | What it is |
| --- | --- |
| `personal-cloud-<version>.apk` | The Android app (signed). Install it on the phone. |
| `cloudsync-windows-<version>.exe` | The desktop sync client for Windows. A command-line program: run `cloudsync.exe login ...` then `cloudsync.exe run` (see `client/README.md`). |
| `SHA256SUMS.txt` | Checksums, so a download can be verified. |

macOS and Linux run the sync client from source (`pip install -e client`), and the server is
deployed from the repository itself (`docs/deployment.md`), so neither is a release file.

> While the repository is **private**, downloading needs a browser (or `gh`)
> logged in to the owner's GitHub account. The files contain no secrets (the server address and
> password are typed into the app), so making the repository public would be safe if you want
> plain download links; that is your decision.

## Installing the Android app

1. Download the `.apk` to the phone (a browser logged in to GitHub, or copy it over).
2. Open it and allow "install from this source" when asked.
3. **If a debug build is already installed, uninstall it first.** Release and debug builds are
   signed with different keys, and Android refuses to install one over the other. Nothing is lost:
   the photos are on the server, and the app recognises files it already uploaded.

Updates install over a previous release as long as they are signed with the **same key**.

## Signing key (do not lose it)

Release APKs are signed with a key kept **outside the repository**, in
`~/.personal-cloud-signing/` (`release.jks` and `keystore.properties`), or in the folder named by
the `PC_SIGNING_DIR` environment variable. It is never committed. **Back this folder up** (a
password manager or an encrypted drive): if it is lost, future releases cannot be installed over
existing installs and everyone has to uninstall and reinstall. Without the key, `assembleRelease`
produces an unsigned APK.

To create a new key (first time only):

```bash
keytool -genkeypair -keystore release.jks -alias personalcloud -keyalg RSA -keysize 2048 \
        -validity 10000 -dname "CN=Personal Cloud"
# then put storeFile/storePassword/keyAlias/keyPassword in keystore.properties next to it
```

## Building a release

```bash
# Android (JDK 17+, Android SDK 34; Android Studio's bundled JBR works)
cd android && ./gradlew testDebugUnitTest assembleRelease
#   -> app/build/outputs/apk/release/app-release.apk
#   bump versionCode / versionName in app/build.gradle.kts first
apksigner verify --print-certs app/build/outputs/apk/release/app-release.apk

# Windows sync client
cd client && pip install -r requirements.txt pyinstaller
pyinstaller --onefile --console --name cloudsync --paths . packaging/cloudsync_entry.py
#   -> dist/cloudsync.exe

# Publish (needs the GitHub CLI, logged in)
sha256sum personal-cloud-0.2.0.apk cloudsync-windows-0.2.0.exe > SHA256SUMS.txt
gh release create v0.2.0 personal-cloud-0.2.0.apk cloudsync-windows-0.2.0.exe SHA256SUMS.txt \
   --title "v0.2.0" --notes-file notes.md
```

Antivirus tools sometimes flag PyInstaller executables as suspicious (a known false positive for
any program packed this way). The checksums let you confirm the file is the one that was built.

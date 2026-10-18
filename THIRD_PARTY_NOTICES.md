# Third-party software and assets

Choud itself is released under the [MIT licence](LICENSE). It builds on the open-source projects below.
This list covers the **direct** dependencies; each project's own licence file (shipped in its package)
covers its further dependencies. Licences were checked against the installed package metadata.

Choud does not redistribute these in this repository: Python, npm, Gradle and Docker fetch them at
install or build time. Where a licence has conditions that matter if **you** redistribute a build
(Android APK, Docker image), they are noted.

## Server (Python)

| Package | Licence |
| --- | --- |
| FastAPI, SQLAlchemy, Alembic, Pydantic, pydantic-settings, PyJWT, argon2-cffi, pytest, Ruff | MIT |
| Uvicorn, HTTPX | BSD-3-Clause |
| python-multipart | Apache-2.0 |
| email-validator | Unlicense (public domain) |
| Pillow | MIT-CMU (HPND-style) |
| pypdf | BSD-3-Clause |
| psycopg2-binary | LGPL-3.0 with exceptions (used as an unmodified, dynamically linked library) |

## Web app (npm)

| Package | Licence |
| --- | --- |
| React, React DOM, React Router, TanStack Query, qrcode-generator, Tailwind CSS, Vite, Vitest, ESLint, Prettier, jsdom | MIT |
| lucide-react (icons) | ISC |
| TypeScript | Apache-2.0 |

## Android app

| Library | Licence |
| --- | --- |
| AndroidX (core, RecyclerView, SwipeRefreshLayout, WorkManager, Security Crypto), Kotlin and kotlinx.coroutines, OkHttp, Okio | Apache-2.0 |
| JUnit | EPL-1.0 (tests only) |

Some small icons in the app's `res/drawable` are drawn from the **Lucide** icon set (ISC licence,
<https://lucide.dev>) and a few from **Material Icons** (Apache-2.0, Google).

## Storage engine (C++)

| Library | Licence |
| --- | --- |
| OpenSSL 3 (hashing) | Apache-2.0 |
| Boost (HTTP server pieces) | Boost Software License 1.0 |
| GoogleTest (tests only) | BSD-3-Clause |

## Programs the stack runs in containers

These are separate programs started by Docker Compose, not linked into Choud:

| Program | Licence | Notes |
| --- | --- | --- |
| PostgreSQL | PostgreSQL Licence | |
| Caddy | Apache-2.0 | |
| nginx (serves the built web app) | BSD-2-Clause | |
| FFmpeg (a static build, only to cut a frame out of uploaded videos for thumbnails) | LGPL/GPL depending on the build | The server image copies a pinned static build (`mwader/static-ffmpeg`) at build time. If you distribute a Docker image built from this repository, you also distribute that FFmpeg build and must comply with its licence. |
| Tailscale | BSD-3-Clause (client) | Optional; Choud works with any network that reaches the server. |

## Code and designs derived from others

- **ThumbHash** (`server/app/services/thumbhash.py`, `android/.../ThumbHash.kt`): ports of the algorithm
  by Evan Wallace, MIT licence, <https://github.com/evanw/thumbhash>.
- **Contributor Covenant** (`CODE_OF_CONDUCT.md`): adapted from version 2.1, CC BY 4.0.
- **Brand artwork** (`choud-brand-assets/`, the generated logos and icons): created for this project and
  released under the same MIT licence as the code. The name "Choud" and the logo identify this project:
  you are free to use them to refer to it, but please do not present a modified fork as the official one.

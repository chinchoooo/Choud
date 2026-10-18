# Contributing to Choud

Thank you for wanting to help. Choud is a self-hosted Google Drive alternative that runs on one spare
Linux machine. It is a small project with strong opinions, so please read this page before you start:
it will save you (and the reviewers) time.

- New to the code? Read [`docs/guide.md`](docs/guide.md) (the whole system in one document) and then
  [`docs/architecture.md`](docs/architecture.md) (the rules and the non-goals).
- Want a smaller entry point? [`docs/learning-prompt.md`](docs/learning-prompt.md) is a prompt you can
  paste into an AI assistant to be taught the project step by step.
- Found a security problem? **Do not open a public issue.** See [`SECURITY.md`](SECURITY.md).

## The rules that decide whether a change is accepted

These come from [`docs/architecture.md`](docs/architecture.md#implementation-rules) and are not
suggestions.

1. **Never silently destroy data.** When unsure, keep the data, return an error and log it.
2. **Do not over-engineer.** No new dependency or abstraction without a concrete reason. Choud is
   deliberately not Kubernetes, not microservices and not "distributed anything" (see the non-goals).
3. **Keep the separation of concerns.** Python owns the API, auth, metadata and business logic; C++ owns
   storage, hashing, chunks and the data plane; React owns the web UI; the Android app and the desktop
   client own their own platforms. The C++ HTTP API stays small: only what the backend actually calls.
4. **Test the failure cases**, not just the happy path: disk full, corrupt or missing object,
   interrupted upload, server disconnect, duplicate upload, invalid token, someone else's file,
   conflicting edits.
5. **Never commit secrets.** `.env` is ignored; only `.env.example` and the placeholder `.env.dev` are
   tracked.

A change that makes the system bigger without making it noticeably better for a self-hoster will
usually be declined, however clever it is.

## Setting up

You need Docker with the Compose plugin for the full stack, and for the individual pieces:

| Piece | Needs |
| --- | --- |
| `server/` | Python 3.12+ |
| `web/` | Node 20+ |
| `engine/` | CMake, a C++17 compiler, `libssl-dev`, `libboost-dev`, `libgtest-dev` |
| `android/` | JDK 17 and the Android SDK (Android Studio is the easy way) |
| `client/` | Python 3.12+ |

```bash
git clone https://github.com/chinchoooo/Choud.git
cd Choud

make install        # server and web dependencies
make dev            # the whole stack with hot reload; the app is on http://localhost:8080
```

`make dev` uses the placeholder secrets in `.env.dev`. For a real deployment use `scripts/setup.sh`
(see [`docs/deployment.md`](docs/deployment.md)).

## Running the tests

Run what you touched, and the others before you open a pull request.

```bash
# Server (uses an in-memory SQLite database and a fake storage engine; no Docker needed)
cd server && pip install -r requirements.txt && ruff check app tests && pytest

# The same suite on real PostgreSQL (do this when you add a constraint, foreign key or delete)
TEST_DATABASE_URL=postgresql+psycopg2://user:pass@localhost/choud_test pytest

# Web
cd web && npm ci && npm run lint && npm run build && npm run test     # `build` type-checks too

# C++ engine
cmake -S engine -B engine/build -DCMAKE_BUILD_TYPE=Release
cmake --build engine/build --parallel && ctest --test-dir engine/build --output-on-failure

# Desktop client (its integration tests run the real server in-process)
cd client && pip install -r requirements.txt && pytest

# Android
cd android && ./gradlew testDebugUnitTest assembleDebug
```

GitHub Actions runs all of this on every pull request ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)).

Traps that have bitten people:

- Use `npm run build`, not just `tsc --noEmit`: the real build uses `tsc -b`, which is stricter.
- A server module that does `from app.services.storage_service import get_storage_service` must also be
  patched in `server/tests/conftest.py`, or its tests will quietly use the real storage service.
- SQLite does not enforce foreign keys; PostgreSQL does. If you change the schema, run the suite on
  PostgreSQL too and add an Alembic migration (`server/migrations/versions/`).

## Style

- **Python:** `ruff` (line length 100). Format only the files you touched; do not reformat unrelated code.
- **TypeScript/React:** ESLint and Prettier (`npm run lint`, `npm run format`). Keep the web app's look:
  the four themes work by remapping Tailwind colours to CSS variables, so avoid hard-coded colours.
- **Kotlin (Android):** the app builds its views in code (no XML layouts, no Compose, no Material). Reuse
  the building blocks in `Ui.kt`, `Kit.kt` and `Sheet.kt` (button, field, list row, sheet, page) instead
  of using stock widgets or `AlertDialog`: the whole app is meant to look the same in all four themes.
- **C++:** keep it small and boring; the engine has no authentication and must stay internal-only.
- **Comments** explain *why*, not what. **Docs** are part of the change: if behaviour or an endpoint
  changes, update `docs/api.md` and the relevant guide.

## Commits and pull requests

- Small, focused pull requests are reviewed faster than big ones.
- Commit messages are short and say what changed and why; the prefixes `feat:`, `fix:`, `docs:`,
  `chore:`, `ci:` and `test:` are used but not enforced.
- Describe what you changed, how you tested it, and anything you could not test (an Android change you
  only ran on an emulator, say). The pull request template has a checklist.
- Do not add new dependencies, services or build tools without discussing them in an issue first.
- AI-assisted contributions are welcome under the same rules: you are responsible for what you submit,
  and it must pass the tests and follow the rules above.

## Good places to start

[`docs/guide.md`](docs/guide.md#16-known-gaps-and-what-to-build-next) lists the known gaps. Some that
suit a first contribution: tablet layout for the Android app, a fast-scroll date handle for the Photos
grid, more server-side tests for edge cases in the sync snapshot, translations, documentation fixes and
packaging for other Linux distributions.

## Licence

By contributing you agree that your contribution is released under the project's [MIT licence](LICENSE).

## For maintainers: how the repository is protected

- **`main`** cannot be deleted or force-pushed (nobody can bypass this). Changes need a pull request with
  one approving review from a code owner (`.github/CODEOWNERS`), resolved review threads, and all six CI
  jobs passing on an up-to-date branch. Repository admins can bypass the review and CI rule for an
  emergency fix.
- **Release tags** (`v*`) cannot be moved, changed or deleted, so a published version stays what it was.
- **Actions:** the default token is read-only, and workflows from first-time outside contributors need a
  maintainer's approval before they run.
- **GitHub security features:** secret scanning with push protection, Dependabot alerts and security
  updates, and private vulnerability reporting are on (see [`SECURITY.md`](SECURITY.md)).
- Dependency bump pull requests arrive monthly and grouped (`.github/dependabot.yml`); major upgrades are
  done by hand.

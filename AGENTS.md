# Guidance for AI coding agents (and humans in a hurry)

Choud is a self-hosted Google Drive alternative: a Python/FastAPI backend, a C++ storage engine, a React
web app, a Kotlin Android app and a Python desktop client, run with Docker Compose behind Caddy. Read
[`docs/guide.md`](docs/guide.md) first (the whole system in one document), then
[`docs/architecture.md`](docs/architecture.md) (the rules). [`docs/roadmap.md`](docs/roadmap.md) holds
the history and the reasons behind decisions. [`CONTRIBUTING.md`](CONTRIBUTING.md) has the full set-up.

## Rules that are not negotiable

1. Never silently destroy data. Unsure: keep it, return an error, log it.
2. Do not over-engineer. No dependency or abstraction without a concrete reason; no Kubernetes,
   microservices or "distributed anything".
3. Keep the separation: Python owns the API, auth, metadata and business logic; C++ owns storage, hashing,
   chunks and the data plane; React owns the web UI; the Android app and desktop client own their platforms.
4. The C++ HTTP API stays small, has no authentication and is never published outside the Docker network.
5. Test failure cases (corrupt or missing object, interrupted upload, bad token, someone else's file,
   conflicting edit), not only the happy path.
6. Never commit secrets. `.env` is ignored; only `.env.example` and the placeholder `.env.dev` are tracked.

## Verify your work with the real checks

```bash
cd server && ruff check app tests && pytest                  # in-memory SQLite + a fake engine
cd web && npm run lint && npm run build && npm run test     # `build` type-checks; do not skip it
cmake -S engine -B engine/build && cmake --build engine/build -j && ctest --test-dir engine/build
cd client && pytest
cd android && ./gradlew testDebugUnitTest assembleDebug
```

Run the server tests on PostgreSQL too (`TEST_DATABASE_URL=postgresql+psycopg2://...`) when you touch the
schema, a foreign key or a delete: SQLite does not enforce foreign keys.

## Things that look fine but are not

- A server module that imports `get_storage_service` by name must also be patched in
  `server/tests/conftest.py`, or its tests silently use the real service.
- Android views are built in code with the kit in `Ui.kt`, `Kit.kt` and `Sheet.kt`. Do not introduce stock
  `Button`, `AlertDialog`, `Toast`, `MediaController` or XML layouts; the app must look the same in all four
  themes.
- Tokens: access, refresh and media tokens are different types on purpose; the media token only opens
  the read-only preview routes.
- The public door (`:8081`) serves only `/s/*`. Anything that adds a route outside `/s/` must not be
  reachable there.
- Generated logos and icons come from `choud-brand-assets/brand-sheet.png` via
  `python scripts/brand/from_sheet.py`; do not edit the generated files by hand.
- Format only the files you changed (`ruff format file.py`); do not reformat the repository.

## Style of work

Small, focused changes with tests; update `docs/api.md` when an endpoint changes; explain *why* in
comments, not *what*; report honestly what you could not test.

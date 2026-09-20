# Engine

The C++20 data-plane engine: object storage, hashing, deduplication, chunk
processing, and synchronization primitives. See
[`../docs/architecture.md`](../docs/architecture.md) and
[`../docs/storage.md`](../docs/storage.md) for the full design.

It exposes a small, local-only HTTP API (never reachable from outside the
Docker network) that the Python backend calls. Phase 1 implements only:

```
GET /health
```

Later phases add `/objects/*`, `/hash`, and `/chunks/*` (see
[`../docs/architecture.md#19-c-engine-api`](../docs/architecture.md)).

## Building

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel
```

Requires a C++20 compiler, CMake ≥ 3.20, Boost (Asio/Beast headers), and
GoogleTest.

## Testing

```bash
ctest --test-dir build --output-on-failure
```

or, from the repository root:

```bash
make engine-test
```

## Running

```bash
ENGINE_HOST=0.0.0.0 ENGINE_PORT=9000 ./build/personal_cloud_engine
```

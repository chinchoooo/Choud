# Synchronization

> **Status:** not yet implemented. This documents the design for Phase 7
> (Desktop Sync) and Phase 8 (Offline + Conflicts). See
> [`architecture.md`](architecture.md#development-phases).

## Desktop client architecture

The desktop client (`client/`) is a separate program from the server. It
owns local filesystem synchronization only — see
[`architecture.md`](architecture.md#implementation-rules), Rule 3.

```text
Local Files
    |
    v
Filesystem Watcher
    |
    v
Local SQLite
    |
    v
Sync Queue
    |
    v
Server API
```

For each tracked file the client keeps:

```text
local_path
file_id
content_hash
server_version
local_modified_time
sync_status
```

## Sync algorithm

When a local file changes:

1. Detect the filesystem event.
2. Wait until the file is no longer being written (debounce).
3. Hash it.
4. Compare against local metadata.
5. Query/reconcile against server metadata.
6. Classify the change: local-only, server-only, or both.
7. Upload or download accordingly.
8. Update local state.

## 22. Offline Mode

The client must keep working when the server is unreachable:

```text
Server unavailable

User edits ~/MyCloud/research/paper.pdf

Client:
- detects the change
- hashes the file
- stores a pending operation
- marks it as queued
```

On reconnection: `connect -> reconcile -> upload pending changes`. The
queue must survive application restarts — it belongs in the client's
local SQLite database, not in memory.

## 23. Conflict Detection

Never silently overwrite a changed file. If both the server and a local
copy started from the same version and were independently modified:

```text
Server: version 10 -> version 11 (edited on another device)
Local:  version 10 -> version 11 (edited offline)
```

that's a conflict. The first-version response is a conflict copy:

```text
report.conflict-2026-09-24.pdf
```

CRDTs, operational transformation, and automatic document merging are
explicitly out of scope for this phase — see
[`architecture.md`](architecture.md#explicit-non-goals). They're future
research directions, not MVP requirements.

## Data-plane responsibilities

The C++ engine's `sync/` module (`sync_engine.hpp`, `sync_queue.hpp`,
`conflict_detector.hpp`) implements the primitives the desktop client's
reconciliation loop calls into — queue durability and conflict
classification — while the client itself owns the filesystem watcher and
local SQLite state. Keep the C++ surface small, per
[`architecture.md`](architecture.md#implementation-rules), Rule 4.

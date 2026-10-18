#pragma once

// Making sure bytes are really on disk before we say they are stored, plus a
// fault-injection hook so tests can "pull the plug" at chosen moments.
//
// Why this exists: rename() makes a file appear under its final name
// atomically, but the file's *contents* and the directory entry itself can
// still be only in memory. After a power cut the final name may then exist
// pointing at an empty or truncated file, which a content-addressed store must
// never allow (the name is the checksum). The cure is the classic sequence:
// fsync the file, rename it into place, fsync the directory that holds it.

#include <filesystem>
#include <functional>
#include <string>

namespace engine::util {

// Flushes a file's data and metadata to stable storage. Throws
// std::runtime_error if the file cannot be opened or the flush fails
// (including "no space left on device", which is how some filesystems report
// a write that was only accepted into the cache).
void fsync_file(const std::filesystem::path& path);

// Flushes a directory's entries (a new name or a rename) to stable storage.
void fsync_dir(const std::filesystem::path& path);

// A name that is unique to this process, thread and call, for temp files, so
// two concurrent writers of the same object never share a temp path.
std::string unique_suffix();

// Called at named points inside storage operations ("put:before-rename" ...).
// Does nothing in production. For tests:
//   - set_fault_handler() installs a function that may throw or abort, or
//   - the environment variable ENGINE_FAULT_AT=<point> makes the process
//     exit immediately (like a power cut: no destructors, no cleanup).
void fault_point(const char* point);
void set_fault_handler(std::function<void(const char*)> handler);

}  // namespace engine::util

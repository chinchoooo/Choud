#pragma once

// Keeps every file path the engine is handed inside the storage root.
//
// The backend passes the engine file PATHS (it shares the storage volume), so a
// bug or a compromised backend could otherwise ask it to read, move or
// overwrite any file the engine process can reach. This confines requests to
// the storage root, resolves "..", "." and symlinks before checking, and keeps
// the stored objects themselves off limits for anything that moves or
// overwrites files.

#include <filesystem>
#include <stdexcept>
#include <string>

namespace engine::util {

class PathError : public std::runtime_error {
   public:
    using std::runtime_error::runtime_error;
};

// Returns the resolved absolute path of `candidate`.
// Throws PathError unless it is absolute, lies under `root`, and (when
// `allow_objects` is false) is not inside `root`/objects.
std::filesystem::path confine(const std::filesystem::path& root, const std::string& candidate,
                              bool allow_objects);

}  // namespace engine::util

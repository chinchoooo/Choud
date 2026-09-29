#pragma once

// Coordinates ObjectStore + hashing and exposes the operations the
// /objects/* and /hash HTTP endpoints call, keeping engine_server.cpp's
// route handling thin.
//
// Reference counting for dedup lives in PostgreSQL, not here — the
// `files.content_hash` / `file_versions.content_hash` columns ARE the
// reference count (docs/storage.md#deduplication); this engine has no
// visibility into those rows. `remove_object()` here is an unconditional
// physical delete — the Python backend is responsible for confirming
// nothing references a hash before calling it. Automatic garbage
// collection (finding and removing unreferenced objects) is explicitly
// out of scope until a later phase — don't build it prematurely.

#include <cstdint>
#include <filesystem>
#include <string>

#include "storage/object_store.hpp"

namespace engine::storage {

class StorageManager {
   public:
    explicit StorageManager(std::filesystem::path storage_root);

    bool object_exists(const std::string& hash) const;
    void store_object(const std::string& hash, const std::filesystem::path& source);
    void retrieve_object(const std::string& hash, const std::filesystem::path& destination) const;
    void remove_object(const std::string& hash);
    std::uint64_t object_size(const std::string& hash) const;

    // Hashes a file already on the shared storage volume (see
    // docs/architecture.md#9-hashing) — streaming, bounded memory.
    std::string hash_file(const std::filesystem::path& path) const;

   private:
    ObjectStore store_;
};

}  // namespace engine::storage

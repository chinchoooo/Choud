#pragma once

// Tracks received chunks per upload, verifies and finalizes completed
// uploads into the object store, and cleans up abandoned ones.
// See docs/architecture.md#10-chunked-uploads and #11-chunk-storage.

#include <cstdint>
#include <filesystem>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

#include "chunks/chunk_store.hpp"
#include "storage/storage_manager.hpp"

namespace engine::chunks {

// A `finalize()` call was asked to reconstruct more chunks than are
// actually on disk (0..total_chunks-1 must all be present). Surfaced
// rather than silently reconstructing a truncated file (Rule 5).
class MissingChunkError : public std::runtime_error {
   public:
    using std::runtime_error::runtime_error;
};

// The reconstructed file's SHA-256 doesn't match what the client claimed
// when it created the upload session. The object is never stored in this
// case (Rule 5: never silently store/serve corrupt data).
class HashMismatchError : public std::runtime_error {
   public:
    using std::runtime_error::runtime_error;
};

class ChunkManager {
   public:
    // `storage_manager` must outlive this ChunkManager — finalize() hands
    // the reconstructed file to it via `store_object` (a put()-shaped
    // operation: ChunkManager builds the final bytes, StorageManager owns
    // getting them into objects/, same division of responsibility as
    // everywhere else object storage is touched).
    ChunkManager(std::filesystem::path storage_root, engine::storage::StorageManager& storage_manager);

    void write(const std::string& upload_id, int index, const std::filesystem::path& source);

    std::vector<int> received_indices(const std::string& upload_id) const;

    struct FinalizeResult {
        std::string hash;
        std::uint64_t size;
    };

    // Verifies chunks 0..total_chunks-1 are all present, streams them
    // (bounded memory — never buffers the whole file) into a
    // reconstructed temp file while hashing incrementally, optionally
    // verifies the result against `expected_hash`, stores it in the
    // object store, and deletes the upload's temp chunk directory.
    //
    // Throws MissingChunkError if any expected chunk is absent, or
    // HashMismatchError if `expected_hash` is given and doesn't match —
    // in both cases nothing is stored and the temp chunks are left in
    // place (a client can still retry: resend the missing chunk, or
    // re-finalize).
    FinalizeResult finalize(const std::string& upload_id, int total_chunks,
                             const std::optional<std::string>& expected_hash);

    // Deletes an upload's temp chunk directory without finalizing it —
    // used for an explicit client abort and for the abandoned/expired
    // sweep (docs/storage.md#chunked-uploads). A no-op if nothing was
    // ever written for `upload_id`. Returns whether anything was removed.
    bool abandon(const std::string& upload_id);

   private:
    ChunkStore chunk_store_;
    engine::storage::StorageManager& storage_manager_;
};

}  // namespace engine::chunks

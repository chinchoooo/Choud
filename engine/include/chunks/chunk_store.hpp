#pragma once

// Temporary on-disk storage for in-progress chunked uploads, separate from
// the final object store. See docs/architecture.md#11-chunk-storage.
//
// Chunks live at ${root}/uploads/<upload-id>/NNNNNN (six-digit zero-padded
// index), mirroring the ${root}/objects/<prefix>/<hash> layout of
// engine::storage::ObjectStore — this class is the chunk-storage analogue
// of that one, deliberately kept just as small.

#include <cstdint>
#include <filesystem>
#include <stdexcept>
#include <string>
#include <vector>

namespace engine::chunks {

// `upload_id` is server-generated (the Python backend creates it as a
// UUID hex string), but this class validates its shape anyway (letters,
// digits, and hyphens only, up to 64 characters) before building a
// filesystem path from it — the same defense-in-depth as ObjectStore's
// hash validation (docs/security.md#filesystem-safety): never trust an
// identifier used to build a path, even one that "should" already be
// safe.
class InvalidUploadIdError : public std::runtime_error {
   public:
    using std::runtime_error::runtime_error;
};

class ChunkStore {
   public:
    explicit ChunkStore(std::filesystem::path root);

    // Adds `source`'s bytes as chunk `index` of `upload_id`. Takes
    // ownership of `source` (moves it in, falling back to copy+remove
    // across filesystems), same contract as ObjectStore::put. Overwrites
    // any existing chunk at that index — a client is free to resend a
    // chunk it's unsure arrived; the write is atomic either way (temp
    // file + rename), so a crash mid-write never leaves a partial chunk
    // under its final name.
    void write_chunk(const std::string& upload_id, int index,
                      const std::filesystem::path& source);

    bool has_chunk(const std::string& upload_id, int index) const;

    // Sorted list of chunk indices currently on disk for `upload_id` —
    // what a resuming client still needs to send is total_chunks minus
    // this set. Empty (not an error) if the upload has no directory yet.
    std::vector<int> chunk_indices(const std::string& upload_id) const;

    std::filesystem::path chunk_path(const std::string& upload_id, int index) const;
    std::filesystem::path upload_dir(const std::string& upload_id) const;

    // Recursively removes `upload_id`'s temp directory. A no-op (not an
    // error) if it doesn't exist — used both after a successful finalize
    // and to clean up an abandoned/expired upload. Returns whether the
    // directory existed (and was removed).
    bool remove_upload(const std::string& upload_id);

   private:
    std::filesystem::path root_;
};

}  // namespace engine::chunks

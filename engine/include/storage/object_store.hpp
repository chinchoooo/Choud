#pragma once

// Content-addressable object storage: exists/put/get/remove/size, keyed by
// SHA-256 hash. See docs/architecture.md#7-content-addressable-storage.

#include <cstdint>
#include <filesystem>
#include <stdexcept>
#include <string>

namespace engine::storage {

class ObjectNotFoundError : public std::runtime_error {
   public:
    using std::runtime_error::runtime_error;
};

// The bytes on disk no longer hash to the name they're stored under —
// bit rot, a truncated write, or manual tampering. Surfaced rather than
// silently returned (Rule 5: never silently destroy/corrupt data).
class ObjectCorruptedError : public std::runtime_error {
   public:
    using std::runtime_error::runtime_error;
};

class InvalidHashError : public std::runtime_error {
   public:
    using std::runtime_error::runtime_error;
};

// Files are addressed by their SHA-256 content hash and sharded under a
// two-character prefix directory so no single directory accumulates an
// unbounded number of entries (docs/architecture.md#7-content-addressable-storage):
//
//   ${root}/objects/a9/a94f2c8c...
class ObjectStore {
   public:
    explicit ObjectStore(std::filesystem::path root);

    bool exists(const std::string& hash) const;

    // Adds `source`'s bytes to the store under `hash`.
    //
    // With `verify` (the default) the bytes are hashed first and a mismatch
    // throws ObjectCorruptedError with the source left untouched: a name in
    // objects/ is its content's checksum, so a wrong claim is refused rather
    // than stored. Callers that have JUST computed the hash from these exact
    // bytes (chunk finalize) pass verify=false to avoid reading them twice.
    //
    // Durable: the data is flushed to disk before the final name appears, and
    // the directory entry is flushed after, so a power cut leaves either no
    // object or a complete one, never a named file with missing contents.
    //
    // Idempotent: if an object already exists under `hash`, this is a
    // no-op: that is what makes deduplication free
    // (docs/storage.md#deduplication). Safe to call concurrently, including
    // for the same hash (each call writes its own temp file).
    //
    // Takes ownership of `source` (moves it into the store when possible,
    // falling back to copy+remove across filesystems) on success. Callers
    // should treat `source` as consumed after a successful return, whether
    // or not the object already existed; after an exception it is left alone
    // (except for a rename that already happened).
    void put(const std::string& hash, const std::filesystem::path& source, bool verify = true);

    // Copies the stored object for `hash` to `destination`.
    // Throws ObjectNotFoundError if `hash` isn't stored, ObjectCorruptedError
    // if the bytes on disk no longer match `hash`.
    void get(const std::string& hash, const std::filesystem::path& destination) const;

    // Removes the object for `hash`. A no-op (not an error) if it doesn't
    // exist — this call doesn't know or care whether anything still
    // references the hash; that's the caller's responsibility (see
    // docs/storage.md#deduplication) until real reference-counted garbage
    // collection lands in a later phase.
    void remove(const std::string& hash);

    // Throws ObjectNotFoundError if `hash` isn't stored.
    std::uint64_t size(const std::string& hash) const;

    std::filesystem::path path_for(const std::string& hash) const;

   private:
    std::filesystem::path root_;
};

}  // namespace engine::storage

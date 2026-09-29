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

    // Adds `source`'s bytes to the store under `hash`. The caller is
    // responsible for `hash` actually being the SHA-256 of `source`'s
    // contents (see engine::hashing) — put() trusts it rather than
    // re-hashing on every call, but validates its shape (64 lowercase hex
    // characters) so an obviously wrong caller fails loudly, not silently.
    //
    // Idempotent: if an object already exists under `hash`, this is a
    // no-op — that's what makes deduplication free
    // (docs/storage.md#deduplication): two uploads with the same content
    // hash never store the bytes twice.
    //
    // Takes ownership of `source` (moves it into the store when possible,
    // falling back to copy+remove across filesystems) — callers should
    // treat `source` as consumed after this returns, whether or not the
    // object already existed.
    void put(const std::string& hash, const std::filesystem::path& source);

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

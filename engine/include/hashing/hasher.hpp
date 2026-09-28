#pragma once

// Streaming SHA-256 hashing (must not load multi-gigabyte files into
// memory). See docs/architecture.md#9-hashing.

#include <cstdint>
#include <filesystem>
#include <string>

namespace engine::hashing {

// Bounded read buffer size for streaming a file into the hasher. Never
// grow this to "just read the whole file" — the point is a file many
// times larger than RAM must still hash in constant memory.
inline constexpr std::size_t kStreamBufferSize = 64 * 1024;

// Incremental SHA-256 hasher. Feed it bytes via `update()` as they become
// available (from a socket, a chunk upload, ...), then call `hex_digest()`
// once at the end. Wraps OpenSSL's EVP API — never hand-roll the
// algorithm itself (Rule: don't rewrite mature crypto primitives).
class Sha256Stream {
   public:
    Sha256Stream();
    ~Sha256Stream();

    Sha256Stream(const Sha256Stream&) = delete;
    Sha256Stream& operator=(const Sha256Stream&) = delete;

    void update(const unsigned char* data, std::size_t length);

    // Finalizes the hash and returns it as 64 lowercase hex characters.
    // Only valid to call once — the underlying context is consumed.
    std::string hex_digest();

   private:
    struct Impl;
    Impl* impl_;
};

// Convenience wrapper: hash a file on disk in bounded 64KB chunks.
// Throws std::runtime_error if the file can't be opened.
std::string hash_file(const std::filesystem::path& path);

// Convenience wrapper: hash an in-memory buffer directly.
std::string hash_bytes(const unsigned char* data, std::size_t length);

}  // namespace engine::hashing

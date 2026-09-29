#pragma once

// Metadata describing a stored, content-addressed object (hash, size,
// reference count for deduplication).

#include <cstdint>
#include <string>

namespace engine::storage {

struct ObjectMetadata {
    std::string hash;
    std::uint64_t size = 0;
    std::uint64_t ref_count = 0;
};

}  // namespace engine::storage

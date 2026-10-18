#include "chunks/chunk_manager.hpp"

#include <algorithm>
#include <array>
#include <fstream>

#include "hashing/hasher.hpp"
#include "util/durability.hpp"

namespace engine::chunks {

ChunkManager::ChunkManager(std::filesystem::path storage_root,
                            engine::storage::StorageManager& storage_manager)
    : chunk_store_(std::move(storage_root)), storage_manager_(storage_manager) {}

void ChunkManager::write(const std::string& upload_id, int index,
                          const std::filesystem::path& source) {
    chunk_store_.write_chunk(upload_id, index, source);
}

std::vector<int> ChunkManager::received_indices(const std::string& upload_id) const {
    return chunk_store_.chunk_indices(upload_id);
}

ChunkManager::FinalizeResult ChunkManager::finalize(
    const std::string& upload_id, int total_chunks,
    const std::optional<std::string>& expected_hash) {
    if (total_chunks <= 0) {
        throw std::invalid_argument("total_chunks must be positive: " +
                                     std::to_string(total_chunks));
    }

    for (int i = 0; i < total_chunks; ++i) {
        if (!chunk_store_.has_chunk(upload_id, i)) {
            throw MissingChunkError("missing chunk " + std::to_string(i) + " of " +
                                     std::to_string(total_chunks) + " for upload " + upload_id);
        }
    }

    const auto reconstructed_path = chunk_store_.upload_dir(upload_id) / "reconstructed.tmp";
    std::filesystem::create_directories(reconstructed_path.parent_path());

    engine::hashing::Sha256Stream hasher;
    std::uint64_t total_size = 0;
    {
        std::ofstream out(reconstructed_path, std::ios::binary | std::ios::trunc);
        if (!out) {
            throw std::runtime_error("could not open reconstruction file for upload " +
                                      upload_id);
        }

        std::array<char, engine::hashing::kStreamBufferSize> buffer{};
        for (int i = 0; i < total_chunks; ++i) {
            std::ifstream in(chunk_store_.chunk_path(upload_id, i), std::ios::binary);
            if (!in) {
                throw std::runtime_error("could not open chunk " + std::to_string(i) +
                                          " for upload " + upload_id);
            }
            while (in.read(buffer.data(), static_cast<std::streamsize>(buffer.size())) ||
                   in.gcount() > 0) {
                const auto read = static_cast<std::size_t>(in.gcount());
                hasher.update(reinterpret_cast<const unsigned char*>(buffer.data()), read);
                out.write(buffer.data(), static_cast<std::streamsize>(read));
                total_size += read;
            }
        }
    }  // `out` closed here, before the reconstructed file is moved/removed below

    // The reconstructed bytes must be durable before they are given a name.
    engine::util::fsync_file(reconstructed_path);

    const auto computed_hash = hasher.hex_digest();

    if (expected_hash.has_value() && *expected_hash != computed_hash) {
        std::filesystem::remove(reconstructed_path);
        throw HashMismatchError("reconstructed content does not match the expected hash for "
                                 "upload " +
                                 upload_id + " (expected " + *expected_hash + ", got " +
                                 computed_hash + ")");
    }

    // store_object() takes ownership of reconstructed_path (moves it into
    // objects/, or discards it if that hash is already stored — dedup
    // applies to chunked uploads too).
    // The hash was just computed from exactly these bytes, so the store need not
    // read them a second time to verify it.
    storage_manager_.store_object(computed_hash, reconstructed_path, /*verify=*/false);

    chunk_store_.remove_upload(upload_id);

    return FinalizeResult{computed_hash, total_size};
}

bool ChunkManager::abandon(const std::string& upload_id) {
    return chunk_store_.remove_upload(upload_id);
}

}  // namespace engine::chunks

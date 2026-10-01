#include "chunks/chunk_store.hpp"

#include <algorithm>
#include <cctype>
#include <iomanip>
#include <sstream>
#include <system_error>

namespace engine::chunks {

namespace {

bool is_valid_upload_id(const std::string& upload_id) {
    if (upload_id.empty() || upload_id.size() > 64) {
        return false;
    }
    // Python generates these with uuid.uuid4().hex (32 lowercase hex
    // chars) — accept alphanumerics and hyphens only, which also rules
    // out "..", "/", and anything else that could escape the uploads/
    // directory.
    return std::all_of(upload_id.begin(), upload_id.end(), [](unsigned char c) {
        return std::isalnum(c) || c == '-';
    });
}

std::string zero_padded_index(int index) {
    std::ostringstream out;
    out << std::setw(6) << std::setfill('0') << index;
    return out.str();
}

}  // namespace

ChunkStore::ChunkStore(std::filesystem::path root) : root_(std::move(root)) {
    std::filesystem::create_directories(root_ / "uploads");
}

std::filesystem::path ChunkStore::upload_dir(const std::string& upload_id) const {
    if (!is_valid_upload_id(upload_id)) {
        throw InvalidUploadIdError("not a valid upload id: " + upload_id);
    }
    return root_ / "uploads" / upload_id;
}

std::filesystem::path ChunkStore::chunk_path(const std::string& upload_id, int index) const {
    if (index < 0) {
        throw std::invalid_argument("chunk index must not be negative: " + std::to_string(index));
    }
    return upload_dir(upload_id) / zero_padded_index(index);
}

void ChunkStore::write_chunk(const std::string& upload_id, int index,
                              const std::filesystem::path& source) {
    const auto target = chunk_path(upload_id, index);  // validates upload_id/index first

    if (!std::filesystem::is_regular_file(source)) {
        throw std::runtime_error("chunk source does not exist: " + source.string());
    }

    std::filesystem::create_directories(target.parent_path());

    // Same atomic temp-file + rename pattern as ObjectStore::put (Rule 5:
    // never leave a partial chunk under its final name).
    const auto tmp_target = target.parent_path() / (std::to_string(index) + ".tmp");

    std::error_code rename_ec;
    std::filesystem::rename(source, tmp_target, rename_ec);
    if (rename_ec) {
        std::error_code copy_ec;
        std::filesystem::copy_file(
            source, tmp_target, std::filesystem::copy_options::overwrite_existing, copy_ec);
        if (copy_ec) {
            throw std::runtime_error("failed to store chunk " + std::to_string(index) + " for " +
                                      upload_id + ": " + copy_ec.message());
        }
        std::filesystem::remove(source);
    }

    std::error_code final_rename_ec;
    std::filesystem::rename(tmp_target, target,
                             final_rename_ec);  // overwrite: rename() replaces an existing target
    if (final_rename_ec) {
        std::filesystem::remove(tmp_target);
        throw std::runtime_error("failed to finalize chunk " + std::to_string(index) + " for " +
                                  upload_id + ": " + final_rename_ec.message());
    }
}

bool ChunkStore::has_chunk(const std::string& upload_id, int index) const {
    return std::filesystem::is_regular_file(chunk_path(upload_id, index));
}

std::vector<int> ChunkStore::chunk_indices(const std::string& upload_id) const {
    std::vector<int> indices;
    const auto dir = upload_dir(upload_id);
    if (!std::filesystem::is_directory(dir)) {
        return indices;
    }
    for (const auto& entry : std::filesystem::directory_iterator(dir)) {
        if (!entry.is_regular_file()) {
            continue;
        }
        const auto name = entry.path().filename().string();
        // Chunk files are exactly six digits; anything else (e.g. a
        // reconstruction temp file mid-finalize) is not a chunk.
        if (name.size() == 6 &&
            std::all_of(name.begin(), name.end(), [](unsigned char c) { return std::isdigit(c); })) {
            indices.push_back(std::stoi(name));
        }
    }
    std::sort(indices.begin(), indices.end());
    return indices;
}

bool ChunkStore::remove_upload(const std::string& upload_id) {
    const auto dir = upload_dir(upload_id);
    const bool existed = std::filesystem::is_directory(dir);
    std::error_code ec;
    std::filesystem::remove_all(dir, ec);
    // Deliberately ignore `ec`: a missing directory is not an error here
    // (abandon/cleanup calls this defensively even when nothing was ever
    // written).
    return existed;
}

}  // namespace engine::chunks

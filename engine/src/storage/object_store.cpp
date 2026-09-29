#include "storage/object_store.hpp"

#include <algorithm>
#include <cctype>
#include <system_error>

#include "hashing/hasher.hpp"

namespace engine::storage {

namespace {

bool is_valid_hash(const std::string& hash) {
    if (hash.size() != 64) {
        return false;
    }
    return std::all_of(hash.begin(), hash.end(), [](unsigned char c) {
        return std::isxdigit(c) && (std::isdigit(c) || std::islower(c));
    });
}

}  // namespace

ObjectStore::ObjectStore(std::filesystem::path root) : root_(std::move(root)) {
    std::filesystem::create_directories(root_ / "objects");
}

std::filesystem::path ObjectStore::path_for(const std::string& hash) const {
    if (!is_valid_hash(hash)) {
        throw InvalidHashError("not a valid SHA-256 hash: " + hash);
    }
    return root_ / "objects" / hash.substr(0, 2) / hash;
}

bool ObjectStore::exists(const std::string& hash) const {
    return std::filesystem::is_regular_file(path_for(hash));
}

void ObjectStore::put(const std::string& hash, const std::filesystem::path& source) {
    const auto target = path_for(hash);  // validates hash shape first

    if (!std::filesystem::is_regular_file(source)) {
        throw std::runtime_error("put source does not exist: " + source.string());
    }

    if (exists(hash)) {
        // Already stored under this hash — dedup means we don't need a
        // second copy. Still consume the source, per this method's
        // documented ownership contract.
        std::filesystem::remove(source);
        return;
    }

    std::filesystem::create_directories(target.parent_path());

    // Write to a sibling temp path first, then atomically rename into
    // place, so a crash mid-copy can never leave a partial object under
    // its final name (Rule 5: never silently corrupt data).
    const auto tmp_target = target.parent_path() / (hash + ".tmp");

    std::error_code rename_ec;
    std::filesystem::rename(source, tmp_target, rename_ec);
    if (rename_ec) {
        // Cross-filesystem (EXDEV) or similar — fall back to copy+remove.
        std::error_code copy_ec;
        std::filesystem::copy_file(
            source, tmp_target, std::filesystem::copy_options::overwrite_existing, copy_ec);
        if (copy_ec) {
            throw std::runtime_error("failed to store object " + hash + ": " + copy_ec.message());
        }
        std::filesystem::remove(source);
    }

    std::error_code final_rename_ec;
    std::filesystem::rename(tmp_target, target, final_rename_ec);
    if (final_rename_ec) {
        std::filesystem::remove(tmp_target);
        throw std::runtime_error("failed to finalize object " + hash + ": " +
                                  final_rename_ec.message());
    }
}

void ObjectStore::get(const std::string& hash, const std::filesystem::path& destination) const {
    const auto source = path_for(hash);

    if (!std::filesystem::is_regular_file(source)) {
        throw ObjectNotFoundError("no object stored for hash: " + hash);
    }

    if (engine::hashing::hash_file(source) != hash) {
        throw ObjectCorruptedError("stored object does not match its hash: " + hash);
    }

    std::filesystem::create_directories(destination.parent_path());
    std::filesystem::copy_file(
        source, destination, std::filesystem::copy_options::overwrite_existing);
}

void ObjectStore::remove(const std::string& hash) {
    std::filesystem::remove(path_for(hash));
}

std::uint64_t ObjectStore::size(const std::string& hash) const {
    const auto target = path_for(hash);
    if (!std::filesystem::is_regular_file(target)) {
        throw ObjectNotFoundError("no object stored for hash: " + hash);
    }
    return static_cast<std::uint64_t>(std::filesystem::file_size(target));
}

}  // namespace engine::storage

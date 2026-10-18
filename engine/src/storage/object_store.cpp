#include "storage/object_store.hpp"

#include <algorithm>
#include <cctype>
#include <system_error>

#include "hashing/hasher.hpp"
#include "util/durability.hpp"

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

// When a put() fails part-way the temp file must not linger, and the caller's
// source file must not be lost: if the source was MOVED into the temp path it is
// moved back, if it was copied the temp copy is simply removed.
struct TempFileGuard {
    std::filesystem::path path;
    std::filesystem::path restore_to;  // set only when the source was moved, not copied
    bool armed = true;
    ~TempFileGuard() {
        if (!armed) {
            return;
        }
        std::error_code ec;
        if (!restore_to.empty() && std::filesystem::exists(path, ec)) {
            std::filesystem::rename(path, restore_to, ec);
            if (!ec) {
                return;
            }
        }
        std::filesystem::remove(path, ec);
    }
};

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

void ObjectStore::put(const std::string& hash, const std::filesystem::path& source, bool verify) {
    const auto target = path_for(hash);  // validates hash shape first

    if (!std::filesystem::is_regular_file(source)) {
        throw std::runtime_error("put source does not exist: " + source.string());
    }

    if (exists(hash)) {
        // Already stored under this hash: dedup means we do not need a
        // second copy. Still consume the source, per this method's
        // documented ownership contract.
        std::filesystem::remove(source);
        return;
    }

    // A name is its content's checksum, so a wrong claim must never reach
    // objects/. The check happens BEFORE anything is moved, so a refused
    // source is left exactly where the caller put it.
    if (verify && engine::hashing::hash_file(source) != hash) {
        throw ObjectCorruptedError("the bytes do not match the hash they were to be stored under: " +
                                   hash);
    }

    const auto shard = target.parent_path();
    const bool new_shard = !std::filesystem::exists(shard);
    std::filesystem::create_directories(shard);

    // Write to a sibling temp path first, then atomically rename into place,
    // so a crash mid-copy can never leave a partial object under its final
    // name (Rule 5: never silently corrupt data). The name is unique per
    // call, so two writers of the same object never share a temp file.
    const auto tmp_target = shard / (hash + "." + engine::util::unique_suffix() + ".tmp");
    TempFileGuard guard{tmp_target};

    bool copied = false;
    std::error_code rename_ec;
    std::filesystem::rename(source, tmp_target, rename_ec);
    if (rename_ec) {
        // Cross-filesystem (EXDEV) or similar: copy, and remove the source
        // only once the object is safely in place.
        std::error_code copy_ec;
        std::filesystem::copy_file(source, tmp_target,
                                   std::filesystem::copy_options::overwrite_existing, copy_ec);
        if (copy_ec) {
            throw std::runtime_error("failed to store object " + hash + ": " + copy_ec.message());
        }
        copied = true;
    } else {
        guard.restore_to = source;
    }
    engine::util::fault_point("put:after-copy");

    // The data must be on disk BEFORE the final name exists, or a power cut
    // can leave that name pointing at an empty or truncated file.
    engine::util::fsync_file(tmp_target);
    engine::util::fault_point("put:before-rename");

    std::error_code final_rename_ec;
    std::filesystem::rename(tmp_target, target, final_rename_ec);
    if (final_rename_ec) {
        throw std::runtime_error("failed to finalize object " + hash + ": " +
                                 final_rename_ec.message());
    }
    guard.armed = false;
    engine::util::fault_point("put:after-rename");

    // ...and the directory entry itself must be durable too.
    engine::util::fsync_dir(shard);
    if (new_shard) {
        engine::util::fsync_dir(root_ / "objects");
    }

    if (copied) {
        std::error_code remove_ec;
        std::filesystem::remove(source, remove_ec);
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
    // A hard link makes the download copy instant; the caller only reads it and deletes it
    // afterwards, which removes the link and never the object. Falls back to a real copy where
    // links are not possible (another filesystem).
    std::error_code ec;
    std::filesystem::remove(destination, ec);
    std::filesystem::create_hard_link(source, destination, ec);
    if (ec) {
        std::filesystem::copy_file(source, destination,
                                   std::filesystem::copy_options::overwrite_existing);
    }
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

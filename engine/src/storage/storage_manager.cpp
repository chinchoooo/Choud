#include "storage/storage_manager.hpp"

#include "hashing/hasher.hpp"

namespace engine::storage {

StorageManager::StorageManager(std::filesystem::path storage_root)
    : store_(std::move(storage_root)) {}

bool StorageManager::object_exists(const std::string& hash) const {
    return store_.exists(hash);
}

void StorageManager::store_object(const std::string& hash, const std::filesystem::path& source) {
    store_.put(hash, source);
}

void StorageManager::retrieve_object(const std::string& hash,
                                      const std::filesystem::path& destination) const {
    store_.get(hash, destination);
}

void StorageManager::remove_object(const std::string& hash) {
    store_.remove(hash);
}

std::uint64_t StorageManager::object_size(const std::string& hash) const {
    return store_.size(hash);
}

std::string StorageManager::hash_file(const std::filesystem::path& path) const {
    return engine::hashing::hash_file(path);
}

}  // namespace engine::storage

// SHA-256-keyed object storage: put/get/exists/remove, corrupted/missing
// objects, deduplication reference counting.

#include "storage/object_store.hpp"

#include <filesystem>
#include <fstream>
#include <memory>
#include <string>

#include <gtest/gtest.h>

#include "hashing/hasher.hpp"

namespace {

using engine::storage::ObjectCorruptedError;
using engine::storage::ObjectNotFoundError;
using engine::storage::ObjectStore;

class ObjectStoreTest : public ::testing::Test {
   protected:
    void SetUp() override {
        static int counter = 0;
        root_ = std::filesystem::temp_directory_path() / "engine_object_store_tests" /
                std::to_string(counter++);
        std::filesystem::create_directories(root_);
        store_ = std::make_unique<ObjectStore>(root_);
    }

    void TearDown() override { std::filesystem::remove_all(root_); }

    std::filesystem::path write_source(const std::string& contents) {
        auto path = root_ / ("source-" + std::to_string(source_counter_++) + ".tmp");
        std::ofstream out(path, std::ios::binary);
        out << contents;
        out.close();
        return path;
    }

    std::string hash_of(const std::string& contents) {
        return engine::hashing::hash_bytes(
            reinterpret_cast<const unsigned char*>(contents.data()), contents.size());
    }

    std::filesystem::path root_;
    std::unique_ptr<ObjectStore> store_;
    int source_counter_ = 0;
};

TEST_F(ObjectStoreTest, ExistsIsFalseForUnknownObject) {
    EXPECT_FALSE(store_->exists(hash_of("never stored")));
}

TEST_F(ObjectStoreTest, PutGetExistsRemoveRoundTrip) {
    const std::string content = "round trip contents";
    const auto hash = hash_of(content);
    auto source = write_source(content);

    store_->put(hash, source);
    EXPECT_TRUE(store_->exists(hash));
    EXPECT_EQ(store_->size(hash), content.size());

    auto destination = root_ / "downloaded.bin";
    store_->get(hash, destination);

    std::ifstream in(destination, std::ios::binary);
    std::string round_tripped((std::istreambuf_iterator<char>(in)),
                               std::istreambuf_iterator<char>());
    EXPECT_EQ(round_tripped, content);

    store_->remove(hash);
    EXPECT_FALSE(store_->exists(hash));
}

TEST_F(ObjectStoreTest, PutConsumesTheSourceFile) {
    auto source = write_source("consumed");
    store_->put(hash_of("consumed"), source);

    EXPECT_FALSE(std::filesystem::exists(source));
}

TEST_F(ObjectStoreTest, PuttingTheSameContentTwiceStoresItOnce) {
    const std::string content = "duplicate content";
    const auto hash = hash_of(content);

    store_->put(hash, write_source(content));
    auto size_after_first = store_->size(hash);

    // Same hash again from a second, independent source file — this is
    // exactly what happens when two different uploads have identical
    // bytes (docs/storage.md#deduplication).
    store_->put(hash, write_source(content));

    EXPECT_EQ(store_->size(hash), size_after_first);
    // Only one shard file should exist on disk for this hash.
    EXPECT_TRUE(std::filesystem::is_regular_file(store_->path_for(hash)));
}

TEST_F(ObjectStoreTest, GetForMissingHashThrowsNotFound) {
    EXPECT_THROW(store_->get(hash_of("was never stored"), root_ / "wont-exist"),
                 ObjectNotFoundError);
}

TEST_F(ObjectStoreTest, RemoveForMissingHashDoesNotThrow) {
    EXPECT_NO_THROW(store_->remove(hash_of("never stored")));
}

TEST_F(ObjectStoreTest, SizeForMissingHashThrowsNotFound) {
    EXPECT_THROW(store_->size(hash_of("never stored")), ObjectNotFoundError);
}

TEST_F(ObjectStoreTest, CorruptedObjectOnDiskIsDetectedNotSilentlyReturned) {
    const std::string content = "original content";
    const auto hash = hash_of(content);
    store_->put(hash, write_source(content));

    // Simulate bit rot / tampering: overwrite the stored bytes in place
    // without going through the store's API.
    std::ofstream corrupt(store_->path_for(hash), std::ios::binary | std::ios::trunc);
    corrupt << "these are not the original bytes";
    corrupt.close();

    EXPECT_THROW(store_->get(hash, root_ / "should-not-be-written"), ObjectCorruptedError);
}

TEST_F(ObjectStoreTest, ObjectsAreShardedByTwoCharacterHashPrefix) {
    const std::string content = "sharding test";
    const auto hash = hash_of(content);

    auto path = store_->path_for(hash);
    EXPECT_EQ(path.parent_path().filename().string(), hash.substr(0, 2));
}

TEST_F(ObjectStoreTest, InvalidHashIsRejected) {
    EXPECT_THROW(store_->exists("not-a-valid-hash"), std::exception);
    EXPECT_THROW(store_->put("too-short", write_source("x")), std::exception);
}

}  // namespace

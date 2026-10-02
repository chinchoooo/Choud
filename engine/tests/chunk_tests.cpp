// Chunk write/finalize, resumability after interruption, cleanup of
// abandoned uploads. See docs/architecture.md#10-chunked-uploads.

#include "chunks/chunk_manager.hpp"
#include "chunks/chunk_store.hpp"

#include <algorithm>
#include <filesystem>
#include <fstream>
#include <memory>
#include <string>

#include <gtest/gtest.h>

#include "hashing/hasher.hpp"
#include "storage/storage_manager.hpp"

namespace {

using engine::chunks::ChunkManager;
using engine::chunks::ChunkStore;
using engine::chunks::HashMismatchError;
using engine::chunks::InvalidUploadIdError;
using engine::chunks::MissingChunkError;
using engine::storage::StorageManager;

std::string hash_of(const std::string& contents) {
    return engine::hashing::hash_bytes(reinterpret_cast<const unsigned char*>(contents.data()),
                                        contents.size());
}

class ChunkStoreTest : public ::testing::Test {
   protected:
    void SetUp() override {
        static int counter = 0;
        root_ = std::filesystem::temp_directory_path() / "engine_chunk_store_tests" /
                std::to_string(counter++);
        std::filesystem::create_directories(root_);
        store_ = std::make_unique<ChunkStore>(root_);
    }

    void TearDown() override { std::filesystem::remove_all(root_); }

    std::filesystem::path write_source(const std::string& contents) {
        auto path = root_ / ("source-" + std::to_string(source_counter_++) + ".tmp");
        std::ofstream out(path, std::ios::binary);
        out << contents;
        out.close();
        return path;
    }

    std::filesystem::path root_;
    std::unique_ptr<ChunkStore> store_;
    int source_counter_ = 0;
};

TEST_F(ChunkStoreTest, HasChunkIsFalseBeforeAnyWrite) {
    EXPECT_FALSE(store_->has_chunk("upload-1", 0));
}

TEST_F(ChunkStoreTest, WriteThenHasChunkRoundTrip) {
    store_->write_chunk("upload-1", 0, write_source("chunk zero"));
    EXPECT_TRUE(store_->has_chunk("upload-1", 0));
    EXPECT_FALSE(store_->has_chunk("upload-1", 1));
}

TEST_F(ChunkStoreTest, WriteConsumesTheSourceFile) {
    auto source = write_source("consumed");
    store_->write_chunk("upload-1", 0, source);
    EXPECT_FALSE(std::filesystem::exists(source));
}

TEST_F(ChunkStoreTest, RewritingTheSameIndexOverwritesRatherThanDuplicates) {
    store_->write_chunk("upload-1", 0, write_source("first attempt"));
    store_->write_chunk("upload-1", 0, write_source("second attempt"));

    std::ifstream in(store_->chunk_path("upload-1", 0), std::ios::binary);
    std::string contents((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
    EXPECT_EQ(contents, "second attempt");
}

TEST_F(ChunkStoreTest, ChunkIndicesReflectsWhatWasReceived) {
    store_->write_chunk("upload-1", 2, write_source("c"));
    store_->write_chunk("upload-1", 0, write_source("a"));
    // Index 1 deliberately never sent — out-of-order + a gap.

    EXPECT_EQ(store_->chunk_indices("upload-1"), (std::vector<int>{0, 2}));
}

TEST_F(ChunkStoreTest, ChunkIndicesIsEmptyForAnUnknownUpload) {
    EXPECT_TRUE(store_->chunk_indices("never-started").empty());
}

TEST_F(ChunkStoreTest, RemoveUploadDeletesAllChunksAndReportsWhetherAnythingExisted) {
    store_->write_chunk("upload-1", 0, write_source("a"));
    store_->write_chunk("upload-1", 1, write_source("b"));

    EXPECT_TRUE(store_->remove_upload("upload-1"));
    EXPECT_TRUE(store_->chunk_indices("upload-1").empty());
    EXPECT_FALSE(store_->has_chunk("upload-1", 0));

    // A second removal of the same (now-empty) upload found nothing to do.
    EXPECT_FALSE(store_->remove_upload("upload-1"));
}

TEST_F(ChunkStoreTest, PathTraversalInUploadIdIsRejected) {
    EXPECT_THROW(store_->write_chunk("../../etc", 0, write_source("x")), InvalidUploadIdError);
    EXPECT_THROW(store_->chunk_path("some/slash", 0), InvalidUploadIdError);
}

class ChunkManagerTest : public ::testing::Test {
   protected:
    void SetUp() override {
        static int counter = 0;
        root_ = std::filesystem::temp_directory_path() / "engine_chunk_manager_tests" /
                std::to_string(counter++);
        std::filesystem::create_directories(root_);
        storage_manager_ = std::make_unique<StorageManager>(root_);
        chunk_manager_ = std::make_unique<ChunkManager>(root_, *storage_manager_);
    }

    void TearDown() override { std::filesystem::remove_all(root_); }

    std::filesystem::path write_source(const std::string& contents) {
        auto path = root_ / ("source-" + std::to_string(source_counter_++) + ".tmp");
        std::ofstream out(path, std::ios::binary);
        out << contents;
        out.close();
        return path;
    }

    // Splits `contents` into `chunk_size`-byte pieces and writes them to
    // `chunk_manager_` out of order (reverse), to exercise the same
    // resumability path a real client's retries would.
    int write_chunks_out_of_order(const std::string& upload_id, const std::string& contents,
                                   std::size_t chunk_size) {
        std::vector<std::string> chunks;
        for (std::size_t offset = 0; offset < contents.size(); offset += chunk_size) {
            chunks.push_back(contents.substr(offset, chunk_size));
        }
        for (int i = static_cast<int>(chunks.size()) - 1; i >= 0; --i) {
            chunk_manager_->write(upload_id, i, write_source(chunks[static_cast<std::size_t>(i)]));
        }
        return static_cast<int>(chunks.size());
    }

    std::filesystem::path root_;
    std::unique_ptr<StorageManager> storage_manager_;
    std::unique_ptr<ChunkManager> chunk_manager_;
    int source_counter_ = 0;
};

TEST_F(ChunkManagerTest, FinalizeReconstructsContentAndMatchesTheOriginalHash) {
    const std::string content = "the quick brown fox jumps over the lazy dog, repeatedly, "
                                 "to make sure this spans more than one chunk";
    auto total_chunks = write_chunks_out_of_order("upload-1", content, /*chunk_size=*/10);

    auto result = chunk_manager_->finalize("upload-1", total_chunks, std::nullopt);

    EXPECT_EQ(result.hash, hash_of(content));
    EXPECT_EQ(result.size, content.size());
    EXPECT_TRUE(storage_manager_->object_exists(result.hash));
}

TEST_F(ChunkManagerTest, FinalizeVerifiesAgainstTheExpectedHashWhenGiven) {
    const std::string content = "verified content";
    auto total_chunks = write_chunks_out_of_order("upload-1", content, /*chunk_size=*/5);

    auto result = chunk_manager_->finalize("upload-1", total_chunks, hash_of(content));

    EXPECT_EQ(result.hash, hash_of(content));
}

TEST_F(ChunkManagerTest, FinalizeRejectsAMismatchedExpectedHash) {
    const std::string content = "some content";
    auto total_chunks = write_chunks_out_of_order("upload-1", content, /*chunk_size=*/5);

    EXPECT_THROW(chunk_manager_->finalize("upload-1", total_chunks, hash_of("different content")),
                 HashMismatchError);

    // Nothing should have been stored under either hash.
    EXPECT_FALSE(storage_manager_->object_exists(hash_of(content)));
}

TEST_F(ChunkManagerTest, FinalizeWithAMissingChunkIsRejected) {
    chunk_manager_->write("upload-1", 0, write_source("first half "));
    // Chunk 1 deliberately never sent.
    chunk_manager_->write("upload-1", 2, write_source("third part"));

    EXPECT_THROW(chunk_manager_->finalize("upload-1", 3, std::nullopt), MissingChunkError);
}

TEST_F(ChunkManagerTest, ResumingAfterAPartialUploadOnlyNeedsTheMissingChunks) {
    const std::string content = "resumable upload content that spans several chunks of data";
    std::vector<std::string> chunks;
    const std::size_t chunk_size = 10;
    for (std::size_t offset = 0; offset < content.size(); offset += chunk_size) {
        chunks.push_back(content.substr(offset, chunk_size));
    }
    const int total_chunks = static_cast<int>(chunks.size());
    ASSERT_GT(total_chunks, 2);

    // "Connection drops" after only the first chunk arrives.
    chunk_manager_->write("upload-1", 0, write_source(chunks[0]));

    auto received = chunk_manager_->received_indices("upload-1");
    EXPECT_EQ(received, (std::vector<int>{0}));

    // Client resumes, sending only what's missing.
    for (int i = 1; i < total_chunks; ++i) {
        chunk_manager_->write("upload-1", i, write_source(chunks[static_cast<std::size_t>(i)]));
    }

    auto result = chunk_manager_->finalize("upload-1", total_chunks, std::nullopt);
    EXPECT_EQ(result.hash, hash_of(content));
}

TEST_F(ChunkManagerTest, FinalizeCleansUpTheTempChunkDirectoryOnSuccess) {
    const std::string content = "cleanup check";
    auto total_chunks = write_chunks_out_of_order("upload-1", content, /*chunk_size=*/6);

    chunk_manager_->finalize("upload-1", total_chunks, std::nullopt);

    EXPECT_TRUE(chunk_manager_->received_indices("upload-1").empty());
}

TEST_F(ChunkManagerTest, FinalizeLeavesChunksInPlaceOnFailureSoTheClientCanRetry) {
    chunk_manager_->write("upload-1", 0, write_source("only chunk"));

    EXPECT_THROW(chunk_manager_->finalize("upload-1", 2, std::nullopt), MissingChunkError);

    // The chunk that *was* received is still there — the client only
    // needs to resend chunk 1, not re-upload everything.
    EXPECT_EQ(chunk_manager_->received_indices("upload-1"), (std::vector<int>{0}));
}

TEST_F(ChunkManagerTest, AbandonRemovesTempChunksWithoutStoringAnObject) {
    const std::string content = "abandoned upload";
    write_chunks_out_of_order("upload-1", content, /*chunk_size=*/5);

    EXPECT_TRUE(chunk_manager_->abandon("upload-1"));
    EXPECT_TRUE(chunk_manager_->received_indices("upload-1").empty());
    EXPECT_FALSE(storage_manager_->object_exists(hash_of(content)));
}

TEST_F(ChunkManagerTest, AbandoningAnUnknownUploadIsANoOp) {
    EXPECT_FALSE(chunk_manager_->abandon("never-started"));
}

TEST_F(ChunkManagerTest, DuplicateContentAcrossUploadsIsDeduplicated) {
    const std::string content = "shared content, uploaded twice via chunks";
    auto total_chunks_a = write_chunks_out_of_order("upload-a", content, /*chunk_size=*/8);
    auto result_a = chunk_manager_->finalize("upload-a", total_chunks_a, std::nullopt);

    auto total_chunks_b = write_chunks_out_of_order("upload-b", content, /*chunk_size=*/8);
    auto result_b = chunk_manager_->finalize("upload-b", total_chunks_b, std::nullopt);

    EXPECT_EQ(result_a.hash, result_b.hash);
    EXPECT_EQ(storage_manager_->object_size(result_a.hash), content.size());
}

}  // namespace

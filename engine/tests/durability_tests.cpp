// Crash and failure injection for the object store and the chunk store.
//
// The rule under test: whatever happens in the middle of a write (a power cut, a full
// disk, two writers at once), a name under objects/ either does not exist or is the
// complete, correct object, and the caller's source file is not lost on a failure.
//
// A "power cut" is simulated for real: the test forks, the child dies with _exit() at a
// chosen point (no destructors, no cleanup run), and the parent then inspects what is on
// disk and opens the store afresh, as a restarted engine would.

#include <atomic>
#include <cerrno>
#include <filesystem>
#include <fstream>
#include <memory>
#include <string>
#include <system_error>
#include <thread>
#include <vector>

#include <gtest/gtest.h>

#include "chunks/chunk_manager.hpp"
#include "chunks/chunk_store.hpp"
#include "hashing/hasher.hpp"
#include "storage/object_store.hpp"
#include "storage/storage_manager.hpp"
#include "util/durability.hpp"

#ifndef _WIN32
#include <sys/wait.h>
#include <unistd.h>
#endif

namespace {

using engine::storage::ObjectStore;

class DurabilityTest : public ::testing::Test {
   protected:
    void SetUp() override {
        static int counter = 0;
        root_ = std::filesystem::temp_directory_path() / "engine_crash_tests" /
                (std::to_string(::getpid()) + "-" + std::to_string(counter++));
        std::filesystem::remove_all(root_);
        std::filesystem::create_directories(root_ / "staging");
        engine::util::set_fault_handler(nullptr);
    }
    void TearDown() override {
        engine::util::set_fault_handler(nullptr);
        std::filesystem::remove_all(root_);
    }

    std::filesystem::path source(const std::string& name, const std::string& contents) {
        const auto path = root_ / "staging" / name;
        std::ofstream out(path, std::ios::binary);
        out << contents;
        return path;
    }

    static std::string hash_of(const std::string& contents) {
        return engine::hashing::hash_bytes(
            reinterpret_cast<const unsigned char*>(contents.data()), contents.size());
    }

    // Number of files in objects/ that are not a finished object (stray temp files).
    std::size_t stray_temp_files() const {
        std::size_t count = 0;
        const auto objects = root_ / "objects";
        if (!std::filesystem::exists(objects)) {
            return 0;
        }
        for (const auto& entry : std::filesystem::recursive_directory_iterator(objects)) {
            if (entry.is_regular_file() && entry.path().extension() == ".tmp") {
                ++count;
            }
        }
        return count;
    }

    std::filesystem::path root_;
};

#ifndef _WIN32

// Runs `body` in a child process that dies (like a power cut) when the named fault point is
// reached. Returns true if the child was killed at that point.
template <typename Body>
bool crash_at(const char* point, Body body) {
    const pid_t pid = ::fork();
    if (pid == 0) {
        engine::util::set_fault_handler([point](const char* p) {
            if (std::string(p) == point) {
                ::_exit(137);
            }
        });
        try {
            body();
        } catch (...) {
            ::_exit(2);
        }
        ::_exit(0);
    }
    int status = 0;
    ::waitpid(pid, &status, 0);
    return WIFEXITED(status) && WEXITSTATUS(status) == 137;
}

TEST_F(DurabilityTest, ACrashBeforeTheRenameLeavesNoObjectAndARetrySucceeds) {
    const std::string content = "bytes that were being stored";
    const auto hash = hash_of(content);
    const auto path = source("a.bin", content);

    ASSERT_TRUE(crash_at("put:before-rename", [&] {
        ObjectStore store(root_);
        store.put(hash, path);
    }));

    ObjectStore restarted(root_);
    EXPECT_FALSE(restarted.exists(hash)) << "a half-stored object must not be visible";

    // The upload is simply tried again, from a fresh source, and works.
    restarted.put(hash, source("a2.bin", content));
    EXPECT_TRUE(restarted.exists(hash));
    const auto copy = root_ / "staging" / "restored.bin";
    restarted.get(hash, copy);  // get() re-hashes, so this proves the bytes are intact
    EXPECT_EQ(engine::hashing::hash_file(copy), hash);
}

TEST_F(DurabilityTest, ACrashAfterTheCopyAlsoLeavesNoObject) {
    const std::string content = "another object";
    const auto hash = hash_of(content);
    const auto path = source("b.bin", content);
    ASSERT_TRUE(crash_at("put:after-copy", [&] {
        ObjectStore store(root_);
        store.put(hash, path);
    }));
    EXPECT_FALSE(ObjectStore(root_).exists(hash));
}

TEST_F(DurabilityTest, ACrashAfterTheRenameLeavesTheCompleteObject) {
    const std::string content = "this one made it";
    const auto hash = hash_of(content);
    const auto path = source("c.bin", content);
    ASSERT_TRUE(crash_at("put:after-rename", [&] {
        ObjectStore store(root_);
        store.put(hash, path);
    }));

    ObjectStore restarted(root_);
    ASSERT_TRUE(restarted.exists(hash));
    const auto copy = root_ / "staging" / "check.bin";
    EXPECT_NO_THROW(restarted.get(hash, copy));  // not corrupted: the hash matches
    EXPECT_EQ(restarted.size(hash), content.size());
}

TEST_F(DurabilityTest, ACrashWhileStoringAChunkLeavesNoHalfChunk) {
    const auto path = source("chunk.bin", "chunk bytes");
    ASSERT_TRUE(crash_at("chunk:before-rename", [&] {
        engine::chunks::ChunkStore chunks(root_);
        chunks.write_chunk("upload-1", 0, path);
    }));
    engine::chunks::ChunkStore restarted(root_);
    EXPECT_FALSE(restarted.has_chunk("upload-1", 0));
    EXPECT_TRUE(restarted.chunk_indices("upload-1").empty());
}

#endif  // _WIN32

TEST_F(DurabilityTest, AFailureWhileStoringLeavesNothingBehindAndKeepsTheSource) {
    const std::string content = "the disk filled up";
    const auto hash = hash_of(content);
    const auto path = source("full.bin", content);

    engine::util::set_fault_handler([](const char* p) {
        if (std::string(p) == "put:after-copy") {
            // What a full disk looks like when the flush is attempted.
            throw std::runtime_error("could not flush file to disk: No space left on device");
        }
    });
    ObjectStore store(root_);
    EXPECT_THROW(store.put(hash, path), std::runtime_error);

    EXPECT_FALSE(store.exists(hash));
    EXPECT_EQ(stray_temp_files(), 0u);
    // The caller's file is still there with its content, so the upload can be retried.
    ASSERT_TRUE(std::filesystem::exists(path));
    EXPECT_EQ(engine::hashing::hash_file(path), hash);

    engine::util::set_fault_handler(nullptr);
    EXPECT_NO_THROW(store.put(hash, path));
    EXPECT_TRUE(store.exists(hash));
}

TEST_F(DurabilityTest, AFailureBeforeTheRenameAlsoCleansUp) {
    const std::string content = "failed at the last moment";
    const auto hash = hash_of(content);
    const auto path = source("late.bin", content);
    engine::util::set_fault_handler([](const char* p) {
        if (std::string(p) == "put:before-rename") {
            throw std::system_error(ENOSPC, std::generic_category());
        }
    });
    ObjectStore store(root_);
    EXPECT_THROW(store.put(hash, path), std::system_error);
    EXPECT_FALSE(store.exists(hash));
    EXPECT_EQ(stray_temp_files(), 0u);
    EXPECT_TRUE(std::filesystem::exists(path));
}

TEST_F(DurabilityTest, ARefusedWrongHashLeavesTheSourceUntouchedAndNothingStored) {
    const auto path = source("wrong.bin", "real content");
    ObjectStore store(root_);
    const auto claimed = hash_of("some other content");
    EXPECT_THROW(store.put(claimed, path), engine::storage::ObjectCorruptedError);
    EXPECT_FALSE(store.exists(claimed));
    EXPECT_TRUE(std::filesystem::exists(path));
    EXPECT_EQ(stray_temp_files(), 0u);
}

TEST_F(DurabilityTest, VerifyCanBeSkippedWhenTheCallerJustComputedTheHash) {
    const std::string content = "trusted";
    const auto path = source("trusted.bin", content);
    ObjectStore store(root_);
    EXPECT_NO_THROW(store.put(hash_of(content), path, /*verify=*/false));
    EXPECT_TRUE(store.exists(hash_of(content)));
}

TEST_F(DurabilityTest, ManyWritersOfTheSameObjectAtOnceLeaveOneCompleteObject) {
    const std::string content(256 * 1024, 'x');
    const auto hash = hash_of(content);
    ObjectStore store(root_);

    std::vector<std::thread> writers;
    std::atomic<int> failures{0};
    for (int i = 0; i < 16; ++i) {
        const auto path = source("w" + std::to_string(i) + ".bin", content);
        writers.emplace_back([&, path] {
            try {
                store.put(hash, path);
            } catch (...) {
                ++failures;
            }
        });
    }
    for (auto& t : writers) {
        t.join();
    }

    EXPECT_EQ(failures.load(), 0);
    ASSERT_TRUE(store.exists(hash));
    EXPECT_EQ(engine::hashing::hash_file(store.path_for(hash)), hash);
    EXPECT_EQ(stray_temp_files(), 0u);
}

TEST_F(DurabilityTest, FinalizingAChunkedUploadStoresAVerifiedObject) {
    engine::storage::StorageManager storage(root_);
    engine::chunks::ChunkManager chunks(root_, storage);
    const std::string part0 = "first part, ";
    const std::string part1 = "second part";
    chunks.write("upload-2", 0, source("p0.bin", part0));
    chunks.write("upload-2", 1, source("p1.bin", part1));
    const auto result = chunks.finalize("upload-2", 2, hash_of(part0 + part1));
    EXPECT_EQ(result.hash, hash_of(part0 + part1));
    EXPECT_TRUE(storage.object_exists(result.hash));
    EXPECT_EQ(stray_temp_files(), 0u);
}

}  // namespace

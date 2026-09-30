// Streaming SHA-256 correctness against known test vectors, large-file
// behavior without loading the whole file into memory.

#include "hashing/hasher.hpp"

#include <filesystem>
#include <fstream>
#include <string>

#include <gtest/gtest.h>

namespace {

std::filesystem::path temp_file_with(const std::string& contents) {
    auto dir = std::filesystem::temp_directory_path() / "engine_hashing_tests";
    std::filesystem::create_directories(dir);
    static int counter = 0;
    auto path = dir / ("file-" + std::to_string(counter++) + ".bin");
    std::ofstream out(path, std::ios::binary);
    out << contents;
    out.close();
    return path;
}

}  // namespace

TEST(HasherTest, EmptyStringMatchesKnownVector) {
    auto digest = engine::hashing::hash_bytes(nullptr, 0);
    EXPECT_EQ(digest, "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
}

TEST(HasherTest, AbcMatchesKnownVector) {
    const std::string input = "abc";
    auto digest = engine::hashing::hash_bytes(
        reinterpret_cast<const unsigned char*>(input.data()), input.size());
    EXPECT_EQ(digest, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
}

TEST(HasherTest, HelloWorldMatchesKnownVector) {
    const std::string input = "hello world";
    auto digest = engine::hashing::hash_bytes(
        reinterpret_cast<const unsigned char*>(input.data()), input.size());
    EXPECT_EQ(digest, "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9");
}

TEST(HasherTest, IncrementalUpdatesProduceSameDigestAsOneShot) {
    const std::string part_a = "hello ";
    const std::string part_b = "world";

    engine::hashing::Sha256Stream stream;
    stream.update(reinterpret_cast<const unsigned char*>(part_a.data()), part_a.size());
    stream.update(reinterpret_cast<const unsigned char*>(part_b.data()), part_b.size());
    auto incremental_digest = stream.hex_digest();

    const std::string whole = part_a + part_b;
    auto one_shot_digest = engine::hashing::hash_bytes(
        reinterpret_cast<const unsigned char*>(whole.data()), whole.size());

    EXPECT_EQ(incremental_digest, one_shot_digest);
}

TEST(HasherTest, HashFileMatchesHashBytesForSameContent) {
    const std::string content = "the quick brown fox jumps over the lazy dog";
    auto path = temp_file_with(content);

    auto file_digest = engine::hashing::hash_file(path);
    auto bytes_digest = engine::hashing::hash_bytes(
        reinterpret_cast<const unsigned char*>(content.data()), content.size());

    EXPECT_EQ(file_digest, bytes_digest);
}

TEST(HasherTest, HashFileLargerThanStreamBufferMatchesWholeReadHash) {
    // Exercise the streaming path: a file several times larger than the
    // bounded read buffer must still produce the correct digest, proving
    // update() is actually being called more than once.
    std::string content;
    content.reserve(engine::hashing::kStreamBufferSize * 3 + 12345);
    for (std::size_t i = 0; i < engine::hashing::kStreamBufferSize * 3 + 12345; ++i) {
        content.push_back(static_cast<char>('a' + (i % 26)));
    }
    auto path = temp_file_with(content);

    auto file_digest = engine::hashing::hash_file(path);
    auto bytes_digest = engine::hashing::hash_bytes(
        reinterpret_cast<const unsigned char*>(content.data()), content.size());

    EXPECT_EQ(file_digest, bytes_digest);
}

TEST(HasherTest, HashFileThrowsForMissingFile) {
    EXPECT_THROW(engine::hashing::hash_file("/nonexistent/path/does-not-exist"),
                 std::runtime_error);
}

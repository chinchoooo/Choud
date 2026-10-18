// The engine's small utilities: the strict JSON reader and escaper, path confinement,
// and the durability helpers.

#include <filesystem>
#include <fstream>
#include <set>
#include <string>
#include <thread>
#include <vector>

#include <gtest/gtest.h>

#include "util/durability.hpp"
#include "util/json.hpp"
#include "util/paths.hpp"

namespace {

using engine::util::JsonError;
using engine::util::parse_flat_object;

// --- JSON reader ---------------------------------------------------------------------------

TEST(JsonTest, ReadsStringsNumbersBooleansAndNull) {
    const auto o = parse_flat_object(R"( { "a" : "text", "n": -42, "yes": true, "no": false, "z": null } )");
    EXPECT_EQ(o.string("a"), "text");
    EXPECT_EQ(o.integer("n"), -42);
    EXPECT_EQ(o.boolean("yes"), true);
    EXPECT_EQ(o.boolean("no"), false);
    EXPECT_TRUE(o.has("z"));
    EXPECT_FALSE(o.string("missing").has_value());
}

TEST(JsonTest, AnEmptyObjectIsFine) {
    EXPECT_NO_THROW(parse_flat_object("{}"));
    EXPECT_NO_THROW(parse_flat_object("  { }  "));
}

TEST(JsonTest, DecodesEveryEscape) {
    const auto o = parse_flat_object(R"({"s":"q\" b\\ s\/ \b\f\n\r\t"})");
    EXPECT_EQ(o.string("s"), std::string("q\" b\\ s/ \b\f\n\r\t"));
}

TEST(JsonTest, DecodesUnicodeEscapesToUtf8) {
    EXPECT_EQ(parse_flat_object(R"({"s":"\u00e9"})").string("s"), "\xC3\xA9");
    EXPECT_EQ(parse_flat_object(R"({"s":"\u20ac"})").string("s"), "\xE2\x82\xAC");
    // A surrogate pair is one code point outside the basic plane (U+1F600).
    EXPECT_EQ(parse_flat_object(R"({"s":"\ud83d\ude00"})").string("s"), "\xF0\x9F\x98\x80");
}

TEST(JsonTest, KeepsRawUtf8AsIs) {
    EXPECT_EQ(parse_flat_object("{\"s\":\"caf\xC3\xA9\"}").string("s"), "caf\xC3\xA9");
}

TEST(JsonTest, RejectsBrokenInput) {
    for (const char* bad : {
             "", "{", "}", "[]", "\"x\"", "{\"a\"}", "{\"a\":}", "{\"a\":1,}", "{,}", "{\"a\":1 \"b\":2}",
             "{\"a\":\"unterminated}", "{\"a\":\"bad\\x\"}", "{\"a\":\"\\u12\"}", "{\"a\":\"\\ud83d\"}",
             "{\"a\":\"\\ude00\"}", "{\"a\":\"\\ud83dx\"}", "{\"a\":\"\\u0000\"}", "{\"a\":01}",
             "{\"a\":1.5}", "{\"a\":1e3}", "{\"a\":-}", "{\"a\":99999999999999999999}",
             "{\"a\":tru}", "{\"a\":nul}", "{\"a\":1} x", "{\"a\":[1]}", "{\"a\":{\"b\":1}}",
             "{'a':1}"}) {
        EXPECT_THROW(parse_flat_object(bad), JsonError) << "accepted: " << bad;
    }
}

TEST(JsonTest, RejectsRawControlCharactersInStrings) {
    EXPECT_THROW(parse_flat_object(std::string("{\"a\":\"line\nbreak\"}")), JsonError);
}

TEST(JsonTest, RejectsDuplicateKeys) {
    EXPECT_THROW(parse_flat_object(R"({"a":1,"a":2})"), JsonError);
}

TEST(JsonTest, WrongTypesAreReportedNotCoerced) {
    const auto o = parse_flat_object(R"({"s":"1","n":1,"b":true})");
    EXPECT_THROW(o.integer("s"), JsonError);
    EXPECT_THROW(o.string("n"), JsonError);
    EXPECT_THROW(o.boolean("n"), JsonError);
    EXPECT_THROW(o.string("b"), JsonError);
}

TEST(JsonTest, EscapeRoundTripsThroughTheReader) {
    const std::string nasty = std::string("quote\" back\\ tab\t nl\n cr\r ctl\x01 \xC3\xA9 end");
    const auto json = "{\"v\":\"" + engine::util::json_escape(nasty) + "\"}";
    EXPECT_EQ(parse_flat_object(json).string("v"), nasty);
}

TEST(JsonTest, EscapeProducesNoRawControlCharacters) {
    const auto escaped = engine::util::json_escape(std::string("a\x01\x1f\n"));
    for (const unsigned char c : escaped) {
        EXPECT_GE(c, 0x20);
    }
}

// --- path confinement ----------------------------------------------------------------------

class PathsTest : public ::testing::Test {
   protected:
    void SetUp() override {
        static int counter = 0;
        root_ = std::filesystem::temp_directory_path() / "engine_paths_tests" /
                std::to_string(counter++);
        std::filesystem::remove_all(root_);
        std::filesystem::create_directories(root_ / "staging");
        std::filesystem::create_directories(root_ / "objects" / "ab");
    }
    void TearDown() override { std::filesystem::remove_all(root_); }
    std::filesystem::path root_;
};

TEST_F(PathsTest, AllowsFilesUnderTheRootIncludingNewOnes) {
    EXPECT_NO_THROW(engine::util::confine(root_, (root_ / "staging" / "new-file.bin").string(), false));
    EXPECT_NO_THROW(engine::util::confine(root_, (root_ / "staging").string(), false));
}

TEST_F(PathsTest, RefusesEmptyRelativeAndNulPaths) {
    EXPECT_THROW(engine::util::confine(root_, "", false), engine::util::PathError);
    EXPECT_THROW(engine::util::confine(root_, "staging/x", false), engine::util::PathError);
    EXPECT_THROW(engine::util::confine(root_, std::string(root_.string()) + std::string("\0x", 2), false),
                 engine::util::PathError);
}

TEST_F(PathsTest, RefusesAnythingOutsideTheRoot) {
    EXPECT_THROW(engine::util::confine(root_, "/etc/passwd", false), engine::util::PathError);
    EXPECT_THROW(engine::util::confine(root_, root_.parent_path().string(), false),
                 engine::util::PathError);
    EXPECT_THROW(engine::util::confine(root_, (root_ / ".." / "elsewhere").string(), false),
                 engine::util::PathError);
}

TEST_F(PathsTest, ASiblingWithTheSamePrefixIsNotInside) {
    // /root-evil must not pass for being "under" /root.
    const auto evil = root_.string() + "-evil/file";
    EXPECT_THROW(engine::util::confine(root_, evil, false), engine::util::PathError);
}

TEST_F(PathsTest, TheRootItselfIsRefused) {
    EXPECT_THROW(engine::util::confine(root_, root_.string(), false), engine::util::PathError);
}

TEST_F(PathsTest, ObjectsAreOffLimitsUnlessAllowed) {
    const auto object = (root_ / "objects" / "ab" / "abcdef").string();
    EXPECT_THROW(engine::util::confine(root_, object, false), engine::util::PathError);
    EXPECT_NO_THROW(engine::util::confine(root_, object, true));
    // Getting around it with ".." does not work either.
    EXPECT_THROW(engine::util::confine(root_, (root_ / "staging" / ".." / "objects" / "ab" / "x").string(), false),
                 engine::util::PathError);
}

#ifndef _WIN32
TEST_F(PathsTest, SymlinksAreResolvedBeforeTheCheck) {
    std::filesystem::create_symlink("/etc", root_ / "staging" / "out");
    EXPECT_THROW(engine::util::confine(root_, (root_ / "staging" / "out" / "passwd").string(), false),
                 engine::util::PathError);
    // A link that stays inside the root is fine, but cannot reach into objects/.
    std::filesystem::create_directory_symlink(root_ / "objects", root_ / "staging" / "in");
    EXPECT_THROW(engine::util::confine(root_, (root_ / "staging" / "in" / "ab" / "x").string(), false),
                 engine::util::PathError);
}
#endif

// --- durability helpers --------------------------------------------------------------------

TEST(DurabilityHelpersTest, FsyncOfAFileAndADirectorySucceeds) {
    const auto dir = std::filesystem::temp_directory_path() / "engine_durability_tests";
    std::filesystem::create_directories(dir);
    const auto file = dir / "f.bin";
    {
        std::ofstream out(file, std::ios::binary);
        out << "data";
    }
    EXPECT_NO_THROW(engine::util::fsync_file(file));
    EXPECT_NO_THROW(engine::util::fsync_dir(dir));
    std::filesystem::remove_all(dir);
}

#ifndef _WIN32
TEST(DurabilityHelpersTest, FsyncOfAMissingFileReportsAnError) {
    EXPECT_THROW(engine::util::fsync_file("/definitely/not/here"), std::runtime_error);
    EXPECT_THROW(engine::util::fsync_dir("/definitely/not/here"), std::runtime_error);
}
#endif

TEST(DurabilityHelpersTest, UniqueSuffixIsUniqueAcrossThreads) {
    std::set<std::string> seen;
    std::mutex mutex;
    std::vector<std::thread> threads;
    for (int t = 0; t < 8; ++t) {
        threads.emplace_back([&] {
            for (int i = 0; i < 200; ++i) {
                auto s = engine::util::unique_suffix();
                std::lock_guard<std::mutex> lock(mutex);
                seen.insert(s);
            }
        });
    }
    for (auto& t : threads) {
        t.join();
    }
    EXPECT_EQ(seen.size(), 1600u);
}

TEST(DurabilityHelpersTest, FaultHandlerSeesNamedPoints) {
    std::vector<std::string> points;
    engine::util::set_fault_handler([&](const char* p) { points.emplace_back(p); });
    engine::util::fault_point("a");
    engine::util::fault_point("b");
    engine::util::set_fault_handler(nullptr);
    engine::util::fault_point("c");  // no handler: ignored
    EXPECT_EQ(points, (std::vector<std::string>{"a", "b"}));
}

}  // namespace

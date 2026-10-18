// What the engine does with hostile or malformed requests: paths that escape the
// storage root, bodies that are not valid JSON, wrong hashes, and many requests at
// once. Its own server instance on its own port, so these tests do not depend on the
// order of the other HTTP tests.

#include <atomic>
#include <boost/asio.hpp>
#include <boost/beast/core.hpp>
#include <boost/beast/http.hpp>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <string>
#include <thread>
#include <vector>

#include <gtest/gtest.h>

#include "api/engine_server.hpp"

namespace asio = boost::asio;
namespace beast = boost::beast;
namespace http = boost::beast::http;
using tcp = boost::asio::ip::tcp;

namespace {

constexpr uint16_t kPort = 19192;

http::response<http::string_body> send(http::verb verb, const std::string& target,
                                       const std::string& body) {
    asio::io_context ioc;
    tcp::socket socket{ioc};
    socket.connect(tcp::endpoint(asio::ip::make_address("127.0.0.1"), kPort));

    http::request<http::string_body> req{verb, target, 11};
    req.set(http::field::host, "127.0.0.1");
    req.set(http::field::content_type, "application/json");
    req.body() = body;
    req.prepare_payload();
    http::write(socket, req);

    beast::flat_buffer buffer;
    http::response<http::string_body> res;
    http::read(socket, buffer, res);
    return res;
}

http::response<http::string_body> post(const std::string& target, const std::string& body) {
    return send(http::verb::post, target, body);
}

std::filesystem::path root() {
    return std::filesystem::temp_directory_path() / "engine_request_safety_tests";
}

std::filesystem::path staging() {
    return root() / "staging";
}

std::filesystem::path make_file(const std::string& name, const std::string& contents) {
    std::filesystem::create_directories(staging());
    const auto path = staging() / name;
    std::ofstream out(path, std::ios::binary);
    out << contents;
    return path;
}

std::string hash_field(const http::response<http::string_body>& res) {
    const auto start = res.body().find("\"hash\":\"");
    return start == std::string::npos ? "" : res.body().substr(start + 8, 64);
}

const std::string kHelloWorldHash =
    "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9";

class RequestSafetyTest : public ::testing::Test {
   protected:
    static void SetUpTestSuite() {
        std::filesystem::remove_all(root());
        std::filesystem::create_directories(staging());
        std::thread([] {
            engine::api::EngineServer server("127.0.0.1", kPort, root().string());
            server.run();
        }).detach();
        std::this_thread::sleep_for(std::chrono::milliseconds(300));
    }
};

TEST_F(RequestSafetyTest, PathsOutsideTheStorageRootAreRefused) {
    EXPECT_EQ(post("/hash", R"({"path":"/etc/passwd"})").result(), http::status::bad_request);
    EXPECT_EQ(post("/objects/put", R"({"hash":")" + std::string(64, 'a') +
                                       R"(","source_path":"/etc/passwd"})")
                  .result(),
              http::status::bad_request);
    EXPECT_EQ(post("/objects/get", R"({"hash":")" + std::string(64, 'a') +
                                       R"(","destination_path":"/tmp/engine-escape"})")
                  .result(),
              http::status::bad_request);
    EXPECT_EQ(
        post("/chunks/write", R"({"upload_id":"u1","index":0,"source_path":"/etc/hostname"})")
            .result(),
        http::status::bad_request);
}

TEST_F(RequestSafetyTest, DotDotCannotEscapeTheStorageRoot) {
    const auto sneaky = (staging() / ".." / ".." / "escape.txt").string();
    EXPECT_EQ(post("/hash", R"({"path":")" + sneaky + R"("})").result(), http::status::bad_request);
}

#ifndef _WIN32
TEST_F(RequestSafetyTest, ASymlinkPointingOutsideTheRootCannotBeFollowed) {
    const auto link = staging() / "link-to-etc";
    std::filesystem::remove(link);
    std::filesystem::create_symlink("/etc", link);
    EXPECT_EQ(post("/hash", R"({"path":")" + (link / "hostname").string() + R"("})").result(),
              http::status::bad_request);
}
#endif

TEST_F(RequestSafetyTest, RelativePathsAreRefused) {
    EXPECT_EQ(post("/hash", R"({"path":"staging/file"})").result(), http::status::bad_request);
}

TEST_F(RequestSafetyTest, TheObjectStoreCannotBeOverwrittenThroughAGetDestination) {
    auto source = make_file("keep-me.bin", "an object that must stay");
    const auto hash = hash_field(post("/hash", R"({"path":")" + source.string() + R"("})"));
    ASSERT_EQ(hash.size(), 64u);
    ASSERT_EQ(post("/objects/put",
                   R"({"hash":")" + hash + R"(","source_path":")" + source.string() + R"("})")
                  .result(),
              http::status::created);

    const auto inside_objects = root() / "objects" / hash.substr(0, 2) / hash;
    auto res = post("/objects/get", R"({"hash":")" + hash + R"(","destination_path":")" +
                                        inside_objects.string() + R"("})");
    EXPECT_EQ(res.result(), http::status::bad_request);
    // ...and the object is still intact.
    EXPECT_EQ(post("/objects/exists", R"({"hash":")" + hash + R"("})").result(), http::status::ok);
}

TEST_F(RequestSafetyTest, PutWithTheWrongHashIsRefusedAndTheSourceIsLeftAlone) {
    auto source = make_file("liar.bin", "these bytes do not hash to the claim");
    auto res = post("/objects/put", R"({"hash":")" + std::string(64, 'c') + R"(","source_path":")" +
                                        source.string() + R"("})");
    EXPECT_EQ(res.result(), http::status::conflict);
    EXPECT_TRUE(std::filesystem::exists(source));
    auto exists_res = post("/objects/exists", R"({"hash":")" + std::string(64, 'c') + R"("})");
    EXPECT_NE(exists_res.body().find("\"exists\":false"), std::string::npos);
}

TEST_F(RequestSafetyTest, MalformedJsonIsABadRequestNotACrash) {
    EXPECT_EQ(post("/hash", "{not json").result(), http::status::bad_request);
    EXPECT_EQ(post("/hash", "").result(), http::status::bad_request);
    EXPECT_EQ(post("/hash", R"({"path":"/a"} trailing)").result(), http::status::bad_request);
    EXPECT_EQ(post("/hash", R"({"path":["nested"]})").result(), http::status::bad_request);
    EXPECT_EQ(post("/hash", R"({"path":"/a","path":"/b"})").result(), http::status::bad_request);
    EXPECT_EQ(
        post("/chunks/write", R"({"upload_id":"u","index":"zero","source_path":"/x"})").result(),
        http::status::bad_request);
    EXPECT_EQ(post("/chunks/write", R"({"upload_id":"u","index":-1,"source_path":"/x"})").result(),
              http::status::bad_request);
    // ...and the engine is still serving afterwards.
    EXPECT_EQ(send(http::verb::get, "/health", "").result(), http::status::ok);
}

TEST_F(RequestSafetyTest, EscapedCharactersInPathsAreDecoded) {
    // A file whose name contains a double quote. The JSON body must escape it, and the
    // engine must decode it back to the real name.
    const auto path = make_file("quote\"name.bin", "hello world");
    std::string escaped;
    for (const char c : path.string()) {
        if (c == '"') {
            escaped += "\\\"";
        } else if (c == '\\') {
            escaped += "\\\\";  // Windows-style separators, should the tests ever run there
        } else {
            escaped.push_back(c);
        }
    }
    auto res = post("/hash", R"({"path":")" + escaped + R"("})");
    EXPECT_EQ(res.result(), http::status::ok);
    EXPECT_EQ(hash_field(res), kHelloWorldHash);
}

TEST_F(RequestSafetyTest, UnicodeEscapesInPathsAreDecoded) {
    const auto path = make_file("caf\xC3\xA9.bin", "hello world");  // UTF-8 for "café.bin"
    (void)path;
    // The backend sends non-ASCII as \u escapes (Python's json.dumps default).
    const auto json = std::string(R"({"path":")") + (staging() / "caf\\u00e9.bin").string() + R"("})";
    auto res = post("/hash", json);
    EXPECT_EQ(res.result(), http::status::ok);
    EXPECT_EQ(hash_field(res), kHelloWorldHash);
}

TEST_F(RequestSafetyTest, ManyRequestsAtOnceAreAllServed) {
    std::vector<std::thread> threads;
    std::atomic<int> ok{0};
    for (int i = 0; i < 24; ++i) {
        threads.emplace_back([&ok, i] {
            const auto path = make_file("concurrent-" + std::to_string(i) + ".bin", "hello world");
            auto res = post("/hash", R"({"path":")" + path.string() + R"("})");
            if (res.result() == http::status::ok && hash_field(res) == kHelloWorldHash) {
                ++ok;
            }
        });
    }
    for (auto& t : threads) {
        t.join();
    }
    EXPECT_EQ(ok.load(), 24);
}

TEST_F(RequestSafetyTest, OnlyPostIsAcceptedOnTheApiRoutes) {
    EXPECT_EQ(send(http::verb::get, "/hash", "").result(), http::status::not_found);
    EXPECT_EQ(send(http::verb::delete_, "/objects/delete", "{}").result(), http::status::not_found);
}

}  // namespace

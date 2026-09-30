#include "api/engine_server.hpp"

#include <boost/asio.hpp>
#include <boost/beast/core.hpp>
#include <boost/beast/http.hpp>
#include <chrono>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <thread>

#include <gtest/gtest.h>

namespace asio = boost::asio;
namespace beast = boost::beast;
namespace http = boost::beast::http;
using tcp = boost::asio::ip::tcp;

namespace {

constexpr uint16_t kTestPort = 19191;

http::response<http::string_body> get(const std::string& target) {
    asio::io_context ioc;
    tcp::socket socket{ioc};
    socket.connect(tcp::endpoint(asio::ip::make_address("127.0.0.1"), kTestPort));

    http::request<http::empty_body> req{http::verb::get, target, 11};
    req.set(http::field::host, "127.0.0.1");
    http::write(socket, req);

    beast::flat_buffer buffer;
    http::response<http::string_body> res;
    http::read(socket, buffer, res);
    return res;
}

http::response<http::string_body> post(const std::string& target, const std::string& body) {
    asio::io_context ioc;
    tcp::socket socket{ioc};
    socket.connect(tcp::endpoint(asio::ip::make_address("127.0.0.1"), kTestPort));

    http::request<http::string_body> req{http::verb::post, target, 11};
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

std::filesystem::path write_temp_file(const std::string& contents) {
    auto dir = std::filesystem::temp_directory_path() / "engine_server_tests_staging";
    std::filesystem::create_directories(dir);
    auto path = dir / (std::string("upload-") + std::to_string(std::rand()) + ".bin");
    std::ofstream out(path, std::ios::binary);
    out << contents;
    out.close();
    return path;
}

class EngineServerTest : public ::testing::Test {
   protected:
    static void SetUpTestSuite() {
        auto storage_root = std::filesystem::temp_directory_path() / "engine_server_tests";
        std::thread([storage_root] {
            engine::api::EngineServer server("127.0.0.1", kTestPort, storage_root.string());
            server.run();
        }).detach();
        // Give the acceptor time to bind before tests connect. The
        // detached thread outlives the test process, which is fine: it
        // is killed when the test binary exits.
        std::this_thread::sleep_for(std::chrono::milliseconds(200));
    }
};

TEST_F(EngineServerTest, HealthReturnsOkWithHealthyStatus) {
    auto res = get("/health");
    EXPECT_EQ(res.result(), http::status::ok);
    EXPECT_NE(res.body().find("\"healthy\""), std::string::npos);
}

TEST_F(EngineServerTest, UnknownRouteReturnsNotFound) {
    auto res = get("/nonexistent");
    EXPECT_EQ(res.result(), http::status::not_found);
}

TEST_F(EngineServerTest, HashComputesSha256OfAFileOnDisk) {
    auto path = write_temp_file("hello world");

    auto res = post("/hash", R"({"path":")" + path.string() + R"("})");

    EXPECT_EQ(res.result(), http::status::ok);
    // SHA-256("hello world")
    EXPECT_NE(res.body().find("b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"),
              std::string::npos);
}

TEST_F(EngineServerTest, HashOfMissingFileReturnsBadRequest) {
    auto res = post("/hash", R"({"path":"/nonexistent/does-not-exist"})");
    EXPECT_EQ(res.result(), http::status::bad_request);
}

TEST_F(EngineServerTest, ObjectsExistsIsFalseForUnknownHash) {
    auto res = post("/objects/exists", R"({"hash":")" + std::string(64, 'b') + R"("})");

    EXPECT_EQ(res.result(), http::status::ok);
    EXPECT_NE(res.body().find("\"exists\":false"), std::string::npos);
}

TEST_F(EngineServerTest, PutThenExistsThenGetRoundTrip) {
    const std::string contents = "round trip contents";
    auto source = write_temp_file(contents);
    auto hash_res = post("/hash", R"({"path":")" + source.string() + R"("})");
    ASSERT_EQ(hash_res.result(), http::status::ok);
    auto start = hash_res.body().find("\"hash\":\"") + 8;
    auto hash = hash_res.body().substr(start, 64);

    // put() consumes the source, so re-write it before storing.
    source = write_temp_file(contents);
    auto put_res = post("/objects/put", R"({"hash":")" + hash + R"(","source_path":")" +
                                             source.string() + R"("})");
    EXPECT_EQ(put_res.result(), http::status::created);

    auto exists_res = post("/objects/exists", R"({"hash":")" + hash + R"("})");
    EXPECT_EQ(exists_res.result(), http::status::ok);
    EXPECT_NE(exists_res.body().find("\"exists\":true"), std::string::npos);

    auto dest = std::filesystem::temp_directory_path() / "engine_server_tests_staging" /
                "downloaded.bin";
    auto get_res =
        post("/objects/get", R"({"hash":")" + hash + R"(","destination_path":")" + dest.string() +
                                  R"("})");
    EXPECT_EQ(get_res.result(), http::status::ok);

    std::ifstream in(dest, std::ios::binary);
    std::string roundtripped((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
    EXPECT_EQ(roundtripped, contents);

    auto delete_res = post("/objects/delete", R"({"hash":")" + hash + R"("})");
    EXPECT_EQ(delete_res.result(), http::status::ok);
    EXPECT_NE(delete_res.body().find("\"deleted\":true"), std::string::npos);

    auto exists_after_delete = post("/objects/exists", R"({"hash":")" + hash + R"("})");
    EXPECT_NE(exists_after_delete.body().find("\"exists\":false"), std::string::npos);
}

TEST_F(EngineServerTest, GetOfMissingHashReturnsNotFound) {
    auto res = post("/objects/get",
                     R"({"hash":")" + std::string(64, 'a') + R"(",)"
                     R"("destination_path":"/tmp/engine_server_tests_should_not_exist"})");
    EXPECT_EQ(res.result(), http::status::not_found);
}

TEST_F(EngineServerTest, PutWithInvalidHashReturnsBadRequest) {
    auto source = write_temp_file("data");
    auto res = post("/objects/put",
                     R"({"hash":"not-a-hash","source_path":")" + source.string() + R"("})");
    EXPECT_EQ(res.result(), http::status::bad_request);
}

TEST_F(EngineServerTest, ChunkWriteThenFinalizeRoundTrip) {
    const std::string upload_id = "http-upload-1";
    const std::string chunk0 = "first half of ";
    const std::string chunk1 = "the reconstructed file";

    auto write0 = post("/chunks/write", R"({"upload_id":")" + upload_id +
                                             R"(","index":0,"source_path":")" +
                                             write_temp_file(chunk0).string() + R"("})");
    EXPECT_EQ(write0.result(), http::status::created);
    EXPECT_NE(write0.body().find("\"received\":true"), std::string::npos);

    auto write1 = post("/chunks/write", R"({"upload_id":")" + upload_id +
                                             R"(","index":1,"source_path":")" +
                                             write_temp_file(chunk1).string() + R"("})");
    EXPECT_EQ(write1.result(), http::status::created);

    auto finalize_res = post(
        "/chunks/finalize", R"({"upload_id":")" + upload_id + R"(","total_chunks":2})");
    EXPECT_EQ(finalize_res.result(), http::status::ok);

    // SHA-256 of "first half of the reconstructed file"
    auto hash_res = post("/hash", R"({"path":")" + write_temp_file(chunk0 + chunk1).string() +
                                       R"("})");
    auto start = hash_res.body().find("\"hash\":\"") + 8;
    auto expected_hash = hash_res.body().substr(start, 64);
    EXPECT_NE(finalize_res.body().find(expected_hash), std::string::npos);

    // The object is now retrievable through the ordinary objects/get path.
    auto exists_res = post("/objects/exists", R"({"hash":")" + expected_hash + R"("})");
    EXPECT_NE(exists_res.body().find("\"exists\":true"), std::string::npos);
}

TEST_F(EngineServerTest, FinalizeWithAMissingChunkReturnsConflict) {
    const std::string upload_id = "http-upload-missing-chunk";
    post("/chunks/write", R"({"upload_id":")" + upload_id + R"(","index":0,"source_path":")" +
                               write_temp_file("only chunk").string() + R"("})");

    auto res = post("/chunks/finalize",
                     R"({"upload_id":")" + upload_id + R"(","total_chunks":2})");
    EXPECT_EQ(res.result(), http::status::conflict);
}

TEST_F(EngineServerTest, FinalizeWithAMismatchedExpectedHashReturnsConflict) {
    const std::string upload_id = "http-upload-bad-hash";
    post("/chunks/write", R"({"upload_id":")" + upload_id + R"(","index":0,"source_path":")" +
                               write_temp_file("actual content").string() + R"("})");

    auto res = post("/chunks/finalize",
                     R"({"upload_id":")" + upload_id + R"(","total_chunks":1,)"
                     R"("expected_hash":")" + std::string(64, 'a') + R"("})");
    EXPECT_EQ(res.result(), http::status::conflict);
}

TEST_F(EngineServerTest, ChunksAbandonRemovesInProgressUploadAndReportsWhetherItExisted) {
    const std::string upload_id = "http-upload-abandon";
    post("/chunks/write", R"({"upload_id":")" + upload_id + R"(","index":0,"source_path":")" +
                               write_temp_file("never finalized").string() + R"("})");

    auto res = post("/chunks/abandon", R"({"upload_id":")" + upload_id + R"("})");
    EXPECT_EQ(res.result(), http::status::ok);
    EXPECT_NE(res.body().find("\"removed\":true"), std::string::npos);

    auto second_res = post("/chunks/abandon", R"({"upload_id":")" + upload_id + R"("})");
    EXPECT_NE(second_res.body().find("\"removed\":false"), std::string::npos);
}

}  // namespace

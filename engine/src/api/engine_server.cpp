#include "api/engine_server.hpp"

#include <boost/asio.hpp>
#include <boost/beast/core.hpp>
#include <boost/beast/http.hpp>
#include <iostream>
#include <optional>
#include <regex>
#include <string>

#include "chunks/chunk_manager.hpp"
#include "storage/object_store.hpp"
#include "storage/storage_manager.hpp"

namespace asio = boost::asio;
namespace beast = boost::beast;
namespace http = boost::beast::http;
using tcp = boost::asio::ip::tcp;

namespace engine::api {

namespace {

// --- tiny JSON helpers ----------------------------------------------------
//
// Request/response bodies here are small, flat objects with string/bool/
// number fields (see docs/api.md's internal API table) exchanged only
// between our own two trusted, Docker-internal processes — never
// user-facing. A regex-based extractor is enough; pulling in a JSON
// library for this would be exactly the unnecessary dependency Rule 2
// warns against.

std::optional<std::string> json_string(const std::string& body, const std::string& key) {
    std::regex pattern("\"" + key + "\"\\s*:\\s*\"([^\"]*)\"");
    std::smatch match;
    if (std::regex_search(body, match, pattern)) {
        return match[1].str();
    }
    return std::nullopt;
}

// Extracts an unsigned integer field (chunk index, total_chunks — never
// negative in any request this engine handles) without quotes, e.g.
// `"index":3`.
std::optional<long long> json_int(const std::string& body, const std::string& key) {
    std::regex pattern("\"" + key + "\"\\s*:\\s*(-?[0-9]+)");
    std::smatch match;
    if (std::regex_search(body, match, pattern)) {
        return std::stoll(match[1].str());
    }
    return std::nullopt;
}

std::string json_escape(const std::string& value) {
    std::string out;
    out.reserve(value.size());
    for (char c : value) {
        if (c == '"' || c == '\\') {
            out.push_back('\\');
        }
        out.push_back(c);
    }
    return out;
}

http::response<http::string_body> json_response(http::status status, unsigned version,
                                                  const std::string& json_body) {
    http::response<http::string_body> res{status, version};
    res.set(http::field::content_type, "application/json");
    res.body() = json_body;
    res.prepare_payload();
    return res;
}

http::response<http::string_body> error_response(http::status status, unsigned version,
                                                   const std::string& message) {
    return json_response(status, version, R"({"error":")" + json_escape(message) + R"("})");
}

// --- routing ---------------------------------------------------------------

http::response<http::string_body> handle_hash(const http::request<http::string_body>& req,
                                                engine::storage::StorageManager& manager) {
    auto path = json_string(req.body(), "path");
    if (!path) {
        return error_response(http::status::bad_request, req.version(), "missing \"path\"");
    }
    try {
        auto hash = manager.hash_file(*path);
        return json_response(http::status::ok, req.version(), R"({"hash":")" + hash + R"("})");
    } catch (const std::exception& ex) {
        return error_response(http::status::bad_request, req.version(), ex.what());
    }
}

http::response<http::string_body> handle_objects_exists(
    const http::request<http::string_body>& req, engine::storage::StorageManager& manager) {
    auto hash = json_string(req.body(), "hash");
    if (!hash) {
        return error_response(http::status::bad_request, req.version(), "missing \"hash\"");
    }
    try {
        bool exists = manager.object_exists(*hash);
        return json_response(http::status::ok, req.version(),
                              std::string(R"({"exists":)") + (exists ? "true" : "false") + "}");
    } catch (const engine::storage::InvalidHashError& ex) {
        return error_response(http::status::bad_request, req.version(), ex.what());
    }
}

http::response<http::string_body> handle_objects_put(const http::request<http::string_body>& req,
                                                       engine::storage::StorageManager& manager) {
    auto hash = json_string(req.body(), "hash");
    auto source_path = json_string(req.body(), "source_path");
    if (!hash || !source_path) {
        return error_response(http::status::bad_request, req.version(),
                               "missing \"hash\" or \"source_path\"");
    }
    try {
        manager.store_object(*hash, *source_path);
        auto size = manager.object_size(*hash);
        return json_response(http::status::created, req.version(),
                              R"({"stored":true,"size":)" + std::to_string(size) + "}");
    } catch (const engine::storage::InvalidHashError& ex) {
        return error_response(http::status::bad_request, req.version(), ex.what());
    } catch (const std::exception& ex) {
        return error_response(http::status::internal_server_error, req.version(), ex.what());
    }
}

http::response<http::string_body> handle_objects_get(const http::request<http::string_body>& req,
                                                       engine::storage::StorageManager& manager) {
    auto hash = json_string(req.body(), "hash");
    auto destination_path = json_string(req.body(), "destination_path");
    if (!hash || !destination_path) {
        return error_response(http::status::bad_request, req.version(),
                               "missing \"hash\" or \"destination_path\"");
    }
    try {
        manager.retrieve_object(*hash, *destination_path);
        auto size = manager.object_size(*hash);
        return json_response(http::status::ok, req.version(),
                              R"({"size":)" + std::to_string(size) + "}");
    } catch (const engine::storage::ObjectNotFoundError& ex) {
        return error_response(http::status::not_found, req.version(), ex.what());
    } catch (const engine::storage::ObjectCorruptedError& ex) {
        return error_response(http::status::conflict, req.version(), ex.what());
    } catch (const engine::storage::InvalidHashError& ex) {
        return error_response(http::status::bad_request, req.version(), ex.what());
    } catch (const std::exception& ex) {
        return error_response(http::status::internal_server_error, req.version(), ex.what());
    }
}

http::response<http::string_body> handle_objects_delete(
    const http::request<http::string_body>& req, engine::storage::StorageManager& manager) {
    auto hash = json_string(req.body(), "hash");
    if (!hash) {
        return error_response(http::status::bad_request, req.version(), "missing \"hash\"");
    }
    try {
        bool existed = manager.object_exists(*hash);
        manager.remove_object(*hash);
        return json_response(http::status::ok, req.version(),
                              std::string(R"({"deleted":)") + (existed ? "true" : "false") + "}");
    } catch (const engine::storage::InvalidHashError& ex) {
        return error_response(http::status::bad_request, req.version(), ex.what());
    }
}

http::response<http::string_body> handle_chunks_write(
    const http::request<http::string_body>& req, engine::chunks::ChunkManager& chunk_manager) {
    auto upload_id = json_string(req.body(), "upload_id");
    auto index = json_int(req.body(), "index");
    auto source_path = json_string(req.body(), "source_path");
    if (!upload_id || !index || !source_path) {
        return error_response(http::status::bad_request, req.version(),
                               "missing \"upload_id\", \"index\", or \"source_path\"");
    }
    try {
        chunk_manager.write(*upload_id, static_cast<int>(*index), *source_path);
        return json_response(http::status::created, req.version(), R"({"received":true})");
    } catch (const engine::chunks::InvalidUploadIdError& ex) {
        return error_response(http::status::bad_request, req.version(), ex.what());
    } catch (const std::exception& ex) {
        return error_response(http::status::internal_server_error, req.version(), ex.what());
    }
}

http::response<http::string_body> handle_chunks_finalize(
    const http::request<http::string_body>& req, engine::chunks::ChunkManager& chunk_manager) {
    auto upload_id = json_string(req.body(), "upload_id");
    auto total_chunks = json_int(req.body(), "total_chunks");
    if (!upload_id || !total_chunks) {
        return error_response(http::status::bad_request, req.version(),
                               "missing \"upload_id\" or \"total_chunks\"");
    }
    auto expected_hash = json_string(req.body(), "expected_hash");  // optional
    try {
        auto result =
            chunk_manager.finalize(*upload_id, static_cast<int>(*total_chunks), expected_hash);
        return json_response(http::status::ok, req.version(),
                              R"({"hash":")" + result.hash + R"(","size":)" +
                                  std::to_string(result.size) + "}");
    } catch (const engine::chunks::MissingChunkError& ex) {
        return error_response(http::status::conflict, req.version(), ex.what());
    } catch (const engine::chunks::HashMismatchError& ex) {
        return error_response(http::status::conflict, req.version(), ex.what());
    } catch (const engine::chunks::InvalidUploadIdError& ex) {
        return error_response(http::status::bad_request, req.version(), ex.what());
    } catch (const std::invalid_argument& ex) {
        return error_response(http::status::bad_request, req.version(), ex.what());
    } catch (const std::exception& ex) {
        return error_response(http::status::internal_server_error, req.version(), ex.what());
    }
}

http::response<http::string_body> handle_chunks_abandon(
    const http::request<http::string_body>& req, engine::chunks::ChunkManager& chunk_manager) {
    auto upload_id = json_string(req.body(), "upload_id");
    if (!upload_id) {
        return error_response(http::status::bad_request, req.version(), "missing \"upload_id\"");
    }
    try {
        bool removed = chunk_manager.abandon(*upload_id);
        return json_response(http::status::ok, req.version(),
                              std::string(R"({"removed":)") + (removed ? "true" : "false") + "}");
    } catch (const engine::chunks::InvalidUploadIdError& ex) {
        return error_response(http::status::bad_request, req.version(), ex.what());
    }
}

http::response<http::string_body> route(const http::request<http::string_body>& req,
                                         engine::storage::StorageManager& manager,
                                         engine::chunks::ChunkManager& chunk_manager) {
    if (req.method() == http::verb::get && req.target() == "/health") {
        return json_response(http::status::ok, req.version(), R"({"status":"healthy"})");
    }
    if (req.method() == http::verb::post && req.target() == "/hash") {
        return handle_hash(req, manager);
    }
    if (req.method() == http::verb::post && req.target() == "/objects/exists") {
        return handle_objects_exists(req, manager);
    }
    if (req.method() == http::verb::post && req.target() == "/objects/put") {
        return handle_objects_put(req, manager);
    }
    if (req.method() == http::verb::post && req.target() == "/objects/get") {
        return handle_objects_get(req, manager);
    }
    if (req.method() == http::verb::post && req.target() == "/objects/delete") {
        return handle_objects_delete(req, manager);
    }
    if (req.method() == http::verb::post && req.target() == "/chunks/write") {
        return handle_chunks_write(req, chunk_manager);
    }
    if (req.method() == http::verb::post && req.target() == "/chunks/finalize") {
        return handle_chunks_finalize(req, chunk_manager);
    }
    if (req.method() == http::verb::post && req.target() == "/chunks/abandon") {
        return handle_chunks_abandon(req, chunk_manager);
    }

    return error_response(http::status::not_found, req.version(), "not found");
}

void handle_connection(tcp::socket socket, engine::storage::StorageManager& manager,
                        engine::chunks::ChunkManager& chunk_manager) {
    beast::error_code ec;
    beast::flat_buffer buffer;

    http::request<http::string_body> req;
    http::read(socket, buffer, req, ec);
    if (ec) {
        return;
    }

    auto res = route(req, manager, chunk_manager);
    res.keep_alive(false);
    http::write(socket, res, ec);

    socket.shutdown(tcp::socket::shutdown_send, ec);
}

}  // namespace

EngineServer::EngineServer(std::string host, uint16_t port, std::string storage_root)
    : host_(std::move(host)), port_(port), storage_root_(std::move(storage_root)) {}

void EngineServer::run() {
    engine::storage::StorageManager manager(storage_root_);
    engine::chunks::ChunkManager chunk_manager(storage_root_, manager);

    asio::io_context ioc{1};
    tcp::acceptor acceptor{ioc, {asio::ip::make_address(host_), port_}};

    std::cout << "engine listening on " << host_ << ":" << port_ << " (storage root "
              << storage_root_ << ")" << std::endl;

    for (;;) {
        tcp::socket socket{ioc};
        acceptor.accept(socket);
        handle_connection(std::move(socket), manager, chunk_manager);
    }
}

}  // namespace engine::api

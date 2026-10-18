#include "api/engine_server.hpp"

#include <atomic>
#include <boost/asio.hpp>
#include <boost/beast/core.hpp>
#include <boost/beast/http.hpp>
#include <chrono>
#include <condition_variable>
#include <iostream>
#include <mutex>
#include <optional>
#include <string>
#include <thread>

#include "chunks/chunk_manager.hpp"
#include "storage/object_store.hpp"
#include "storage/storage_manager.hpp"
#include "util/json.hpp"
#include "util/paths.hpp"

namespace asio = boost::asio;
namespace beast = boost::beast;
namespace http = boost::beast::http;
using tcp = boost::asio::ip::tcp;

namespace engine::api {

namespace {

using engine::util::JsonError;
using engine::util::JsonObject;
using engine::util::PathError;

// How many requests may run at once. A large finalize (hashing gigabytes) must
// not make every other upload wait, but the cap keeps a flood of connections
// from exhausting memory or threads.
constexpr std::size_t kMaxConcurrentRequests = 32;

// A client that connects and sends nothing is dropped after this long.
constexpr std::chrono::seconds kReadTimeout{60};

struct Context {
    engine::storage::StorageManager& manager;
    engine::chunks::ChunkManager& chunks;
    std::filesystem::path root;
};

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
    return json_response(status, version,
                          R"({"error":")" + engine::util::json_escape(message) + R"("})");
}

// --- routing ---------------------------------------------------------------

http::response<http::string_body> handle_hash(unsigned version, const JsonObject& body,
                                                const Context& ctx) {
    auto path = body.string("path");
    if (!path) {
        return error_response(http::status::bad_request, version, "missing \"path\"");
    }
    try {
        // Hashing may read stored objects (a scrub), but only inside the storage root.
        const auto safe = engine::util::confine(ctx.root, *path, /*allow_objects=*/true);
        auto hash = ctx.manager.hash_file(safe);
        return json_response(http::status::ok, version, R"({"hash":")" + hash + R"("})");
    } catch (const PathError& ex) {
        return error_response(http::status::bad_request, version, ex.what());
    } catch (const std::exception& ex) {
        return error_response(http::status::bad_request, version, ex.what());
    }
}

http::response<http::string_body> handle_objects_exists(unsigned version, const JsonObject& body,
                                                          const Context& ctx) {
    auto hash = body.string("hash");
    if (!hash) {
        return error_response(http::status::bad_request, version, "missing \"hash\"");
    }
    try {
        bool exists = ctx.manager.object_exists(*hash);
        return json_response(http::status::ok, version,
                              std::string(R"({"exists":)") + (exists ? "true" : "false") + "}");
    } catch (const engine::storage::InvalidHashError& ex) {
        return error_response(http::status::bad_request, version, ex.what());
    }
}

http::response<http::string_body> handle_objects_put(unsigned version, const JsonObject& body,
                                                       const Context& ctx) {
    auto hash = body.string("hash");
    auto source_path = body.string("source_path");
    if (!hash || !source_path) {
        return error_response(http::status::bad_request, version,
                               "missing \"hash\" or \"source_path\"");
    }
    try {
        const auto safe = engine::util::confine(ctx.root, *source_path, /*allow_objects=*/false);
        // The backend sets "verified" when the engine itself just hashed this very file, so the
        // second full read is skipped. Anything else is checked before it is stored.
        const bool verified = body.boolean("verified").value_or(false);
        ctx.manager.store_object(*hash, safe, /*verify=*/!verified);
        auto size = ctx.manager.object_size(*hash);
        return json_response(http::status::created, version,
                              R"({"stored":true,"size":)" + std::to_string(size) + "}");
    } catch (const engine::storage::InvalidHashError& ex) {
        return error_response(http::status::bad_request, version, ex.what());
    } catch (const PathError& ex) {
        return error_response(http::status::bad_request, version, ex.what());
    } catch (const engine::storage::ObjectCorruptedError& ex) {
        return error_response(http::status::conflict, version, ex.what());
    } catch (const std::exception& ex) {
        return error_response(http::status::internal_server_error, version, ex.what());
    }
}

http::response<http::string_body> handle_objects_get(unsigned version, const JsonObject& body,
                                                       const Context& ctx) {
    auto hash = body.string("hash");
    auto destination_path = body.string("destination_path");
    if (!hash || !destination_path) {
        return error_response(http::status::bad_request, version,
                               "missing \"hash\" or \"destination_path\"");
    }
    try {
        const auto safe =
            engine::util::confine(ctx.root, *destination_path, /*allow_objects=*/false);
        ctx.manager.retrieve_object(*hash, safe);
        auto size = ctx.manager.object_size(*hash);
        return json_response(http::status::ok, version, R"({"size":)" + std::to_string(size) + "}");
    } catch (const engine::storage::ObjectNotFoundError& ex) {
        return error_response(http::status::not_found, version, ex.what());
    } catch (const engine::storage::ObjectCorruptedError& ex) {
        return error_response(http::status::conflict, version, ex.what());
    } catch (const engine::storage::InvalidHashError& ex) {
        return error_response(http::status::bad_request, version, ex.what());
    } catch (const PathError& ex) {
        return error_response(http::status::bad_request, version, ex.what());
    } catch (const std::exception& ex) {
        return error_response(http::status::internal_server_error, version, ex.what());
    }
}

http::response<http::string_body> handle_objects_delete(unsigned version, const JsonObject& body,
                                                          const Context& ctx) {
    auto hash = body.string("hash");
    if (!hash) {
        return error_response(http::status::bad_request, version, "missing \"hash\"");
    }
    try {
        bool existed = ctx.manager.object_exists(*hash);
        ctx.manager.remove_object(*hash);
        return json_response(http::status::ok, version,
                              std::string(R"({"deleted":)") + (existed ? "true" : "false") + "}");
    } catch (const engine::storage::InvalidHashError& ex) {
        return error_response(http::status::bad_request, version, ex.what());
    }
}

http::response<http::string_body> handle_chunks_write(unsigned version, const JsonObject& body,
                                                        const Context& ctx) {
    auto upload_id = body.string("upload_id");
    auto index = body.integer("index");
    auto source_path = body.string("source_path");
    if (!upload_id || !index || !source_path) {
        return error_response(http::status::bad_request, version,
                               "missing \"upload_id\", \"index\", or \"source_path\"");
    }
    if (*index < 0 || *index > 1'000'000) {
        return error_response(http::status::bad_request, version, "\"index\" is out of range");
    }
    try {
        const auto safe = engine::util::confine(ctx.root, *source_path, /*allow_objects=*/false);
        ctx.chunks.write(*upload_id, static_cast<int>(*index), safe);
        return json_response(http::status::created, version, R"({"received":true})");
    } catch (const engine::chunks::InvalidUploadIdError& ex) {
        return error_response(http::status::bad_request, version, ex.what());
    } catch (const PathError& ex) {
        return error_response(http::status::bad_request, version, ex.what());
    } catch (const std::exception& ex) {
        return error_response(http::status::internal_server_error, version, ex.what());
    }
}

http::response<http::string_body> handle_chunks_finalize(unsigned version, const JsonObject& body,
                                                           const Context& ctx) {
    auto upload_id = body.string("upload_id");
    auto total_chunks = body.integer("total_chunks");
    if (!upload_id || !total_chunks) {
        return error_response(http::status::bad_request, version,
                               "missing \"upload_id\" or \"total_chunks\"");
    }
    if (*total_chunks <= 0 || *total_chunks > 1'000'000) {
        return error_response(http::status::bad_request, version,
                               "\"total_chunks\" is out of range");
    }
    auto expected_hash = body.string("expected_hash");  // optional
    try {
        auto result =
            ctx.chunks.finalize(*upload_id, static_cast<int>(*total_chunks), expected_hash);
        return json_response(http::status::ok, version,
                              R"({"hash":")" + result.hash + R"(","size":)" +
                                  std::to_string(result.size) + "}");
    } catch (const engine::chunks::MissingChunkError& ex) {
        return error_response(http::status::conflict, version, ex.what());
    } catch (const engine::chunks::HashMismatchError& ex) {
        return error_response(http::status::conflict, version, ex.what());
    } catch (const engine::chunks::InvalidUploadIdError& ex) {
        return error_response(http::status::bad_request, version, ex.what());
    } catch (const std::invalid_argument& ex) {
        return error_response(http::status::bad_request, version, ex.what());
    } catch (const std::exception& ex) {
        return error_response(http::status::internal_server_error, version, ex.what());
    }
}

http::response<http::string_body> handle_chunks_abandon(unsigned version, const JsonObject& body,
                                                          const Context& ctx) {
    auto upload_id = body.string("upload_id");
    if (!upload_id) {
        return error_response(http::status::bad_request, version, "missing \"upload_id\"");
    }
    try {
        bool removed = ctx.chunks.abandon(*upload_id);
        return json_response(http::status::ok, version,
                              std::string(R"({"removed":)") + (removed ? "true" : "false") + "}");
    } catch (const engine::chunks::InvalidUploadIdError& ex) {
        return error_response(http::status::bad_request, version, ex.what());
    }
}

http::response<http::string_body> route(const http::request<http::string_body>& req,
                                         const Context& ctx) {
    const unsigned version = req.version();
    if (req.method() == http::verb::get && req.target() == "/health") {
        return json_response(http::status::ok, version, R"({"status":"healthy"})");
    }
    if (req.method() != http::verb::post) {
        return error_response(http::status::not_found, version, "not found");
    }

    using Handler = http::response<http::string_body> (*)(unsigned, const JsonObject&,
                                                           const Context&);
    Handler handler = nullptr;
    if (req.target() == "/hash") {
        handler = handle_hash;
    } else if (req.target() == "/objects/exists") {
        handler = handle_objects_exists;
    } else if (req.target() == "/objects/put") {
        handler = handle_objects_put;
    } else if (req.target() == "/objects/get") {
        handler = handle_objects_get;
    } else if (req.target() == "/objects/delete") {
        handler = handle_objects_delete;
    } else if (req.target() == "/chunks/write") {
        handler = handle_chunks_write;
    } else if (req.target() == "/chunks/finalize") {
        handler = handle_chunks_finalize;
    } else if (req.target() == "/chunks/abandon") {
        handler = handle_chunks_abandon;
    }
    if (handler == nullptr) {
        return error_response(http::status::not_found, version, "not found");
    }

    try {
        const auto body = engine::util::parse_flat_object(req.body());
        return handler(version, body, ctx);
    } catch (const JsonError& ex) {
        return error_response(http::status::bad_request, version,
                               std::string("invalid request body: ") + ex.what());
    }
}

// Counts requests in flight and makes the accept loop wait when too many are running.
class ConcurrencyGate {
   public:
    void enter() {
        std::unique_lock<std::mutex> lock(mutex_);
        cv_.wait(lock, [this] { return active_ < kMaxConcurrentRequests; });
        ++active_;
    }
    void leave() {
        {
            std::lock_guard<std::mutex> lock(mutex_);
            --active_;
        }
        cv_.notify_one();
    }

   private:
    std::mutex mutex_;
    std::condition_variable cv_;
    std::size_t active_ = 0;
};

void handle_connection(tcp::socket socket, const Context& ctx) {
    beast::error_code ec;
    beast::tcp_stream stream(std::move(socket));
    beast::flat_buffer buffer;

    http::request<http::string_body> req;
    stream.expires_after(kReadTimeout);
    http::read(stream, buffer, req, ec);
    if (ec) {
        return;
    }
    stream.expires_never();  // the work below (hashing a large file) may take minutes

    http::response<http::string_body> res;
    try {
        res = route(req, ctx);
    } catch (const std::exception& ex) {
        // Nothing may take the whole engine down: one bad request answers 500 and the
        // next one is served normally.
        res = error_response(http::status::internal_server_error, req.version(), ex.what());
    } catch (...) {
        res = error_response(http::status::internal_server_error, req.version(),
                              "unexpected error");
    }
    res.keep_alive(false);
    http::write(stream, res, ec);

    stream.socket().shutdown(tcp::socket::shutdown_send, ec);
}

}  // namespace

EngineServer::EngineServer(std::string host, uint16_t port, std::string storage_root)
    : host_(std::move(host)), port_(port), storage_root_(std::move(storage_root)) {}

void EngineServer::run() {
    engine::storage::StorageManager manager(storage_root_);
    engine::chunks::ChunkManager chunk_manager(storage_root_, manager);
    const Context ctx{manager, chunk_manager, std::filesystem::path(storage_root_)};

    asio::io_context ioc{1};
    tcp::acceptor acceptor{ioc, {asio::ip::make_address(host_), port_}};

    std::cout << "engine listening on " << host_ << ":" << port_ << " (storage root "
              << storage_root_ << ")" << std::endl;

    ConcurrencyGate gate;
    for (;;) {
        tcp::socket socket{ioc};
        acceptor.accept(socket);
        gate.enter();
        std::thread([&gate, &ctx, sock = std::move(socket)]() mutable {
            handle_connection(std::move(sock), ctx);
            gate.leave();
        }).detach();
    }
}

}  // namespace engine::api

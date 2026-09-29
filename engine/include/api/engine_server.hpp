#pragma once

#include <cstdint>
#include <string>

namespace engine::api {

// Minimal local-only HTTP server for the C++ data-plane engine.
//
// Exposes GET /health, the object-storage endpoints from Phase 4
// (POST /objects/exists, /objects/put, /objects/get, /objects/delete,
// POST /hash), and the chunked-upload endpoints from Phase 5
// (POST /chunks/write, /chunks/finalize, /chunks/abandon — see
// docs/architecture.md#19-c-engine-api). Sync primitives (Phase 7+) are
// added as their phase lands. This server must never be exposed outside
// the Docker-internal network.
class EngineServer {
   public:
    EngineServer(std::string host, uint16_t port, std::string storage_root);

    // Blocks, accepting and handling connections one at a time until the
    // process is terminated.
    void run();

   private:
    std::string host_;
    uint16_t port_;
    std::string storage_root_;
};

}  // namespace engine::api

#include <cstdlib>
#include <string>

#include "api/engine_server.hpp"

namespace {

std::string env_or(const char* name, std::string fallback) {
    const char* value = std::getenv(name);
    return value != nullptr ? std::string(value) : std::move(fallback);
}

uint16_t env_port_or(const char* name, uint16_t fallback) {
    const char* value = std::getenv(name);
    if (value == nullptr) {
        return fallback;
    }
    return static_cast<uint16_t>(std::stoi(value));
}

}  // namespace

int main() {
    const std::string host = env_or("ENGINE_HOST", "0.0.0.0");
    const uint16_t port = env_port_or("ENGINE_PORT", 9000);
    const std::string storage_root = env_or("STORAGE_ROOT", "/data/cloud");

    engine::api::EngineServer server(host, port, storage_root);
    server.run();

    return 0;
}

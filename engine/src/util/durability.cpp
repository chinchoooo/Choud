#include "util/durability.hpp"

#include <atomic>
#include <cerrno>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <thread>

#ifndef _WIN32
#include <fcntl.h>
#include <unistd.h>
#endif

namespace engine::util {

namespace {

std::mutex g_handler_mutex;
std::function<void(const char*)> g_handler;

#ifndef _WIN32
void sync_path(const std::filesystem::path& path, int flags, const char* what) {
    const int fd = ::open(path.c_str(), flags);
    if (fd < 0) {
        throw std::runtime_error(std::string("could not open ") + what + " " + path.string() +
                                 " to flush it: " + std::strerror(errno));
    }
    const int rc = ::fsync(fd);
    const int saved = errno;
    ::close(fd);
    if (rc != 0) {
        throw std::runtime_error(std::string("could not flush ") + what + " " + path.string() +
                                 " to disk: " + std::strerror(saved));
    }
}
#endif

}  // namespace

void fsync_file(const std::filesystem::path& path) {
#ifndef _WIN32
    sync_path(path, O_RDONLY, "file");
#else
    (void)path;  // the engine only runs on Linux in production; tests elsewhere skip this
#endif
}

void fsync_dir(const std::filesystem::path& path) {
#ifndef _WIN32
    sync_path(path, O_RDONLY | O_DIRECTORY, "directory");
#else
    (void)path;
#endif
}

std::string unique_suffix() {
    static std::atomic<unsigned long long> counter{0};
    std::ostringstream out;
    out << std::this_thread::get_id() << '-' << counter.fetch_add(1);
#ifndef _WIN32
    out << '-' << ::getpid();
#endif
    return out.str();
}

void set_fault_handler(std::function<void(const char*)> handler) {
    std::lock_guard<std::mutex> lock(g_handler_mutex);
    g_handler = std::move(handler);
}

void fault_point(const char* point) {
    std::function<void(const char*)> handler;
    {
        std::lock_guard<std::mutex> lock(g_handler_mutex);
        handler = g_handler;
    }
    if (handler) {
        handler(point);
        return;
    }
    const char* at = std::getenv("ENGINE_FAULT_AT");
    if (at != nullptr && std::strcmp(at, point) == 0) {
        std::_Exit(137);  // a power cut: no cleanup runs
    }
}

}  // namespace engine::util

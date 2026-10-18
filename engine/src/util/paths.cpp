#include "util/paths.hpp"

namespace engine::util {

namespace {

bool is_inside(const std::filesystem::path& base, const std::filesystem::path& path) {
    auto base_it = base.begin();
    auto path_it = path.begin();
    for (; base_it != base.end(); ++base_it, ++path_it) {
        if (path_it == path.end() || *path_it != *base_it) {
            return false;
        }
    }
    return true;
}

}  // namespace

std::filesystem::path confine(const std::filesystem::path& root, const std::string& candidate,
                              bool allow_objects) {
    if (candidate.empty()) {
        throw PathError("an empty path was given");
    }
    if (candidate.find('\0') != std::string::npos) {
        throw PathError("a path may not contain a NUL character");
    }
    const std::filesystem::path given(candidate);
    if (!given.is_absolute()) {
        throw PathError("path must be absolute: " + candidate);
    }

    std::error_code ec;
    const auto base = std::filesystem::weakly_canonical(root, ec);
    if (ec) {
        throw PathError("the storage root cannot be resolved");
    }
    const auto resolved = std::filesystem::weakly_canonical(given, ec);
    if (ec) {
        throw PathError("path cannot be resolved: " + candidate);
    }
    if (resolved == base || !is_inside(base, resolved)) {
        throw PathError("path is outside the storage root: " + candidate);
    }
    if (!allow_objects && is_inside(base / "objects", resolved)) {
        throw PathError("path is inside the object store, which is read-only here: " + candidate);
    }
    return resolved;
}

}  // namespace engine::util

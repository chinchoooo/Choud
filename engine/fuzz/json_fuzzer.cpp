// libFuzzer target for the engine's request parsing: whatever bytes arrive, the JSON
// reader must either return an object or throw JsonError, and the path check must either
// return a path or throw PathError. Anything else (a crash, a hang, a different exception,
// undefined behaviour) is a bug.
//
// Build and run (needs clang):
//   cmake -S engine -B build-fuzz -DCMAKE_CXX_COMPILER=clang++ -DENGINE_FUZZ=ON
//   cmake --build build-fuzz --target json_fuzzer
//   build-fuzz/fuzz/json_fuzzer -max_total_time=60

#include <cstddef>
#include <cstdint>
#include <string>

#include "util/json.hpp"
#include "util/paths.hpp"

extern "C" int LLVMFuzzerTestOneInput(const uint8_t* data, size_t size) {
    const std::string text(reinterpret_cast<const char*>(data), size);
    try {
        const auto object = engine::util::parse_flat_object(text);
        for (const auto& [key, value] : object.fields_) {
            // A parsed string must survive being escaped and read back.
            if (const auto* s = std::get_if<std::string>(&value)) {
                const auto round = engine::util::parse_flat_object(
                    "{\"k\":\"" + engine::util::json_escape(*s) + "\"}");
                if (round.string("k") != *s) {
                    __builtin_trap();
                }
                try {
                    engine::util::confine("/tmp/engine-fuzz-root", *s, false);
                } catch (const engine::util::PathError&) {
                }
            }
            (void)key;
        }
    } catch (const engine::util::JsonError&) {
    }
    return 0;
}

#pragma once

// A small, strict JSON reader for the engine's request bodies.
//
// The bodies are flat objects of strings, whole numbers, booleans and nulls
// (see docs/api.md, "Internal: C++ engine API"). This parser handles exactly
// that, fully and correctly (escapes, \uXXXX including surrogate pairs, no
// trailing garbage, no duplicate keys, no nested values), instead of pulling
// in a general JSON library for a four-field protocol. Anything it does not
// understand is an error, never a guess.

#include <map>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <variant>

namespace engine::util {

class JsonError : public std::runtime_error {
   public:
    using std::runtime_error::runtime_error;
};

using JsonValue = std::variant<std::nullptr_t, bool, long long, std::string>;

class JsonObject {
   public:
    // Each returns nullopt when the key is absent and throws JsonError when
    // the key is present with a value of the wrong type.
    std::optional<std::string> string(const std::string& key) const;
    std::optional<long long> integer(const std::string& key) const;
    std::optional<bool> boolean(const std::string& key) const;
    bool has(const std::string& key) const { return fields_.count(key) != 0; }

    std::map<std::string, JsonValue> fields_;
};

// Throws JsonError on any problem.
JsonObject parse_flat_object(std::string_view text);

// Escapes a value for use inside a JSON string (quotes, backslashes, control
// characters).
std::string json_escape(std::string_view value);

}  // namespace engine::util

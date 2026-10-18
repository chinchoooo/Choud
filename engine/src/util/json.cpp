#include "util/json.hpp"

#include <cstdint>

namespace engine::util {

namespace {

class Reader {
   public:
    explicit Reader(std::string_view text) : text_(text) {}

    JsonObject parse() {
        skip_space();
        expect('{');
        JsonObject object;
        skip_space();
        if (peek() == '}') {
            ++pos_;
        } else {
            for (;;) {
                skip_space();
                auto key = read_string();
                skip_space();
                expect(':');
                skip_space();
                auto value = read_value();
                if (!object.fields_.emplace(std::move(key), std::move(value)).second) {
                    throw JsonError("duplicate key in JSON object");
                }
                skip_space();
                const char c = next();
                if (c == '}') {
                    break;
                }
                if (c != ',') {
                    throw JsonError("expected ',' or '}' in JSON object");
                }
            }
        }
        skip_space();
        if (pos_ != text_.size()) {
            throw JsonError("unexpected text after the JSON object");
        }
        return object;
    }

   private:
    char peek() const { return pos_ < text_.size() ? text_[pos_] : '\0'; }

    char next() {
        if (pos_ >= text_.size()) {
            throw JsonError("unexpected end of JSON");
        }
        return text_[pos_++];
    }

    void expect(char c) {
        if (next() != c) {
            throw JsonError(std::string("expected '") + c + "' in JSON");
        }
    }

    void skip_space() {
        while (pos_ < text_.size() &&
               (text_[pos_] == ' ' || text_[pos_] == '\t' || text_[pos_] == '\n' ||
                text_[pos_] == '\r')) {
            ++pos_;
        }
    }

    unsigned read_hex4() {
        unsigned value = 0;
        for (int i = 0; i < 4; ++i) {
            const char c = next();
            value <<= 4;
            if (c >= '0' && c <= '9') {
                value |= static_cast<unsigned>(c - '0');
            } else if (c >= 'a' && c <= 'f') {
                value |= static_cast<unsigned>(c - 'a' + 10);
            } else if (c >= 'A' && c <= 'F') {
                value |= static_cast<unsigned>(c - 'A' + 10);
            } else {
                throw JsonError("bad \\u escape in JSON string");
            }
        }
        return value;
    }

    static void append_utf8(std::string& out, unsigned code) {
        if (code < 0x80) {
            out.push_back(static_cast<char>(code));
        } else if (code < 0x800) {
            out.push_back(static_cast<char>(0xC0 | (code >> 6)));
            out.push_back(static_cast<char>(0x80 | (code & 0x3F)));
        } else if (code < 0x10000) {
            out.push_back(static_cast<char>(0xE0 | (code >> 12)));
            out.push_back(static_cast<char>(0x80 | ((code >> 6) & 0x3F)));
            out.push_back(static_cast<char>(0x80 | (code & 0x3F)));
        } else {
            out.push_back(static_cast<char>(0xF0 | (code >> 18)));
            out.push_back(static_cast<char>(0x80 | ((code >> 12) & 0x3F)));
            out.push_back(static_cast<char>(0x80 | ((code >> 6) & 0x3F)));
            out.push_back(static_cast<char>(0x80 | (code & 0x3F)));
        }
    }

    std::string read_string() {
        expect('"');
        std::string out;
        for (;;) {
            const char c = next();
            if (c == '"') {
                return out;
            }
            if (static_cast<unsigned char>(c) < 0x20) {
                throw JsonError("raw control character inside a JSON string");
            }
            if (c != '\\') {
                out.push_back(c);
                continue;
            }
            const char escape = next();
            switch (escape) {
                case '"': out.push_back('"'); break;
                case '\\': out.push_back('\\'); break;
                case '/': out.push_back('/'); break;
                case 'b': out.push_back('\b'); break;
                case 'f': out.push_back('\f'); break;
                case 'n': out.push_back('\n'); break;
                case 'r': out.push_back('\r'); break;
                case 't': out.push_back('\t'); break;
                case 'u': {
                    unsigned code = read_hex4();
                    if (code >= 0xD800 && code <= 0xDBFF) {
                        if (next() != '\\' || next() != 'u') {
                            throw JsonError("unpaired surrogate in JSON string");
                        }
                        const unsigned low = read_hex4();
                        if (low < 0xDC00 || low > 0xDFFF) {
                            throw JsonError("unpaired surrogate in JSON string");
                        }
                        code = 0x10000 + ((code - 0xD800) << 10) + (low - 0xDC00);
                    } else if (code >= 0xDC00 && code <= 0xDFFF) {
                        throw JsonError("unpaired surrogate in JSON string");
                    }
                    if (code == 0) {
                        throw JsonError("a NUL character is not allowed in a value");
                    }
                    append_utf8(out, code);
                    break;
                }
                default:
                    throw JsonError("bad escape in JSON string");
            }
        }
    }

    JsonValue read_value() {
        const char c = peek();
        if (c == '"') {
            return read_string();
        }
        if (c == '-' || (c >= '0' && c <= '9')) {
            return read_integer();
        }
        if (text_.substr(pos_, 4) == "true") {
            pos_ += 4;
            return true;
        }
        if (text_.substr(pos_, 5) == "false") {
            pos_ += 5;
            return false;
        }
        if (text_.substr(pos_, 4) == "null") {
            pos_ += 4;
            return nullptr;
        }
        if (c == '{' || c == '[') {
            throw JsonError("nested JSON values are not supported");
        }
        throw JsonError("unexpected value in JSON");
    }

    long long read_integer() {
        const std::size_t start = pos_;
        if (peek() == '-') {
            ++pos_;
        }
        const std::size_t digits = pos_;
        while (pos_ < text_.size() && text_[pos_] >= '0' && text_[pos_] <= '9') {
            ++pos_;
        }
        if (pos_ == digits || pos_ - digits > 18) {
            throw JsonError("bad number in JSON");
        }
        if (text_[digits] == '0' && pos_ - digits > 1) {
            throw JsonError("a number may not start with 0");
        }
        if (peek() == '.' || peek() == 'e' || peek() == 'E') {
            throw JsonError("only whole numbers are supported");
        }
        return std::stoll(std::string(text_.substr(start, pos_ - start)));
    }

    std::string_view text_;
    std::size_t pos_ = 0;
};

}  // namespace

std::optional<std::string> JsonObject::string(const std::string& key) const {
    const auto it = fields_.find(key);
    if (it == fields_.end()) {
        return std::nullopt;
    }
    if (const auto* value = std::get_if<std::string>(&it->second)) {
        return *value;
    }
    throw JsonError("\"" + key + "\" must be a string");
}

std::optional<long long> JsonObject::integer(const std::string& key) const {
    const auto it = fields_.find(key);
    if (it == fields_.end()) {
        return std::nullopt;
    }
    if (const auto* value = std::get_if<long long>(&it->second)) {
        return *value;
    }
    throw JsonError("\"" + key + "\" must be a whole number");
}

std::optional<bool> JsonObject::boolean(const std::string& key) const {
    const auto it = fields_.find(key);
    if (it == fields_.end()) {
        return std::nullopt;
    }
    if (const auto* value = std::get_if<bool>(&it->second)) {
        return *value;
    }
    throw JsonError("\"" + key + "\" must be true or false");
}

JsonObject parse_flat_object(std::string_view text) {
    return Reader(text).parse();
}

std::string json_escape(std::string_view value) {
    static const char* hex = "0123456789abcdef";
    std::string out;
    out.reserve(value.size());
    for (const unsigned char c : value) {
        switch (c) {
            case '"': out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\b': out += "\\b"; break;
            case '\f': out += "\\f"; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default:
                if (c < 0x20) {
                    out += "\\u00";
                    out.push_back(hex[c >> 4]);
                    out.push_back(hex[c & 0xF]);
                } else {
                    out.push_back(static_cast<char>(c));
                }
        }
    }
    return out;
}

}  // namespace engine::util

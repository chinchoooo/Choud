#include "hashing/hasher.hpp"

#include <openssl/evp.h>

#include <array>
#include <fstream>
#include <sstream>
#include <stdexcept>

namespace engine::hashing {

struct Sha256Stream::Impl {
    EVP_MD_CTX* ctx;
};

Sha256Stream::Sha256Stream() : impl_(new Impl{EVP_MD_CTX_new()}) {
    if (impl_->ctx == nullptr) {
        throw std::runtime_error("failed to allocate EVP_MD_CTX");
    }
    if (EVP_DigestInit_ex(impl_->ctx, EVP_sha256(), nullptr) != 1) {
        EVP_MD_CTX_free(impl_->ctx);
        throw std::runtime_error("failed to initialize SHA-256 digest");
    }
}

Sha256Stream::~Sha256Stream() {
    if (impl_ != nullptr) {
        EVP_MD_CTX_free(impl_->ctx);
        delete impl_;
    }
}

void Sha256Stream::update(const unsigned char* data, std::size_t length) {
    if (EVP_DigestUpdate(impl_->ctx, data, length) != 1) {
        throw std::runtime_error("SHA-256 update failed");
    }
}

std::string Sha256Stream::hex_digest() {
    unsigned char digest[EVP_MAX_MD_SIZE];
    unsigned int digest_len = 0;
    if (EVP_DigestFinal_ex(impl_->ctx, digest, &digest_len) != 1) {
        throw std::runtime_error("SHA-256 finalize failed");
    }

    static constexpr char kHex[] = "0123456789abcdef";
    std::string out;
    out.reserve(static_cast<std::size_t>(digest_len) * 2);
    for (unsigned int i = 0; i < digest_len; ++i) {
        out.push_back(kHex[(digest[i] >> 4) & 0x0F]);
        out.push_back(kHex[digest[i] & 0x0F]);
    }
    return out;
}

std::string hash_file(const std::filesystem::path& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        throw std::runtime_error("could not open file for hashing: " + path.string());
    }

    Sha256Stream hasher;
    std::array<char, kStreamBufferSize> buffer{};
    while (in.read(buffer.data(), static_cast<std::streamsize>(buffer.size())) || in.gcount() > 0) {
        hasher.update(reinterpret_cast<const unsigned char*>(buffer.data()),
                      static_cast<std::size_t>(in.gcount()));
    }
    return hasher.hex_digest();
}

std::string hash_bytes(const unsigned char* data, std::size_t length) {
    Sha256Stream hasher;
    hasher.update(data, length);
    return hasher.hex_digest();
}

}  // namespace engine::hashing

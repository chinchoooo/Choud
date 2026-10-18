# Fuzz targets (clang + libFuzzer). Enabled with -DENGINE_FUZZ=ON.
add_executable(json_fuzzer json_fuzzer.cpp)
target_compile_options(json_fuzzer PRIVATE -fsanitize=fuzzer,address,undefined -fno-omit-frame-pointer -g)
target_link_options(json_fuzzer PRIVATE -fsanitize=fuzzer,address,undefined)
target_link_libraries(json_fuzzer PRIVATE engine_core)

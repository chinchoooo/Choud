find_package(GTest REQUIRED)
include(GoogleTest)

add_executable(engine_tests
    engine_server_tests.cpp
    hashing_tests.cpp
    storage_tests.cpp
    chunk_tests.cpp
)
target_link_libraries(engine_tests PRIVATE engine_core GTest::gtest GTest::gtest_main)

gtest_discover_tests(engine_tests)

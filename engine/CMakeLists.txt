cmake_minimum_required(VERSION 3.20)
project(personal_cloud_engine CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif()

find_package(Boost REQUIRED)
find_package(Threads REQUIRED)
find_package(OpenSSL REQUIRED)

add_library(engine_core
    src/api/engine_server.cpp
    src/hashing/hasher.cpp
    src/storage/object_store.cpp
    src/storage/storage_manager.cpp
    src/chunks/chunk_store.cpp
    src/chunks/chunk_manager.cpp
)
target_include_directories(engine_core PUBLIC include)
target_link_libraries(engine_core PUBLIC Boost::boost Threads::Threads OpenSSL::Crypto)

add_executable(personal_cloud_engine src/main.cpp)
target_link_libraries(personal_cloud_engine PRIVATE engine_core)

enable_testing()
add_subdirectory(tests)

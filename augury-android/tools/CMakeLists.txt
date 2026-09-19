# ---------------------------------------------------------------------------
# Host build of the Android engine core (see tools/host_test.cpp for why).
#
# Compiles the SAME app/src/main/cpp/augury_engine.cpp that ships in
# libaugury_llama.so, against the same pinned llama.cpp, as a Linux binary.
# ---------------------------------------------------------------------------
cmake_minimum_required(VERSION 3.22)
project(augury_host_test CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif()

set(AUGURY_ROOT      "${CMAKE_CURRENT_SOURCE_DIR}/..")
set(AUGURY_CPP_DIR   "${AUGURY_ROOT}/app/src/main/cpp")
set(AUGURY_LLAMA_DIR "${AUGURY_ROOT}/third_party/llama.cpp")

if(NOT EXISTS "${AUGURY_LLAMA_DIR}/CMakeLists.txt")
    message(FATAL_ERROR "llama.cpp not found at ${AUGURY_LLAMA_DIR}")
endif()

# Same options as the Android build: static, no tools/tests/server.
set(BUILD_SHARED_LIBS    OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_TESTS    OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_TOOLS    OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_SERVER   OFF CACHE BOOL "" FORCE)
set(LLAMA_CURL           OFF CACHE BOOL "" FORCE)
# ggml's runtime CPU dispatch is on by default for a native build, which is what
# we want here (the host CPU genuinely has AVX2). The Android x86_64 build pins
# SSE4.2 instead, because the TCG emulator lacks AVX -- see app/src/main/cpp/CMakeLists.txt.
set(GGML_NATIVE          ON  CACHE BOOL "" FORCE)

add_subdirectory("${AUGURY_LLAMA_DIR}" "${CMAKE_CURRENT_BINARY_DIR}/llama.cpp")

add_executable(augury_host_test
    host_test.cpp
    "${AUGURY_CPP_DIR}/augury_engine.cpp"
)

target_include_directories(augury_host_test PRIVATE "${AUGURY_CPP_DIR}")
target_compile_options(augury_host_test PRIVATE -O3 -fexceptions -frtti)
target_link_libraries(augury_host_test PRIVATE llama ggml)

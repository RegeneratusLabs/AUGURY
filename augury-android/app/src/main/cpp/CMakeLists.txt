# ---------------------------------------------------------------------------
# AUGURY Gate C / W5 spike -- native llama.cpp shim
#
# Builds ONE shared library, libaugury_llama.so, for each requested ABI.
# llama.cpp + ggml are compiled *statically* into it (BUILD_SHARED_LIBS=OFF) so
# the APK ships a single .so instead of libllama.so + libggml*.so + JNI glue.
# ---------------------------------------------------------------------------
cmake_minimum_required(VERSION 3.22.1)

project(augury_llama C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(AUGURY_LLAMA_CPP_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../../../third_party/llama.cpp")
if(NOT EXISTS "${AUGURY_LLAMA_CPP_DIR}/CMakeLists.txt")
    message(FATAL_ERROR
        "llama.cpp sources not found at ${AUGURY_LLAMA_CPP_DIR}.\n"
        "Run scripts/fetch-llama-cpp.sh first.")
endif()

# ---------------------------------------------------------------------------
# llama.cpp build options -- MUST be set before add_subdirectory().
# ---------------------------------------------------------------------------
set(BUILD_SHARED_LIBS        OFF CACHE BOOL "" FORCE)  # static -> one .so ships
set(LLAMA_BUILD_IS_DEV       OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_COMMON       OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_TESTS        OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_TOOLS        OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_EXAMPLES     OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_SERVER       OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_APP          OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_MTMD         OFF CACHE BOOL "" FORCE)
set(LLAMA_CURL               OFF CACHE BOOL "" FORCE)
set(LLAMA_OPENSSL            OFF CACHE BOOL "" FORCE)
set(LLAMA_LLGUIDANCE         OFF CACHE BOOL "" FORCE)
set(GGML_OPENMP              OFF CACHE BOOL "" FORCE)  # no libomp.so in the APK
set(GGML_LLAMAFILE           OFF CACHE BOOL "" FORCE)  # x86-only tinyBLAS; unused here
set(GGML_BLAS                OFF CACHE BOOL "" FORCE)
set(GGML_CCACHE              OFF CACHE BOOL "" FORCE)
set(GGML_ACCELERATE          OFF CACHE BOOL "" FORCE)
set(GGML_ALL_WARNINGS        OFF CACHE BOOL "" FORCE)
set(GGML_ALL_WARNINGS_3RD_PARTY OFF CACHE BOOL "" FORCE)
set(GGML_FATAL_WARNINGS      OFF CACHE BOOL "" FORCE)

# ---------------------------------------------------------------------------
# x86_64 ISA baseline.
#
# ggml turns AVX/AVX2/FMA/F16C/BMI2 ON by default whenever it is cross-compiling
# (ggml/CMakeLists.txt: INS_ENB = NOT GGML_NATIVE_DEFAULT, and GGML_NATIVE_DEFAULT
# is OFF under CMAKE_CROSSCOMPILING). Those flags are compiled in unconditionally,
# so the resulting .so executes AVX2/F16C instructions on any CPU that reports
# them at build time -- there is no per-function runtime dispatch.
#
# The only x86_64 Android device on this host is the emulator, and this host has
# no /dev/kvm, so the emulator runs QEMU-TCG. That guest CPU advertises neither
# AVX nor F16C (the emulator logs "TCG doesn't support requested feature:
# CPUID.01H:ECX.avx"). An AVX2-built ggml therefore SIGILLs inside the guest.
# Pin x86_64 to the SSE4.2 baseline so the spike actually runs there.
#
# arm64-v8a is left at the NDK default (armv8-a baseline + NEON), which is what
# real phones need anyway -- no dotprod/i8mm/SVE assumptions.
# ---------------------------------------------------------------------------
if(ANDROID_ABI STREQUAL "x86_64")
    message(STATUS "augury: x86_64 -> pinning ggml to the SSE4.2 baseline (no AVX/FMA/F16C)")
    set(GGML_SSE42 ON  CACHE BOOL "" FORCE)
    set(GGML_AVX   OFF CACHE BOOL "" FORCE)
    set(GGML_AVX2  OFF CACHE BOOL "" FORCE)
    set(GGML_FMA   OFF CACHE BOOL "" FORCE)
    set(GGML_F16C  OFF CACHE BOOL "" FORCE)
    set(GGML_BMI2  OFF CACHE BOOL "" FORCE)
    set(GGML_AVX_VNNI OFF CACHE BOOL "" FORCE)
    set(GGML_AVX512  OFF CACHE BOOL "" FORCE)
endif()

add_subdirectory("${AUGURY_LLAMA_CPP_DIR}" "${CMAKE_CURRENT_BINARY_DIR}/llama.cpp")

# ---------------------------------------------------------------------------
# The JNI shim itself.
# ---------------------------------------------------------------------------
add_library(augury_llama SHARED
    augury_engine.cpp
    augury_jni.cpp
)

target_include_directories(augury_llama PRIVATE
    "${CMAKE_CURRENT_SOURCE_DIR}"
    "${AUGURY_LLAMA_CPP_DIR}/include"
    "${AUGURY_LLAMA_CPP_DIR}/ggml/include"
)

target_compile_options(augury_llama PRIVATE -O3 -fexceptions -frtti -Wall -Wextra)

# `llama` PUBLIC-links `ggml`, which links `ggml-base` + the CPU backend.
target_link_libraries(augury_llama PRIVATE llama ggml)

find_library(ANDROID_LOG_LIB log)
if(ANDROID_LOG_LIB)
    target_link_libraries(augury_llama PRIVATE ${ANDROID_LOG_LIB})
endif()

# Keep the JNI entry points; strip everything else in release.
target_link_options(augury_llama PRIVATE "-Wl,--exclude-libs,ALL")

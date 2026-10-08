#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Fetch the pinned llama.cpp sources for the AUGURY Android native formatter.
#
#   ./scripts/fetch-llama-cpp.sh
#
# This is OPTIONAL. The shipped AUGURY build is template-only and never loads the
# formatter, so a clean clone builds without llama.cpp -- CMake compiles
# `augury_jni_stub.cpp` instead (see app/src/main/cpp/CMakeLists.txt). Run this
# script only if you are working on the native engine or building the separate
# conversational version.
#
# The sources land in `third_party/llama.cpp`, which is gitignored: it is a
# vendored build input, not part of the repository.
#
# Why a pinned commit and not a branch: `app/build.gradle.kts` asserts the exact
# revision (`checkLlamaCppPin`) because llama.cpp's C API moves, and the JNI shim
# in `app/src/main/cpp/` is written against one revision.
# ---------------------------------------------------------------------------
set -euo pipefail

PIN="60081bb2b5b3294165a4d67c5cbeebe74c868014"
REMOTE="${AUGURY_LLAMA_REMOTE:-https://github.com/ggml-org/llama.cpp.git}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANDROID_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEST="${ANDROID_DIR}/third_party/llama.cpp"

echo "llama.cpp pin : ${PIN}"
echo "remote        : ${REMOTE}"
echo "destination   : ${DEST}"

# --- already correct? -------------------------------------------------------
if [ -d "${DEST}/.git" ] && [ -f "${DEST}/CMakeLists.txt" ]; then
    current="$(git -C "${DEST}" rev-parse HEAD 2>/dev/null || echo unknown)"
    if [ "${current}" = "${PIN}" ]; then
        echo "already at the pinned revision -- nothing to do."
        exit 0
    fi
    echo "existing checkout at ${current}; fetching the pin..."
    if git -C "${DEST}" fetch --depth 1 origin "${PIN}" 2>/dev/null; then
        git -C "${DEST}" checkout --detach FETCH_HEAD
        echo "now at $(git -C "${DEST}" rev-parse HEAD)"
        exit 0
    fi
    echo "shallow fetch by SHA was refused; falling back to a full fetch."
    git -C "${DEST}" fetch --tags origin
    git -C "${DEST}" checkout --detach "${PIN}"
    echo "now at $(git -C "${DEST}" rev-parse HEAD)"
    exit 0
fi

# --- fresh checkout ---------------------------------------------------------
mkdir -p "$(dirname "${DEST}")"

# Prefer a blobless clone: llama.cpp's history is large and the build only needs
# the working tree at one commit.
if git clone --filter=blob:none --no-checkout "${REMOTE}" "${DEST}" 2>/dev/null; then
    if git -C "${DEST}" checkout --detach "${PIN}" 2>/dev/null; then
        echo "checked out ${PIN}"
        exit 0
    fi
    echo "pin not reachable in the partial clone; fetching it explicitly..."
    if git -C "${DEST}" fetch --depth 1 origin "${PIN}" 2>/dev/null; then
        git -C "${DEST}" checkout --detach FETCH_HEAD
        echo "checked out ${PIN}"
        exit 0
    fi
    echo "removing the partial clone and retrying with a full clone."
    rm -rf "${DEST}"
fi

git clone "${REMOTE}" "${DEST}"
git -C "${DEST}" checkout --detach "${PIN}"
echo "checked out ${PIN}"

echo
echo "Done. Rebuild the app; CMake will detect the sources and compile the real"
echo "engine instead of the stub. Verify the pin with:"
echo "    cd ${ANDROID_DIR} && ./gradlew checkLlamaCppPin"

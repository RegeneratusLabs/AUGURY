#!/usr/bin/env bash
# Run the Android emulator's QEMU binary DIRECTLY, bypassing the `emulator`
# launcher wrapper (gRPC server, crash handler, SwiftShader "environment scene",
# hung-thread watchdog). Used because the wrapper SIGSEGVs during graphics
# bring-up on this host; QEMU itself provides the console (5554) and adb (5555).
#
# The argument vector is captured verbatim from `emulator -verbose` output
# (see README "Build obstacles"). Two flags in that captured list are consumed by
# the launcher and are NOT understood by Android's QEMU fork, so they are dropped:
#   -no-audio
#   -serial null
#
# Re-capture with:
#   emulator -avd <name> ... -verbose 2>&1 | grep 'Concatenated QEMU options:'
set -euo pipefail

EMU_DIR=/home/jthomson/Android/Sdk/emulator
QEMU_CMD_FILE="${1:?usage: run-qemu-direct.sh <qemu-cmd-file>}"

export LD_LIBRARY_PATH="$EMU_DIR/lib64:$EMU_DIR/lib64/gles_swiftshader:$EMU_DIR/lib64/gles_angle:$EMU_DIR/lib64/gles_llvmpipe:${LD_LIBRARY_PATH:-}"

# Re-split the captured command line respecting the embedded quotes (the -append
# value is single-quoted), then drop the launcher-only flags.
eval "set -- $(cat "$QEMU_CMD_FILE")"

args=()
skip_next=0
for a in "$@"; do
    if [ "$skip_next" = "1" ]; then skip_next=0; continue; fi
    case "$a" in
        -no-audio)   continue ;;
        -serial)     skip_next=1; continue ;;
    esac
    args+=("$a")
done

exec "${args[@]}"

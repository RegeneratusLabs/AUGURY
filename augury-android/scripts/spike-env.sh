#!/usr/bin/env bash
# Environment shim for the AUGURY Android spike.
#
# WHY THIS EXISTS
# ---------------
# This sandbox mounts $HOME (and therefore ~/.gradle, ~/.android, ~/.cache) read-only,
# and DSH pins TMPDIR at a read-only path. Gradle, adb and the Android emulator all
# need writable state, so we redirect every one of those locations into a writable
# directory that lives *outside* the git repo (../.dsh-runtime).
#
# Source this before running gradle / adb / emulator:
#     source scripts/spike-env.sh
#
# On a normal machine you do NOT need this file: just set ANDROID_HOME (or rely on
# local.properties) and run ./gradlew. See README.md.

export AUGURY_ANDROID_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export RT="${AUGURY_RUNTIME_DIR:-$(dirname "$AUGURY_ANDROID_DIR")/.dsh-runtime}"

mkdir -p "$RT/home" "$RT/avd" "$RT/tmp" "$RT/xdg" "$RT/logs" "$RT/gradle-home"

# Writable stand-ins for the read-only standard locations.
export HOME="$RT/home"
export TMPDIR="$RT/tmp"
export XDG_RUNTIME_DIR="$RT/xdg"
export XDG_CACHE_HOME="$RT/home/.cache"
export ANDROID_USER_HOME="$RT/home/.android"
export ANDROID_AVD_HOME="$RT/avd"
export GRADLE_USER_HOME="$RT/gradle-home"
mkdir -p "$XDG_CACHE_HOME"

# Android SDK (ANDROID_HOME is unset on this host; local.properties has sdk.dir too).
export ANDROID_HOME="${ANDROID_HOME:-/home/jthomson/Android/Sdk}"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export JAVA_HOME="${JAVA_HOME:-/usr/lib/jvm/java-21-openjdk}"

export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"

# The emulator used for the spike (created writable, see README).
export AUGURY_AVD="${AUGURY_AVD:-augury}"
# Writable copy of the model, pushed to the device.
export AUGURY_MODEL_HOST="${AUGURY_MODEL_HOST:-/home/jthomson/AUGURY/models/MiniCPM5-1B-AUGURY-Q4_K_M.gguf}"

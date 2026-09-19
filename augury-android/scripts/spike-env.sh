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

# Android SDK.
#
# NOTE: we must discover this WITHOUT hardcoding a home directory — a tracked file
# containing an absolute home path is a portability trap (tests/test_workspace_hygiene.py
# enforces that), and it breaks for every other user.
#
# HOME has already been redirected above, so we cannot use $HOME here. Resolve the
# real home from the password database instead, which survives the redirect and
# needs no absolute path in this file.
_resolve_real_home() {
  if [ -n "${AUGURY_REAL_HOME:-}" ]; then printf '%s' "$AUGURY_REAL_HOME"; return; fi
  if command -v getent >/dev/null 2>&1; then
    _h="$(getent passwd "$(id -u)" 2>/dev/null | cut -d: -f6)"
    if [ -n "$_h" ]; then printf '%s' "$_h"; return; fi
  fi
  # Last resort: the shell's own expansion, before any redirection is in effect
  # for a subshell.
  printf '%s' "$(eval echo "~$(id -un)")"
}
REAL_HOME="$(_resolve_real_home)"

# Prefer, in order: an explicit env var, local.properties (the standard Android
# location), then the usual SDK install dirs under the real home.
_detect_android_sdk() {
  if [ -n "${ANDROID_HOME:-}" ] && [ -d "$ANDROID_HOME" ]; then printf '%s' "$ANDROID_HOME"; return; fi
  if [ -f "$AUGURY_ANDROID_DIR/local.properties" ]; then
    _lp="$(sed -n 's/^sdk\.dir=//p' "$AUGURY_ANDROID_DIR/local.properties" | head -1)"
    if [ -n "$_lp" ] && [ -d "$_lp" ]; then printf '%s' "$_lp"; return; fi
  fi
  for _c in "$REAL_HOME/Android/Sdk" "$REAL_HOME/Android/sdk" "/opt/android-sdk" \
            "/usr/local/android-sdk" "/usr/lib/android-sdk"; do
    if [ -d "$_c" ]; then printf '%s' "$_c"; return; fi
  done
}
_SDK="$(_detect_android_sdk)"
if [ -z "$_SDK" ]; then
  echo "spike-env.sh: could not locate the Android SDK." >&2
  echo "  Set ANDROID_HOME, or write sdk.dir=... into $AUGURY_ANDROID_DIR/local.properties" >&2
else
  export ANDROID_HOME="$_SDK"
  export ANDROID_SDK_ROOT="$ANDROID_HOME"
fi

export JAVA_HOME="${JAVA_HOME:-/usr/lib/jvm/java-21-openjdk}"

if [ -n "${ANDROID_HOME:-}" ]; then
  export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
fi

# The emulator used for the spike (created writable, see README).
export AUGURY_AVD="${AUGURY_AVD:-augury}"
# Writable copy of the model, pushed to the device. Derived from the repo layout
# (this file lives at <repo>/augury-android/scripts/), never hardcoded.
export AUGURY_MODEL_HOST="${AUGURY_MODEL_HOST:-$(dirname "$AUGURY_ANDROID_DIR")/models/MiniCPM5-1B-AUGURY-Q4_K_M.gguf}"

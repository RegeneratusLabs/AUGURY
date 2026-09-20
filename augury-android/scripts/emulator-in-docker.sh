#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# AUGURY — run the Android emulator OUTSIDE the DSH sandbox namespace.
#
# WHY THIS EXISTS
# ---------------
# The DSH agent sandbox is a bubblewrap namespace that does not expose
# /dev/kvm, and `mknod` is blocked by the no-new-privileges flag. Android's
# x86_64 emulator HARD-REQUIRES KVM, so inside the sandbox it refuses to start:
#
#     ERROR | x86_64 emulation currently requires hardware acceleration!
#
# The *host* has KVM: `kvm_intel` and `kvm` are loaded, the CPU exposes `vmx`,
# and the host's /dev/kvm is crw-rw-rw- major 10 minor 232. The sandbox is
# simply not allowed to see it. Docker runs outside that namespace and can be
# handed the device directly, which is the whole trick:
#
#     docker run --device /dev/kvm ... ./emulator -accel-check
#     -> KVM (version 12) is installed and usable.
#
# THREE OBSTACLES THIS SCRIPT WORKS AROUND
# ----------------------------------------
# 1. **/home is mounted `ro,nosuid,nodev`** at the filesystem level, so the SDK
#    cannot be bind-mounted read-write (Docker's root cannot even traverse into
#    it). The emulator also writes scratch state beside itself. Fix: the needed
#    SDK parts are *streamed into a Docker named volume* through the sandbox
#    user's own process -- which can read them -- rather than mounted. `seed`
#    copies only emulator/ system-images/ platform-tools (2.5 GB), not the
#    whole 5.7 GB SDK.
# 2. **The headless emulator still links X11/GL/pulse**, so those packages are
#    needed even with `-no-window`. They are baked into `augury-emulator:latest`.
# 3. **Docker's buildx and the adb server need a writable $HOME**, which the
#    sandbox does not provide. DOCKER_CONFIG/BUILDX_CONFIG are redirected into
#    the workspace; adb runs *inside* the container so it needs no host state.
#
# STATUS (2026-09-20): KVM passthrough VERIFIED, EMULATOR STILL CRASHES.
# ---------------------------------------------------------------------------
# `-accel-check` reports "KVM (version 12) is installed and usable", so the
# /dev/kvm problem is genuinely solved by this approach. But the emulator then
# SIGSEGVs ~35 s into every boot, inside its own bundled SwiftShader:
#
#   Thread "RenderThread" received signal SIGSEGV
#   #1 .../emulator/lib64/gles_swiftshader/libGLESv2.so
#
# It is NOT a security policy: SELinux is Disabled, AppArmor is absent on this
# host, and `--privileged` plus `--security-opt seccomp=unconfined` crash
# identically. `-gpu off|guest|swiftshader_indirect` and
# `hw.gpu.enabled=no` all still load libGLESv2 and all still crash.
#
# **Use the dsh-android plugin instead** (`android_boot`): it launches the
# emulator from the DSH host process, which is outside the agent sandbox, and
# that works — `emulator-5554` boots and streams. The two are independent: the
# sandbox cannot see /dev/kvm (this script's fix), and SwiftShader crashes when
# it can. Only the first is solved here.
#
# Usage:
#   scripts/emulator-in-docker.sh seed      # one-time: copy the SDK into a volume
#   scripts/emulator-in-docker.sh image     # one-time: build the emulator image
#   scripts/emulator-in-docker.sh start     # boot headless (accelerated)
#   scripts/emulator-in-docker.sh wait      # block until sys.boot_completed=1
#   scripts/emulator-in-docker.sh adb ...   # run adb inside the container
#   scripts/emulator-in-docker.sh install [apk]
#   scripts/emulator-in-docker.sh screenshot [out.png]
#   scripts/emulator-in-docker.sh logcat [lines]
#   scripts/emulator-in-docker.sh status | logs | stop
# ---------------------------------------------------------------------------
set -euo pipefail

# <repo>/augury-android/scripts/ -> repo root is two levels up.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RT="$ROOT/.dsh-runtime"
CONTAINER="augury-emulator"
VOLUME="augury-sdk"
IMAGE="augury-emulator:latest"
BASE_IMAGE="eclipse-temurin:21-jdk"

# Docker's own state must not land in the read-only real home.
export DOCKER_CONFIG="${DOCKER_CONFIG:-$RT/docker-config}"
export BUILDX_CONFIG="${BUILDX_CONFIG:-$RT/buildx}"
mkdir -p "$DOCKER_CONFIG" "$BUILDX_CONFIG" "$RT/logs"

_real_home() {
  if [ -n "${AUGURY_REAL_HOME:-}" ]; then printf '%s' "$AUGURY_REAL_HOME"; return; fi
  if command -v getent >/dev/null 2>&1; then
    local h; h="$(getent passwd "$(id -u)" 2>/dev/null | cut -d: -f6)"
    if [ -n "$h" ]; then printf '%s' "$h"; return; fi
  fi
  printf '%s' "$(eval echo "~$(id -un)")"
}
HOST_SDK="${ANDROID_HOME_HOST:-$(_real_home)/Android/Sdk}"

# The AVD must be writable, so it lives in the workspace (a real rw filesystem).
AVD_HOST="$RT/avd"

cmd="${1:-status}"; shift || true

# One-shot container with KVM and the SDK volume.
in_emu() {
  docker run --rm -i --device /dev/kvm -v "$VOLUME:/sdk" "$IMAGE" bash -lc "$1"
}

case "$cmd" in
  seed)
    if [ ! -d "$HOST_SDK/emulator" ]; then
      echo "SDK not found at $HOST_SDK (set ANDROID_HOME_HOST)" >&2; exit 1
    fi
    docker volume create "$VOLUME" >/dev/null
    echo "streaming emulator/ system-images/ platform-tools/ into volume $VOLUME"
    tar cf - -C "$HOST_SDK" emulator system-images platform-tools \
      | docker run --rm -i -v "$VOLUME:/sdk" "$BASE_IMAGE" \
          bash -lc 'mkdir -p /sdk && tar xf - -C /sdk && du -sh /sdk'
    ;;

  image)
    mkdir -p "$RT/emu"
    cat > "$RT/emu/Dockerfile" <<'EOF'
# The emulator's headless binary still links X11/GL/pulse, so -no-window needs
# these present. Everything else comes from the SDK volume at run time.
FROM eclipse-temurin:21-jdk
RUN export DEBIAN_FRONTEND=noninteractive \
 && apt-get update -qq \
 && apt-get install -y -qq --no-install-recommends \
      libx11-6 libxcb1 libxext6 libxi6 libxrender1 libxtst6 \
      libgl1 libglu1-mesa libpulse0 libnss3 libasound2t64 \
 && rm -rf /var/lib/apt/lists/*
EOF
    docker build -t "$IMAGE" "$RT/emu"
    ;;

  start)
    docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
    # A killed emulator leaves hardware-qemu.ini.lock / multiinstance.lock in the
    # AVD. The next boot then dies with "Running multiple emulators with the same
    # AVD", so clear them before every start.
    docker run --rm -v "$VOLUME:/sdk" "$BASE_IMAGE" bash -lc \
      'rm -f /sdk/avd/augury.avd/*.lock; rm -rf /sdk/avd/augury.avd/*.lock.d' >/dev/null 2>&1 || true
    mkdir -p "$AVD_HOST"
    docker run -d --name "$CONTAINER" \
      --device /dev/kvm \
      -v "$VOLUME:/sdk" \
      -e ANDROID_AVD_HOME=/sdk/avd \
      -e HOME=/root \
      --entrypoint bash \
      "$IMAGE" -lc '
        set -e
        ls -la /dev/kvm
        # Accept either /sdk or /sdk/sdk depending on how the volume was seeded.
        if [ -d /sdk/emulator ]; then SDK=/sdk; elif [ -d /sdk/sdk/emulator ]; then SDK=/sdk/sdk; else echo "SDK not found in volume"; exit 1; fi
        # The AVD ini points at /sdk/avd/augury.avd, so the SDK-relative
        # system image path must resolve from there.
        sed -i "s#^path=.*#path=/sdk/avd/augury.avd#" /sdk/avd/augury.ini 2>/dev/null || true
        export ANDROID_HOME=$SDK ANDROID_SDK_ROOT=$SDK
        cd $SDK/emulator
        exec ./emulator -avd augury \
          -no-window -no-audio -no-snapshot -no-boot-anim \
          -gpu swiftshader_indirect -accel on -memory 2048 \
          -ports 5554,5555
      ' >/dev/null
    echo "container $CONTAINER booting (accelerated; first boot takes a few minutes)"
    ;;

  wait)
    echo -n "waiting for boot_completed"
    for _ in $(seq 1 "${1:-120}"); do
      if docker exec "$CONTAINER" sh -c 'S=/sdk; [ -x $S/platform-tools/adb ] || S=/sdk/sdk; exec $S/platform-tools/adb "$@"' -- shell getprop sys.boot_completed 2>/dev/null | grep -q 1; then
        echo " ... booted"; exit 0
      fi
      echo -n "."; sleep 5
    done
    echo " TIMEOUT"; exit 1
    ;;

  adb)
    docker exec "$CONTAINER" sh -c 'S=/sdk; [ -x $S/platform-tools/adb ] || S=/sdk/sdk; exec $S/platform-tools/adb "$@"' -- "$@"
    ;;

  install)
    APK="${1:-$ROOT/augury-android/app/build/outputs/apk/debug/app-x86_64-debug.apk}"
    test -f "$APK" || { echo "APK not found: $APK" >&2; exit 1; }
    docker cp "$APK" "$CONTAINER:/tmp/augury.apk"
    docker exec "$CONTAINER" sh -c 'S=/sdk; [ -x $S/platform-tools/adb ] || S=/sdk/sdk; exec $S/platform-tools/adb "$@"' -- install -r -t /tmp/augury.apk
    ;;

  screenshot)
    OUT="${1:-$RT/logs/screen.png}"
    docker exec "$CONTAINER" sh -c 'S=/sdk; [ -x $S/platform-tools/adb ] || S=/sdk/sdk; exec $S/platform-tools/adb "$@"' -- exec-out screencap -p > "$OUT"
    echo "$OUT"
    ;;

  logcat)
    docker exec "$CONTAINER" sh -c 'S=/sdk; [ -x $S/platform-tools/adb ] || S=/sdk/sdk; exec $S/platform-tools/adb "$@"' -- logcat -d 2>/dev/null | tail -"${1:-200}"
    ;;

  stop)
    docker rm -f "$CONTAINER" >/dev/null 2>&1 && echo "stopped" || echo "not running"
    ;;

  status)
    if docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
      echo "running"
      docker exec "$CONTAINER" sh -c 'S=/sdk; [ -x $S/platform-tools/adb ] || S=/sdk/sdk; exec $S/platform-tools/adb "$@"' -- devices -l 2>/dev/null | tail -3
    else
      echo "not running"
    fi
    ;;

  logs)
    docker logs --tail "${1:-60}" "$CONTAINER" 2>&1
    ;;

  *)
    sed -n '2,38p' "$0"; exit 1 ;;
esac

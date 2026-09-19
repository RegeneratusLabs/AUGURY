# AUGURY — Android app

**Weeds as soil-health indicators.** Take a photo of a weed (or pick one from a
list) and read what it says about your soil — compaction, pH, nutrients, drainage.
Indicators only, no management advice. Runs fully on the phone; no account, no API
key, no server bill.

This app is a **shell**. It bundles no model data. Everything it needs is
downloaded from Hugging Face on first launch and verified against a manifest.

---

## What it downloads

| Artifact | Size | Purpose |
|---|---|---|
| `MiniCPM5-1B-AUGURY-Q4_K_M.gguf` | 688 MB | the formatter ("the voice") |
| `dinov2-base-fp32.onnx` | 347 MB | image encoder for the photo path |
| `vision-index-v3.tar.gz` | 20 MB | retrieval index (13,448 vectors) |
| `augury-ondevice.json` | 1 MB | species database |
| **total** | **~1.06 GB** | one-time, Wi-Fi by default |

The raw 15 GB image gallery is **never** downloaded — the phone gets the compact
index. `index.faiss` is deliberately excluded: retrieval is brute-force kNN in
Kotlin over 13,448 × 384 floats, so FAISS is not a runtime dependency.

---

## Architecture

```
manifest.json (HF)  ← the only update lever
        │
        ▼
┌──────────────────── Shell APK ─────────────────────┐
│  [📷 photo]  [🖼 gallery]  [🔎 tap a weed]          │
│        │                        │                  │
│        ▼                        ▼                  │
│  ONNX CLS → L2 → PCA-whiten → L2 → kNN             │
│        └──► top-3 + confidence band ──┐            │
│                                       ▼            │
│  SpeciesStore → prompt → llama.cpp JNI → GGUF      │
│                                       ▼            │
│  Grounding + IntentGuard → soil story              │
└────────────────────────────────────────────────────┘
```

**The app never hard-codes a version, species count, dimension, or threshold.**
Species, indicators, regions, band thresholds and preprocessing parameters all come
from the manifest, so recalibrating or adding species is a data change, not an app
release. See `../docs/mobile-app-decision.md`.

---

## Building

### Prerequisites

- JDK 21
- Android SDK with `platforms/android-36`, `build-tools/37.0.0`,
  **`ndk/27.1.12297006`** and `cmake/3.22.1`
- ~8 GB free RAM (the native build is parallel and memory-hungry)

### On a normal machine

```bash
git clone --recursive <this repo>
cd augury-android
echo "sdk.dir=$ANDROID_HOME" > local.properties
./gradlew :app:assembleDebug
```

The llama.cpp submodule is pinned; `./gradlew checkLlamaCppPin` verifies it.

### In this sandbox

`$HOME` is mounted read-only, so Gradle cannot initialize its native services
there. Source the shim, which redirects `HOME`, `~/.gradle`, `~/.android` and
`TMPDIR` into a writable directory:

```bash
cd augury-android
source scripts/spike-env.sh
./gradlew :app:assembleDebug
```

Without `spike-env.sh` you get
`Could not initialize native services / Failed to load native library 'libnative-platform.so'`.

Unit tests need no device or emulator:

```bash
source scripts/spike-env.sh
./gradlew :app:testDebugUnitTest
```

---

## Verifying the engine without a phone

This host has **no `/dev/kvm`**, so the Android emulator falls back to QEMU-TCG —
far too slow for a 1B model, and its guest CPU lacks AVX/F16C (an AVX2-built ggml
SIGILLs inside it; the x86_64 build pins SSE4.2 for that reason).

The engine is therefore split so the **same C++ translation unit** compiles as a
plain Linux binary and can be validated here:

```bash
cmake -S tools -B build/host -DCMAKE_BUILD_TYPE=Release
cmake --build build/host -j
./build/host/augury_host_test ../models/MiniCPM5-1B-AUGURY-Q4_K_M.gguf 8
```

Measured on the real 688 MB GGUF (16-core host, 8 threads):

```
template_source : embedded-chat-template   ← the model's own template
prompt_tokens   : 174
gen_tokens      : 78
tokens_per_sec  : 66.84
wall_ms         : 1685                      ← 1.7 s per answer
```

That validates the llama.cpp API usage, chat-template application, sampling and
tokenisation. **It does not prove the `.so` loads on a physical phone — that test
is still outstanding.**

Native builds verified for both ABIs:

| ABI | Unstripped | Stripped | Note |
|---|---|---|---|
| `arm64-v8a` | 46.6 MB | **4.1 MB** | real device target |
| `x86_64` | 46.1 MB | — | pinned to SSE4.2 (see above) |

To build an ABI directly, bypassing Gradle:

```bash
export NDK=$ANDROID_HOME/ndk/27.1.12297006
$ANDROID_HOME/cmake/3.22.1/bin/cmake -S app/src/main/cpp -B build/arm64 \
  -DCMAKE_TOOLCHAIN_FILE=$NDK/build/cmake/android.toolchain.cmake \
  -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-26 -DCMAKE_BUILD_TYPE=Release
$ANDROID_HOME/cmake/3.22.1/bin/cmake --build build/arm64 -j
```

---

## Two hard-won behaviours this app must preserve

### 1. Always show top-3. Never silently accept a photo ID.

Retrieval top-1 is **81.8–83.6%** depending on the query subset. A confident
top-1 can still be the wrong species (look-alikes, immature plants, poor
lighting), and the formatter will then faithfully describe the wrong plant. The
`auto` band means *higher confidence*, not *safe to accept*. The user always taps
to confirm.

### 2. The grounding pass is mandatory.

Running the real model with the real prompt, given the fact
`Soil pH: neutral to slightly acidic`, it produced:

> *"Dandelion indicates acidic conditions, **likely below 6.5**."*

**"6.5" appears nowhere in the input.** The database says "wide range, weakly acid
to neutral". This is an invented number, and it is reproducible. `Grounding.kt`
exists to neutralise numbers that are not in the injected facts. A build without
it will confidently print invented soil chemistry.

---

## Confidence bands

Calibrated per index and read from the **manifest** — never hard-coded.

| Band | Threshold | Coverage | Precision |
|---|---|---|---|
| auto | ≥ 0.68 | 51.6% | **95.1%** |
| confirm | 0.43 – 0.68 | 94.1% cumulative | 85.0% |
| unknown | < 0.43 | 5.9% | — |

Precision on the whitened score scale **peaks near 0.68 and falls above 0.75**, so
the legacy `0.80/0.60` constants select the worst decile. Do not reintroduce them.

---

## Encoder: fp32, not int8

Dynamic int8 quantisation was measured and **rejected**. On the same queries
against the shipped gallery:

| Arm | top-1 | top-3 |
|---|---|---|
| fp32 PyTorch (control) | 0.7500 | 0.8500 |
| **ONNX fp32** | **0.7500** | **0.8500** |
| ONNX int8 | 0.0500 | 0.1250 |

The fp32 control matching PyTorch exactly proves the pipeline is sound, so the
collapse is a genuine quantisation effect — ViT attention needs more dynamic range
than int8 weights provide. Full corpus: fp32 ONNX matches PyTorch to **+0.00p** on
866 queries. Record: `../data/vision/bench/encoder_gate_dinov2-base-fp32.json`.

---

## Layout

```
app/src/main/cpp/          native engine (llama.cpp JNI shim)
  augury_engine.{h,cpp}    engine core — no <jni.h>, so it builds as a host binary too
  augury_jni.cpp           the JNI surface
app/src/main/java/au/org/regeneratus/augury/
  LlamaEngine.kt           Kotlin facade over the native layer
  core/                    SpeciesStore, StoryComposer, IntentGuard, Grounding
  ui/                      setup, picker, photo
tools/                     host test harness
third_party/llama.cpp      pinned submodule (MIT)
scripts/spike-env.sh       sandbox environment shim
```

## Licence

Apache-2.0. `llama.cpp` is MIT. Base model `openbmb/MiniCPM5-1B` is Apache-2.0.
The retrieval gallery is a non-commercial aggregate with per-image licence
sidecars; only the compact index is a runtime artifact.

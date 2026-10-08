# AUGURY — the Kotlin vision and formatter paths, verified

**Written:** 2026-09-22
**Subject:** what has actually been *run* about the on-device half of the app —
the ONNX photo path, the decode bound, and the formatter model — on the host and
on a device, with the numbers.

Companions: `docs/HANDOVER-2026-09-20.md` (the app shell and the download
pipeline), `docs/mobile-app-decision.md` (why the app is a shell),
`docs/HANDOVER-2026-09-19-vision.md` (the retrieval track).

---

## 1 · Why this document exists

The 2026-09-20 handover named the single largest unknown in the project:

> **`OnnxEncoder` has never loaded the 346 MB graph on a device.** … The
> device-side surfaces are untested: ORT Mobile loading the `.onnx`,
> `BitmapFactory` decode feeding the preprocessor, and peak memory when the
> encoder is resident.

and, beside it, that the formatter model "has never been loaded/run", so every
story the product could produce was the deterministic template.

Both are now exercised, on a device, against the artifacts the app downloads and
verifies. This is the record of what was run, what it proved, and what it did
**not**.

The split is forced by the platform: ONNX Runtime Mobile and llama.cpp ship
Android shared libraries, so **no host JVM can load either**. The host can verify
the arithmetic around the graph ([`VisionParityTest`]); only a device can verify
the graph itself ([`OnDevicePipelineTest`]).

---

## 2 · What the host proves — `VisionParityTest` (8 tests)

These compare the Kotlin implementation against Python ground truth recorded by
`augury-android/tools/emit_vision_fixtures.py`, not against itself:

| Check | Result |
|---|---|
| resize + crop + uint8 round-trip reproduces torchvision | byte-for-byte on the recorded fixture |
| the tensor is CHW `[3, crop, crop]` as the graph requires | pass |
| the recorded CLS token has the graph's output width | pass |
| L2 → PCA-whiten → L2 reproduces the Python whitened query | within float tolerance (≈3e-8 on the recorded vector) |
| the shipped index matches the manifest it is published with | pass |
| the band matches the manifest thresholds | pass |
| kNN over the shipped gallery reproduces the Python top-3 | identical keys and scores |
| the tolerated bicubic difference does not change the identification | pass |

The preprocessing kernel is a deliberate port of torchvision's antialiased
bicubic (Catmull-Rom, `a = -0.5`, `align_corners = false`), validated on the host
at ≤ 2.1e-05 max absolute difference on a float32 resize; the uint8 output agrees
with the reference within 4 LSB on 100% of pixels, 82% of them exactly.

**What this cannot see:** the ONNX session, the JPEG decoder, and the GGUF.

---

## 3 · What the device proves — `OnDevicePipelineTest` (4 tests)

Run on AUGURY's own AVD (`augury-api34`: Android 14 / API 34, x86_64, 4 cores,
`hw.ramSize=3072`, `vm.heapSize=512`) with the four artifacts the app had
downloaded, verified and promoted on that device.

```
./gradlew :app:connectedDebugAndroidTest
# or:
adb shell am instrument -w \
  au.org.regeneratus.augury.test/androidx.test.runner.AndroidJUnitRunner
```

**Result: `OK (4 tests)` in 58.0 s.**

### 3.1 · The photo path ran, and was right

Twelve gallery photos — each one a row that *is* in the shipped index, chosen from
the row-aligned `keys.json` / `files.json` by
`augury-android/tools/select_device_vision_samples.py`, so its reference embedding
is in `embeddings.npy`:

```
photo path: top1=12/12 top3=12/12 named=12/12 pss 950089kB -> 1252739kB
```

Per-image top-1 scores were **0.9993 – 1.0000**. That is the expected shape for
in-index rows (the pipeline is reproducing an embedding the reference already
computed, so a disagreement would be a device bug, not a hard query) — and it is
exactly the check the host could not make.

The confirm card's display name is resolved on the device too, from the species
database rather than from the index key:

| Index key | Shown on the confirm card |
|---|---|
| `acacia nilotica` | Prickly acacia |
| `lagurus ovatus` | Hare's tail grass |
| `tamarix aphylla` | Athel pine |
| `ranunculus repens` | Creeping buttercup (Ranunculus repens) |
| `carex hirta` | Carex hirta *(no vernacular name in the database)* |

113 of the index's 173 species have a distinct vernacular name; 57 more carry the
binomial as their common name; the remaining 3 fall back to the database's own
spelling, which is what the last row shows.

### 3.2 · The decode bound does not change the answer

`DecodeBounds` exists because a full-resolution decode of a 12 MP photo spends
roughly 130 MB of the app's heap to throw away more than 99% of the pixels before
a 256-px resize. The bound is measured against the real graph, with the
full-resolution decode as the control:

```
decode parity: source 256x256 -> 2048x2048, comparing sampleSize 1 vs 2
decode parity: full=acacia nilotica@0.9532776 bounded=acacia nilotica@0.95218736
```

Same top-1, same top-3 ordering, top-1 score moved by **0.0011** (the assertion
allows 0.02). Android only honours power-of-two subsampling, so the decoded
longest edge lands in `[TARGET_LONGEST_EDGE, 2 × TARGET_LONGEST_EDGE)` — a bound
that does not grow with the camera (a 48 MP photo decodes to the same size as a
12 MP one) while staying as close to the reference as the decoder allows.

### 3.3 · The formatter model generated a story, and the encoder was released

```
story: usedModel=true repairs=0 chars=408 pss 930057kB -> 589776kB
```

`usedModel=true` is the load-bearing value: it is false whenever the model could
not be loaded and the deterministic template stood in. The PSS drop is the
co-residency constraint made observable — the 346 MB encoder's ONNX session was
released before the ~700 MB GGUF was mapped.

The same path through the **app's own UI** (Home → Dandelion → Story), read from
logcat under the `AuguryGateway` tag:

```
formatter draft for 'taraxacum officinale': loading MiniCPM5-1B-AUGURY-Q4_K_M.gguf
formatter draft for 'taraxacum officinale': load=585ms total=43700ms chars=255
  :: load_ms=582;prompt_tokens=184;prompt_ms=9916;gen_tokens=65;gen_ms=33188;
     tokens_per_sec=1.959;template=embedded-chat-template;n_ctx=2048;n_threads=4
```

The Story screen rendered the model's prose, disclosed its provenance ("Written by
**on-device formatter model, grounded against the database**"), and showed no
"CORRECTED" card because the grounding pass found nothing to repair in that draft.

**Emulator performance is recorded, not extrapolated.** ~2.0–4.1 tokens/sec on an
x86_64 emulator with 4 cores is a footnote about QEMU, not a phone measurement. No
phone figure exists yet: the target device is a CMF Phone 1
(`docs/HANDOVER-2026-09-23.md` §5.0), and nothing in this document was measured on
it.

---

## 3.4 · Streaming, and the grounding repair that finally fired

Both of these were open items in `docs/HANDOVER-2026-09-22.md`. They are now
measured, and the two together close the loop on "the model writes prose, and the
database still owns the facts".

### 3.4.1 · The formatter streams — `OnDeviceStreamTest` (2 tests)

```
./gradlew :app:assembleDebugAndroidTest
adb shell am instrument -w -e class \
  au.org.regeneratus.augury.OnDeviceStreamTest \
  au.org.regeneratus.augury.test/androidx.test.runner.AndroidJUnitRunner

OK (2 tests) in 30.7 s
```

```
stream: pieces=48 chars=206 first_piece_ms=8998 total_ms=23091
stream stats: load_ms=272;prompt_tokens=174;prompt_ms=8713;gen_tokens=48;
              gen_ms=14093;tokens_per_sec=3.406;n_ctx=2048;n_threads=4
stream early stop: pieces=3 chars=12
```

Three things this pins that no host test can:

1. **`nativeGenerateStream` resolves across JNI at all.** The entry point looks up
   `boolean onPiece(String)` on the sink object. A Kotlin/JNI signature mismatch is
   a `NoSuchMethodError` that a host test structurally cannot reach — this is the
   same class of bug as §4's `vision.preprocess`, one layer down.
2. **The first piece arrives at 8,998 ms of a 23,091 ms turn — 39% in.** A "stream"
   that called back once at the end would pass every state-machine test on the
   host; the timing assertion is what makes the claim falsifiable.
3. **The pieces are the same turn.** Same prompt, same seed, so the concatenation
   equals the returned text exactly, and the streamed prefix is a prefix of what
   `generate()` produces. `tools/host_test.cpp` asserts the same parity against the
   real 688 MB GGUF on the host, where it runs in 1.9 s:

   ```
   stream_pieces : 40    stream_chars : 160    stream_ms : 1905
   ```

The 8,998 ms is **prompt evaluation, not a stall**: 8,713 ms of the 8,998 ms is
`prompt_ms`. That is why the screen has two distinct waiting states — "Reading the
database…" before the first token, "Writing…" after it.

### 3.4.2 · The CORRECTED card, rendered from a real hallucination

The handover's open item was that every recorded draft was clean (`repairs=0`), so
the repair path had never fired on a device. It has now, against the device's own
species database, driven by `OnDeviceGroundingRepairTest` (4 tests):

```
grounding fixture check: facts contain no '6.5'
grounding repair fired: action=neutralised removed=[6.5] chars=322
grounding repair: action=neutralised removed=[6.5]
  before='The pH picture: Dandelion indicates acidic conditions, likely below 6.5.'
  after ='The pH picture: Dandelion indicates acidic conditions.'
```

The draft is not invented for the occasion. It is **the text the real GGUF
produced on the host** for that species and prompt (recorded in §3.3's session),
and the test *first* asserts that `6.5` is absent from the shipped facts — so if
the database ever gains that number, the fixture stops being a hallucination and
the test fails loudly instead of passing vacuously.

Two further assertions keep the guard rail honest in both directions: a draft that
only restates the facts comes through **byte-for-byte** with zero repairs, and the
port's documented Python example (`Lantana … likely below 6.5.` → `Lantana
indicates acidic conditions.`) produces the identical result on the device.

### 3.4.3 · The draft on screen, through the app's own UI

Driven on the emulator (Home → search → species → Story). Mid-turn, read from the
uiautomator dump:

```
"Button grass"  /  "Dactyloctenium radulans · Australia"
WRITING…
  " alkaline"                                    ← draft, dimmed italic
  "Not checked against the database yet. The verified reading
   replaces this as soon as the writer finishes."
```

and when the turn landed, the draft block was replaced by the grounded reading —
"WHAT IT SAYS ABOUT YOUR SOIL", the 6 database indicator rows, and the provenance
card. The draft is a *separate* state field from the verified story, so a streamed
prefix is structurally unable to render as the answer.

---

## 4 · The bug the device found, and the test that now guards it

The first device run failed every test that touched the photo path, with:

```
The image recogniser could not be loaded: manifest vision.preprocess is missing
```

Two defects in one hand-built mapping, in `AuguryGatewayImpl.visionPipeline()`:

1. `PreprocessSettings.fromManifest(vision)` reads `vision["preprocess"]`, but the
   gateway passed the inner `preprocess` block — so the key was missing.
2. The inner numbers were the typed manifest's `Int`s, while `VisionJson` was
   written for JSON-parsed values and `num()` accepted only a `Double`.

Both are invisible to 181 host tests, because the pipeline cannot be constructed
without ONNX Runtime Mobile. The mapping now lives in the pure function
`visionPreprocessBlock` (`ui/VisionManifestBridge.kt`) and
`VisionManifestBridgeTest` compares it against the *reference* parse of the
shipped manifest — the same comparison the device made, on the host, in
milliseconds. `VisionJson.num` also accepts any `Number`, so the next caller that
rebuilds a block from typed data cannot hit the same trap.

**This is the lesson the 2026-09-20 handover drew, applied one layer down:** a
green suite is only as good as the path it actually exercises.

---

## 5 · What is still unverified

| Area | Status |
|---|---|
| **Held-out photo accuracy** | The device samples are *in* the index, so 12/12 measures device parity, not accuracy. The recorded held-out top-1 is 85.9% (920 queries). |
| **A physical phone** | Not measured. The target is a **CMF Phone 1** (Dimensity 7300, 8 GB, 1080×2400, Android 14 / Nothing OS 2.6) — *not* the Galaxy A10s the earlier docs assumed; see `docs/HANDOVER-2026-09-23.md` §5.0. Real tokens/sec, prompt-evaluation time, ONNX load time and memory pressure remain unknown. |
| **Real-world photos** | The emulator camera cannot produce a weed. The gallery picker *was* driven end to end with a pushed sample photo, which exercised the confirm card, but the subjects are gallery images. |
| **The `<think>` strip** | `Reasoning.stripThink` is applied and unit-tested, but the model emitted no `<think>` block in any run, so it was a no-op in practice. It matches `scripts/augury_funnel.py` and is safe either way. |
| **Grounding repairs on a real draft** | ✅ **Closed 2026-09-23** — see §3.4.2. Fired on the device against the real database, `neutralised`, `6.5` removed, the true claim kept. What remains unmeasured is a *live model* hallucination: the fixture is the real GGUF's recorded output, replayed, not a fresh sample. |
| **Release build** | Unsigned, `isDebuggable = true`, unminified. Unchanged by this work. |
| **Memory headroom** | The photo path's resident encoder is ~300 MB on top of the app (PSS 950 MB → 1.25 GB observed). Fine at 3072 MB; a 2 GB device would be tight. |
| **Streaming throughput on a phone** | The 3.4 tok/s and 8.7 s prompt evaluation are **emulator** numbers. The phone figure still does not exist. |

---

## 6 · Reproducing it

```bash
cd <repo-root>

# host: the maths
cd augury-android && ./gradlew :app:testDebugUnitTest

# device: the graph. Needs a device with the artifacts installed and ready.
python3 augury-android/tools/select_device_vision_samples.py --count 12
./gradlew :app:assembleDebug :app:assembleDebugAndroidTest
adb install -r -t app/build/outputs/apk/debug/app-x86_64-debug.apk
adb install -r -t app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk
adb shell am instrument -w \
  au.org.regeneratus.augury.test/androidx.test.runner.AndroidJUnitRunner

# the measured numbers, as the test logs them
adb logcat -d -s AuguryDeviceTest:V
```

The sample photos live under
`augury-android/app/src/androidTest/assets/vision-samples/` (≈556 KB) so the
device test is hermetic; regenerate them from the shipped gallery with the script
above. They are new files, untracked until committed.

The streaming and grounding-repair tests are part of the same instrumentation run:

```bash
# all four device classes
adb shell am instrument -w \
  au.org.regeneratus.augury.test/androidx.test.runner.AndroidJUnitRunner

# or one at a time
adb shell am instrument -w -e class au.org.regeneratus.augury.OnDeviceStreamTest \
  au.org.regeneratus.augury.test/androidx.test.runner.AndroidJUnitRunner
adb shell am instrument -w -e class au.org.regeneratus.augury.OnDeviceGroundingRepairTest \
  au.org.regeneratus.augury.test/androidx.test.runner.AndroidJUnitRunner
```

The native streaming half also runs **on the host**, against the real GGUF, in
about two seconds — this is the cheapest way to check the engine after a change:

```bash
cd augury-android
cmake -S tools -B build/host -DCMAKE_BUILD_TYPE=Release && cmake --build build/host -j
./build/host/augury_host_test ../models/MiniCPM5-1B-AUGURY-Q4_K_M.gguf 8
```

> Do not run `adb shell am instrument` and drive the app's UI at the same time:
> `monkey`'s force-stop will kill the instrumentation process mid-test and report
> it as "Process crashed". That is a harness collision, not an app crash — the
> crash buffer is empty and the app's own log shows the test was working.

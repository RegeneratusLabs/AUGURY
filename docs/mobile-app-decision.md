# AUGURY — Mobile App Decision Record

**Status:** 2026-09-19 · **Active.** Supersedes `docs/mobile-app-plan.md`.
**Question answered:** how do non-technical users get AUGURY on a phone, for free,
with an open-source licence, and keep getting model updates?

---

## 1 · The constraint that decides everything

Four requirements were fixed by the project owner, and they eliminate most
architectures on their own:

| Requirement | Consequence |
|---|---|
| **$0 — never a hosting bill** | No server we run. Hugging Face is the only network dependency. |
| **Runs on device** | Inference happens on the phone; no cloud API at runtime. |
| **Free and open source** | Every shipped component must be MIT/Apache/CC-BY licensable. |
| **Users have zero technical ability** | No sideloading instructions beyond "install this file we sent you"; no in-app configuration. |

A hosted web app satisfies the last two and violates the first. A native app
satisfies the first three, and the fourth is handled by guiding early users
through a **standalone APK** (explicitly accepted: "we can guide enough users to
install an apk"). That is the shipped decision.

---

## 2 · Why OpenBMB's apps were NOT forked

`docs/mobile-app-plan.md` proposed forking
[`OpenBMB/MiniCPM-V-Apps`](https://github.com/OpenBMB/MiniCPM-V-Apps). That
proposal is **rejected**, on four independently-verified grounds.

### 2.1 It has no licence

The GitHub API returns `"license": null` for the repository and there is no
`LICENSE` file in the tree. Under default copyright, "no licence" means **all
rights reserved** — not "free to use". Vendoring it into an Apache-2.0 project
would make AUGURY's licensing claim false. `llama.cpp` (which their app wraps) is
MIT and is fine to build on; their *app code* is not.

### 2.2 It cannot run AUGURY's photo path

Their apps are a thin shell over a `llama.cpp` fork
(`tc-mb/llama.cpp-omni`). AUGURY's retrieval is **DINOv2-base embeddings + kNN
over a 13,448-vector index** — neither is a llama.cpp capability. Forking buys a
chat UI and then requires reimplementing the entire AI layer anyway, because
AUGURY's identity is the *three-layer decomposition* (retrieval / deterministic
DB / formatter), not the chat surface.

### 2.3 It cannot deliver the actual requirement

The project owner's requirement is *"when the model is updated on HF it can pull
through to the app."* Their apps download model **weights** in-app, but app
**logic** changes only via a new APK
(`releases/download/v2.5/MiniCPM-V-demo-Android-v2.5.apk`). A fork reproduces the
exact problem it was meant to solve.

### 2.4 Its distribution model is unusable for the target user

GitHub Releases APK, iOS TestFlight, HarmonyOS HAP — "research/preview, not
optimized products". Sideloading demands "install unknown apps" / "trust this
developer", and iOS requires a Mac and $99/yr. For a user with zero technical
ability, this is a dead end.

**What we took from their design instead:** a pinned artifact catalogue
(repo + filename + checksum), a resumable first-launch downloader with visible
progress, and persona injection at the engine level. Those ideas are good, and
they are MIT-licensable when built on `llama.cpp` directly — which is what this
app does.

---

## 3 · Architecture: the app is a shell

The app ships **no model data**. Everything it needs is fetched from Hugging Face,
verified, and version-pinned.

```
   RegeneratusLabs/augury-app/manifest.json   ← the only update lever
                     │
                     ▼
┌──────────────── Shell APK (Kotlin, Apache-2.0) ────────────────┐
│  UI + download/verify/storage + declared PROTOCOLS            │
│  [📷 photo] [🖼 gallery] [🔎 tap a weed]                       │
│        │                    │                                 │
│        ▼                    ▼                                 │
│  ONNX CLS → L2 → PCA-whiten → L2 → kNN(inner product)         │
│        └──► top-3 + band ──┐                                  │
│                            ▼                                  │
│  species_lookup (Kotlin) → augury-ondevice.json               │
│                            ▼                                  │
│  prompt → llama.cpp JNI → GGUF                                │
│                            ▼                                  │
│  grounding + intent guard → soil story                        │
└───────────────────────────────────────────────────────────────┘
```

### 3.1 What lives where

| In the APK | On Hugging Face |
|---|---|
| UI code | formatter GGUF (688 MB) |
| The **protocols** it can execute (§3.3) | encoder ONNX (~88 MB int8) |
| Download / verify / storage / rollback logic | retrieval index (42 MB) |
| Bootstrap pointer (manifest repo + filename) | **confidence bands** |
| — | **species database** |

The species DB is deliberately **not** bundled: the species count, the indicator
keys and the regions all change over time, and bundling it would mean a new APK
for a data edit. `_compose_template()` in `scripts/augury_funnel.py` iterates
`for key, val in ind.items()` with **no hard-coded indicator name anywhere**, and
the DB carries nine free-form indicator keys today. New species, new indicator
types and new regions are therefore pure data changes the app renders without a
release. That property is the reason the shell design works.

### 3.2 One manifest, independent versions

Every artifact is listed with **its own repo, revision, bytes and sha256**:

```json
{
  "manifest_schema": 1,
  "generation": "<sha256 of this manifest, minus this field>",
  "formatter": {"protocol":"formatter.chatml-grounded@1","repo":"…","path":"…",
                "revision":"…","bytes":0,"sha256":"…","generation":"…"},
  "facts":     {"protocol":"species.db@1","schema":1,"repo":"…","path":"…", "…":"…"},
  "vision": {
    "index":    {"protocol":"vision.clip-token-l2-pca-knn-ip@1","schema":1,
                 "backend":"dinov2-base","vectors":0,"dim":0,"species":0,"…":"…"},
    "encoders": [{"backend":"dinov2-base","quant":"int8","…":"…"}],
    "bands":    {"auto_conf":0.68,"confirm_conf":0.43},
    "preprocess": {"resize_shortest_edge":256,"crop":224,"resample":"bicubic",
                   "mean":[0.485,0.456,0.406],"std":[0.229,0.224,0.225],
                   "output":"cls_token"}
  }
}
```

Consequences worth stating plainly:

- **Each artifact moves on its own schedule.** Recalibrate the bands and the app
  re-downloads ~1 KB, not 1 GB. Add species and nothing else changes. Retrain the
  formatter and only the GGUF entry moves.
- **Version mismatch is structurally impossible.** There is exactly one place
  that declares which combination is current, so the app cannot pair a v2 band
  file with a v3 index — the failure mode this repo has already been bitten by
  twice (§4).
- **Rollback is a one-line edit**, not an APK emergency, because revisions are
  pinned.
- **Everything tunable is data.** Image size, mean/std, band thresholds, `k` and
  score semantics are all manifest values, so recalibration is never an app
  change. *(A deliberate interim compromise: preprocessing in the manifest is a
  shim — the shell must still implement it correctly. The robust end state is
  baking resize+normalise into the ONNX graph so the encoder becomes a black box
  and that class of drift is impossible. Tracked as a follow-up, not done.)*
- **On-device layout:** `files/artifacts/<name>/<generation>/`. A new generation
  is staged and verified before the pointer flips; the previous generation is
  retained until the next successful start.

### 3.3 The compatibility gate — what "dynamic" can and cannot absorb

This is the honest boundary of the shell design:

| Change | Shell handles alone? |
|---|---|
| Species added / removed, new indicator keys, new region | ✅ |
| New band thresholds | ✅ |
| Denser gallery → new index | ✅ |
| Retrained formatter → new GGUF | ✅ |
| Swap encoder (DINOv2 → SigLIP2) with the same contract | ✅ new artifact |
| Encoder with a **different** preprocessing/output contract | ⚠️ new `backend`, must be declared |
| Multi-crop TTA, score fusion, reranking, **different score semantics** | ❌ new **protocol** → APK update required |

The shell therefore declares the **protocols** it can execute — currently
`vision.clip-token-l2-pca-knn-ip@1` and `formatter.chatml-grounded@1` — plus the
`manifest_schema` / `index_schema` / `species_db_schema` it understands. If the
manifest presents something else, the app says **"this app update is required"**
rather than running a mismatched encoder and returning plausible garbage. That
single gate is what makes everything else safely dynamic.

---

## 4 · Confirmed defect: `index-v3` was serving uncalibrated bands

Found and fixed 2026-09-19, during the app's design. It is the **same class of bug
as the "2.2-point discrepancy"** already recorded in
`docs/HANDOVER-2026-09-18.md`, and it would have surfaced directly in the app UI.

**What was wrong.** `scripts/vision/calibrate_bands.py` wrote its output to
`band_calibration.json` (its `--out` default), but `scripts/vision/photo_id.py`
reads `<index_dir>/band_config.json`. `index-v3` contained only the former, so:

```python
PhotoID(index_dir='data/vision/index-v3').band_config
# -> {'auto_conf': 0.8, 'confirm_conf': 0.6, 'calibrated': False}
```

v3's measured calibration is **auto ≥ 0.68** (51.6% coverage, **95.1% precision**)
and **confirm ≥ 0.43**. It was silently running on the legacy `0.80/0.60`
constants — which is exactly the threshold `index-v2/README.md` documents as
*actively harmful*, because on the whitened score scale precision **peaks near
0.68 and falls above 0.75**. In the app, almost no photo would have cleared 0.80,
so users would have been asked to confirm nearly every identification even when
the model was 95% sure.

**The fix.** `calibrate_bands.py` now emits **both** files from one computation —
`band_config.json` in the shape `PhotoID` reads, and `band_calibration.json` as
the audit trail — and reports `calibrated: false` plus a stderr warning when the
precision targets are unreachable, instead of shipping thresholds that only look
confident. `data/vision/index-v3/band_config.json` was regenerated (`0.68`/`0.43`,
`calibrated: true`).

**The guard.** `tests/test_band_config.py` (6 checks, stdlib-only, offline) pins
the invariant that would have caught it: *if a calibration run happened for an
index, the runtime config must exist, be well-formed, and agree with the audit
trail.* Verified to fail (exit 1) with the config removed and pass (exit 0)
restored. It also asserts the legacy `0.80/0.60` constants never appear as live
thresholds on a whitened index.

**Why this matters to the app specifically:** the app does not read a band file
from the index directory at all. Bands come from the **manifest**, so this
dual-file trap cannot recur there. The Python-side fix is still required because
the benchmark harness and the shipped `PhotoID` read it.

---

## 5 · On-device budget

| Artifact | Size | Notes |
|---|---|---|
| formatter GGUF Q4_K_M | **688 MB** | `RegeneratusLabs/augury-1b` |
| encoder ONNX int8 | **~88 MB** | *pending measurement — see §6* |
| retrieval index (`index-v3`) | **42 MB** | 13,448 vectors × 384-d, no FAISS |
| species DB | **~1.5 MB** | from the manifest, not the APK |
| **Total first-launch download** | **~1.15 GB** | |

**The ~1 GB first-launch download is accepted and expected.** It is the price of a
local, open-source, self-hosted model with no server bill: the weights must reach
the device exactly once. `index.faiss` is deliberately excluded from the published
index, because the app performs brute-force kNN over 13,448 × 384 floats in plain
Kotlin — which removes FAISS as a native dependency and shrinks the artifact.

**Memory constraint carried over from the CLI:** the encoder (~350 MB) and the
GGUF (~700 MB) are never resident together — `scripts/thirdparty_test/run_field_test.py`
documents this for a 16 GB host. The app must release the encoder before
generation.

---

## 6 · Measured accuracy (and what it means for the UI)

Benchmark: `data/vision/au_split.json`, cleaned v3 gallery, **910 queries / 184
species**, fixed seed, every query excluded from its own gallery.

| Configuration | top-1 | top-3 |
|---|---|---|
| `index-v2` (pre-clean gallery) | 82.4% *(its own 916-query split)* | 91.3% |
| `index-v2` scored on the cleaned split | ~~95.5%~~ **invalid — see below** | — |
| **`index-v3` (shipped)** | **81.8%** | **89.7%** |
| 90% target | ❌ not reached | — |
| measured encoder ceiling | 92.3% | — |

> **A second, larger leakage trap — found 2026-09-19 while building this app.**
> Scoring `index-v2` on the cleaned `au_split.json` reports **95.5%**, which is
> self-matching, not retrieval. Measured directly: **805 of 910 (88.5%)** of that
> split's query vectors are *exact duplicates* of vectors in `index-v2`'s own
> gallery (median max cosine **1.0000**), because v2 was built from the
> pre-cleanup gallery while the split was regenerated during cleanup. `index-v3`
> shows only 9.5%, at median max cosine 0.6875 — genuinely different photos of
> the same species.
>
> **Critically, a filename check does not catch this.** Comparing query paths
> against `index-v2/files.json` reports **0** overlaps, because the gallery
> stores the same photos under *canonicalised* keys (`ribwort plantain` vs
> `plantago lanceolata`). The leak is invisible except in embedding space.
>
> **Consequence:** the honest v2 figure is **82.4%**, and **81.8% (index-v3) is
> the number to quote**. The invalid 95.5% and the reason are preserved in
> `data/vision/index-v2/band_config.json` under `superseded_measurement` so it
> cannot be resurrected by accident. Full log:
> `data/vision/bench/README-measurements.md`.

**The v2→v3 accuracy delta is +1.1 pt (n=93) — not significant.** The value of
the gallery repair is elsewhere: four contaminated species went from unlearnable
to working (`holcus lanatus` 0/5 → 4/5, `raphanus raphanistrum` 0/5 → 4/5,
`sinapis arvensis` 0/5 → 5/5), per-species numbers became meaningful, and **the
95% precision band became reachable** — the handover's "no threshold reaches 95%"
was a symptom of the contamination, not an encoder limit.

> **Two distinct leakage traps have now been hit in this repo.** The first
> (recorded in the handover) reported **97.88%** on a regenerated split, because
> rebuilding the split made 803 original query files into gallery members. The
> second is the v2 duplicate-vector leak above, which is larger and **invisible
> to filename comparison**. Both produce inflated numbers that look like
> progress. The standing rule: never compare across two splits, and always probe
> for exact duplicate vectors rather than trusting path sets.

### Product consequences — these are UI requirements, not suggestions

1. **Never silently accept a species from a photo.** Top-1 is 81.8%; the app
   always shows top-3 and requires a tap. `auto` means *higher confidence*, never
   *safe to accept*.
2. **Do not resurrect `0.80`.** v3 uses `0.68`/`0.43`, read from the manifest.
3. **A confident wrong ID yields a faithfully-formatted story about the wrong
   plant.** Blind spot #2 in `docs/model-understanding-and-blindspots.md` is the
   strongest argument for the confirm step.
4. **The tap-a-weed picker is the most reliable path in the product** — 185 of 188
   AU species have real common names, all 188 have indicators, and it avoids the
   **56.3%** held-out extraction rate that would otherwise fail non-technical
   users. It should be the default surface, not a fallback.

---

## 7 · Known issues carried forward

- **The published species DB is stale.** HF serves `database-merged.json` at
  revision `85e57fb` (2026-08-11, 1,155,275 bytes); the working copy is 1,125,629
  bytes and includes the AU merge, the mojibake repair and the canonical-group
  indicator merge. Republish before the app reads facts from HF.
- **The vision index is not published yet.** `RegeneratusLabs/augury-vision-index`
  does not exist on HF.
- **`index-v3` does not satisfy the original 90% top-1 target.** The remaining gap
  is thin galleries plus genuinely hard look-alike genera
  (`banksia`/`hakea`/`callistemon`/`lepidosperma`,
  `austrostipa`/`austrodanthonia`), not corruption.
- **18 gallery images still have unresolved licences** (`license: null`,
  `requires_verification`). `scripts/backfill_sidecars.py --check-publishable`
  exits non-zero while that holds, by design — the gallery cannot be published by
  accident.
- **Encoder accuracy on-device is unmeasured until §5's export gate runs.**
  Whatever int8 costs, it must be measured through the *app's* encoder, not
  assumed from the fp32 benchmark.

---

## 8 · References

- [`OpenBMB/MiniCPM-V-Apps`](https://github.com/OpenBMB/MiniCPM-V-Apps) — surveyed and rejected (§2)
- [`ggml-org/llama.cpp`](https://github.com/ggml-org/llama.cpp) — MIT, the inference engine used
- [`facebook/dinov2-base`](https://huggingface.co/facebook/dinov2-base) — the retrieval encoder
- `data/vision/index-v3/` — the shipped index and its calibrated bands
- `data/vision/bench/README-measurements.md` — the contamination repair and leakage trap
- `docs/mobile-app-plan.md` — superseded proposal, retained for the OpenBMB survey and distribution table

*Companion docs: `technical-stack.md`, `model-understanding-and-blindspots.md`,
`data-roadmap.md`.*

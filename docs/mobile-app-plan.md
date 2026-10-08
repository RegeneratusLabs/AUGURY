# AUGURY — Mobile App / Distribution Plan (SUPERSEDED)

> **⚠️ SUPERSEDED 2026-09-19 by [`docs/mobile-app-decision.md`](mobile-app-decision.md).**
>
> The decision to **fork OpenBMB's MiniCPM-V-Apps** (§3 Option A, §6 Phase 0.3,
> §9 decision 2) has been **rejected**, on evidence gathered 2026-09-19:
>
> 1. **`OpenBMB/MiniCPM-V-Apps` has no licence.** The GitHub API returns
>    `"license": null` and there is no `LICENSE` file in the tree — unlicensed
>    code is "all rights reserved", so vendoring it into an Apache-2.0 project
>    breaks the open-source promise. (`llama.cpp` itself is MIT — fine.)
> 2. **It cannot run AUGURY's photo path.** Their apps are a shell over a
>    `llama.cpp` fork; AUGURY's retrieval is DINOv2-base embeddings + kNN over a
>    13,448-vector index, none of which is a llama.cpp capability. We would
>    rewrite the entire AI layer anyway.
> 3. **It cannot deliver "pull from HF".** Their model weights download in-app,
>    but app logic changes only via a new APK release — the exact problem the app
>    is meant to solve.
> 4. **Sideload/TestFlight is unusable for the target user** (zero technical
>    ability, and iPhone unsupported).
>
> **What replaced it:** a standalone Android APK built on the MIT `llama.cpp`
> bindings, structured as a **shell** — it bundles no model data and pulls every
> artifact from HF through a version-pinned manifest.
>
> Also superseded by measurement: §7's confidence-band note (`0.80` auto-accept)
> is **wrong** — see `docs/mobile-app-decision.md` §4. Bands are now calibrated
> per index (`index-v3`: 0.64 / 0.30) and read from the artifact, never
> hard-coded. And §2's "186/188 AU species, 14,274 vectors" describes the
> abandoned v1 index; the shipped artifact is `index-v3`, 13,448 vectors.
>
> The rest of this document is retained for provenance — particularly §2's survey
> of OpenBMB's repo internals and §5's distribution table, both of which remain
> accurate and useful.

**Status:** PARKED 2026-08-18 — this is a continuation document, not an active
workstream. Pick up from here when ready.

---

## 0 · Context: decisions already locked this session

- The 15GB image gallery was **deleted from HF** — it is a local-only build-time
  source (never read at runtime). No record remains on HF; GitHub reflects this.
- The local FAISS index is **AU-only** (186/188 AU species, 14,274 vectors,
  ~85MB). `astrebia spp` + `austrocylindropuntia spp` missing (no/few photos).
- The text funnel (extraction → DB → formatter) is the proven, working layer.
- The 15GB is never bundled in any app — the phone gets at most the AU index.

---

## 1 · Goal & success criteria

Ship AUGURY so **non-technical users** can use it on a phone, fully on-device
(no cloud, no API keys — project guard rail), **AU-scoped for v1**.

**Success criteria:**
- A non-technical user installs the app (Android first) and asks "What does
  dandelion indicate about my soil?" → gets the AUGURY soil story, offline.
- Model downloads once in-app (WiFi), MD5-verified, stored.
- Photo path (v1.1, optional): camera → top-3 AU species → confirm → story.
- All bundled artifacts licensed (Apache-2.0 code/weights, CC-BY-4.0 DB);
  the 15GB gallery is NOT bundled.

---

## 2 · Research findings (grounds the fork decision)

### OpenBMB's official app repo — [MiniCPM-V-Apps](https://github.com/OpenBMB/MiniCPM-V-Apps)
- Ships iOS / Android / HarmonyOS demos running MiniCPM models **fully on-device
  via llama.cpp**, and **explicitly supports MiniCPM5-1B (text-only)** — our
  exact base model.
- Android: min API 26, arm64-v8a, ≥4GB RAM recommended for the 1B model.
  Pre-built APK ~21MB (model downloads separately).
- Distribution (their `DOWNLOAD.md`): GitHub Releases APK + iOS TestFlight +
  HarmonyOS HAP — "research/preview, not optimized products", **not on
  Play/App Store**. Our goal ("app store download") is a higher bar.
- **No LICENSE file in their repo** — demo code is unlicensed upstream
  (models Apache-2.0, llama.cpp MIT). Licensing approach needs a decision
  (see §6).

### Android demo internals (the fork surface — ~20 Kotlin files)
- `ModelInfo.kt` — model catalogue (`hfRepo`, `ggufFileName`, MD5). Add one
  entry → our GGUF. Downloader races HF/ModelScope, verifies MD5, deletes on
  mismatch.
- `LlamaEngine.kt` — llama.cpp JNI binding with `setSystemPrompt()` (the AUGURY
  persona drops in cleanly).
- `ModelDownloadService.kt` + `ModelManagerActivity` — first-launch in-app
  model download UI with expected-directory layout + `adb push` sideload.
- `MainActivity` / `ChatAdapter` — chat UI, replaceable with AUGURY flow.

### Our runtime artifacts
| Artifact | Size | Notes |
|---|---|---|
| `MiniCPM5-1B-AUGURY-Q4_K_M.gguf` | 657MB | in-app download from `RegeneratusLabs/augury-1b`; **MD5 `a222bbcaf055b790f2e9e13d2bb3d8cb`** |
| `database-merged.json` (2,230 spp) | 1.2MB | bundle in APK assets |
| `species_list.json` (names + AU flags) | 1.1MB | powers picker/autocomplete |
| AU FAISS index (`keys.json` + embeddings) | ~85MB | photo path only |
| DINOv2-base encoder | 331MB | photo path only — **not** llama.cpp-runnable (⚠️ §4B) |

---

## 3 · Core product decision: what does the app DO?

### Option A — "Ask AUGURY" text app (recommended v1)
- User picks a weed (searchable list, AU-first, common-name-first) or multi-selects
  ("docks and thistles").
- **Deterministic DB lookup runs on-device** (the model never generates facts —
  guard rail). Two sub-paths:
  - **A1 (recommended): species picker + multi-select.** No regex, no
    LLM-extraction fragility. Non-technical users don't type scientific names.
  - A2: port the funnel's regex + fuzzy-match extraction to Kotlin for free-text.
    More work + edge cases; only if free-text is a must-have.
- Then: DB lookup → build the training-format prompt (`Species / Region /
  Indicators:`) → `setSystemPrompt` (AUGURY persona) → llama.cpp chat →
  soil story. Region = AU for v1 (keep selector for EU later).
- Reuses the OpenBMB shell ~90%; real work = AUGURY flow, DB assets, one
  `ModelInfo` entry, branding.

### Option B — Add the photo path (v1.1, significant extra work)
- Camera/gallery → DINOv2-base embed → FAISS kNN over the AU index → top-3 with
  confidence bands (auto ≥0.80 / confirm ≥0.60 / unknown) → confirm → same story.
- ⚠️ **DINOv2 is NOT a llama.cpp model.** Options: export to ONNX + ONNX Runtime
  Mobile, or TFLite (~1-2 weeks engineering; 331MB encoder downloaded in-app).
  Or defer — the photo path is the least-proven layer anyway.

### Option C — Full funnel ported to Kotlin (most faithful, most work)
Only worth it if free-text questions are the product.

**Recommendation: Option A1 for v1** (picker + DB + formatter, AU-scoped);
photo path as v1.1.

---

## 4 · Beta testing: free / low-cost inference server (user suggestion)

**New idea (2026-08-18): run the funnel on a hosted inference server for beta
testing instead of building the app first.** This is cheap, fast to stand up
(the server already exists), and lets real users validate the *behaviour*
(fact-echo, refusals, multi-species) before investing in the app build.

- **What exists today:** `scripts/augury_server.py` (Flask + llama.cpp + funnel)
  already serves a web chat UI with a feedback loop. It runs on the local
  16-core box today.
- **Hosting options (free/low-cost):**
  | Host | Cost | Notes |
  |---|---|---|
  | Hugging Face Spaces (CPU) | free tier | small LLM OK; cold starts; slow but works |
  | Hugging Face Spaces (GPU) | low | T4 small — fast enough for a 1B Q4 |
  | Railway / Render / Fly.io | ~$5/mo | deploy the Flask app; llama.cpp build needed |
  | Cheap VPS (Hetzner/OVH/Linode 4GB) | ~$4-6/mo | most control; run llama-server |
  | RunPod / Modal / Replicate | per-second | good for spikes; not for always-on beta |
- **UX for testers:** a plain web link (no install) — chat box in the browser,
  or a PWA added to home screen. Non-technical testers just open a URL.
- **Trade-off vs the app:** violates the "no cloud at runtime" guard rail — but
  ONLY as a beta vehicle with a clearly scoped opt-in; the shipped product
  remains on-device. Also validates UX before Play Store friction.
- **Recommendation:** stand up a cheap Spaces/VPS instance of `augury_server.py`
  (AU-region default) → share the link with beta testers → collect feedback →
  THEN build the Android app (Phase 1) once behaviour is validated.
- Note: the model GGUF is already on HF (`RegeneratusLabs/augury-1b`); the
  server needs only GGUF + `database-merged.json` + `species_list.json`.

---

## 5 · Distribution options (the "app store" question)

| Option | Effort | Cost | Friction for users | Notes |
|---|---|---|---|---|
| **GitHub Releases APK** (what OpenBMB does) | Low | $0 | Medium — "install unknown apps" | Fastest; great for testing; not "app store" |
| **Google Play Store** | Medium | **$25 one-time** + account | Low | Needs privacy policy + data-safety form + AI-content disclosure. **Real v1 store target.** |
| **Apple App Store / TestFlight** | High | **$99/yr** + Apple device + review | Low | Swift; separate path; OpenBMB uses TestFlight rolling. Defer. |
| **F-Droid** | Low | $0 | Low-medium | Free, no review; Android-only; secondary channel. |
| **Direct sideload link** | Low | $0 | High — "unknown sources" | Last resort. |

**Recommendation:** beta via hosted inference server (§4) → Android APK on
GitHub Releases (internal) → Google Play (user-facing v1). iOS later.

---

## 6 · Implementation phases (for later — NOT active)

### Phase 0 — Confirmations & prerequisites
1. v1 scope: text-only picker app (A1), photo path deferred.
2. Distribution: GitHub Releases APK first, Play Store as the goal (needs Play
   Console account + $25 + privacy policy).
3. **Licensing decision:** OpenBMB demo code is **unlicensed** upstream.
   Options: (a) vendor OpenBMB demo code with attribution (risky), or
   (b) **build our own thin Android app on llama.cpp's MIT Android binding,
   copying only the patterns** (clean licensing, more work).
   **Recommend (b).**

### Phase 1 — Android text app
- New repo `RegeneratusLabs/augury-android` (Kotlin + Gradle, llama.cpp MIT
  binding).
- Model catalogue entry: `RegeneratusLabs/augury-1b` /
  `MiniCPM5-1B-AUGURY-Q4_K_M.gguf` / MD5 `a222bbcaf055b790f2e9e13d2bb3d8cb`.
- First-launch download screen (WiFi hint, progress, resume, MD5 verify,
  ≥2GB free check).
- Species picker from bundled `species_list.json` (AU first, multi-select).
- DB layer: bundled `database-merged.json` (SQLite or in-memory JSON).
- Prompt builder = the funnel's exact training-format payload; system prompt =
  AUGURY persona (`FORMAT_SYSTEM` in `augury_funnel.py`); temperature 0.3,
  max_tokens 500.
- Refusal + "no data" paths (e.g. serrated tussock) deterministic.
- Tests mirroring the local acceptance battery (fact-echo, multi-species,
  refusal, unknown).

### Phase 2 — Publish
- GitHub Releases APK → Play Store (privacy policy, data-safety, AI-content
  disclosure, listing copy, screenshots). Update README/docs.

### Phase 3 — Photo path (v1.1, gated)
- DINOv2 → ONNX/TFLite; bundle/download AU index; kNN + bands; real-device
  accuracy pass vs 80.9% top-1 server baseline.

### Phase 4 — iOS (defer)
- Only after Android validated with real users.

---

## 7 · Edge cases & failure modes (planned for)

- Model download failures on limited connections → resume + MD5 + retry;
  consider ModelScope mirror (OpenBMB downloader races HF/ModelScope by default).
- Storage pressure → ≥2GB free check before download.
- Low-RAM devices → 1B Q4 needs ≥4GB RAM; detect and warn.
- Common-name gaps (~110/2,230 have real common names) → picker falls back to
  scientific names, AU-first; known DB gap, not an app bug.
- Species with no indicators → deterministic "no indicator data yet" answer.
- Offline guarantee → no network permission after model download.

---

## 8 · Explicit assumptions

- v1 = Android, text-only, AU-scoped (per "keep it AU only at the moment").
- The 15GB gallery is NOT bundled (local-only; app gets at most the AU index).
- OpenBMB demo code = reference, not vendored verbatim, unless the licensing
  risk is accepted (Phase 0.3).
- Play Store account/listing is the user's responsibility; I prepare all assets.
- Beta inference server (if used) is an explicitly-scoped beta vehicle, not the
  shipped product's runtime.

---

## 9 · Open decisions (pick up here next session)

1. v1 scope: text-only picker app (A1) — agree?
2. Licensing: own app on llama.cpp MIT binding (recommended) vs vendor OpenBMB code?
3. Distribution: GitHub Releases APK now + Google Play as goal — agree?
4. Beta path first: stand up a free/low-cost inference server (§4) to validate
   behaviour with testers before the app build — want this?
5. App name/branding: "AUGURY — soil health from your weeds"? (open to naming)

---

*Continuation doc. Companion: `docs/model-understanding-and-blindspots.md`,
`docs/gallery-phone-discussion.md`, `docs/data-roadmap.md`.*

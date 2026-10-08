# AUGURY — Release Decision: ship the database, park the model

**Date:** 2026-10-08 · **Status:** proposed, awaiting owner decision
**Question answered:** after months of stalled progress, what is the shortest path
to something real in the public's hands — and is the OpenBMB model, or the custom
photo-ID component, on that path?

> **One-line answer.** Neither. The thing that can ship already exists in the repo:
> the tap-a-weed picker and the deterministically rendered indicator card. Ship
> **that**, at ~1 MB and fully offline, as v1.0. The OpenBMB formatter is a research
> artefact that has already been (correctly) excluded from the app. The custom photo
> index is a genuinely good piece of engineering that is currently a **legal
> liability, not a differentiator**, and it costs 368 MB of first-launch download to
> produce an 85% top-3 shortlist on the one distribution it was tuned on, and 60%
> top-1 on the only independent test. The project is not stalled on a hard problem.
> It is stalled on packaging work that contains no research.

---

## 1 · The evidence, in one place

Everything below was re-verified against the working tree on 2026-10-08.

| Claim | Reality | Where |
|---|---|---|
| The app exists and works | ✅ Compose UI, 6 screens, real species store, real resumable SHA-256-verified downloads, real ONNX photo path | `augury-android/app/src/main/java/au/org/regeneratus/augury/**` |
| The app can be built from a clean clone | ❌ `CMakeLists.txt` hard-fails on `third_party/llama.cpp`, which is **gitignored, absent, has no `.gitmodules` entry, and whose fetch script `scripts/fetch-llama-cpp.sh` does not exist and never did** | `app/src/main/cpp/CMakeLists.txt:15-20`; `.gitignore:49-50` |
| The release variant is shippable | ❌ `isDebuggable = true`, no `signingConfig`, no R8 rules, `versionName = "0.1.0-spike"`, no launcher icon, no `mipmap/` at all, `targetSdk = 34` | `app/build.gradle.kts:24-25,58-62`; `AndroidManifest.xml:16-21` |
| It has been run on a real phone | ❌ Never. The host has no `/dev/kvm`, the emulator is unusable for this workload | `docs/HANDOVER-2026-09-26.md` |
| The work is committed | ❌ HEAD is 2026-09-20. **32 modified + 15 untracked files** — the entire template-only pivot (2026-09-29) lives only in the working tree | `git status` |
| Photo ID accuracy (benchmark) | 85.87% top-1 / 92.83% top-3 on a 920-query AU holdout — **the same set used to calibrate the bands** | `data/vision/index-v3/band_calibration.json`; `HANDOVER-2026-09-26.md:151-162` |
| Photo ID accuracy (independent) | **60% top-1 / 85% top-3** on 20 fresh third-party photos; `auto` band was 3/5 = 60% precise; 2/10 non-weed controls false-accepted | `data/thirdparty/report-augury-thirdparty-test.md` §4.1-4.2 |
| Photo ID coverage | **173 species** of the app's 2,256 (7.7%); zero European or UK species despite 2,102 EU DB rows | `data/vision/index-v3/meta.json`; `data/app/augury-ondevice.json` |
| Photo ID download cost | **~372 MB** (346.5 MB encoder + 24.7 MB index) to reach 173 species | `data/app/manifest.json` |
| Picker download cost | **~1.0 MB** (`augury-ondevice.json`), enough for all 2,256 species | `data/app/manifest.json:12` |
| The formatter (OpenBMB MiniCPM5-1B) is shipped | ❌ Already excluded — `USES_STORY_MODEL = false`; it invented a pH threshold in 7/20 field-test answers and needs a grounding pass | `ShellCapabilities.kt:62`; `report-augury-thirdparty-test.md` §4.4 |
| The vision gallery is licence-clean | ❌ 5,636 CC-BY-NC images of 64,520 (**8.7%**), including **47 NoDerivatives**; 18 unresolved; the project's own publish gate exits non-zero by design | `data/vision/dataset_stats.md`; `backfill_sidecars.py --check-publishable` |
| The shipped index has a licence and attribution | ❌ Published on HF twice with **no dataset card, no licence, no attribution** | `RegeneratusLabs/augury-vision-index`, `augury-app` |
| Docs are internally consistent | ❌ `README.md` juxtaposes two numbers as if independent; `augury-android/README.md` still advertises a 1.06 GB download and a llama.cpp diagram; `technical-stack.md` still calls index-v3 unpublished | see §11 |
| "185 of 188 AU species have real common names" | ❌ 185 have *a* `common_names` field; **57 of those are just the scientific name repeated**. Genuine vernacular names: **147 of 221** AU species in the shipped bundle | verified against `data/app/augury-ondevice.json` |

**The pattern:** the science is done and unusually honest. The shipping work is not
done, and it is not even started.

---

## 2 · Why the project stalled

This is not a project that hit a wall. It is a project that keeps finding new
interesting walls to look at instead of walking out the door.

Three dynamics, all visible in the artefacts:

1. **The definition of done kept moving.** From `docs/HANDOVER.md` (31 July):
   *"Pick ONE path and finish it. Don't revisit the architecture debate."* That
   advice was correct and was not followed. Since then: Path A vs Path B, template
   vs voice, fork OpenBMB vs build a shell, 80.9% → 82.4% → 81.8% → 85.87%,
   index-v2 → index-v3. Each pivot was individually justified. Collectively they
   reset "done" every time.

2. **Every remaining task is a research task except the ones that ship.** Measuring
   leakage, calibrating bands, auditing grounding — these are tractable, scoreable,
   intellectually satisfying, and never finish. Signing a keystore, drawing an icon
   and packaging an APK are unglamorous, unscored, and finish in an afternoon.
   The project has optimised for the first kind.

3. **The architecture debate was settled, then re-opened in the user's own head.**
   `docs/mobile-app-decision.md` already concluded that the picker "is the most
   reliable path in the product... It should be the default surface, not a
   fallback" (§6, consequence 4). The code already implements exactly that
   (`HomeScreen.kt:37-50`). The question "should we emphasise photo ID or use an
   existing platform?" has therefore **already been answered in the repo** — it just
   has not been *acted on*.

Effort is not the constraint. The repo contains ~19,700 lines of verified research,
2,256 species, 200 Kotlin unit tests, six handovers and 30 unpushed commits — and
zero releases.

---

## 3 · Is the OpenBMB model the right path forward?

**No. And you already decided this — you should now make the decision final.**

There are three separate "OpenBMB" things in this project's history and they should
not be conflated:

| Thing | Status | Verdict |
|---|---|---|
| Forking `OpenBMB/MiniCPM-V-Apps` | Rejected in `docs/mobile-app-decision.md` §2 (no licence, cannot run the photo path, wrong distribution model) | ✅ Correctly rejected. Leave it. |
| `openbmb/MiniCPM5-1B` + LoRA ("the voice") | Trained, published, and **already excluded from the shipped app** | ✅ Correctly excluded. Now **freeze** it. |
| A future OpenBMB VLM as the photo-ID engine | Not built | ❌ Not a release path (licence terms, on-device size). Research only. |

The evidence for freezing the voice is stronger than the decision record admits:

- It **invented a decimal pH threshold in 7/20 answers**, including a
  self-contradiction on wild radish that would have told a farmer to lime an
  already-acidic soil — and a stricter prompt did **not** fix it (still 7/20).
- It costs **688 MB**, the single largest artefact in the project.
- It adds **~4 s per answer** and a mandatory grounding pass.
- It returns prose. The deterministic template returns a card that **cannot** be
  wrong about a number, because no model writes one.

The voice is a solution to a problem the product does not have. Nobody needs soil
indicators delivered conversationally; they need them correct and fast. Publishing
the LoRA as an open artefact is a fine contribution to the ecosystem — but it is not
v1, and continuing to develop it is continuing to delay the release.

**Action:** publish the model card as-is, stop training, and remove the
"conversational version" from all public roadmaps. Keep the code; it is tested.

---

## 4 · Photo ID: build, buy, or drop?

### 4.1 Reframe the question

Every photo-ID path in this product ends the same way: **the user taps a species.**
The pipeline *structurally requires* top-3 and refuses to run a configuration that
could silently accept one (`VisionPipeline.kt`). For 36% of benchmark queries the
result lands in the `confirm` band; 2.5% of top-3 sets are congeneric pairs that need
a botanical key. "High confidence" is wrong **4.81%** of the time.

So the question is not "can we identify the plant?" It is **"is a ranked shortlist
worth 368 MB of first-launch download?"** Judged that way, the photo component is a
nice-to-have, not the product.

### 4.2 The three options

| | A · Build (current) | B · Buy (Pl@ntNet / iNat API) | C · Drop for v1 |
|---|---|---|---|
| First-launch download | **~372 MB** | ~1 MB | **~1 MB** |
| Species reachable by photo | 173 (7.7% of DB) | open-set; intersect with your DB list | n/a |
| Works offline | ✅ | ❌ (falls back to picker) | ✅ (picker) |
| Licence exposure | **CC-BY-NC/ND-derived index** | third-party terms + attribution | **none** |
| Build complexity | ONNX Runtime + llama.cpp native + CMake + NDK | HTTP client | none of it |
| Real-photo top-1 | 60% (n=20 independent) | unknown; needs a trial | n/a |
| Grass/rosette performance | **worst class** (grasses 1/4 top-1, 2/4 top-3) | unknown; likely better coverage | n/a |
| Effort to ship | blocked (build is broken) | ~2-5 days + API key | **~0** |
| Marginal value over picker | shortlist | shortlist | — |

> **API specifics, pricing, quotas and terms:** see the companion research summary
> in §12 once the market survey lands. The decisive constraint is not price — it is
> that the free tiers are sized for a *pilot*, not a public launch, and every option
> introduces a third-party runtime dependency into a project whose stated design
> constraint is "no cloud at runtime".

### 4.3 Recommendation

**C now → B next → A parked.**

1. **v1.0 ships with no photo ID at all.** The picker is offline, instant, 1 MB, and
   already written. This is the shortest possible path to "released".
2. **v1.1 adds photo ID as an online assist**, behind a flag, clearly labelled
   "needs internet", which *pre-filters the picker* rather than answering. Use an
   existing API. Intersect its ranked output with the 2,256-species DB list so the
   candidates it offers are always answerable.
3. **Park the custom index** as a research track. Revisit it only if (a) the
   licence is fixed by rebuilding NC-free, **and** (b) it beats the API on the same
   30 third-party photos. That is a measurable question, and cheap to answer once
   the API baseline exists — which is another reason to buy first.

### 4.4 The one real cost of dropping photo ID

Offline photo ID in a paddock with no signal. But note: the picker is *already*
offline and covers 13× more species. The genuine loss is small, and the mitigation
is a labelled fallback, not a 372 MB tax on every install.

---

## 5 · The licence landmine — why the build path is worse than it looks

Independent audit, 2026-10-08:

- **8.7% of the vision corpus is CC-BY-NC**, including **47 NoDerivatives** images
  and 22 unknown-licence images (`data/vision/dataset_stats.md`). iNaturalist's
  default licence is CC-BY-NC, so the AU subset's share is unmeasured and could be
  higher.
- **18 gallery images have unresolved licences and `backfill_sidecars.py
  --check-publishable` exits non-zero by design** — *the project's own tooling
  refuses to publish this*. It was overridden.
- **The embedding index is redistributed** (two HF dataset repos plus git), and it is
  derived from those images. Whether embeddings are "Adapted Material" is legally
  unsettled — which is precisely why a public release should not bet on the
  favourable reading.
- **Worse: it ships with no licence and no attribution at all.** Both HF repos have
  no dataset card. `data/vision/index-v3/files.json` republishes a resolvable list
  of the exact source photo filenames with no photographer names and no copyright
  notices.
- **The repo's own claims are then false.** `README.md` says "Apache-2.0 (code,
  weights) · CC-BY-4.0 (database, training data)" and "All open source";
  `technical-stack.md` says "Everything Apache-2.0 / MIT / CC-BY-4.0" — while the
  same document calls the gallery non-commercial. CC-BY-NC fails the Open Source
  Definition. **"All open source" is not true today.**
- Secondary: 13 CC-BY-NC photos are committed under `data/thirdparty/photos/` with
  no carve-out in `LICENSE-DATA`.

**Consequences:** open-sourcing the vision component as claimed is a compliance
defect; a free, ad-free, personally-published Play listing is defensible *only if
genuinely non-commercial*; any commercial use is off the table without a rebuild.

**And the fix is already half-written:** `pull_inaturalist.py` defines
`NC_OK = {"cc0","cc-by","cc-by-sa"}` and already sorts non-NC images first. A
licence-clean rebuild is a filter, a re-pull, a re-index and a re-measure — days,
not months.

**For v1.0 this entire section is moot, because you ship no index.** That is the
strongest argument for option C: it removes a live legal question from launch day
rather than answering it under time pressure.

---

## 6 · Recommendation: what v1.0 is

**v1.0 — "Name the weed, read the soil."**

| In scope | Out of scope (deliberately) |
|---|---|
| Search/browse 2,256 species by common or scientific name | Photo identification |
| Region filter: Australia / UK / Europe | The MiniCPM formatter |
| The deterministic indicator card | The "conversational version" |
| Top-3-style honesty: indicator keys are shown, never generated | The SLM ecosystem roadmap (soil / remediation / grazing) |
| "Indicators only, no management advice" framing | Any new species research |
| Offline after first load | Analytics/telemetry (the app has none — keep it that way) |
| ~1 MB first-launch download | |

This is not a compromise product. It is the product the app's own decision record
already named as the most reliable one, aimed at the users it was built for.

---

## 7 · The release plan

Assumes one focused person and the current code. Durations are working days.

| # | Task | Days | Why it blocks release |
|---|---|---|---|
| 1 | **Commit the template-only pivot.** Then make the llama.cpp native build conditional (or delete it and `SpikeActivity`) and get `git clone && ./gradlew assembleRelease` working on a clean checkout. | 1 | The shipped app provably never loads llama.cpp (`ShellCapabilities.kt:62`, `AuguryGatewayImpl.kt:911-919`). Removing it unblocks reproducible builds and drops a native crash class. |
| 2 | **Make vision optional** in the manifest contract and the download plan, and fix the startup/offline error path (the real message is currently trapped on an unreachable Settings screen). | 1 | Turns a 372 MB first launch into a 1 MB one. This is the single highest-leverage product change. |
| 3 | **Release config:** `isDebuggable = false`, signing keystore (outside the repo), R8, `versionCode`/`versionName`, launcher + adaptive icon, `targetSdk` 36. | 1 | Play rejects debuggable APKs outright; a missing icon is a hard listing failure. |
| 4 | **Install on a real phone and use it for a day.** Fix what breaks. | 1 | The only verification that has never been performed. Everything on-device is currently unproven. |
| 5 | **Ship:** privacy policy, data-safety answers, a "what this is / is not" screen, then publish the APK to GitHub Releases. | 1 | Distribution. GitHub Releases first (no account gate); Play in parallel if wanted. |
| 6 | **Put it in 10 users' hands** — farmers, agronomists, the third-party tester already in `data/thirdparty/`. Watch what they do. | 2-3 | You have no usage data at all. Nothing you believe about this product is currently tested against a user. |
| 7 | **Play listing** if desired: account, screenshots (feature graphic + 512×512 icon), data safety, content rating. | 1-2 | Optional; the APK is already "released" without it. |

**Total: ~1 week to a public APK, 2-4 weeks to a Play-ready listing.**

Then — not before — v1.1 photo assist, driven by whether users actually ask for the
camera.

---

## 8 · Stop-doing list

Written down because each of these has consumed real time in the last quarter:

1. **Stop tuning the index.** 90% top-1 was never the goal; it was a proxy that
   replaced the goal. The goal is a released app someone uses twice.
2. **Stop training the formatter.** It is published and excluded. Done.
3. **Stop the ecosystem roadmap in public.** "AUGURY → Soil → Remediation → Grazing"
   tells a user you have not shipped the first one. Remove it from `README.md`.
4. **Stop adding species and research** before there are users to justify it. 2,256
   species is not the bottleneck; 0 users is.
5. **Stop treating "an existing photo platform" as a dependency risk** when the
   alternative on the table is no release at all.
6. **Stop reopening the architecture debate.** It is answered, in writing, in
   `docs/mobile-app-decision.md` §6.

---

## 9 · How you will know it is working

Measure these from day 1, because none of them have ever been measured:

- **Time from install to first soil story** — target under 60 seconds. (Currently
  gated behind a 372 MB download.)
- **Install → first lookup rate.** Do people open it at all?
- **Second lookup rate.** Does anyone come back with a second weed? *This is the
  real product test.*
- **Photo-button taps per session** — the demand signal for v1.1.

If retention is flat, the problem is the value proposition, not the identification
model — and no amount of indexing work will fix it. That is why shipping first is
not a compromise; it is the only way to learn which thing to build next.

---

## 10 · Decisions required from the owner

These are decisions, not research tasks. Each can be made today:

1. **Distribution:** GitHub Releases APK only, or Play too? (Recommendation: both,
   APK first.)
2. **Do you accept an online photo assist** (the photo leaves the device) as the
   v1.1 trade for a 1 MB install? (Recommendation: yes, opt-in and labelled.)
3. **Do you kill the conversational version publicly**, or keep it as a separate
   published artefact with no roadmap presence? (Recommendation: the latter.)
4. **Do you rebuild the index licence-clean**, or unpublish it and declare the photo
   component non-commercial until you do? (Recommendation: unpublish the tarball
   now — it has no licence card anyway — and rebuild only if v1.1 evidence justifies
   it.)

---

## 11 · Corrections to existing documents

Found while verifying this decision. These should be fixed regardless of which path
is taken, because they are claims that do not survive contact with the artefacts:

| Document | Claim | Correction |
|---|---|---|
| `README.md:28-29` | Juxtaposes 81.8/89.7 and 85.87/92.83 as if two independent results | The 920-query set is the same holdout used to **calibrate the bands**, and its top-3 is 89.7% in the measurement log; 92.83% is the app's duplicate-collapsing variant. Present one number, labelled. |
| `README.md:96-103` | "Apache-2.0 (code, weights) · CC-BY-4.0" and "All open source" | Not true while a CC-BY-NC/ND-derived index is distributed. Either rebuild or restate. |
| `docs/mobile-app-decision.md:430-433`; `HomeScreen.kt:41-43` | "185 of 188 AU species have real common names" | 185 have a `common_names` field; **57 repeat the scientific name**. Genuine vernacular names: 147/221 AU species in the shipped bundle. The picker still works, but the claim is ~25% overstated. |
| `augury-android/README.md:8-21,31-46` | ~1.06 GB download; llama.cpp architecture diagram | Contradicts the shipped template-only manifest (~372 MB, no GGUF). |
| `docs/technical-stack.md:40,132` | index-v3 13,448 vectors / 42 MB / unpublished | The shipped index is 16,580 vectors and is published (two HF repos). |
| `docs/data-roadmap.md` §3.1 | "~110 species have real common names" | Understated the other way, but the figure is still not the one to quote. Use "227 of 2,256 globally; 147 of 221 for AU". |
| `docs/model-understanding-and-blindspots.md:184-191` | "on-device footprint ~1.15 GB: an ~88 MB int8 encoder..." | int8 was measured and rejected; fp32 is 346.5 MB. |

---

## 12 · External platform survey

**Status: market survey in progress (Pl@ntNet, Plant.id/Kindwise, iNaturalist CV,
on-device VLMs, and the OpenBMB weight licences). It will be appended here when it
lands.** The questions it must answer:

1. Free-tier quota and **commercial-use terms** for Pl@ntNet and each alternative.
2. Whether the API accepts a **candidate species list** (so results can be
   constrained to the 2,256 species that actually have indicator data).
3. Attribution and result-storage obligations.
4. Published accuracy on **grasses, rosettes and immature plants** — the class the
   custom index is worst at.
5. Monthly cost at 1k / 10k / 100k identifications.
6. Whether an on-device VLM is a realistic photo-ID engine on a phone in 2026, and
   under what licence.

**What matters for the decision today, independent of the survey:** option C does
not depend on any of it. Ship the picker; evaluate the APIs when there are users to
justify the evaluation. The survey informs **v1.1**, not **v1.0**.

One project-specific finding worth carrying into that evaluation: the repo already
contains working clients for both iNaturalist CV and Pl@ntNet
(`scripts/plant_id.py`), so the "buy" path is a day of integration, not a rewrite.
Note also that the photo path has already been compared to Pl@ntNet-300K once —
`data/vision/plantnet_verdict.md` records that the *dataset* overlap was only
155 of 2,230 species, which is a statement about that dataset, **not** about the
live API. Do not let the earlier verdict stand in for an API trial.

---

## 13 · What could not be verified

- **Per-image licence composition of the shipped AU index.** The gallery sidecars
  (`data/vision/images/**/sources.jsonl`) are gitignored, absent, and were never
  committed. The 8.7% NC figure is dataset-wide, not index-specific.
- **Same-observation leakage in the benchmark.** iNaturalist observation IDs were
  never stored, so gallery/query grouping cannot be checked. The audit found no
  positive evidence of excess (13.7% vs a 14.4% baseline), but it cannot be ruled
  out. A residual 9.5% exact-duplicate rate is documented by the project itself and
  may inflate top-1 by ~1.5 pt.
- **Real-device behaviour of any kind.** No APK exists, and the app has never run on
  a physical phone.
- **The Gradle and instrumented test suites.** Not runnable in this environment (no
  JDK, no Android SDK, no Gradle cache). 8 of 10 root Python test files pass; the
  two failures are environmental (`faiss` not installed; the 15 GB gallery is
  absent by design).

---

## Appendix · Companion documents

- `docs/mobile-app-decision.md` — the shell architecture and the picker-first
  conclusion (§6) this decision acts on
- `docs/model-understanding-and-blindspots.md` — the honest failure-mode list
- `data/thirdparty/report-augury-thirdparty-test.md` — the independent field test
- `data/vision/dataset_stats.md` — the licence histogram behind §5

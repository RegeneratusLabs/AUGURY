# AUGURY — Session Handover: vision pipeline & workspace

**Date:** 2026-09-19 (vision/retrieval track)
**Scope:** workspace cleanup, then a root-cause hunt for why photo-ID stalled at
82% against a 90% target.
**State:** all work committed, **9 test files / 77 checks green**, tree clean.
`index-v3` is the current retrieval artifact at **85.9% top-1**.

> **Companion handover:** `docs/HANDOVER-2026-09-19.md` covers the **Android app**,
> built in a parallel session. Read it if you are touching the app — and note its
> §3: the app's bundled artifacts are **stale** because this session rebuilt the
> gallery after they were generated. You are reading the vision-side handover.

---

## 1 · TL;DR

| Area | Before | After | Status |
|---|---|---|---|
| AU photo-ID top-1 | 81.8% | **85.9%** (920 held-out queries) | improved; 90% missed |
| Auto-accept band | 95% unreachable | **t=0.64 → 95.4% precision, 63.7% coverage** | done |
| Cross-species contamination | 24 collision groups | **0** | done |
| Unvalidated galleries | 10 species at 100% | **0** | done |
| Duplicate species keys (text) | 12 pairs, differing data | **merged, identical answers** | done |
| Management questions | answered off-topic | **declined + redirected** | done |
| Mojibake entries | 14 | **0** | done |
| Gallery sidecar gaps | 21 | **0** | done |
| Workspace | junk dirs, home paths, no tests | **clean, 9 test files** | done |

**Headline: the 90% target was not primarily a compute problem.** The gallery was
teaching the model the wrong plants.

---

## 2 · The root cause — read this first

Ten AU species had galleries built entirely from an **unvalidated full-text search**.
The tell is the filename prefix: `q` (`q21504bc0_112844517.jpg`) means the species was
never resolved to an iNaturalist taxon, so the images were whatever text search
returned.

```
callistemon spp     11/11    austrostipa spp      47/47    hakea spp          45/45
banksia spp         50/50    dianella spp         48/48    lepidosperma spp   50/50
gahnia spp          50/50    cirsium spp          50/50    opuntia spp        50/50
austrodanthonia spp 11/11
```

`lepidosperma spp` — a **sedge** — contained a **pink poppy**. These were also
exactly the worst performers: `callistemon` 0%, `austrostipa` 20%, `hakea` 20%,
`banksia` 40%.

**Mechanism.** `pull_inaturalist.match_taxon()` accepted the first taxon candidate
sharing "any two tokens of 4+ characters" with the query — resemblance, not identity.
It resolved `prosopis spp` → taxon 52793, which *is* **Holcus lanatus**, and
`sinapis arvensis` → 55411, which *is* **Raphanus raphanistrum** (verified against
the API, not inferred). The ids were cached and never re-validated, so the damage
persisted and spread.

**Two earlier bugs had the same shape** — label registries disagreeing:
- The "2.2-point photo-ID discrepancy" was `PhotoID.canonical()` letting the legacy
  alias map override canonical merges; two entries reversed a merge by a full stop.
- The text DB carried all 19 duplicate species keys as separate species, **12 with
  different indicator data**, so "curled dock" and *Rumex crispus* gave different
  soil stories for the same weed.

---

## 3 · Verified numbers

### Photo ID trajectory (every row leakage-checked)

| build | gallery | top-1 | note |
|---|---|---|---|
| v1 raw keys | 13,358 | 71.8% | label fragmentation |
| v2 canonical + PCA | 13,358 | 82.4% | labels also cross-contaminated |
| v3 cleaned | 13,448 | 81.8% | contamination repaired |
| **v3 validated** | **16,580** | **85.9%** | 10 fallback galleries re-pulled |

Current: **920 held-out queries / 184 species**, top-3 89.7%, auto band t=0.64 at
95.4% precision (63.7% coverage). **Leakage check: 0 of 920 query files appear in the
gallery.**

### Levers measured and ruled out — do not retry

| lever | result |
|---|---|
| kNN label voting (k=3…50) | 80.1% → 67.0% — hurts at every k |
| similarity / sim³ weighted voting | 79.0% → 80.1% — still below 1-NN |
| Flip-TTA | 80.5% — slightly negative |
| Per-species gallery caps 40/60/100 | harmful at 40, neutral at 60/100 |
| Linear classifier head (174-way) | 20.2% — far worse than retrieval |
| SigLIP2-400M fusion | 0.17 img/s CPU (~23 h/AU pass) |
| DINOv2-large | 0.16 img/s (~24 h) |

### Still live

| lever | measured |
|---|---|
| Density pilot (4 species, 50→300 imgs) | **+35 pts pooled**, n=20, CIs overlap — indicative, not settled |

---

## 4 · Where 90% stands

**4.1 points short.** The arithmetic is unforgiving — even taking *every* species
below 90% to exactly 90% reaches only **89.3%**. So:

1. **Resume densification** to 300/species on *thin* species — ~46,323 images.
   Measured throughput **24–70 images/min single-stream** → **11–32 hours**.
   Parallelising the download is the real lever, **not GPU rental**: embedding 46k
   images is ~1.3 h on CPU (~8 min on a rented GPU).
2. **Encoder fine-tune** — now viable because labels are clean. The prior attempt
   failed (8.6% vs 74.6%), which was a recipe bug, not a verdict.
   `scripts/vision/fine_tune_encoder.py` exists. This attacks congeners and
   ambiguous field photos, where density is hitting diminishing returns.
3. **Genus look-alikes** (`banksia`/`hakea`, `austrostipa`/`austrodanthonia`) are now
   correctly populated but genuinely hard. Decide whether they are species-level
   products or should be honestly presented as genus-level.

---

## 5 · What shipped

### New scripts

| Path | Purpose |
|---|---|
| `scripts/junk_keys.py` | denylist of non-species keys (UK soil associations, truncations) |
| `scripts/cleanup_workspace.py` | removes empty dirs left by junk keys; idempotent |
| `scripts/backfill_sidecars.py` | repairs gallery provenance; `--check-publishable` gate |
| `scripts/repair_mojibake.py` | PDF-extraction artefact repair (URL-safe) |
| `scripts/claim_verify.py` | direction verifier — **62.5% FP, deliberately NOT shipped** |
| `scripts/vision/audit_gallery_integrity.py` | detects cross-species contamination |
| `scripts/vision/repair_gallery_labels.py` | moves mislabelled images to the true owner |
| `scripts/vision/scan_image_quality.py` | cheap metrics over all 111k images |
| `scripts/vision/triage_image_quality.py` | shortlist, ranked within resolution strata |
| `scripts/vision/measure_density_gain.py` | leave-one-out density gradient |
| `scripts/vision/compare_indexes.py` | compares builds on one fixed query set |

### Artifacts

- `data/vision/index-v3/` — current index (16,580 vectors, 384-d whitened)
- `data/vision/bench/README-measurements.md` — **the measurement log; read it**
- `data/vision/bench/_au_split_original.json` — fixed query set for comparisons
- `data/vision/quarantine_fallback/` — 10 unvalidated galleries (moved, not deleted)
- `tests/` — 9 files, 77 checks, stdlib only, offline

---

## 6 · Traps for the next session

**Never quote a number without its query set.** Rebuilding the split reshuffles which
images are held out, so two builds' own reported numbers are not comparable. A naive
before/after here reported **97.88%**; the honest figure was +1.1 points. Verify every
query is absent from the gallery being scored.

**It is easy to hit that trap twice.** `compare_indexes.py` initially showed v2 at
95.49% vs v3 at 94.40% on the original 910 queries. That comparison is also
meaningless: v2 was built from a *different* split, so those queries are legitimately
out-of-sample for it and it cannot be compared to v3 on them. Only the
81.8% → 85.9% pair shares a held-out set (checked: v2's only committed split is the
186-species one, so v2's true benchmark figure remains the 82.4% in §3).

**Never trust an image's folder name.** The contamination was invisible in metadata
and only appeared visually. `q`-prefixed filenames mean unvalidated provenance.

**Do not reintroduce `AUTO_CONF = 0.80`.** On the whitened scale precision peaks near
0.68 and *falls* above 0.75.

**Recalibration must write `band_config.json`, not only the audit trail.** That bug
was live until this session: `index-v3` served 0.68/0.43 while its own audit said
0.64/0.30.

**A verifier that deletes true claims is worse than the overclaim.** `claim_verify.py`
measured 62.5% false positives against reviewed-faithful answers; it raises unless
`allow_unsafe=True`, and the funnel does not import it.

**Subagents overstepped twice.** Briefed to return JSON, they also edited docs and
left scratch directories. The doc numbers were checked and are correct, but verify
anything they touched.

**The gallery is local-only and gitignored.** A fresh clone must re-embed
(`cache_embeddings.py`, ~10 img/s on this CPU) before benchmarking.

---

## 7 · Reproduction

```bash
# tests (offline, no model, no network)
.venv-mcpmv46/bin/python tests/run_all.py

# current accuracy
.venv-mcpmv46/bin/python scripts/vision/calibrate_bands.py \
    --index-dir data/vision/index-v3 --out data/vision/index-v3/band_calibration.json

# gallery integrity (expect 0 collisions)
.venv-mcpmv46/bin/python scripts/vision/audit_gallery_integrity.py

# full rebuild from on-disk images
.venv-mcpmv46/bin/python scripts/vision/build_au_benchmark.py --out data/vision
.venv-mcpmv46/bin/python scripts/vision/cache_embeddings.py --backend dinov2-base \
    --split data/vision/au_split.json          # resumable
.venv-mcpmv46/bin/python scripts/vision/fit_pca.py
.venv-mcpmv46/bin/python scripts/vision/build_index_v2.py --out data/vision/index-v3
.venv-mcpmv46/bin/python scripts/vision/calibrate_bands.py --index-dir data/vision/index-v3

# resume densification (validated path; safe to interrupt)
.venv-mcpmv46/bin/python scripts/vision/pull_inaturalist.py --target 300 --au-first
```

---

## 8 · Open items

1. **90% not reached** (85.9%) — routes in §4.
2. **App artifacts stale** — see `docs/HANDOVER-2026-09-19.md` §3.
3. **Publishing.** `augury-vision-index` on HF pending. **18 sidecar licences are
   `requires_verification`**; `backfill_sidecars.py --check-publishable` exits
   non-zero and must gate any publication.
4. **Model card** documents a Capeweed example the live DB does not return (the DB
   has only `General indicators` plus a phosphorus claim; the card shows
   Moisture/pH/Fertility).
5. **51 species** have no indicators in any region.
6. **Direction verifier** — built, measured unsafe, documented. Four defects diagnosed
   in the module docstring; needs a lexicon derived from indicator values rather than
   word frequency.
7. **The third-party 60% result** (20 photos, n=1/species, CI 38.7–78.1%) had four of
   its five worst cases in *contaminated* species. Worth re-running now that the
   gallery is clean — it is the closest thing to a real-world number.
8. **`augury-android/`** is its own git repo inside the workspace (1,865 tracked
   files). This session only untracked its build outputs. Someone should decide
   whether it belongs in this repo.
9. **Density is still unmeasured at scale** — the +35 pt pilot was 4 species, n=20.

---

## 9 · Decisions taken, and why

1. **Audit before spending.** The plan was to download 46k images and rent GPU time.
   One look at an existing image found the contamination. The density run was stopped
   deliberately rather than adding volume to a broken path.
2. **Cascade, not brute force.** A visual review of 111,302 images would be ~111k
   model calls. Cheap metrics on all; visual review on the flagged 4%.
3. **Quarantine, never delete.** The 10 bad galleries were moved to
   `quarantine_fallback/` so the decision stays reversible.
4. **Label, never promote.** Forcing a species to outrank a genus bucket produced
   *Oxalis acetosella* (a European wood-sorrel) for "soursob". Genus answers stay
   genus-level and say so.
5. **Refuse rather than guess.** Unresolvable taxon matches return `None` and fall
   through to a clade-validated search, instead of accepting a plausible-looking
   wrong answer.

---

*Companion documents: `data/vision/bench/README-measurements.md` (measurements),
`docs/model-understanding-and-blindspots.md` (operating picture),
`docs/HANDOVER-2026-09-19.md` (Android app track),
`data/thirdparty/report-augury-thirdparty-test.md` §13 (independent test + correction),
`data/thirdparty/RUNBOOK.md` (model-dependent gates).*

# AUGURY — Data Roadmap

Where the data is, what's broken, and how it grows. Companion to
`openbmb-playbook.md`. Status as of 2026-08-11.

## 1 · Canonical assets (single source of truth: the git repo)

| Asset | Path | Status |
|---|---|---|
| Species DB (2,230 spp, 3 regions) | `data/research/database-merged.json` | ✅ clean (14 mojibake entries — fix §3.1) |
| Vision species list (2,230) | `data/vision/species_list.json` | ✅ `is_au` tags, common names |
| Text formatting data | `data/training/weeds_indicators_merged_{train,val}.jsonl` | ✅ regenerated 2026-08-11, AU-balanced (186/188 AU) |
| Vision splits | `data/vision/{train,val}.jsonl` | ✅ 58,121 / 6,519, relative paths |
| Image gallery | `data/vision/images/` (15GB, 111,320 imgs) | ✅ sidecars per species; local build source — 185/188 AU spp mirrored on HF Hub |
| Legacy text data | `data/training/standalone_*`, `data/v3_function_calling/` | reference only |

## 2 · Closed gaps (done 2026-08-11)

- **H4 AU merge landed**: formatting data regenerated from `database-merged.json`
  with all AU species region-tagged (was: 95% European, zero AU examples).
- **Portable image paths**: builder emits relative paths (was: absolute, broke
  any non-local run).
- **Gallery mirrored to HF** (185/188 AU species; full raw gallery kept locally
  as the index-build source — the runtime artifact is the compact FAISS index,
  not the raw images; see `docs/gallery-phone-discussion.md`).

## 3 · Open items

### 3.1 DB hygiene (small, do anytime)
- 14 entries with mojibake/soft-hyphen garbage in `database-merged.json` —
  identify + clean or archive.
- **35 species exist without indicator data** (22 with no regions, 13 with empty
  indicators) — e.g. **Nassella trichotoma (serrated tussock)**, a major AU weed.
  Fill from AU research packs / mining data; the funnel correctly refuses them
  today ("no indicator data"), which is honest but a coverage gap.
- Common-name coverage: only ~110 species have real common names (H3). Priority:
  the 188 AU species — farmers use common names.
- **Gallery alias merging**: species_list has alias keys (ribwort plantain /
  plantago lanceolata, spear thistle / cirsium vulgare, juncus acutus / spiny
  rush). Merge to canonical keys → lifts retrieval top-1 meaningfully.

### 3.2 Image acquisition (the ID accuracy lever)
- Targets: ≥100 images/species for the ~50 priority AU weeds (weeds with
  government-sourced indicators); ≥50 for the rest of the 188 AU set.
- Tools exist: `scripts/vision/pull_inaturalist.py` (resumable, throttled,
  idempotent), `pull_gbif.py` (gap-fill), `pull_deepweeds.py`.
- License compliance: keep `sources.jsonl` sidecars per species (iNat
  per-photo licenses; aggregate stays non-commercial).
- **Josh's lane**: field photos of AU weeds — the look-alike killers
  (phone-held, varied angles/stages/lighting). Even 50-100 photos of priority
  species have outsized value.

### 3.3 Text data (formatter quality)
- Refusal expansion: current refusal set is herbicide/agronomy-focused; add
  non-plant photos (via the unknown gallery path) and out-of-region cases.
- Multi-species AU pairs: formatter synthesis for "docks + thistles" style
  queries currently EU-dominant — generate AU pairs from the DB.
- Eval harness for the formatter: held-out fact-consistency (model states only
  the given facts) + style + refusal accuracy — sample review of generated
  answers against the DB facts is the qualitative template.

### 3.4 Model/embedding artifacts (after GPU quota)
- Fine-tune DINOv2-base on the AU set (WS1b, `fine_tune_encoder.py`) → target
  top-1 ≥ 75% (was 72.6% off-the-shelf).
- Re-embed full gallery with the fine-tuned encoder → new FAISS index.
- Fine-tune MiniCPM5-1B formatter on the AU-balanced text data (QLoRA, ~1h on
  A10) → publish GGUF.

## 4 · Growth model (no retraining for new species)

1. New species → field photos + iNat pull → `images/<key>/` + sidecar + DB row.
2. Embed new photos, add to FAISS index (minutes, no training).
3. Formatter handles it automatically — it presents given DB facts.
Only a *style/synthesis* change ever retrains the formatter. Only an *ID
accuracy* shortfall retrains the encoder.

## 5 · Community layer
- Sinong team (Nanjing Agricultural University, llm4cca@njau.edu.cn): Chinese
  weed bioindicator data collaboration (Josh in Nanjing).
- Community DB contributions: common names, regional corrections, field
  photos — the "community-driven expansion" path in PROJECT.md.

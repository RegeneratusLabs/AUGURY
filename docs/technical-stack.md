# AUGURY — Technical Stack Write-Up

**Weeds as soil-health indicators, fully on-device.** An open-source pipeline that
turns a photo (or a question) about a weed into a plain-language explanation of
what that plant says about the soil — compaction, pH, nutrients, drainage.
Indicators only, no management advice. No cloud. No API keys. Built from
off-the-shelf Apache/MIT components and one small fine-tune.

---

## The design bet: decompose, don't amalgamate

Open-ended fine-grained species identification is a retrieval problem, not a
generation problem — so we decomposed the pipeline. Each layer does one thing
it's genuinely good at, and **nothing in the critical path requires retraining
as the data grows**:

```
[photo]  → DINOv2-base embedding → FAISS kNN over 111k-photo library → top-k species
[text]   → deterministic species extraction (regex + fuzzy DB match)
                                    │
                                    ▼
                     species_lookup.py → database-merged.json (2,230 spp)
                                    │  (the model NEVER emits facts)
                                    ▼
              MiniCPM5-1B + LoRA ("the voice") → conversational soil story
```

## The three layers

### 1. Perception — retrieval, not classification

- **Encoder:** `facebook/dinov2-base` (86M params, ~350MB) — the fine-grained
  similarity specialist. Embeddings L2-normalised.
- **Index:** FAISS `IndexFlatIP` over the photo gallery.
- **Gallery:** 111,320 images, 2,174 species, pulled from iNaturalist
  (research-grade, per-photo license sidecars), DeepWeeds (CC BY 4.0), GBIF.
- **Numbers — the shipped retrieval index (`index-v3`, 2026-09-19), AU-scoped,
  910 held-out queries / 184 species:**
  - **top-1 81.8% / top-3 89.7%** (`data/vision/bench/cleaned_v3.json`)
  - Superseded: **80.9%** was a bake-off figure on the *contaminated* v2 gallery.
    A naive before/after reported 97.9% until it was caught: rebuilding the split
    reshuffled the held-out set, and 803 query files had become gallery members,
    so queries were matching themselves. The honest v2→v3 delta on a fixed query
    set is **+1.1 pt** (n=93), and the real repair was elsewhere — four
    contaminated species went from unlearnable to working (`holcus lanatus` 0/5 →
    4/5, `raphanus raphanistrum` 0/5 → 4/5, `sinapis arvensis` 0/5 → 5/5).
    See `data/vision/bench/README-measurements.md`.
- **Canonical alias merge:** 21 duplicate species keys collapse at index build
  (ribwort plantain = plantago lanceolata; curled dock = rumex crispus). The text
  DB merges the same groups' indicators rather than picking a side — 12 of the 20
  pairs held *different* data, so a farmer asking "curled dock" and one asking
  *Rumex crispus* used to get different soil stories for the same weed.
- **Confidence bands are calibrated per index and read from the artifact — never
  hard-coded.** `index-v3`: **auto ≥ 0.68** (51.6% coverage, **95.1% precision**),
  **confirm ≥ 0.43** (94.1% coverage), below → honest "not in my library".
  Precision on the whitened scale **peaks near 0.68 and falls above 0.75**, so the
  legacy `0.80/0.60` constants select the worst decile. They must not be
  reintroduced — `tests/test_band_config.py` now enforces this.

**Why retrieval over fine-tuning:** new species = new gallery photos + one DB
row. The encoder never retrains. The index is a public artifact — anyone can
rebuild or extend it.

### 2. Facts — deterministic database

- **`database-merged.json`:** 2,256 species entries (`SpeciesDB` loads **2,319**
  after the mining/research merges; `species_list.json` carries 2,230) × region
  (Australia/Europe/UK) × indicator dicts (Moisture, Soil pH, Fertility,
  Salinity, Structure, …), sourced from Ellenberg (1991), Maughan & Amos, CAWR,
  AU government publications, plus mined nutrient claims.
  **220 species carry an Australian region; 2,264 have at least one real
  vernacular name.** Indicator keys are free-form data, not a schema — nine exist
  today (`Moisture`, `Fertility`, `Soil pH`, `Salinity`, `Structure`, `Ph`,
  `Species`, `General indicators`, `Other indicators`) and consumers must render
  whatever is present rather than hard-coding a list.
- The formatter is *given* the facts; it cannot hallucinate a pH value because
  it never generates one. Guard rail: DB is the source of truth.

### 3. Voice — the one fine-tune

- **Base:** `openbmb/MiniCPM5-1B` (Apache-2.0, chatml, tool-calling capable).
- **Method:** LoRA r=16/α=32, 3 epochs, lr 2e-4 cosine, effective batch 32,
  bf16, LLaMA-Factory, one A10 24GB session (~45 min).
- **Data:** 13,627 train / 1,514 val rows, AU-balanced (186/188 AU species).
  Row shape: `Species / Region / Indicators:` in the user turn → conversational
  soil story in the assistant turn. Generated from the DB, never hand-written.
- **Eval:** val loss 0.0398 (from 3.72 initial) · local smoke: 6/6 fact-keys
  echoed, correct refusal boundary.
- **Deploy:** GGUF Q4_K_M — **660MB**, runs on a phone via llama.cpp.

## The funnel (text + photo share the backend)

- **Species extraction:** deterministic regex segmentation (conjunction/location/
  quantity parsing) + fuzzy DB match. We tried LLM extraction: the fine-tuned
  model is persona-locked (refuses the extractor role) and the base model's
  thinking mode eats the JSON budget — so we shipped the deterministic path.
  Honest, fast, zero-hallucination.
- **Composition:** the trained formatter writes the story from injected DB
  facts; template fallback if the model's unavailable.
- **Latency:** 6-12s per answer on a 16-core CPU laptop (Q4 GGUF, llama.cpp).
- **Multi-species:** "docks and thistles" → both extracted, one synthesized
  answer. **Refusals:** management/herbicide questions return indicators only.

## Guard rails (hard-won)

1. Per-species eval, never loss
2. DB is the source of truth — the model formats facts, never generates them
3. JSON contracts, never XML tool-calls
4. Region-scoped label space + explicit unknown path
5. Per-image licenses for the photo gallery (aggregate is non-commercial —
   iNat cc-by-nc photos)
6. Everything Apache-2.0 / MIT / CC-BY-4.0

## What didn't work (learned in public)

- **Contrastive fine-tune of the encoder (WS1b):** 5 epochs, MultiSimilarity
  loss stayed flat (~0.90), and the projection head made retrieval *worse*
  (8.6% vs 74.6% baseline). Recipe under repair — the off-the-shelf encoder
  already passes gates, so v1 ships with it.
- **Model-based species extraction:** both candidates failed (persona lock /
  thinking mode) → deterministic regex won.

## Artifacts

| What | Where |
|---|---|
| Model (GGUF Q4_K_M 688 MB / F16 / merged fp16 / LoRA) | `RegeneratusLabs/augury-1b` (HF) |
| Species DB | `RegeneratusLabs/augury-species-db` (HF) — **stale at 2026-08-11**; see below |
| Training data (13,627 rows) | `RegeneratusLabs/augury-training-data` (HF) |
| Vision gallery (111k imgs + license sidecars) | **local only** — `data/vision/images/` (build-time source; never read at runtime) |
| Vision retrieval index (**built**: `index-v3`, 13,448 vectors / 173 canonical species / 42 MB) | `RegeneratusLabs/augury-vision-index` (**not yet published**) |
| Android app (shell + manifest contract) | `docs/mobile-app-decision.md`; app source `augury-android/` |
| Code, scripts, docs, playbook | `github.com/RegeneratusLabs/AUGURY` |

> **⚠️ The published species DB is behind the working tree.** HF serves
> `database-merged.json` at revision `85e57fb` (2026-08-11, 1,155,275 bytes) while
> the working copy is 1,125,629 bytes and carries later work — the AU species
> merge, the mojibake repair and the canonical-group indicator merge. Anything
> that pulls facts from HF today gets **pre-fix data**. Republish before pointing
> the app at it; a model rebuild is in progress, so this is expected to move.

## Roadmap

- Full-gallery FAISS index (CPU instance, overnight — zero GPU)
- Photo → species → story end-to-end serving (UI with image upload)
- Field photos from farmers (the look-alike killer)
- Future siblings in the ecosystem: Soil Assessment SLM → Remediation SLM →
  Grazing SLM — each model does one thing, all phone-deployable

*Written 2026-08-13 · AUGURY v0.1 — the text pipeline is live and testable; the
photo path is mid-build.*

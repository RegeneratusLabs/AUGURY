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
- **Numbers (AU-scoped, all 188 AU species, full gallery, val queries):**
  - SigLIP2-400M: 63.1% top-1 / 79.1% top-3
  - DINOv2-base: 72.6% top-1 / 86.4% top-3
  - **DINOv2-base + alias merge: 80.9% top-1 / 88.3% top-3** (both gates passed)
- **Alias merge:** 18 species keys were the same plant under two keys
  (ribwort plantain = plantago lanceolata). Canonical-key resolution at eval
  time lifted top-1 by +8.3 points for free.
- **Confidence bands:** top-1 ≥ 0.80 auto-accept · ≥ 0.60 show top-3 + confirm ·
  below → honest "not in my library" path.

**Why retrieval over fine-tuning:** new species = new gallery photos + one DB
row. The encoder never retrains. The index is a public artifact — anyone can
rebuild or extend it.

### 2. Facts — deterministic database

- **`database-merged.json`:** 2,230 species × region (Australia/Europe/UK) ×
  indicator dicts (Moisture, Soil pH, Fertility, Salinity, Structure, …),
  sourced from Ellenberg (1991), Maughan & Amos, CAWR, AU government
  publications, plus mined nutrient claims.
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
| Model (GGUF Q4_K_M + F16 + merged fp16 + LoRA) | `RegeneratusLabs/augury-1b` (HF) |
| Species DB (2,230 spp) | `RegeneratusLabs/augury-species-db` (HF) |
| Training data (13,627 rows) | `RegeneratusLabs/augury-training-data` (HF) |
| Vision gallery (111k imgs + license sidecars; local build source — 185/188 AU spp mirrored on HF) | `RegeneratusLabs/augury-vision-gallery` (HF) |
| Vision retrieval index (runtime artifact — **to be built**) | `RegeneratusLabs/augury-vision-index` (pending) |
| Code, scripts, docs, playbook | `github.com/RegeneratusLabs/AUGURY` |

## Roadmap

- Full-gallery FAISS index (CPU instance, overnight — zero GPU)
- Photo → species → story end-to-end serving (UI with image upload)
- Field photos from farmers (the look-alike killer)
- Future siblings in the ecosystem: Soil Assessment SLM → Remediation SLM →
  Grazing SLM — each model does one thing, all phone-deployable

*Written 2026-08-13 · AUGURY v0.1 — the text pipeline is live and testable; the
photo path is mid-build.*

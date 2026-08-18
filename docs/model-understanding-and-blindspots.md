# AUGURY — Model Understanding & Blind Spots

**Status:** 2026-08-18 · Companion to `technical-stack.md` (architecture) and
`data-roadmap.md` (data). This doc is the honest operating picture: what the
system actually is, what it can and cannot do, and where its known failure
modes live. Read this before promising anyone accuracy numbers.

---

## 1 · What AUGURY actually is (one paragraph)

AUGURY is **not one model** — it is a three-layer pipeline with a strict
separation of duties:

```
[photo]  → DINOv2-base embedding → FAISS kNN over 111k-photo gallery → top-k species
[text]   → deterministic species extraction (regex + fuzzy DB match)
                                    │
                                    ▼
                     species_lookup.py → database-merged.json (2,230 spp)
                                    │   the model NEVER generates facts
                                    ▼
              MiniCPM5-1B + LoRA ("the voice") → conversational soil story
```

Only the **last layer** is a fine-tuned language model. Everything upstream is
deterministic retrieval + a curated database. This is the core design bet:
*decompose, don't amalgamate*. Open-ended fine-grained species ID is a retrieval
problem (nearest-neighbour over a gallery scales to new species without
retraining); factual claims are a database problem (the model cannot hallucinate
a pH value because it never generates one); and the LLM is reduced to a
*formatter* — a persona that turns given facts into a farmer-friendly story.

---

## 2 · The three layers in detail

### 2.1 Perception — retrieval, not classification

| | |
|---|---|
| Encoder | `facebook/dinov2-base` (86M params, ~350MB), embeddings L2-normalised |
| Index | FAISS `IndexFlatIP` (inner product ≈ cosine on normalised vectors) |
| Gallery | 111,320 photos, 2,231 species keys (iNat research-grade + DeepWeeds + GBIF), per-image license sidecars |
| Scope metric | AU-scoped (188 Australian weeds, alias-merged): **80.9% top-1 / 88.3% top-3** |
| Confidence bands | top-1 ≥ 0.80 auto-accept · ≥ 0.60 top-3 + confirm · below → honest "not in my library" |
| Alias merge | 18 keys collapsed (e.g. ribwort plantain = *Plantago lanceolata*) — worth +8.3 top-1 points |

**Critical status caveat:** the full-gallery FAISS index has **not yet been
built**. The local `data/vision/index/` holds only 100 species / 14,274 vectors
(checkpoint from an interrupted run). The 80.9% figure is from a **bake-off
evaluation** (held-out AU queries against the gallery), not from a live
end-to-end photo→answer test. The photo path is *architecturally designed* but
*not yet field-proven as a product*.

### 2.2 Facts — deterministic database

- `data/research/database-merged.json`: 2,230 species × region (Australia /
  Europe / UK) × indicator dicts (Moisture, Soil pH, Fertility, Salinity,
  Structure, nutrients…).
- Sources: Ellenberg (1991), Maughan & Amos, CAWR (UK), AU government
  publications, plus mined nutrient claims. (This is literature, not
  field-verified soil science.)
- `scripts/species_lookup.py` does fuzzy, region-aware matching. Common-name
  coverage is thin (~110 species have real common names) — scientific names
  dominate the DB.
- Published to HF as `RegeneratusLabs/augury-species-db` (with
  `species_list.json` + `unified_species_database.json`).

### 2.3 Voice — the one fine-tune

| | |
|---|---|
| Base | `openbmb/MiniCPM5-1B` (Apache-2.0, chatml) |
| Method | LoRA r=16 / α=32, 3 epochs, lr 2e-4 cosine, eff. batch 32, bf16, LLaMA-Factory on an A10 24GB |
| Data | 13,627 train / 1,514 val rows, **AU-balanced (186/188 AU species)**; rows generated from the DB, never hand-written |
| Eval | val loss 0.0398 (from 3.72); local smoke: 6/6 fact-keys echoed, correct refusal boundary |
| Deploy | GGUF Q4_K_M = 688MB → llama.cpp (llama_cpp python bindings in the funnel) |
| Input contract | `Species / Region / Indicators:` in the user turn → story in the assistant turn |
| Refusal lane | management / herbicide / remediation / non-plant questions → indicators only |

The formatter is *given* the facts (constructed by the funnel from the DB) and
told "do not add or change any indicator". Temperature 0.3, max_tokens 500.

---

## 3 · The funnel (runtime)

- `scripts/augury_funnel.py` — single entry point. **Species extraction is
  deterministic regex** (segmentation on conjunctions/quantity/location parsing
  + fuzzy DB match). The LLM-extractor path exists in code but is disabled —
  the trained persona refuses the extractor role and the base model's thinking
  mode eats the JSON budget.
- `scripts/augury_server.py` — Flask chat server with a feedback loop
  (`data/feedback.jsonl`).
- Latency: 6-12s per answer on a 16-core CPU laptop (Q4 GGUF).
- Multi-species: "docks and thistles" → both extracted → one synthesised answer.

---

## 4 · Blind spots (severity-ordered, honest)

### 🔴 High — will bite in real use

1. **Photo path is not production-proven.** No full-gallery index exists yet
   (100/2,231 species local checkpoint). The headline 80.9% is a bake-off
   number, not a shipped product number. Anything that promises "point your
   phone at a weed" is currently aspirational until the index is built and
   end-to-end tested on real field photos.
2. **Retrieval confidence ≠ correctness.** The bands only re-rank gallery
   similarity. A *confident* top-1 (score ≥ 0.80) can still be the *wrong*
   species — look-alikes, immature plants, unusual growth stages, phone
   lighting. The system will assert a wrong ID with high confidence and the
   funnel will then faithfully tell the farmer what that *wrong* species
   indicates. There is no second-opinion or uncertainty-aware fallback beyond
   the score bands.
3. **No "don't know" for the known-unknown.** Below 0.60 the system says "not
   in my library" — but between 0.60 and 0.80 it *shows* top-3 and asks the
   user to confirm. That is a UX decision point where an untrained user may
   just accept suggestion #1. The refusal is honest but the interaction needs
   real product testing.

### 🟠 Medium — known data/quality gaps

4. **DB coverage holes.** ~35 species exist without indicator data (22 with no
   regions, 13 with empty indicators) — e.g. **serrated tussock
   (*Nassella trichotoma*), a major AU weed** — the funnel correctly refuses
   them ("no indicator data"), which is honest but a product gap for exactly
   the farmers it targets. 14 DB entries carry mojibake/soft-hyphen garbage.
5. **Common-name thinness.** Only ~110 of 2,230 species have real common
   names. Farmers think and speak in common names ("serrated tussock", "Paterson's
   curse", "capeweed"). The 188 AU species are the priority for this fix and
   are partially covered, but extraction quality for free-text common names is
   a ceiling on the text funnel's usefulness.
6. **Alias merge is partial.** 18 keys merged in the eval; `species_list.json`
   still carries alias keys (ribwort plantain / plantago lanceolata, spear
   thistle / cirsium vulgare, juncus acutus / spiny rush). The eval merge is
   canonicalisation-at-eval-time, not necessarily at runtime in every path.
7. **Multi-species is synthesis, not reasoning.** "Docks and thistles" extracts
   both and concatenates facts — but conflicting indicators (one says wet, one
   says dry), abundance/density signals, and interactions are not modelled.
   A farmer with a *dominant* weed gets the same treatment as a *mix*.

### 🟡 Lower / known-hard

8. **Encoder is off-the-shelf.** Fine-tuning DINOv2-base (WS1b, contrastive)
   made retrieval *worse* (8.6% vs 74.6% baseline) — the recipe is under
   repair and v1 ships the untuned encoder. Fine-grained discrimination is
   capped by the base model's capability.
9. **Format-lock.** The voice is trained on one exact input contract. Deviate
   (no region, odd phrasing, multi-turn chat, follow-up questions) and quality
   drops; it is not a general conversational model.
10. **Literature, not field-verified.** Indicator claims come from published
    Ellenberg/CAWR/AU-gov values. They are *referenced*, not *measured*. A pH
    band can be wrong for a specific paddock even when faithfully formatted.
11. **Region skew.** EU (Ellenberg) rows dominate raw counts; AU species are
    region-tagged and AU-balanced in training, but the underlying indicator
    dataset leans European. Non-AU, non-EU regions (US, NZ, South Africa) are
    effectively uncovered — the DB has Australia/Europe/UK only.
12. **Quantization.** Q4_K_M adds small fidelity loss vs fp16; the F16 GGUF
    exists but the shipped default is Q4.
13. **Phone reality is unbuilt.** The phone UI, image-capture flow, on-device
    index download, and offline behaviour **do not exist yet** — only a CLI and
    a Flask script. "Designed to run on a phone" is a design constraint, not a
    shipped property. The 15GB raw gallery is NOT what a phone downloads (see
    the gallery discussion) — the phone would download the compact FAISS index
    (~40-400MB depending on scope/quantisation), which is also not yet built at
    full scale.

---

## 5 · What it is NOT (anti-claims)

- Not a plant-identification model (retrieval layer does ID).
- Not a fact generator (DB does facts; the model formats them).
- Not an agronomist / no management, herbicide, or remediation advice by design.
- Not multilingual, not multi-turn conversational, not a general assistant.
- Not validated against field soil tests.

---

## 6 · How to think about the numbers

- **80.9% top-1 / 88.3% top-3 (AU, alias-merged)** is a **retrieval** metric on
  held-out AU queries — it measures "did the right species surface in the
  gallery kNN", not "was the farmer's question answered correctly end-to-end".
- **val loss 0.0398** measures the formatter's style/echo on DB-injected rows —
  it says nothing about retrieval accuracy or real-world soil truth.
- Neither number says anything about **field accuracy** (is the indicator
  claim true for this soil?) — that requires agronomic validation no one has
  done yet.

*Companion docs: `technical-stack.md` (design), `data-roadmap.md` (data
gaps/growth), `model-cards/augury-1b.md` (published card).*

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
| Scope metric | AU-scoped **retrieval**: top-1 **81.8%** / top-3 **89.7%** (`index-v3`, 910 held-out queries / 184 species, 2026-09-19) |
| Confidence bands | **calibrated per index, read from the artifact** — `index-v3`: ≥ 0.68 auto (51.6% coverage, **95.1% precision**) · ≥ 0.43 top-3 + confirm · below → honest "not in my library" |
| Canonical merge | 21 duplicate keys collapsed (e.g. ribwort plantain = *Plantago lanceolata*) — worth **+8.3 top-1 points** |

**The earlier 80.9% / 88.3% figure is superseded.** It came from a bake-off on a
**contaminated** gallery (four species had leaked query images into the gallery).
The honest fixed-query-set delta is **+1.1 pt** (n=93); the value of the repair was
that those species became learnable at all and that a **95% precision band became
reachable**. A naive before/after reported 97.9% until a leakage check caught it —
rebuilding the split reshuffled the held-out set and 803 query files had become
gallery members, so queries were matching themselves. Full log:
`data/vision/bench/README-measurements.md`.

**The full-gallery index is now built** (`index-v3`, 13,448 vectors, 173 canonical
AU species, 42 MB) — this supersedes the "100 species / 14,274 vectors checkpoint,
not yet built" caveat this document previously carried. What is still true: the
photo path has **not been field-proven as a product** and no on-device app existed
until now. **90% top-1 was not reached** — the gap is thin galleries plus genuinely
hard look-alike genera (`banksia`/`hakea`/`callistemon`/`lepidosperma`,
`austrostipa`/`austrodanthonia`), and the measured encoder ceiling is 92.3%.

### 2.2 Facts — deterministic database

- `data/research/database-merged.json`: 2,256 species entries (`SpeciesDB` loads
  2,319 after the mining/research merges) × region (Australia /
  Europe / UK) × indicator dicts (Moisture, Soil pH, Fertility, Salinity,
  Structure, nutrients…).
- Sources: Ellenberg (1991), Maughan & Amos, CAWR (UK), AU government
  publications, plus mined nutrient claims. (This is literature, not
  field-verified soil science.)
- `scripts/species_lookup.py` does fuzzy, region-aware matching. **2,264**
  species carry at least one real vernacular name (the old "~110" figure was a
  stale pass-2 count, now corrected below).
- Published to HF as `RegeneratusLabs/augury-species-db` (with
  `species_list.json` + `unified_species_database.json`) — **but that copy is
  stale at 2026-08-11 and predates the AU merge, the mojibake repair and the
  canonical-group indicator merge.**

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
   (the index is now built — see §2.1). The headline retrieval number
   (81.8% top-1) is a benchmark measurement, not a shipped product number.
   Anything that promises "point your phone at a weed" is still aspirational
   until it is end-to-end tested on real field photos.
2. **Retrieval confidence ≠ correctness.** The bands only re-rank gallery
   similarity. A *confident* top-1 (score ≥ 0.68) can still be the *wrong*
   species — look-alikes, immature plants, unusual growth stages, phone
   lighting. The system will assert a wrong ID with high confidence and the
   funnel will then faithfully tell the farmer what that *wrong* species
   indicates. There is no second-opinion or uncertainty-aware fallback beyond
   the score bands. **This is the single most important reason the app must
   always show top-3 and never silently accept a photo ID.**
3. **No "don't know" for the known-unknown.** Below 0.43 the system says "not
   in my library" — but from 0.43 to 0.68 it *shows* top-3 and asks the user to
   confirm. That is a UX decision point where an untrained user may just accept
   suggestion #1. The refusal is honest but the interaction needs real product
   testing.

### 🟠 Medium — known data/quality gaps

4. **DB coverage holes.** **51 species** load with no indicator data in any
   region (`SpeciesDB`), and 17 entries in `database-merged.json` have no
   indicators at all — e.g. **serrated tussock (*Nassella trichotoma*), a major
   AU weed**. The funnel correctly refuses them ("no indicator data"), which is
   honest but a product gap for exactly the farmers it targets. ✅ The 14
   mojibake/soft-hyphen entries were repaired 2026-09-19.
5. **Common-name coverage is better than previously recorded.** **2,264** of
   ~2,319 species carry at least one vernacular name, and **185 of the 188 AU
   species** in `species_list.json` do. The old "~110 species" figure was a
   stale count from the pass-2 era and understated the picker's viability
   considerably. ✅ **The remaining ceiling is *extraction*, not coverage**:
   held-out measurement gives fuzzy matching alone only **56.3%** on curated
   synonyms — which is why the app's tap-a-weed picker is the primary path and
   free-text is secondary.
6. **Alias merge is partial.** 18 keys merged in the eval; `species_list.json`
   still carries alias keys (ribwort plantain / plantago lanceolata, spear
   thistle / cirsium vulgare, juncus acutus / spiny rush). The eval merge is
   canonicalisation-at-eval-time, not necessarily at runtime in every path.
   ✅ **Text path fixed 2026-09-19** — `get_indicators()` now resolves the whole
   canonical group and *merges* indicators rather than choosing a side. The
   vision path resolves canonical labels at index build and `PhotoID.__init__`
   raises if any label escapes the index. **The app must reproduce both.**
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
13. **Phone reality is now being built (in progress).** The Android app is a
    **shell** — it ships no model data and downloads everything from HF at
    runtime, so the phone never sees the 15 GB gallery. On-device footprint is
    ~1.15 GB: a **~88 MB** int8 encoder, the **42 MB** compact retrieval index
    (`index-v3`, no FAISS — plain kNN), and the **688 MB** GGUF. See
    `docs/mobile-app-decision.md`. Until that ships and is field-tested,
    "designed to run on a phone" remains a design constraint rather than a
    shipped property.

---

## 5 · What it is NOT (anti-claims)

- Not a plant-identification model (retrieval layer does ID).
- Not a fact generator (DB does facts; the model formats them).
- Not an agronomist / no management, herbicide, or remediation advice by design.
- Not multilingual, not multi-turn conversational, not a general assistant.
- Not validated against field soil tests.

---

## 6 · How to think about the numbers

- **81.8% top-1 / 89.7% top-3 (AU, canonical-merged, `index-v3`)** is a
  **retrieval** metric on 910 held-out AU queries — it measures "did the right
  species surface in the gallery kNN", not "was the farmer's question answered
  correctly end-to-end". The superseded 80.9% came from a contaminated gallery;
  do not quote it.
- **95.1% auto-band precision** is the share of *correct* IDs among queries
  scoring ≥ 0.68 — it covers only **51.6%** of queries, and it will not transfer
  unchanged to messy field photos, because benchmark queries are drawn from the
  same galleries.
- **val loss 0.0398** measures the formatter's style/echo on DB-injected rows —
  it says nothing about retrieval accuracy or real-world soil truth.
- Neither number says anything about **field accuracy** (is the indicator
  claim true for this soil?) — that requires agronomic validation no one has
  done yet.

*Companion docs: `technical-stack.md` (design), `data-roadmap.md` (data
gaps/growth), `mobile-app-decision.md` (the Android shell + HF manifest
contract), `model-cards/augury-1b.md` (published card).*

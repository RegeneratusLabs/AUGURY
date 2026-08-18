# AUGURY

**Weeds as soil-health indicators.** An open-source pipeline that maps weed species
to the soil conditions they indicate — compaction, waterlogging, nutrient imbalances,
pH, salinity, organic-matter state. Indicators only. No management advice.
No cloud required. Designed to run on a phone.

> "The plant is the mirror of the soil." — Gérard Ducerf

## How it works

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

Three layers, one job each:

1. **Perception — retrieval, not classification.** DINOv2-base embeddings + FAISS
   over a 111,320-photo gallery. New species = new photos + a DB row; the encoder
   never retrains. **AU-scoped: 80.9% top-1 / 88.3% top-3** on 188 Australian weeds
   (alias-merged).
2. **Facts — a deterministic database.** 2,230 species × region (Australia /
   Europe / UK) × indicator dicts, from Ellenberg (1991), Maughan & Amos, CAWR,
   AU government publications. The model formats these facts — it cannot
   hallucinate a pH value because it never generates one.
3. **Voice — one small fine-tune.** MiniCPM5-1B LoRA (r16/α32, 3 epochs, bf16,
   one A10 session) on 13,627 DB-generated rows. **GGUF Q4_K_M = 660MB**, phone-ready
   via llama.cpp. Eval: val loss 0.0398; 6/6 fact-keys echoed in local smoke.

## Status (2026-08-13)

- ✅ **Text funnel live**: species extraction → DB → trained formatter story.
  Multi-species ("docks and thistles"), region-aware, correct refusal boundary
  (indicators only, never management advice). 6-12s/answer on a 16-core laptop.
- 🔄 **Photo path building**: full-gallery FAISS index in progress; confidence
  bands (auto-accept / top-3 confirm / honest unknown).
- ✅ All artifacts published: model, species DB, training data. The vision
  gallery is the local index-build source (185/188 AU species mirrored on HF;
  the runtime artifact is the compact FAISS index, not the raw images).

## Quickstart

```bash
# text funnel (CLI)
.venv-mcpmv46/bin/python scripts/augury_funnel.py \
    --model models/MiniCPM5-1B-AUGURY-Q4_K_M.gguf --region Australia \
    "What does dandelion indicate about my soil?"

# chat server (Flask, feedback loop included)
.venv-mcpmv46/bin/python scripts/augury_server.py
```

## Artifacts

| What | Where |
|---|---|
| Model (GGUF Q4_K_M / F16 / merged fp16 / LoRA adapter) | [RegeneratusLabs/augury-1b](https://huggingface.co/RegeneratusLabs/augury-1b) |
| Species database (2,230 spp) | [RegeneratusLabs/augury-species-db](https://huggingface.co/datasets/RegeneratusLabs/augury-species-db) |
| Training data (13,627 rows) | [RegeneratusLabs/augury-training-data](https://huggingface.co/datasets/RegeneratusLabs/augury-training-data) |
| Vision gallery (111k imgs; build source — 185/188 AU spp mirrored on HF) | [RegeneratusLabs/augury-vision-gallery](https://huggingface.co/datasets/RegeneratusLabs/augury-vision-gallery) |
| Vision retrieval index (the runtime artifact — **to be built**) | `RegeneratusLabs/augury-vision-index` (pending) |

## Hard-won lessons (see `docs/technical-stack.md`)

- **Retrieval beats classification for open-ended fine-grained ID** — a
  nearest-neighbour search over the gallery scales to new species without
  retraining; a fixed classifier cannot.
- **Loss is a liar.** Always evaluate per-species on held-out data; never trust
  the train-loss curve alone.
- The voice model formats given facts; the funnel never lets it do anything else.

## Docs

- [Technical stack](docs/technical-stack.md) · [OpenBMB playbook](docs/openbmb-playbook.md) ·
  [Data roadmap](docs/data-roadmap.md) · [Model card](docs/model-cards/augury-1b.md) ·
  [Model understanding & blind spots](docs/model-understanding-and-blindspots.md)

## License

Apache-2.0 (code, weights) · CC-BY-4.0 (database, training data) · vision gallery
is non-commercial aggregate with per-image license sidecars (iNat cc-by-nc photos).

## Roadmap

AUGURY is the first model in a composable SLM ecosystem for regenerative agriculture:
`AUGURY (weeds → indicators) → Soil Assessment SLM → Remediation SLM → Grazing SLM`.
Each model does one thing. All open source. All phone-deployable.

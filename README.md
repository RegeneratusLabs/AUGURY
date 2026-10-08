# AUGURY

**Weeds as soil-health indicators.** An open-source pipeline that maps weed species
to the soil conditions they indicate — compaction, waterlogging, nutrient imbalances,
pH, salinity, organic-matter state. Indicators only. No management advice.
No cloud required. Designed to run on a phone.

> "The plant is the mirror of the soil." — Gérard Ducerf

## How it works

```
[photo]  → DINOv2-base embedding → kNN over photo gallery → top-k species
[text]   → deterministic species extraction (regex + fuzzy DB match)
                                        │
                                        ▼
                         species_lookup.py → database-merged.json (2,230 spp)
                                        │   the model NEVER emits facts
                                        ▼
                     deterministic template ("the story") → soil reading
                     [optional, separate version] MiniCPM5-1B LoRA → conversational
```

Two layers ship, one job each:

1. **Perception — retrieval, not classification.** DINOv2-base embeddings + kNN
   over a photo gallery. New species = new photos + a DB row; the encoder
   never retrains. **AU-scoped: 81.8% top-1 / 89.7% top-3** on 184 Australian weeds
   (alias-merged); **85.87% top-1 / 92.83% top-3** on 920 unseen images on-device.
2. **Facts — a deterministic database.** 2,230 species × region (Australia /
   Europe / UK) × indicator dicts, from Ellenberg (1991), Maughan & Amos, CAWR,
   AU government publications. The story is rendered by a **deterministic
   template**, so a pH value cannot be hallucinated — nothing generates one.

### The voice is a separate version

A fine-tuned **MiniCPM5-1B LoRA** (GGUF Q4_K_M, 688 MB) writes the same story as
conversational prose. It is **not shipped in the app**: the mobile build is
template-only — ~368 MB instead of ~1.06 GB, no per-answer generation latency,
and no grounding pass, because the template cannot invent a number. The fine-tune
stays published for a **separate conversational version**; see
`docs/mobile-app-decision.md`.

## Status

- ✅ **The app ships template-only**: species picker / photo → DB → deterministic
  story. No story model is downloaded, so the first-launch download is **~368 MB**
  instead of ~1.06 GB, answers are instant, and no answer can invent an indicator.
- ✅ **Photo path measured on-device**: **85.87% top-1 / 92.83% top-3** over 920
  unseen images; top-3 confirmation is mandatory and the confidence bands are read
  from the manifest, never hard-coded.
- 🔄 **Conversational voice — separate version**: the MiniCPM5-1B LoRA is
  published but deliberately **not shipped here**; it is the basis of a later
  conversational build (see `docs/mobile-app-decision.md`).

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
| Voice model — **separate conversational version, not in the app** (GGUF Q4_K_M / F16 / merged fp16 / LoRA) | [RegeneratusLabs/augury-1b](https://huggingface.co/RegeneratusLabs/augury-1b) |
| Species database (2,230 spp) | [RegeneratusLabs/augury-species-db](https://huggingface.co/datasets/RegeneratusLabs/augury-species-db) |
| Training data (13,627 rows) | [RegeneratusLabs/augury-training-data](https://huggingface.co/datasets/RegeneratusLabs/augury-training-data) |
| On-device bundle + manifest (facts, index, encoder) | `data/app/` — template-only manifest, published to `RegeneratusLabs/augury-app` |
| Vision gallery (111k imgs + license sidecars) | **local only** — `data/vision/images/` (build-time source; never read at runtime) |
| Vision retrieval index | `RegeneratusLabs/augury-vision-index` |

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

# AUGURY

**Weeds as soil-health indicators.** An open-source small language model that maps weed
species to the soil conditions they indicate — compaction, waterlogging, nutrient
imbalances, pH, salinity, organic-matter state. Indicators only. No management advice.
No cloud required. Designed to run on a phone.

> "The plant is the mirror of the soil." — Gérard Ducerf

## What it does

Given a plant name (or a photo), AUGURY reports what that plant indicates about the soil:

```
Q: What does dandelion indicate about soil conditions?
A: Dandelion indicates: high fertility, nitrogen-rich soils, compaction,
   poorly draining conditions (Europe / Ellenberg 1991).
```

The model **never answers from memory**. It proposes species; a deterministic database
resolves; the database supplies the facts — the model cannot hallucinate a pH value.

```
[photo] ──┐
          ├─→ vision / text model → {"species": [...]} JSON → species_lookup.py
[question]┘        (fuzzy, region-aware)              │
                                                    ▼
                                database-merged.json (2,230 spp — source of truth)
                                                    │
                                                    ▼
                              formatter → conversational soil-indicator answer
```

## Architecture

| Layer | Model | Status |
|---|---|---|
| Text formatter / species extraction | MiniCPM5-1B (V3 tool-calling) | Trained (LoRA), GGUF on device |
| Vision (photo → species JSON) | MiniCPM-V 4.6 (1.3B), LoRA, vision tower frozen | Dataset built (58k images) — training on cloud GPU |
| Lookup engine | `scripts/species_lookup.py` — deterministic, region-aware, fuzzy | Working |
| Source of truth | `data/research/database-merged.json` — 2,230 species, 188 AU | Working |

**Decisions that are locked** (see `docs/augury-vision.md`):
LLaMA-Factory only (Unsloth has no MiniCPM support) · JSON output, never XML tool-calls ·
DB is source of truth · region-constrained label space + explicit "unknown" path ·
freeze vision tower · template `minicpm_v_4_6` consistent train→serve · merge LoRA before
GGUF · per-species eval, not top-1 · no cloud API at runtime.

## Repository layout

```
LICENSE              Apache-2.0 (code)
LICENSE-DATA         CC-BY-4.0 (database + training data) + image license notes
data/
  research/          database-merged.json (source of truth), research briefs
  training/          text training data (Ellenberg, Maughan & Amos, CAWR, AU)
  v3_function_calling/  tool-calling examples (1,522 rows)
  vision/            vision dataset: jsonl splits, species list, dataset_info.json
                     (images NOT in git — published separately, non-commercial)
  mining/            web-sourced indicator claims
scripts/
  species_lookup.py  fuzzy, region-aware lookup engine
  augury_server.py   Flask serving entry point (+ feedback loop)
  plant_id.py        iNaturalist / PlantNet API clients (label bootstrapping only)
  vision/            dataset builders, iNat/DeepWeeds/GBIF pullers, eval, GGUF export
docs/                project status, handovers, vision plan, audits
```

## Quickstart

```bash
# lookup only (no ML runtime needed)
python3 scripts/species_lookup.py "prickly acacia"

# serve the API
python3 scripts/augury_server.py
```

### Rebuild the vision dataset

```bash
# 58,121 train / 6,519 val rows, per-species caps, seed 42, relative image paths
python3 scripts/vision/build_llamafactory_dataset.py
```

### Train (vision, cloud GPU — 6GB local cards OOM)

Package `data/vision/` + `scripts/vision/train_v4_6_lora.yaml` for the cloud host, then:

```bash
sed -i "s|^model_name_or_path:.*|model_name_or_path: <base-model-path>|" train_v4_6_lora.yaml
sed -i "s|^dataset_dir:.*|dataset_dir: <host-path>/data/vision|"            train_v4_6_lora.yaml
export DOWNSAMPLE_MODE=4x
llamafactory-cli train train_v4_6_lora.yaml
```

Steps for ModelScope/Colab are in `docs/HANDOVER_VISION.md`.

### Eval + deploy

```bash
# eval (gates: ≥85% per-species top-1, ≥95% JSON adherence, <2s latency)
.venv-mcpmv46/bin/python scripts/vision/eval_vision.py \
  --model data/vision/output/augury-v4_6-merged --val data/vision/val.jsonl

# merge LoRA → GGUF Q4_K_M + mmproj for llama.cpp
bash scripts/vision/export_gguf.sh
```

## Data sources

Ellenberg Indicator Values (1991, Europe) · Maughan & Amos bioindicators guides (UK) ·
CAWR field guide (UK) · AU Pasture Weeds SA / VIC Soil Health Brown Book (Australia) ·
Ducerf encyclopedias (research reference — excluded from training due to OCR quality) ·
iNaturalist / DeepWeeds / GBIF images (vision).

See `LICENSE-DATA` for per-source terms. The vision image aggregate is **non-commercial**
(per-image CC-BY-NC constraints from iNaturalist).

## Known limitations

- European Ellenberg data dominates the text dataset — AU coverage is growing but thin.
- Indicator claims are literature-based, **not verified on-farm**.
- The vision label space is the trained species list — out-of-list plants route to the
  "unknown" path.

## Roadmap

AUGURY is the first model in a composable SLM ecosystem for regenerative agriculture:
`AUGURY (weeds → indicators) → Soil Assessment SLM → Remediation SLM → Grazing SLM`.
Each model does one thing. All open source. All phone-deployable.

## Contact

- Org: Regeneratus Labs · contact@regeneratus.app
- Data collaboration: Sinong team, Nanjing Agricultural University (llm4cca@njau.edu.cn)

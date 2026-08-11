# AUGURY — Project Summary

**What:** An open-source small language model that maps weed species to soil health indicators. Given a plant name, it outputs what soil conditions that plant indicates — compaction, waterlogging, nutrient imbalances, pH, salinity. Indicators only. No management advice. Open source. Deployable on a laptop or affordable cloud VM.

**Why:** Ducerf's encyclopedia (800+ species of plant bioindicators, 3 French volumes) is locked in books. CAWR field guides, AU pasture weed manuals, and permaculture literature contain decades of knowledge scattered across PDFs. AUGURY compiles this into a farmer-accessible tool with data sovereignty — no cloud required, no data leaving the device.

**Why:** Ducerf's encyclopedia (800+ species of plant bioindicators, 3 French volumes) is locked in books. CAWR field guides, AU pasture weed manuals, and permaculture literature contain decades of knowledge scattered across PDFs. AUGURY compiles this into a farmer-accessible tool with data sovereignty — no cloud, no subscriptions, no data leaving the device.

## Status (July 2026): Architecture locked — V3 tool-calling on Qwen3.5-4B

Three generations of architecture:
- **Pass 1 (done):** Model memorised weed→indicator mappings. Deployed as `augury.Q4_K_M.gguf`. Problem: hallucination risk.
- **Pass 2 (superseded):** Model formats data from deterministic lookup → key-value responses. Never trained.
- **V3 (current target):** Model calls `lookup_species()` as a tool, reads deterministic data from the database, then synthesises conversational responses. 100% indicator accuracy — the model cannot hallucinate a pH value because it reads facts from the tool response.

**Two research phases completed** (19,735 lines of discovery):
- Phase 1 (global): 144 species verified with Ellenberg values, 12 new indicator dimensions, 16 nutrients tracked, 4 paradigm challenges identified
- Phase 2 (AU-only): 61 new Australian species with government-sourced data. 104 total AU species now covered.

**What's built:**
- Species database: 2,133 active species (107 obscure European endemics archived)
- Australian species: ~104 with government/extension-sourced indicator data (NSW DPI, QLD DAF, Agriculture Vic, SA Landscape Board)
- Nutrient enrichment: Claims for 16+ nutrients across 29+ species (to be expanded with research data)
- Training data: 13,627 train + 1,514 val (ShareGPT format; regenerated 2026-08-11 from database-merged.json with AU balance — 186/188 AU species covered)
- V3 tool-calling training data: 1,369 train + 153 val (1,522 total) in MiniCPM5 XML format across 4 layers (tool use, direct answer, multi-species, refusal)
- Server integration: Species lookup engine (`species_lookup.py`) with fuzzy matching and region-aware retrieval
- Plant ID pipeline: iNaturalist and PlantNet API clients (`plant_id.py`) for photo-to-species

## Vision Dataset (2026-08-05)

Photo-to-species front-end for the funnel. See `HANDOVER_VISION.md` + `data/vision/README.md` for the full picture.

- **Species list**: `data/vision/species_list.json` — 2,230 species (188 AU) from `database-merged.json`
- **Images**: iNaturalist (primary, research-grade, resumable background pull — in progress),
  DeepWeeds (5 in-DB AU species ~1,000 imgs each + 12,321 refusal-layer imgs), GBIF (gap-filler);
  Pl@ntNet-300K coverage-only (verdict: `data/vision/plantnet_verdict.md`)
- **Dataset**: `data/vision/train.jsonl` / `val.jsonl` (LLaMA-Factory sharegpt, DB-generated answers,
  stratified 90/10, refusal rows) + `dataset_info.json`
- **Training suite** (run by Josh): `scripts/vision/train_local.sh` / `train_colab.ipynb` →
  MiniCPM-V 4.6 LoRA (bf16, QLoRA fallback) → `eval_vision.py` → `export_gguf.sh`
- **Guards**: DB is source of truth; JSON never XML; per-species eval; no cloud at runtime

## Data Sources

### Pass 2 (current dataset — `data/training/`)

| Source | Region | Examples | Quality |
|---|---|---|---|
| Ellenberg Indicator Values | Europe | 27,159 | High — CSV conversion, 2,707 species |
| Maughan & Amos (2022) | UK | 545 | High — manually extracted |
| CAWR Bioindicators Field Guide | UK | 376 | Medium — OCR artifacts remain, low impact |
| Maughan & Amos (2024) | UK | 127 | High |
| AU Pasture Weeds (SA) | Australia | 88 | High — government publication |
| VIC Soil Health Brown Book | Australia | 48 | High — extension manual |
| Refusal examples | — | 106 | Synthetic, 7 categories |
| **Total** | | **13,627 train + 1,514 val** (regenerated 2026-08-11 with AU balance) | |

### Removed from pass 2 (deliberately)

| Source | Why removed |
|---|---|
| Ducerf Vol 1-3 (OCR) | Garbled OCR text, Franglish translations — too noisy |
| Permaculturedesign.fr extract | Same Franglish issues |

If clean translations of Ducerf become available, they can be re-added.

## Known Limitations (pass 2 dataset)

1. **Ellenberg dominates 95.6%** — the model will be a European Ellenberg parrot. UK (3.6%) and AU (0.5%) are token contributions. AU-specific knowledge will be weak.
2. **No common names in assistant responses** — user questions include common names, but the model never learns to echo "Common names: daisy" in its output. 0 of 13,492 training examples include a "Common names:" field.
3. **Only 243 of 2,707 Ellenberg species have common names mapped.** Obscure species output scientific names only.
4. **Australian data is thin** (136 examples). Region-tagged but limited depth.
5. **Key-value format is not conversational** — by design for machine chaining, but pass 1 feedback suggests users find it confusing.

## Training Data

- `data/training/weeds_indicators_merged_train.jsonl` — 13,627 examples (USE THIS; regenerated 2026-08-11 with AU balance)
- `data/training/weeds_indicators_merged_val.jsonl` — 1,514 examples (USE THIS)
- `data/training/standalone_train.jsonl` — 612 examples (Path B standalone)
- `data/training/standalone_val.jsonl` — 69 examples (Path B standalone)
- `data/training/ellenberg_indicators.jsonl` — Intermediate (original format)
- `data/training/ellenberg_indicators_v2.jsonl` — Intermediate (v2 format)
- `data/training/maughan_amos_2022.jsonl` — Intermediate
- `data/training/maughan_amos_2024.jsonl` — Intermediate
- `data/training/refusal_examples.jsonl` — Intermediate
- Format: ShareGPT chat (system + user + assistant messages)
- 8 question templates per species
- All user messages prefixed with `[Region: Europe/UK/Australia]`
- Responses in key-value contract format (no "AUGURY v1" header):

```
Moisture: damp ground. Constantly moist or poorly draining soils
Soil pH: moderately acidic. pH 4.5–6.0
Fertility: moderately infertile. Below-average nutrient levels
Source: Ellenberg Indicator Values (Europe)
```

## Files

```
/home/jthomson/AUGURY/
├── PROJECT.md                                      ← This file
├── HANDOVER.md                                     ← Detailed handover with Colab training steps
├── augury.Q4_K_M.gguf                              ← Pass 1 deployable GGUF (379MB)
├── Weeds V1/                                       ← Pass 1 LoRA adapter (reference)
├── augury_merged_fp16/                             ← Pass 1 merged fp16 (reference)
├── unified_species_database.json                   ← 208KB species lookup
├── feedback.jsonl                                  ← Pass 1 user feedback (4 ratings)
├── data/
│   ├── sources/                                    ← Raw downloads (Ellenberg CSV, Maughan PDFs)
│   └── training/                                   ← Built datasets (see above)
├── scripts/
│   ├── build_ellenberg_dataset.py                  ← Ellenberg CSV → JSONL
│   ├── build_maughan_amos_dataset.py               ← Maughan/Amos → JSONL
│   ├── build_v2_improvements.py                    ← Strip headers, add common names, refusals
│   ├── maughan_amos_data.py                        ← Manually extracted species data
│   ├── merge_datasets.py                           ← Dedup + contract + region tags + split
│   ├── train_augury.py                             ← Colab training script (pass 1 reference)
│   ├── evaluate.py                                 ← Model evaluation (word-overlap scoring)
│   ├── convert_to_gguf.py                          ← LoRA merge + GGUF quantize
│   └── augury_server.py                            ← Flask chat server + feedback collection
└── llama.cpp/                                      ← Cloned for GGUF conversion tools
```

## Model Target

- **Base**: MiniCPM5-1B (OpenBMB)
- **Training**: QLoRA via Unsloth, rank 16, 3 epochs, lr 2e-4
- **Platform**: Local RTX 3060 6GB (or similar consumer GPU)
- **Deployment**: GGUF Q4_K_M (~656 MB) — runs on laptops and modern phones via llama.cpp
- **Inference**: llama-cpp-python with XML tool-call interceptor, 2048 ctx
- **Architecture**: V3 tool-calling — model emits `<tool_call>` XML for DB lookups
- **Scope**: Indicators ONLY — no management recommendations
- **Format**: MiniCPM5 native XML tool calls (`<tool_call>{"name": "...", "arguments": {...}}</tool_call>`)

## Current Priorities

1. ✅ **Database merged** — Phase 1 + Phase 2 research integrated. 2,316 species, 160 AU, 73 with nutrients.
2. ✅ **Training data regenerated** — V3 tool-calling data (1,369 train / 153 val) in MiniCPM5 XML format. Note: still European-only per DATA_AUDIT.md H4 — AU tool-call examples pending regeneration from database-merged.json.
3. ✅ **Obscure European species archived** — 107 removed from active training budget.
4. ✅ **Contradictions resolved** — Purslane phosphorus and Parthenium null-effect findings documented.
5. ✅ **Feedback loop fixed** — User question now captured alongside ratings.
6. 🔴 **Train V3** — Run `scripts/train_minicpm5.py --train` on RTX 3060 6GB. QLoRA, 3 epochs, ~2-3 hours.
7. 🔴 **Evaluate** — Test tool-call format adherence, refusal accuracy, multi-species synthesis.

## Known Blind Spots

These are accepted limitations. Community-driven expansion is the long-term strategy.

| Blind Spot | Status | Future Path |
|---|---|---|
| **US/North America coverage** | Zero — no species region-tagged for US. Cosmopolitan weeds use EU values only. | Community DB + future research phase targeting USDA/NRCS/extension |
| **New Zealand, Africa, Asia, South America** | Same — European values applied globally | Community contributions |
| **Field validation** | Untested — every claim from published sources but none verified on-farm | Post-launch: open source community testing |
| **Common names** | Only 110 of 2,316 species have real common names. Model outputs scientific names for 95% of species | Community DB — users can submit common names |
| **1B tool-calling reliability** | Unproven — MiniCPM5-1B is the target but may be too weak for reliable XML tool-call format | Fallback: Qwen3.5-4B (GGUF on disk, ready to train) |
| **Multi-species synthesis at 1B** | May produce weak answers for "docks + thistles + dandelions" type queries | Evaluate after training. Upgrade to 4B if insufficient. |
8. **Beta testing** — Deploy to 5-10 testers with instrumented feedback
9. **V3.1** — Expand AU coverage, add new dimensions (Mineral Balance, Soil Type, Salinity Type)

## Future

This is the first model in a composable SLM ecosystem for regenerative agriculture:

```
AUGURY (weeds → indicators) → Soil Assessment SLM → Remediation SLM → Grazing SLM
```

Each model does one thing. All open source. All phone-deployable.

## Contact

**Sinong team** (Nanjing Agricultural University): potential data collaboration
- Email: llm4cca@njau.edu.cn
- Josh in Nanjing next month

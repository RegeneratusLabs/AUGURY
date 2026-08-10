# AUGURY v3 — Training Plan

## Architecture

Tool-calling reasoning engine. Model calls `lookup_species()` → database returns indicator data → model synthesizes holistically.

## Training Data

1,542 examples across 4 layers in `data/v3_function_calling/` — **EUROPEAN-ONLY. Needs regeneration with merged database.**

**Research integration complete:** 2,228 species (160 AU) merged into `augury-research-pack/database-merged.json`. Training data must be regenerated from this file to include AU species.

**Data audit complete:** See `DATA_AUDIT.md` for findings. 3 critical bugs fixed (feedback loop, empty query, Pigweed common name). Database healthy.

| Layer | Current Count | Target After Regeneration | Content |
|---|---|---|
| A — Tool use | 300 | Learn to call lookup_species() when asked about a species |
| B — Direct answer | 400 | Memorized answers for top ~100 common weeds |
| C — Multi-species synthesis | 422 | 2+ species → multiple lookups → holistic synthesis |
| D — Refusal | 420 | Herbicide, non-plant, and edge-case refusal |

## Base Model

MiniCPM5-1B (OpenBMB, July 2026). 1B-class SOTA for tool use. Q4_K_M GGUF: ~656 MB.
Trainable on consumer GPUs (RTX 3060 6GB). Sovereignty-first — no cloud GPU required.

## Training

HF Jobs on A10G-large, OR local RTX 3060 6GB via Unsloth QLoRA:
With Trackio monitoring. Local training via `scripts/train_minicpm5.py`.
```python
hf_jobs("uv", {"script": "...", "flavor": "a10g-large", "timeout": "4h"})
```

## Inference

```bash
python scripts/inference_loop.py "What do docks and thistles indicate?"
```

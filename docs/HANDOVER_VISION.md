# AUGURY — Vision Integration Handover (2026-08-08)

**Read this first, then `augury-vision.md` (the approved 6-phase plan).**
**Status: dataset COMPLETE; training decided to move to Google Colab (local 6GB card exhausted
every memory lever). Next session: run the Colab notebook, then eval + GGUF export, then the
`plant_id.py` funnel rework.**

---

## Where we are (verified on disk)

### ✅ Dataset — COMPLETE (`data/vision/`)
- **Species list**: `data/vision/species_list.json` — 2,230 species (188 AU) from
  `database-merged.json` (deliberate superset; `database-active.json` drops 75 AU species).
- **Images**: **111,320 on disk** + 12,321 DeepWeeds refusal-layer images.
  - iNaturalist (primary): all 2,230 species processed — 2,153 done (≥10 imgs), 32 partial,
    45 no-images. Research-grade, non-captive, license sidecars (`sources.jsonl` per species).
  - DeepWeeds (CC BY 4.0): 5 in-DB species (~1,000 imgs each) + Chinee apple / Snake weed /
    Siam weed / Negative → `data/vision/images_unknown/` (refusal layer).
  - GBIF gap-fill: ran; only 4 species gained images (the rest of the gaps are obscure endemics
    with no imagery on any source).
  - Pl@ntNet-300K: **coverage-only** (155/2,230 overlap; 31.9GB pull not justified) —
    `data/vision/plantnet_verdict.md`.
- **Final splits**: `train.jsonl` **58,121** / `val.jsonl` **6,519** rows, 2,174 species with
  images, 120 refusal rows. LLaMA-Factory sharegpt format, assistant answers auto-generated
  from the DB (never hand-written), `dataset_info.json` registered
  (`augury_vision_train`/`augury_vision_val`, `dataset_dir: data/vision`).
- **Docs**: `data/vision/README.md` (dataset card), `data/vision/coverage_report.md` (final),
  `data/vision/dataset_stats.md`.

### ✅ Environment (`.venv-mcpmv46`, python 3.11.15)
- torch 2.8.0+cu128 · torchvision 0.23.0 · **torchaudio 2.8.0+cu128** (added 08-08; LLaMA-Factory
  import requires it) · transformers 5.7.0 · peft 0.18.1 · trl 0.24.0 · accelerate 1.13.0 ·
  deepspeed 0.18.3 · llamafactory 0.9.6.dev0 (editable from `third_party/LlamaFactory`) ·
  flash-attn 2.8.3 (built OK) · **bitsandbytes 0.50.0** (added 08-08 for QLoRA) · gdown 6.1.0.
- Models on disk: `models/MiniCPM-V-4.6/` (safetensors), `models/MiniCPM-V-4_6-Q4_K_M.gguf`,
  `models/mmproj-model-f16.gguf`, MiniCPM5-1B, Qwen3.5-4B (text fallback).

### ✅ GPU gate — PASSED (08-08)
- `nvidia-smi` shows **RTX 3060 Mobile 6GB**, driver 580.126.18, CUDA 13.0. Modules load under
  Secure Boot (MOK question is moot — no enrollment needed; a reboot + `modprobe` cycle fixed the
  missing `/dev/nvidia*` nodes). GPU is 5.67 GiB usable — **too small for this model's training**,
  see below.

---

## Training — the local 6GB saga (do NOT retry local; use Colab)

Sequence of failures on the 6GB card, each fixed then still marginal:
1. **bf16 LoRA** → CUDA OOM at step 1 (peak ~6.4GB). 
2. **QLoRA** (`--qlora`, NF4) → LLaMA-Factory bug: mm-projector hook assumed tensor but
   MiniCPM-V 4.6's merger returns a **list** → **patched**
   `third_party/LlamaFactory/src/llamafactory/model/model_utils/visual.py`
   (`_mm_projector_forward_post_hook` now handles list/tuple). **Note: patch is lost if
   LLaMA-Factory is re-cloned.**
3. QLoRA then OOM'd at ~1% (2.46GB single allocation = fp32 logits of a long image sequence) →
   **`models/MiniCPM-V-4.6/preprocessor_config.json`: `max_slice_nums` 9 → 2** (reversible; also
   affects HF-format inference) and **`train_v4_6_lora.yaml`: `cutoff_len` 4096 → 2048**
   (sequences are ~350–400 tokens after the slice cap).
4. User decision: **move training to Google Colab** — T4 16GB fits bf16 LoRA comfortably.

**`scripts/vision/train_colab.ipynb` was fully rewritten for this** (8 cells, validated JSON):
GPU check → env install → model download + yaml auto-patch to absolute Colab paths + dataset
sanity check → train (bf16, ~3–4h estimate on T4) → merge LoRA. Dataset upload is the one chore:
15GB (`data/vision/images`), via Drive mount or Files panel; a `--cap 15` variant (~7GB) is the
fallback if upload is painful.

## Scripts inventory (`scripts/vision/`)
- `build_species_list.py` · `pull_inaturalist.py` (resumable, throttled) · `pull_deepweeds.py` ·
  `pull_gbif.py` (gap-fill; widened to partial species) · `pull_plantnet.py` (verdict) ·
  `coverage_probe.py` · `build_llamafactory_dataset.py` (regenerable; fixed tuple bug + title-case) ·
  `train_v4_6_lora.yaml` (+ `--qlora` variant via `train_local.sh`) · `train_local.sh` ·
  `train_colab.ipynb` · `eval_vision.py` (per-species top-1, confusion matrix, JSON adherence,
  latency) · `export_gguf.sh` (merge → F16 GGUF + mmproj → Q4_K_M).

## Next steps (in order)

1. **Train on Colab** (user action): open `scripts/vision/train_colab.ipynb`, upload
   `data/vision/` + the yaml, run cells. ~3–4h on free T4. If interrupted, checkpoints resume.
2. **Fetch the merged model back** → `data/vision/output/augury-v4_6-merged/`.
3. **Eval** (gates: **≥85% top-1** on label list, **≥95% JSON adherence**, **<2s**):
   `.venv-mcpmv46/bin/python scripts/vision/eval_vision.py --model data/vision/output/augury-v4_6-merged --val data/vision/val.jsonl`
4. **Export**: `bash scripts/vision/export_gguf.sh` → `data/vision/output/gguf/MiniCPM-V-4.6-AUGURY-Q4_K_M.gguf` + `mmproj-AUGURY-F16.gguf`.
5. **Phase 5 — funnel rework** (not yet started): `plant_id.py` → on-device MiniCPM-V 4.6 GGUF →
   `{"species": [...]}` JSON → `scripts/species_lookup.py` → `database-merged.json` →
   conversational answer; low-confidence → top-3 + "confirm with an expert".
6. **Phase 6 — beta**: 5–10 testers, feedback loop already fixed in the text pipeline.

## Decisions (locked — do not re-litigate)
- Path A (DB + formatter); vision feeds `species_lookup.py`; DB is source of truth.
- JSON output, never XML tool-calls.
- Canonical species list = database-merged.json (2,230), not active (2,133).
- Pl@ntNet coverage-only; iNat primary + DeepWeeds + GBIF carry the images.
- Training runs on **Colab (bf16 LoRA)**, not the 6GB laptop (QLoRA exists as a documented fallback only).
- Local changes that persist but are env-specific: LLaMA-Factory visual.py hook patch,
  preprocessor max_slice_nums=2, cutoff_len=2048 (all noted above).

## Standing rules (non-negotiable)
1. LLaMA-Factory, NOT Unsloth (no MiniCPM support) · 2. transformers ≥ 5.7.0 · 3. No packing ·
4. `DOWNSAMPLE_MODE=4x` (note: may not take effect — processor config showed 16x) ·
5. JSON output, never XML · 6. DB is the source of truth · 7. Region-constrained + unknown path ·
8. Freeze vision tower · 9. `minicpm_v_4_6` template train→serve consistent · 10. Merge LoRA
before GGUF · 11. max_slice_nums low, cutoff_len ≥ 2048 (lowered for 6GB; restore 4096 on Colab
if desired) · 12. Per-species eval, not top-1 · 13. No cloud API at runtime.

## Process rules (learned)
- Sign off sub-steps with evidence; never re-validate validated work.
- Background jobs need a stated duration + checkpoint; the iNat pull is resumable via
  `pull_inaturalist.py` (idempotent) with state in `data/vision/inat_state.json`.
- Start every session by reading this + `augury-vision.md`, then re-verify.

## Environment
- Victus (HP Victus 16-d0xxx, Fedora), RTX 3060 Mobile 6GB (GPU works — nvidia-smi OK),
  ~14G disk free (92% used — free space before big downloads), `.venv-mcpmv46`.
- Dataset: `data/vision/` · Plan: `augury-vision.md` (root) · Scripts: `scripts/vision/`.

## Open risks / watch-outs
- T4 training time is an **estimate** (no public 4.6 benchmark) — smoke-test with `--cap 8` +
  1 epoch first if you want certainty.
- 15GB dataset upload is the main friction; `--cap 15` halves it.
- `eval_vision.py` uses the transformers path on the merged fp16 model (needs the venv + GPU or CPU;
  on CPU it will be slow — run eval on the Colab GPU or Victus after export).
- LLaMA-Factory re-clone would lose the visual.py patch (QLoRA path only).
- If Colab runs bf16 with 9 slices (default preprocessor there), worst-case sequences are longer —
  T4 16GB handles it; cutoff 2048 may truncate a few — acceptable.

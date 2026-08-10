# AUGURY Vision — script suite

Turn the image dataset into a finished MiniCPM-V 4.6 model. Two paths: **local**
(Victus, `.venv-mcpmv46`) and **cloud** (Colab, `train_colab.ipynb`).

Guard rails that this suite enforces (see `augury-vision.md` for all 13):
LLaMA-Factory (not Unsloth) · transformers >= 5.7.0 · no packing ·
`DOWNSAMPLE_MODE=4x` · template `minicpm_v_4_6` · freeze vision tower ·
merge LoRA before GGUF · per-species eval.

## 0. Dataset build (already executed — results in `data/vision/`)

```
scripts/vision/build_species_list.py     -> data/vision/species_list.json (2,230 spp)
scripts/vision/pull_inaturalist.py       -> data/vision/images/<species>/*.jpg + sources.jsonl
scripts/vision/pull_deepweeds.py         -> DeepWeeds 8 classes (5 train + 3 unknown/negative)
scripts/vision/pull_gbif.py              -> gap-filler for species below the iNat floor
scripts/vision/build_llamafactory_dataset.py -> train.jsonl / val.jsonl / dataset_info.json
```

## 1. Train

**Local (Victus, 6GB):**
```bash
bash scripts/vision/train_local.sh            # bf16 LoRA (try first)
bash scripts/vision/train_local.sh --qlora    # QLoRA NF4 if bf16 OOMs
```
GPU prereq: `nvidia-smi` must show the RTX 3060 (Secure Boot: `sudo akmods --force`
+ `sudo mokutil --import /etc/pki/akmods/certs/public_key.der` + reboot with MOK).

**Cloud (Colab T4/A10G):** open `scripts/vision/train_colab.ipynb`, run cells in
order. Upload `data/vision/` + `scripts/vision/train_v4_6_lora.yaml` first.

Config knobs (`train_v4_6_lora.yaml`): `lora_rank/alpha`, `num_train_epochs`,
`learning_rate`, `gradient_accumulation_steps` (effective batch = 1 × accum).

## 2. Eval

```bash
.venv-mcpmv46/bin/python scripts/vision/eval_vision.py \
    --model data/vision/output/augury-v4_6-merged \
    --val data/vision/val.jsonl --out data/vision/eval_report.md
```
Reports per-species top-1, macro/micro accuracy, confusion matrix, JSON
adherence, latency. Success gates: >= 85% top-1 on the label list, >= 95% JSON
adherence, < 2s/image on the target hardware.

## 3. Export GGUF (deploy on llama.cpp / Ollama / phone)

```bash
bash scripts/vision/export_gguf.sh
# -> data/vision/output/gguf/MiniCPM-V-4.6-AUGURY-Q4_K_M.gguf + mmproj-AUGURY-F16.gguf
```
Serve: `llama-server -m ...Q4_K_M.gguf --mmproj mmproj-AUGURY-F16.gguf`.

## 4. Wire into the AUGURY funnel (Phase 5)

`plant_id.py` rework: photo -> MiniCPM-V 4.6 GGUF -> `{"species": [...]}` JSON ->
`scripts/species_lookup.py` (fuzzy, region-aware) -> `database-merged.json` ->
conversational answer. Low confidence / `[]` -> top-3 suggestions + "confirm with
an expert" — never a silent wrong answer.

## Notes

- License audit: every image has a `sources.jsonl` sidecar (source, license);
  the dataset card in `data/vision/README.md` breaks down CC licenses (non-NC
  preferred; NC included only to meet image targets).
- iNaturalist API is throttled (~1 req/s) by design in `pull_inaturalist.py`; the
  pull is resumable — rerun the same command to continue after an interruption.

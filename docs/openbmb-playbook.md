# AUGURY — OpenBMB Model Playbook

Permanent knowledge base for fine-tuning and serving OpenBMB MiniCPM models for
AUGURY. Written 2026-08-11 after the MiniCPM-V 4.6 vision run (8% species ID)
and the pivot to retrieval + text formatter. **Read before any training run.**

## 1 · Model catalog (verified 2026-08-11, all Apache-2.0)

| Model | Params | Role in AUGURY | Q4 GGUF | Notes |
|---|---|---|---|---|
| **MiniCPM5-1B** | 1.1B | **Text formatter** (the v1 language model) | 657MB | Long-context, tool-calling capable; trains on 6GB VRAM |
| MiniCPM-V 4.6 | ~1.3B | ~~Vision ID~~ **archived** | ~1.7GB | SigLIP2-400M + Qwen3.5-0.8B; phone-first; free API exists |
| MiniCPM-V 4.5 | 8.7B | Retrain option only (never for v1) | ~5GB | Bigger sibling; needs ≥24GB VRAM to train |
| MiniCPM-o 4.5 | 9.4B | Not for v1 | — | Omni-modal flagship |

**Verdict from the vision run:** open-ended species ID of 2,174 classes is beyond
any 1.3B VLM (8% species / 29% genus vs 85% gate). Do not retry ID with a VLM at
this scale. The retrieval funnel (see §4) replaces it.

## 2 · Data formats (LLaMA-Factory)

**Text formatter (ShareGPT / chatml):** each row `{"messages": [system, user,
assistant]}`. The AUGURY formatting contract: user turn carries the *facts*
(`Species: X / Region: Y / Indicators: - Moisture: ...`), assistant turn is the
conversational story. **The model never generates facts — only presents given
ones.** See `data/training/weeds_indicators_merged_train.jsonl`.

**Vision (ShareGPT + images):** `{"messages": [...], "images": ["rel/path.jpg"]}`,
registered via `dataset_info.json` with `dataset_dir`. Image paths in the JSONL
must be **relative** to `dataset_dir` (the builder was patched 2026-08-08 to emit
`images/<key>/<file>.jpg` — absolute paths break any non-local run).

## 3 · Training (LLaMA-Factory — Unsloth does NOT support MiniCPM)

Working config pattern (`scripts/vision/train_v4_6_lora.yaml`):

```yaml
finetuning_type: lora      # freeze_vision_tower: true for VLMs
template: minicpm_v_4_6    # MUST match serving template (mismatch = garbage)
cutoff_len: 2048           # covers image tokens at low max_slice_nums
per_device_train_batch_size: 1
gradient_accumulation_steps: 16
learning_rate: 2.0e-4      # lora_rank 16 / alpha 32
num_train_epochs: 3
bf16: true                 # QLoRA (quantization_bit: 4) only for <8GB VRAM
```

Environment (verified working):
- transformers **>= 5.7.0** (5.3.0 ships with the repo and BREAKS the processor)
- `pip install -U mistral_common` if "cannot import name 'ReasoningEffort'"
- Launch: `export DOWNSAMPLE_MODE=4x && export DISABLE_VERSION_CHECK=1 && unset USE_V1`

**Processor gotcha (the eval bug):** `downsample_mode` / `max_slice_nums` are
silently DROPPED unless passed via `processor_kwargs={...}` to
`apply_chat_template` in transformers 5.7. Passing them as direct kwargs changes
nothing (the first eval run measured the model under wrong settings — results
were identical anyway, but don't repeat the confusion).

**Resume:** save_steps 50, checkpoints on persistent storage, re-run the same
train command (auto-resumes from the highest checkpoint).

## 4 · Retrieval funnel (the v1 ID path — no VLM training)

```
photo → encoder (DINOv2-base, 86M) → 768-dim embedding
      → FAISS IndexFlatIP kNN over the 111k-photo gallery → top-k species
      → species_lookup.py → database-merged.json → formatter (§1 MiniCPM5-1B)
```

- **bake_off.py** — multi-encoder eval: per-species top-1/top-3, confusion
  matrix, markdown report, fine-tuned-checkpoint support
- **fine_tune_encoder.py** — MultiSimilarity contrastive fine-tune
  (pytorch-metric-learning; MPerClass sampler; bf16; A10-ready)
- Results (2026-08-11, AU-only, full gallery): DINOv2-base 72.6% top-1 /
  86.4% top-3; SigLIP2-400M 63.1% / 79.1%. **DINOv2-base wins and is 4.6x
  smaller.**
- Gallery aliasing (ribwort plantain = plantago lanceolata) inflates errors —
  merge alias keys before trusting top-1.
- **The gallery grows without retraining** — new species = new photos + DB row.

## 5 · Eval methodology (non-negotiable)

1. **Per-species eval, never loss.** Train loss measures the easy part (the
   100-word soil text), not the hard part (the species name). "Loss is a liar."
2. Compare against held-out ground truth; report top-1 AND top-3 AND confusion.
3. JSON/format adherence gate (≥95%) where the contract matters.
4. Latency gate (<2s) for on-device serving.

## 6 · ModelScope DSW workflow (cloud GPU)

- **NAS persists; instances die.** Keep everything under `/mnt/workspace`.
- Fresh-instance drill (3 commands):
  ```bash
  cd /mnt/workspace/LLaMA-Factory && pip install -e .
  pip install "transformers==5.7.0"
  pip install -U mistral_common
  ```
- Train: `nohup llamafactory-cli train ... > train.log 2>&1 &`
- **Uploads from AU to CN crawl (~2Mbps).** Push data to the NAS from the cloud
  instance (datacenter speed) or use the hub as the transfer station.
- `modelscope upload <ns>/<repo> <local_path>` — positional repo_id, needs
  `--token`.

## 7 · Deployment

- Formatter: MiniCPM5-1B Q4_K_M GGUF (657MB) via llama.cpp — laptop + modern
  phone.
- Encoder + index: DINOv2-base (~350MB fp16) + FAISS (Android/iOS builds
  exist); total device footprint ~1.5GB.
- No cloud API at runtime. DB is the source of truth. Unknown/low-confidence →
  top-3 + "confirm with an expert".

## 8 · Sources

- MiniCPM-V 4.6 card: https://huggingface.co/openbmb/MiniCPM-V-4.6
- CookBook (fine-tune/deploy recipes): https://github.com/OpenSQZ/MiniCPM-V-CookBook
- LLaMA-Factory: https://github.com/hiyouga/LlamaFactory
- DINOv2: https://huggingface.co/facebook/dinov2-base
- pytorch-metric-learning: https://github.com/KevinMusgrave/pytorch-metric-learning

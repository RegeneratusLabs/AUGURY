# AUGURY — Vision Integration Implementation Plan

**Date:** 2026-08-04 · **Status:** Plan (nothing implemented) · **Owner:** Josh builds (Reasonix), spec by Hermes
**Where this runs:** Victus (GPU host, has HANDOVER.md + V3 artifacts). The ASUS box holds a stale Jul 25 snapshot — do NOT build on this box's copy.

---

## 0 · TL;DR

Finish **Path A** (deterministic DB + formatter — the foundation, ~90% built), then bolt a **vision front-end** onto it: a LoRA-fine-tuned **MiniCPM-V 4.6** that turns photos into species JSON, feeding the *same* `species_lookup.py` → DB funnel as the text formatter. DB stays the source of truth. **JSON, never XML tool-calls** (V3's lesson). Everything on-device, all-MiniCPM-family.

```
[text question] ──┐
                  ├─→ formatter / vision model (JSON species) → species_lookup.py (fuzzy, region-aware)
[photo] ──────────┘                                                    │
                                                                       ▼
                                                        database-merged.json (2,230 spp) — deterministic
                                                                       │
                                                                       ▼
                                                 MiniCPM-V 4.6 conversational formatting → answer
```

---

## 1 · Architecture decisions (settled — do not re-litigate)

| Decision | Choice | Why |
|---|---|---|
| Text pipeline | **Path A** (DB retrieval + formatter) | Vision model will make ID errors; DB must be the source of truth. Path B (memory) caps vision at 151 spp + resurrects Pass-1 hallucination risk |
| Vision contract | **JSON** `{"species": [...], "confidence": [...]}` | V3 proved XML tool-calls unreliable on 1B-class models. JSON is what species_lookup consumes |
| Vision model | **MiniCPM-V 4.6** (1.3B) — not 4.6-Thinking for v1 | Phone-class, fits Pixel 6 (~1.7GB Q4), LoRA-trainable on Victus 8GB |
| Trainer | **LLaMA-Factory** | Unsloth does NOT support MiniCPM (verified). LLaMA-Factory has official 4.6 support + cookbook guide |
| Fine-tune mode | **LoRA on LLM projections, vision tower frozen** | Smallest VRAM, stable; unfreeze later if needed |
| Deployment | llama.cpp GGUF (Q4_K_M) → Ollama/llama.cpp → Pixel 6 via edge app or Termux | All offline, data sovereignty |

---

## 2 · Guard rails (REQUIRED — feed these to Reasonix verbatim)

1. **Unsloth does NOT support MiniCPM** — verified against their model catalog. Use **LLaMA-Factory** or OpenBMB official `finetune/` scripts. Do not attempt unsloth.
2. **transformers >= 5.7.0 is required** for MiniCPM-V 4.6 (official support landed there).
3. **Do NOT use packing mode** in LLaMA-Factory — transformers has a known issue with packed training on the Qwen3.5 series.
4. **Set `DOWNSAMPLE_MODE=4x`** for fine-detail images (plant close-ups, microscope frames). 16x is default and loses leaf/flower detail.
5. **JSON output, never XML tool-calls.** V3 failed on XML format adherence; the vision contract is JSON.
6. **DB is the source of truth.** The model proposes species; `species_lookup.py` resolves; the DB answers. Never let the model emit indicators from memory.
7. **Region-constrained species list.** The label space defines accuracy. QLD rangeland vs SEQ pasture are different problems. Ship an explicit `unknown`/`low confidence` path.
8. **Freeze the vision tower initially** (`--tune_vision false` / `freeze_vision_tower: true`). LoRA the LLM attention projections (q/k/v/o) only.
9. **Chat template must be `minicpm_v_4_6`** and consistent train→serve. Template mismatch = garbage.
10. **Merge LoRA into the base model before GGUF conversion.** GGUF can't carry the adapter alone.
11. **Training images: keep `max_slice_nums` low (1–3) and max_length ≥ 4096** to cover image tokens. Slice=9 at 1344² ≈ 640 image tokens/sample.
12. **Evaluate per-species confusion, not top-1.** Same-genus look-alikes dominate errors. Never claim ID outside the trained list.
13. **No cloud API at runtime.** GPT-4o/PlantNet API are label-bootstrapping tools only. On-device inference only (sovereignty).

---

## 3 · Phases & tasks

### Phase 0 — Reconcile docs vs disk (0.5 day)
- [ ] Refresh PROJECT.md with verified counts: merged train/val **13,492/1,499** (not 28,449/3,131); V3 **1,369/153**; standalone **612/69**
- [ ] Delete 0-byte `tmp_minicpm5_*.json` scratch files
- [ ] **Decide merged-file currency**: is `weeds_indicators_merged_train.jsonl` current, or must it be regenerated from `database-merged.json` + mining outputs (EU-dominance gap — the merged file appears not regenerated with AU research)? If regenerating, rerun the merge scripts and diff row counts.
- [ ] Confirm base model paths on disk: MiniCPM5-1B (688MB) + Qwen3.5-4B fallback; download `openbmb/MiniCPM-V-4.6` + `openbmb/MiniCPM-V-4.6-gguf` if not present.

### Phase 1 — Finish Path A text pipeline (1–2 days)
- [ ] Make `augury_server.py` (or _v2) the single serving entry point: text → formatter model (MiniCPM5-1B) extracts species → `species_lookup.py` → DB → response
- [ ] Formatter reliability: constrain to **JSON extraction** (`{"species": [...]}`), with retry + fallback to raw-string fuzzy match
- [ ] Wire the fixed feedback loop (question capture + empty-query validation — already fixed, verify in server)
- [ ] End-to-end test harness: 30 hand-written text queries × 5 regions; assert DB rows returned, format contract, refusal paths
- [ ] Ship text-only v1 to 2–3 testers while vision builds (validates the funnel before the camera lands)

### Phase 2 — Vision dataset (2–4 days)
- [ ] **Define region-constrained species list(s)** from `database-merged.json` (start: QLD rangeland 9 DeepWeeds species + 30–60 top AU species from the DB with image availability)
- [ ] Assemble images:
  - **DeepWeeds** (weed-ai.sydney.edu.au, 17,509 imgs, 9 AU species) — the AU core
  - **Pl@ntNet-300K** slice (306k imgs / 1,081 spp; Zenodo DOI 10.5281/zenodo.5645731 or HF mirror `mikehemberger/plantnet300K`) — filter to species in the region list
  - **iNatAg** slice (4.7M imgs / 2,959 spp, geo-aware; arXiv 2503.20068) — AU coverage + growth stages
  - **Own field photos: 200–500**, phone-held, varied lighting/angles/stages (the look-alike killer)
- [ ] **Auto-generate assistant turns from the DB** — the moat: `"This is {species}. In AU cropping it indicates {indicators}. Key features: {...}"` from `database-merged.json` per species (never hand-write answers; keep DB as label source)
- [ ] Convert to LLaMA-Factory format: `{"messages": [user (with image), assistant], "images": [path], "source_file": ..., "channel": ...}`, template `minicpm_v_4_6`
- [ ] Include refusal/uncertain rows: unknown plant, low-confidence, out-of-region
- [ ] Train/val split per species (stratified); target 300–500 images minimum, 1,000–3,000 ideal

### Phase 3 — Fine-tune MiniCPM-V 4.6 (1–2 days incl. setup + ~1h training)
- [ ] Env (per cookbook, verified): python 3.11, torch 2.8.0, torchvision 0.23.0, **transformers==5.7.0**, accelerate 1.13.0, deepspeed 0.18.3, peft 0.18.1, trl 0.24.0, flash-attn 2.8.3, LLaMA-Factory (git clone + `pip install -e .`)
- [ ] `train.yaml` (LoRA SFT): `finetuning_type: lora`, `template: minicpm_v_4_6`, `freeze_vision_tower: true`, `DOWNSAMPLE_MODE=4x`, `cutoff_len: 4096`, `learning_rate: 2e-4`, `num_train_epochs: 3`, `per_device_train_batch_size: 1` + grad accum to effective 16–32, `lora_rank: 16`, `lora_alpha: 32`, target q/k/v/o + gate/up/down, `bf16: true`, no packing, flash_attn fa2
- [ ] Train on Victus 8GB (~30–60 min per 1k images × 3 epochs); QLoRA (NF4 base) if VRAM tight; Colab T4 free tier for 8B-scale runs
- [ ] Eval during training: holdout set, per-species accuracy + confusion matrix, JSON-format adherence rate
- [ ] Export: merge LoRA → fp16 → convert GGUF → quantize Q4_K_M (+ mmproj f16) per cookbook quantization recipe

### Phase 4 — Integrate vision into the funnel (1 day)
- [ ] `plant_id.py` rework: replace/augment iNaturalist/PlantNet API path with on-device MiniCPM-V 4.6 GGUF (llama.cpp, mmproj), JSON species output
- [ ] Photo → JSON species → `species_lookup.py` → DB → conversational summary (same funnel as text formatter — reuse the formatting step verbatim)
- [ ] Camera input: phone photo / gallery / farm tablet; wire Pixel 6 edge app (OpenBMB `MiniCPM-V-Apps` or Termux llama.cpp) as the thin client to the ASUS mini-PC server or fully on-device
- [ ] Uncertainty path: low-confidence species → "confirm with expert" + top-3 suggestions, never silent wrong answer

### Phase 5 — Evaluate + beta (1–2 days)
- [ ] Test harness: 100 AU weed photos (labeled) → ID accuracy, per-species confusion, JSON validity, latency on Victus / ASUS / Pixel 6
- [ ] Instrumented beta: 5–10 testers (farmers/agronomists), feedback loop already fixed; capture ratings + misidentified photos
- [ ] Success gates: ≥85% top-1 on region species list (MVP), ≥95% JSON adherence, <2s response on Victus, works offline

### Optional side-track — Path B validation (0.5 day, parallel)
- [ ] Train standalone (612/69) on MiniCPM5-1B for 30–45 min as a text-only sanity check of the family + quick feedback to testers. NOT the vision integration target.

---

## 4 · Reasonix agent brief (copy-paste)

> **Task:** Implement the AUGURY vision integration per `~/.hermes/plans/augury-vision.md`. Work in the AUGURY project workspace on Victus (the one with HANDOVER.md — NOT the stale copy on the ASUS box).
>
> **Load these installed skills first:** `peft-fine-tuning`, `llm-inference`, `gguf-quantization`. Do NOT use the `unsloth` skill — Unsloth has no MiniCPM support.
>
> **Read these references before writing any training code:**
> - MiniCPM-V CookBook docs site: https://opensqz.github.io/MiniCPM-V-CookBook/
> - LLaMA-Factory fine-tune guide: https://github.com/OpenSQZ/MiniCPM-V-CookBook/blob/main/finetune/llamafactory/finetune_llamafactory.md
> - **MiniCPM-V 4.6 LLaMA-Factory tutorial (the authoritative recipe):** https://github.com/OpenSQZ/MiniCPM-V-CookBook/blob/main/finetune/llamafactory/llamafactory_minicpmv46.md
> - Official OpenBMB finetune scripts (data format + LoRA): https://github.com/OpenBMB/MiniCPM-V/tree/main/finetune + readme.md
> - GGUF quantization: https://github.com/OpenSQZ/MiniCPM-V-CookBook/blob/main/quantization/gguf/minicpm-v4_6_gguf_quantize.md
> - llama.cpp deploy: https://github.com/OpenSQZ/MiniCPM-V-CookBook/blob/main/deployment/llama.cpp/minicpm-v4_6_llamacpp.md
> - Model + GGUF repos: https://huggingface.co/openbmb/MiniCPM-V-4.6 · https://huggingface.co/openbmb/MiniCPM-V-4.6-gguf
> - Edge apps (Pixel 6): https://github.com/OpenBMB/MiniCPM-V-Apps
>
> **Guard rails (non-negotiable):** ① Unsloth does NOT support MiniCPM — use LLaMA-Factory. ② transformers >= 5.7.0 required. ③ No packing mode. ④ `DOWNSAMPLE_MODE=4x` for fine detail. ⑤ JSON structured output, never XML tool-calls. ⑥ DB is source of truth — model proposes, species_lookup resolves, DB answers. ⑦ Region-constrained species list + unknown path. ⑧ Freeze vision tower (LoRA on LLM projections only). ⑨ Template `minicpm_v_4_6` train→serve consistent. ⑩ Merge LoRA before GGUF. ⑪ max_slice_nums low, cutoff_len ≥ 4096. ⑫ Per-species eval, not top-1. ⑬ No cloud API at runtime.
>
> **Report back:** per-phase completion, exact commands run, eval numbers (per-species accuracy, confusion matrix, JSON adherence, latency), and the final GGUF paths. Do not claim a phase done without the eval output to prove it.

---

## 5 · Risks & open questions

- **Workspace location:** this plan assumes the real project (HANDOVER.md, V3 LoRA, scripts) on Victus. Confirm path before Phase 0.
- **MiniCPM-V 4.6 weights:** public (Apache-2.0), GGUF repo public. Only MiniCPM-V-2.6 base is gated — not our path.
- **8B-scale (4.5) vision fine-tune** needs cloud (Colab T4 16GB, ~2–4h per 1k images) — defer until 4.6 proves the loop.
- **Community QLoRA numbers for 4.6 on 8GB** are estimates (official docs show full-FT on 8×GPU); verify VRAM on first run before committing time.
- **Vision data quality > quantity:** 300–500 clean, multi-stage AU images beat 10k noisy ones. The DB-generated answers keep label quality uniform.
- **Time budget:** ~1.5–2 weeks part-time to the instrumented beta, if Phase 0/1 don't rabbit-hole.

## 6 · Definition of done

Text pipeline + vision front-end share one funnel; photo → species JSON → DB indicators → conversational answer works end-to-end offline on Victus and Pixel 6; ≥85% top-1 on the region species list; ≥95% JSON adherence; eval + beta report written; no cloud dependency at runtime.

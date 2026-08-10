# AUGURY — Session Checkpoint (31 July 2026, late)

## Where We Parked

The project is parked at a **clean decision point**. After a long session of
architecture pivots, we have two validated paths and all the assets to pursue
either. No further decisions were locked tonight — the user chose to rest and
re-evaluate with fresh eyes.

## The Core Decision (unresolved — for next session)

**Which architecture to ship?**

| Path | Pattern | Evidence it's valid | Effort to finish |
|---|---|---|---|
| A. RAG / DB retrieval | Model calls deterministic DB (2,316 species) | AgroLLM, KrishokBondhu, AgriRegion papers | Needs serving stack |
| B. Standalone fine-tune | Model answers from memory (151 species) | AgriGPT (342K Q&A, no runtime DB) | ~30-45 min training, done |

The literature research tonight confirmed **both** are legitimate, published
approaches in agriculture-AI. The project failed to ship because we switched
between them mid-stream, not because either is wrong.

## What's Ready (both paths have working assets)

### Database (for Path A)
- `data/research/database-merged.json` — 2,230 species, 160+ AU
- `scripts/species_lookup.py` — deterministic lookup, works
- `scripts/augury_server_v2.py` — formatter architecture (server does lookup,
  model formats). Refusal logic proven.
- Known bug fixed: 396 malformed region entries normalized; `get_indicators()`
  no longer crashes on missing `source`

### Standalone dataset (for Path B)
- `data/training/standalone_train.jsonl` — **612 train / 69 val examples**
- `data/training/standalone_val.jsonl`
- 151 well-documented species (62 AU), clean Q&A pairs, refusal baked in
- `scripts/generate_standalone_data.py` — regenerates from DB
- `scripts/train_standalone.py` — ready to run (~30-45 min on RTX 3060 6GB)
- Base model: MiniCPM5-1B (GGUF on disk, 656 MB). dill/Python 3.14 fix
  already in the training script.

## Technical State (known-good)
- MiniCPM5-1B GGUF downloaded: `models/MiniCPM5-1B-Q4_K_M.gguf`
- Training worked end-to-end (test run completed; full run produced a LoRA)
- dill/Python 3.14 incompatibility: FIXED in both train scripts
- Python.h/Triton issue: fixed by `sudo dnf install python3-devel`
- Convert to GGUF: `scripts/convert_to_gguf.py` (auto-detects adapter_final/)
- Test harness: `scripts/test_trained_model.py` (accepts bare JSON + wrapped)

## Open Threads (not urgent)
- US species research was run but output never saved to disk — needs re-run
  to integrate. Not needed for either Path A or B v1.
- Layer C (multi-species) training data has 0% AU region — acceptable for v1
- The tool-calling V3 model (minicpm5_v3_lora) exists but format adherence
  was unreliable — that's why we pivoted to the two clean paths above

## Recommendation for Next Session
Pick ONE path and finish it. Don't revisit the architecture debate.
- If "release a free model for community use" is the goal → **Path B** (fastest)
- If "accuracy + extensibility" is the goal → **Path A** (already 90% built)

The database + research is the durable asset either way. That's the real
value of this project.

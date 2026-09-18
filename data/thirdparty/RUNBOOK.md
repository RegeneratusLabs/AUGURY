# AUGURY third-party test — reproduction runbook

Generated 2026-09-18 10:39 UTC. Host: 16 cores, CPU only, `/home/jthomson/AUGURY`.

## 0. Preconditions
- Python venv `.venv-mcpmv46`: torch (CPU), transformers, faiss-cpu, llama-cpp-python, pillow,
  huggingface_hub. `facebook/dinov2-base` must be in the HF cache (or downloadable) for the
  vision phase.
- Hash-pinned artifacts (verified in report §2):
  - `models/MiniCPM5-1B-AUGURY-Q4_K_M.gguf`
    sha256 `febcf5e6dfcc8b79326ca9a5f4dcf9c2535464ef086a48edbf4dd925254d7026`
    (live: https://huggingface.co/RegeneratusLabs/augury-1b revision `342d62ab82a985fbc26e6d01c6d2953815f3a434`)
  - `data/research/database-merged.json`
    sha256 `c6d2505b4b80cc830f5a5d4a09f53898417fe377098663ad7c0b45c74936818c`
    (live: https://huggingface.co/datasets/RegeneratusLabs/augury-species-db)
  - `data/vision/index/` (DINOv2-base FAISS index) and `data/vision/images/` (gallery, read only
    to build the held-out SHA-256 rejection set)

## 1. Acquire fresh third-party photos (network, ~5 min)
```
.venv-mcpmv46/bin/python scripts/thirdparty_test/fetch_test_photos.py \
    --out data/thirdparty --seed 20260818
```
Resumable: re-run with `--resume`; refetch a subset with `--only key1,key2`.
Any image whose SHA-256 is already in the gallery is rejected automatically.
Sources tried per species, in order: GBIF occurrence media (AU) → Wikimedia Commons → iNaturalist.

## 2. Provenance + self-test gates
```
.venv-mcpmv46/bin/python scripts/thirdparty_test/run_field_test.py --phase provenance
.venv-mcpmv46/bin/python scripts/thirdparty_test/run_field_test.py --phase selftest
```
`provenance` exits non-zero if the local model/DB hashes differ from the pinned live values.

## 3. Vision pass (DINOv2 + FAISS, ~1 min)
```
.venv-mcpmv46/bin/python scripts/thirdparty_test/run_field_test.py --phase vision
```

## 4. Text pass (MiniCPM5-1B-AUGURY Q4_K_M, ~5 min)
```
.venv-mcpmv46/bin/python scripts/thirdparty_test/run_field_test.py --phase text \
    --strict --repeat 3 --repeat-subset 5
```
Phases are deliberately separate processes: the encoder and the GGUF are never resident together
(this host has ~5 GB free RAM; peaks were ~2.6 GB and ~2.3 GB respectively).

## 5. Report
```
.venv-mcpmv46/bin/python scripts/thirdparty_test/build_report.py --out data/thirdparty
```

## Notes
- Every figure in the report is recomputed from the raw JSON/JSONL at report time.
- The shipped `alias_map.json` is never modified; duplicate-key merging is applied in memory only
  (`EVAL_ALIAS` in `run_field_test.py`).
- iNaturalist/GBIF `cc-by-nc` media is used for local, non-commercial evaluation only, with
  per-image attribution recorded in `corpus.json`.
- Re-running the text phase at temperature 0.3 produces different wording; the invented-pH
  behaviour is stable across runs (see gate E).

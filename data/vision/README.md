# AUGURY Vision Dataset — card

Status: **COMPLETE** — full 2,230-species acquisition done (2,174 with images; 56 obscure endemics
have no imagery on any source and are excluded from the label set), 111,320 images on disk,
final splits built (train 58,121 / val 6,519 rows). Regeneration is only needed if you re-run
any pull script.

## Contents

| Path | Description |
|---|---|
| `species_list.json` | Canonical species list (2,230 spp, 188 AU) from `database-merged.json` |
| `images/<species>/*.jpg` | Acquired images, one dir per species (key = species_list key) |
| `images/<species>/sources.jsonl` | Sidecar: per-image `{photo_id, file, license, source}` |
| `images_unknown/` | Refusal layer: `chinee_apple/`, `snake_weed/`, `siam_weed/`, `negative/` (DeepWeeds, CC BY 4.0) |
| `train.jsonl` / `val.jsonl` | LLaMA-Factory sharegpt rows: `messages` (user `<image>` + prompt, DB-generated assistant answer), `images` (abs paths), `source_file`, `channel` |
| `dataset_info.json` | Registration (`augury_vision_train` / `augury_vision_val`) — consumed by `train_v4_6_lora.yaml` (`dataset_dir: data/vision`) |
| `dataset_stats.md` | Counts, split, license histogram |
| `coverage_report.md` | Per-source coverage (preliminary — regenerate post-pull) |
| `plantnet_species_map.json`, `species2plantnet.json`, `plantnet_verdict.md` | Pl@ntNet-300K coverage mapping + no-pull verdict |

## Sources & licenses

- **iNaturalist** (primary, ~all species): research-grade, non-captive observations;
  per-image license in `sources.jsonl` (cc0/cc-by/cc-by-sa preferred; cc-by-nc* included only to reach targets).
- **DeepWeeds** (Olsen et al. 2019, CC BY 4.0): 5 in-DB species (~1,000 imgs each) + Chinee apple /
  Snake weed / Siam weed / Negative → refusal layer (12,321 imgs).
- **GBIF media** (gap-filler): for species below the iNat floor; license recorded per image.
- **Pl@ntNet-300K**: coverage mapping only (155/2,230 overlap; 31.9GB pull not justified) — see `plantnet_verdict.md`.

## Regenerate (after the iNat pull completes)

```bash
.venv-mcpmv46/bin/python scripts/vision/pull_gbif.py              # gap-fill iNat misses
.venv-mcpmv46/bin/python scripts/vision/coverage_probe.py         # final coverage report
.venv-mcpmv46/bin/python scripts/vision/build_llamafactory_dataset.py --cap 30 --cap-deepweeds 60
```

## Train / eval / export

See `scripts/vision/README.md`:
```bash
bash scripts/vision/train_local.sh            # or --qlora; or scripts/vision/train_colab.ipynb
.venv-mcpmv46/bin/python scripts/vision/eval_vision.py --model data/vision/output/augury-v4_6-merged
bash scripts/vision/export_gguf.sh
```

## Notes

- Assistant answers are auto-generated from `database-merged.json` (DB = source of truth, guard rail 6);
  never hand-written. Answer format: `This is {Common} ({Sci}). In {region} conditions it indicates: ...`
  Unknown/refusal rows answer with a refusal (no indicators).
- Per-species caps: 30 imgs default, 60 for DeepWeeds species — keeps the class balance sane across 2,000+ species.
- The iNat pull is resumable: rerun `pull_inaturalist.py --target 50 --min 10 --au-first` to continue.

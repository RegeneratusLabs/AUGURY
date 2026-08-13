# AUGURY Vision — script suite

Turn the image gallery into the retrieval index + serve the photo path.
Environment: `.venv-mcpmv46` (Victus) or any host with torch + transformers.

Guard rails this suite enforces: DB is the source of truth · per-species eval ·
JSON contracts, never XML tool-calls · per-image license sidecars · no cloud API
at runtime.

## 0. Dataset build (already executed — results in `data/vision/`)

```
scripts/vision/build_species_list.py     -> data/vision/species_list.json (2,230 spp)
scripts/vision/pull_inaturalist.py       -> data/vision/images/<species>/*.jpg + sources.jsonl
scripts/vision/pull_deepweeds.py         -> DeepWeeds 8 classes (5 train + 3 unknown/negative)
scripts/vision/pull_gbif.py              -> gap-filler for species below the iNat floor
scripts/vision/build_llamafactory_dataset.py -> train.jsonl / val.jsonl / dataset_info.json
```

## 1. Build the retrieval index

```bash
# AU-scoped (v1): DINOv2-base embeddings + FAISS, resumable
.venv-mcpmv46/bin/python scripts/vision/embed_gallery.py \
    --images-dir data/vision/images --au-only --device cuda
# full gallery (all 2,174 species): omit --au-only
```

## 2. Identify a photo

```bash
.venv-mcpmv46/bin/python scripts/vision/photo_id.py photo.jpg
# -> top-k species + confidence bands (auto-accept / top-3 confirm / unknown)
```

## 3. Encoder evaluation (bake-off)

```bash
# per-species top-1/top-3 + confusion matrix across candidate encoders
.venv-mcpmv46/bin/python scripts/vision/bake_off.py --au-only --encoders dinov2-base
```

## 4. Wire into the AUGURY funnel

`photo_id.py` output -> `scripts/species_lookup.py` (fuzzy, region-aware) ->
`database-merged.json` -> trained formatter -> conversational answer.
Low confidence / `[]` -> top-3 suggestions + "confirm with an expert" — never a
silent wrong answer.

## Notes

- License audit: every image has a `sources.jsonl` sidecar (source, license);
  the dataset card in `data/vision/README.md` breaks down CC licenses (non-NC
  preferred; NC included only to meet image targets).
- iNaturalist API is throttled (~1 req/s) by design in `pull_inaturalist.py`; the
  pull is resumable — rerun the same command to continue after an interruption.

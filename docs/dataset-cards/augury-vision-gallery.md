# AUGURY Vision Gallery

Retrieval gallery for AUGURY's photo → species funnel: 111,320 images across
2,174 species, used as a FAISS kNN library (DINOv2-base embeddings). The
library grows without model retraining — new species = new photos + a DB row.

## Contents

- `images/<species-key>/<file>.jpg` — the photos (research-grade where sourced
  from iNaturalist)
- `images/<species-key>/sources.jsonl` — **per-image license sidecars**
  (`photo_id`, `file`, `license`, `source`) — read these before any use
- `species_list.json` — 2,230 species, `is_au` flag, indicator data
- `train.jsonl` / `val.jsonl` — LLaMA-Factory sharegpt splits (58,121 / 6,519
  rows; assistant answers DB-generated, image paths relative)
- `dataset_info.json` — LLaMA-Factory registration

## Image provenance & licenses

| Source | Count | License |
|---|---|---|
| iNaturalist (research-grade) | ~110k | per-photo: cc0 / cc-by / cc-by-sa / cc-by-nc / cc-by-nc-sa / cc-by-nc-nd — see sidecars |
| DeepWeeds (5 in-DB AU species) | ~5.2k | CC BY 4.0 |
| GBIF gap-fill | ~dozens | per-record, see sidecars |

**The aggregate is NON-COMMERCIAL** (iNaturalist cc-by-nc photos cannot be
relicensed). Commercial use requires dropping NC images or negotiating with
the photographers. Attribute photographers per the sidecars.

## Build

Regenerate splits any time from `scripts/vision/build_llamafactory_dataset.py`
(per-species caps, seed 42, relative image paths).

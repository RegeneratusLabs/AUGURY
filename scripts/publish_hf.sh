#!/usr/bin/env bash
# AUGURY — publish_hf.sh
# Publishes the AUGURY datasets to HF Hub under RegeneratusLabs.
# Prereqs: hf auth login (write token), org RegeneratusLabs exists.
#
# Usage:
#   bash scripts/publish_hf.sh all         # everything
#   bash scripts/publish_hf.sh db          # species DB (small, quick)
#   bash scripts/publish_hf.sh text        # text training data (small)
#   bash scripts/publish_hf.sh gallery     # 15GB image gallery (slow, resumable)
#
# Gallery upload is resumable: re-run to continue. Run in background if you
# want:  nohup bash scripts/publish_hf.sh gallery > /tmp/hf-gallery.log 2>&1 &
set -euo pipefail
cd "$(dirname "$0")/.."

ORG="RegeneratusLabs"
CARDS="docs/dataset-cards"
STAGE="/tmp/opencode/hf-stage"
mkdir -p "$STAGE"

publish() {
  local repo="$1" dir="$2" card="$3"
  local full="$ORG/$repo"
  echo ">> [$repo] staging $dir + card"
  rm -rf "$STAGE/$repo"
  mkdir -p "$STAGE/$repo"
  cp -r "$dir" "$STAGE/$repo/$(basename "$dir")"
  cp "$CARDS/$card" "$STAGE/$repo/README.md"
  echo ">> [$repo] ensuring repo exists"
  hf repo create "$full" --type dataset --yes 2>/dev/null || true
  echo ">> [$repo] uploading (resumable)"
  hf upload "$full" "$STAGE/$repo" --repo-type dataset --yes
  echo ">> [$repo] done"
}

case "${1:-all}" in
  db)      publish augury-species-db  data/research/database-merged.json augury-species-db.md
           publish augury-species-db  data/vision/species_list.json      augury-species-db.md
           publish augury-species-db  data/unified_species_database.json augury-species-db.md ;;
  text)    publish augury-training-data data/training            augury-training-data.md
           publish augury-training-data data/v3_function_calling augury-training-data.md ;;
  gallery) publish augury-vision-gallery data/vision/images      augury-vision-gallery.md
           publish augury-vision-gallery data/vision/species_list.json augury-vision-gallery.md
           publish augury-vision-gallery data/vision/train.jsonl augury-vision-gallery.md
           publish augury-vision-gallery data/vision/val.jsonl   augury-vision-gallery.md
           publish augury-vision-gallery data/vision/dataset_info.json augury-vision-gallery.md ;;
  all)     bash "$0" db; bash "$0" text; bash "$0" gallery ;;
  *) echo "usage: $0 {db|text|gallery|all}"; exit 1 ;;
esac

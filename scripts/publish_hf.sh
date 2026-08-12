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
# Gallery upload is resumable: re-run to continue. Run in background:
#   nohup bash scripts/publish_hf.sh gallery > /tmp/hf-gallery.log 2>&1 &
set -euo pipefail
cd "$(dirname "$0")/.."

ORG="RegeneratusLabs"
CARDS="docs/dataset-cards"
# Stage on real disk, NOT /tmp (tmpfs ~7.7GB — the 15GB gallery overflows it).
# Also NOT inside the Syncthing-synced Hermes Shared tree.
STAGE="/data/Documents/.hf-stage"

stage() {  # stage <repo> <local_path> [path_in_repo]
  local repo="$1" src="$2" dst="${3:-}"
  mkdir -p "$STAGE/$repo"
  if [ -d "$src" ]; then
    cp -r "$src" "$STAGE/$repo/${dst:-$(basename "$src")}"
  else
    cp "$src" "$STAGE/$repo/${dst:-$(basename "$src")}"
  fi
}

publish() {  # publish <repo> <card>
  local repo="$1"
  local card="$2"
  local full="$ORG/$repo"
  cp "$CARDS/$card" "$STAGE/$repo/README.md"
  echo ">> [$repo] ensuring repo exists"
  hf repo create "$full" --type dataset --exist-ok 2>/dev/null || true
  echo ">> [$repo] uploading (resumable)"
  hf upload "$full" "$STAGE/$repo" --repo-type dataset
  echo ">> [$repo] done"
}

rm -rf "$STAGE"

case "${1:-all}" in
  db)
    stage augury-species-db data/research/database-merged.json
    stage augury-species-db data/vision/species_list.json
    stage augury-species-db data/unified_species_database.json
    publish augury-species-db augury-species-db.md ;;
  text)
    stage augury-training-data data/training
    stage augury-training-data data/v3_function_calling
    publish augury-training-data augury-training-data.md ;;
  gallery)
    stage augury-vision-gallery data/vision/images
    stage augury-vision-gallery data/vision/species_list.json
    stage augury-vision-gallery data/vision/train.jsonl
    stage augury-vision-gallery data/vision/val.jsonl
    stage augury-vision-gallery data/vision/dataset_info.json
    cp "$CARDS/augury-vision-gallery.md" "$STAGE/augury-vision-gallery/README.md"
    echo ">> [augury-vision-gallery] uploading (parallel, resumable)"
    hf upload-large-folder "$ORG/augury-vision-gallery" \
        "$STAGE/augury-vision-gallery" --repo-type dataset --num-workers 8
    echo ">> [augury-vision-gallery] done" ;;
  all) bash "$0" db; bash "$0" text; bash "$0" gallery ;;
  *) echo "usage: $0 {db|text|gallery|all}"; exit 1 ;;
esac

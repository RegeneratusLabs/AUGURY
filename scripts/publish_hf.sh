#!/usr/bin/env bash
# AUGURY — publish_hf.sh
# Publishes the AUGURY datasets to HF Hub under RegeneratusLabs.
# Prereqs: hf auth login (write token), org RegeneratusLabs exists.
#
# Usage:
#   bash scripts/publish_hf.sh all         # everything
#   bash scripts/publish_hf.sh db          # species DB (small, quick)
#   bash scripts/publish_hf.sh text        # text training data (small)
#
# NOTE (2026-08-18): the 15GB image gallery is LOCAL-ONLY by design — the raw
# images are a build-time source, never read at runtime, so they are not
# published to HF. The runtime artifact for the photo path is the compact FAISS
# index (build via scripts/vision/embed_gallery.py -> RegeneratusLabs/augury-vision-index).
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
  all) bash "$0" db; bash "$0" text ;;
  *) echo "usage: $0 {db|text|all}"; exit 1 ;;
esac

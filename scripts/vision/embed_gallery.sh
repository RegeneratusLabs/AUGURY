#!/usr/bin/env bash
# AUGURY — embed_gallery.sh (DSW CPU instance: build the retrieval index)
#
# Runs on the free 8-core CPU instance once the gallery upload to HF finishes.
# Downloads the gallery from HF, embeds with DINOv2-base, builds FAISS,
# pushes index+embeddings+keys to RegeneratusLabs/augury-vision-index.
# Resumable: re-run to catch up (state on the persistent NAS).
#
#   nohup bash embed_gallery.sh > /mnt/workspace/embed.log 2>&1 &
set -euo pipefail
export HF_TOKEN="${HF_TOKEN:?HF_TOKEN not set}"

echo "=== env ==="
pip install -q -U transformers torch faiss-cpu huggingface_hub pillow numpy 2>&1 | tail -1

echo "=== embed (resumable) ==="
python /mnt/workspace/scripts/vision/embed_gallery.py 2>&1 | tail -20

echo "=== done: index pushed to HF ==="

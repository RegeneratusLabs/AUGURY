#!/usr/bin/env bash
# AUGURY — monitor_gallery_upload.sh (watch + resume the gallery upload)
#
# STATUS 2026-08-18: the full 15GB gallery upload was STOPPED by decision —
# the raw images are not an operational dependency (the model reads the FAISS
# index, not the JPEGs). 86,015/111,320 images (185/188 AU spp) remain on HF.
# This script is retained for future use IF the decision is reversed (e.g. to
# mirror the full gallery for open-source reproducibility) or for pushing the
# remaining AU tail. The uploader is resumable: `hf upload-large-folder`
# dedupes already-sent xorbs, so re-running it after a crash is cheap and safe.
#
# This script:
#   1. Reports current hub image count vs target (111,320) every $POLL seconds.
#   2. If the upload process is gone but the target isn't reached, resumes the
#      EXACT same command (idempotent — already-sent data is skipped).
#   3. When the target is reached, prints DONE and exits 0.
#
# Usage:
#   export HF_TOKEN=...            # only needed if not already logged in
#   nohup bash scripts/vision/monitor_gallery_upload.sh > /tmp/gallery-monitor.log 2>&1 &
#
# NOTE: do NOT run a second upload concurrently — the running process is the
# primary uploader. This script only restarts when the primary dies.
set -uo pipefail

REPO="RegeneratusLabs/augury-vision-gallery"
STAGE="/data/Documents/.hf-stage/augury-vision-gallery"
TARGET="${TARGET:-111320}"
POLL="${POLL:-300}"                 # seconds between checks
LOG="${AUGURY_UPLOAD_LOG:-/home/jthomson/AUGURY/data/vision/upload_monitor.log}"
UPLOADER_OUT="${UPLOADER_OUT:-/home/jthomson/AUGURY/data/vision/upload_large_folder.log}"

count_hub() {
    python3 - "$REPO" <<'PY'
import sys
from huggingface_hub import HfApi
repo = sys.argv[1]
info = HfApi().repo_info(repo, repo_type="dataset")
n = sum(1 for s in info.siblings if s.rfilename.endswith(".jpg"))
print(n)
PY
}

is_uploading() {
    pgrep -f "upload-large-folder.*$REPO" > /dev/null 2>&1
}

echo "=== gallery upload monitor ===" | tee -a "$LOG"
echo "repo:   $REPO" | tee -a "$LOG"
echo "target: $TARGET images" | tee -a "$LOG"
echo "poll:   ${POLL}s" | tee -a "$LOG"
date -u | tee -a "$LOG"

while :; do
    cur="$(count_hub 2>/dev/null || echo 0)"
    line="[$(date -u +%FT%TZ)] hub images: ${cur:-0} / $TARGET ($(awk "BEGIN{if(${cur:-0}>0) printf \"%.1f\", 100*${cur:-0}/$TARGET; else print 0}")%)"
    echo "$line" | tee -a "$LOG"
    if [ "${cur:-0}" -ge "$TARGET" ]; then
        echo "=== DONE: target reached ===" | tee -a "$LOG"
        exit 0
    fi
    if ! is_uploading; then
        echo "[$(date -u +%FT%TZ)] upload process NOT running — resuming" | tee -a "$LOG"
        # Uploader is idempotent; already-sent xorbs are skipped.
        nohup hf upload-large-folder "$REPO" "$STAGE" \
            --repo-type dataset --num-workers 2 >> "$UPLOADER_OUT" 2>&1 &
        echo "[$(date -u +%FT%TZ)] resumed (pid $!)" | tee -a "$LOG"
    fi
    sleep "$POLL"
done

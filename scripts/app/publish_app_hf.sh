#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# AUGURY — publish_app_hf.sh
#
# Publishes the Android app's runtime artifacts to Hugging Face.
#
# WHY A SEPARATE SCRIPT
# ---------------------
# The app is a SHELL: it bundles no model data and pulls everything from HF
# through one manifest. This script is the publish half of that contract. It is
# deliberately separate from `scripts/publish_hf.sh`, which publishes the
# *training* artifacts (model weights, training data, species DB).
#
# ORDERING IS LOAD-BEARING
# ------------------------
# `manifest.json` is uploaded LAST. The manifest is the only thing the app reads
# first; if it referenced an artifact that had not landed yet, every installed
# app would fail its next update check. Uploading it last makes that impossible.
#
# WHAT IS UPLOADED
# ----------------
#   RegeneratusLabs/augury-app      (dataset repo — the app's bootstrap point)
#     manifest.json                 the update lever, uploaded LAST
#     augury-ondevice.json          the species DB the app reads
#     dinov2-base-fp32.onnx         the image encoder (~346 MB)
#     vision-index-v3.tar.gz        the retrieval index (~20 MB)
#
#   RegeneratusLabs/augury-vision-index  (dataset repo)
#     vision-index-v3.tar.gz        same tarball, canonical home for the index
#
# `index.faiss` is DELIBERATELY EXCLUDED from the tarball: the app does
# brute-force kNN in Kotlin, so FAISS is not a runtime dependency and the 20 MB
# file would be dead weight on every user's phone.
#
# WHY fp32 AND NOT int8
# ---------------------
# Dynamic int8 quantisation was measured and REJECTED (2026-09-19): on the same
# 40 queries ONNX fp32 scored 0.7500/0.8500 — identical to PyTorch, delta +0.00p —
# while int8 collapsed to 0.0500/0.1250, delta -70.00p. The fp32 control matching
# PyTorch exactly proves the pipeline was sound, so the collapse is a genuine
# quantisation effect (ViT attention needs more dynamic range than int8 provides).
# Record: data/vision/bench/encoder_gate_dinov2-base-fp32.json
#
# Usage:
#   bash scripts/app/publish_app_hf.sh --dry-run     # default; makes NO network calls
#   bash scripts/app/publish_app_hf.sh --publish     # actually uploads
# ---------------------------------------------------------------------------
set -euo pipefail

cd "$(dirname "$0")/../.."
ROOT="$(pwd)"

APP_REPO="RegeneratusLabs/augury-app"
INDEX_REPO="RegeneratusLabs/augury-vision-index"
REPO_TYPE="dataset"

MANIFEST="$ROOT/data/app/manifest.json"
FACTS="$ROOT/data/app/augury-ondevice.json"
INDEX_TAR="$ROOT/data/app/vision-index-v3.tar.gz"
ENCODER="$ROOT/models/onnx/dinov2-base-fp32.onnx"

MODE="dry-run"
case "${1:-}" in
  --dry-run) MODE="dry-run" ;;
  --publish) MODE="publish" ;;
  -h|--help) sed -n '2,50p' "$0"; exit 0 ;;
  *) echo "usage: $0 [--dry-run|--publish]" >&2; exit 1 ;;
esac

hr() { printf '%s\n' "--------------------------------------------------------------------"; }
sha() { sha256sum "$1" | cut -d' ' -f1; }
size() { stat -c%s "$1"; }
human() { awk -v b="$1" 'BEGIN{printf "%.1f MB", b/1000000}'; }

# ---------------------------------------------------------------------------
# 0. Preconditions — fail loudly BEFORE touching the network.
# ---------------------------------------------------------------------------
echo "AUGURY app publish — mode: $MODE"
hr
missing=0
for f in "$MANIFEST" "$FACTS" "$ENCODER" "$INDEX_TAR"; do
  if [ ! -f "$f" ]; then
    echo "  MISSING: ${f#$ROOT/}"
    missing=1
  fi
done
if [ "$missing" -ne 0 ]; then
  echo
  echo "Refusing to publish: required artifacts are absent."
  echo "Build them first:"
  echo "  .venv-mcpmv46/bin/python scripts/app/export_encoder_onnx.py export"
  echo "  .venv-mcpmv46/bin/python scripts/app/build_ondevice_bundle.py --index-tar <path>"
  exit 1
fi

# The tarball must NOT contain index.faiss (dead weight on every phone).
if tar tzf "$INDEX_TAR" | grep -qx "index.faiss"; then
  echo "Refusing to publish: $INDEX_TAR contains index.faiss."
  echo "The app does brute-force kNN in Kotlin and must not ship FAISS."
  exit 1
fi

# The manifest must not reference the rejected int8 encoder.
if grep -q 'dinov2-base-int8' "$MANIFEST"; then
  echo "Refusing to publish: manifest still references dinov2-base-int8.onnx,"
  echo "which was measured and rejected (delta -70.00p top-1)."
  exit 1
fi

# Every artifact hash in the manifest must match the file we are about to upload.
echo "Artifact verification (manifest hash vs local file):"
for pair in "facts:$FACTS" "encoders:$ENCODER" "index:$INDEX_TAR"; do
  label="${pair%%:*}"; path="${pair#*:}"
  want="$(python3 - "$MANIFEST" "$label" <<'PY' 2>/dev/null || true
import json,sys
m=json.load(open(sys.argv[1])); k=sys.argv[2]
if k=="facts": print(m["facts"].get("sha256") or "")
elif k=="encoders": print(m["vision"]["encoders"][0].get("sha256") or "")
elif k=="index": print(m["vision"]["index"].get("sha256") or "")
PY
)"
  got="$(sha "$path")"
  if [ -z "$want" ]; then
    echo "  [WARN] $label: manifest hash is NULL (unresolved) — local=$(printf '%.12s' "$got")…"
  elif [ "$want" = "$got" ]; then
    echo "  [ OK ] $label  $(printf '%.12s' "$got")…"
  else
    echo "  [FAIL] $label  manifest=$(printf '%.12s' "$want")… local=$(printf '%.12s' "$got")…"
    echo "         Re-run build_ondevice_bundle.py so the manifest is regenerated."
    exit 1
  fi
done
hr

# ---------------------------------------------------------------------------
# 1. Plan
# ---------------------------------------------------------------------------
echo "Upload plan"
echo
printf '  %-28s %12s  %s\n' "FILE" "SIZE" "SHA256"
printf '  %-28s %12s  %s\n' "----" "----" "------"
for f in "$INDEX_TAR" "$ENCODER" "$FACTS" "$MANIFEST"; do
  printf '  %-28s %12s  %.16s…\n' "$(basename "$f")" "$(human "$(size "$f")")" "$(sha "$f")"
done
echo
echo "  target repos:"
echo "    $APP_REPO      ($REPO_TYPE)  <- all four files"
echo "    $INDEX_REPO    ($REPO_TYPE)  <- vision-index-v3.tar.gz"
echo
echo "  upload order (manifest LAST — see header):"
echo "    1. vision-index-v3.tar.gz"
echo "    2. dinov2-base-fp32.onnx"
echo "    3. augury-ondevice.json"
echo "    4. manifest.json          <-- the app reads this first"
hr

if [ "$MODE" = "dry-run" ]; then
  echo "DRY RUN — nothing uploaded, no network calls made."
  echo
  echo "To publish for real:"
  echo "  1. confirm you are authed:  hf auth whoami"
  echo "  2. run:                     bash scripts/app/publish_app_hf.sh --publish"
  echo
  echo "Then pin the resulting revisions into the manifest and re-run this script,"
  echo "so the app can verify exactly what it downloads:"
  echo "  .venv-mcpmv46/bin/python scripts/app/build_ondevice_bundle.py \\"
  echo "      --revision $APP_REPO=<sha> --revision $INDEX_REPO=<sha>"
  exit 0
fi

# ---------------------------------------------------------------------------
# 2. Publish
# ---------------------------------------------------------------------------
HF="${HF_CLI:-hf}"
command -v "$HF" >/dev/null 2>&1 || { echo "hf CLI not found (looked for '$HF')"; exit 1; }

echo ">> ensuring repos exist"
"$HF" repo create "$APP_REPO"   --type "$REPO_TYPE" --exist-ok
"$HF" repo create "$INDEX_REPO" --type "$REPO_TYPE" --exist-ok

echo ">> [$INDEX_REPO] vision-index-v3.tar.gz"
"$HF" upload "$INDEX_REPO" "$INDEX_TAR" vision-index-v3.tar.gz --repo-type "$REPO_TYPE"

echo ">> [$APP_REPO] vision-index-v3.tar.gz"
"$HF" upload "$APP_REPO" "$INDEX_TAR" vision-index-v3.tar.gz --repo-type "$REPO_TYPE"

echo ">> [$APP_REPO] dinov2-base-fp32.onnx ($(human "$(size "$ENCODER")")) — this is slow"
"$HF" upload "$APP_REPO" "$ENCODER" dinov2-base-fp32.onnx --repo-type "$REPO_TYPE"

echo ">> [$APP_REPO] augury-ondevice.json"
"$HF" upload "$APP_REPO" "$FACTS" augury-ondevice.json --repo-type "$REPO_TYPE"

echo ">> [$APP_REPO] manifest.json  (LAST — the app's entry point)"
"$HF" upload "$APP_REPO" "$MANIFEST" manifest.json --repo-type "$REPO_TYPE"

hr
echo "Published. Next: capture the resulting revisions and pin them"
echo "  hf api ... or the web UI; then:"
echo "  .venv-mcpmv46/bin/python scripts/app/build_ondevice_bundle.py \\"
echo "      --revision $APP_REPO=<sha> --revision $INDEX_REPO=<sha>"
echo "and re-upload manifest.json."

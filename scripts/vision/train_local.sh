#!/usr/bin/env bash
# AUGURY vision — train_local.sh (Victus / any local GPU host)
# Usage:
#   bash scripts/vision/train_local.sh            # bf16 LoRA (default)
#   bash scripts/vision/train_local.sh --qlora    # QLoRA NF4 fallback for 6GB VRAM
set -euo pipefail
cd "$(dirname "$0")/../.."

VENV=".venv-mcpmv46"
if [ ! -x "$VENV/bin/python" ]; then
  echo "ERROR: venv not found at $VENV — create it first (see scripts/vision/README.md)" >&2
  exit 1
fi

YAML="scripts/vision/train_v4_6_lora.yaml"
if [ "${1:-}" = "--qlora" ]; then
  TMPYAML="data/vision/train_v4_6_lora_qlora.yaml"
  sed 's/# quantization_bit: 4/quantization_bit: 4/' "$YAML" > "$TMPYAML"
  YAML="$TMPYAML"
  echo ">> QLoRA variant: $YAML"
fi

export DOWNSAMPLE_MODE="${DOWNSAMPLE_MODE:-4x}"   # guard rail 4
export DISABLE_VERSION_CHECK=1
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True   # reduce fragmentation on 6GB
unset USE_V1                                     # v2 launcher required

echo ">> training: $YAML"
"$VENV/bin/llamafactory-cli" train "$YAML"
echo ">> done. Merge + export: bash scripts/vision/export_gguf.sh"

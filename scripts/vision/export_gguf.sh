#!/usr/bin/env bash
# AUGURY vision — export_gguf.sh
# Merges the trained LoRA into the base, converts to GGUF, quantizes to Q4_K_M.
# Prereqs: llama.cpp checkout >= b9049 with build/bin/llama-quantize + convert_hf_to_gguf.py
#          (the repo-local llama.cpp clone is past b9049).
# Usage: bash scripts/vision/export_gguf.sh [lora_dir] [out_dir]
set -euo pipefail
cd "$(dirname "$0")/../.."

LORA_DIR="${1:-data/vision/output/augury-v4_6-lora}"
OUT_DIR="${2:-data/vision/output/gguf}"
MERGE_DIR="data/vision/output/augury-v4_6-merged"
LLAMA_CPP="llama.cpp"

if [ ! -d "$LORA_DIR" ]; then
  echo "ERROR: LoRA dir not found: $LORA_DIR" >&2; exit 1
fi

export DISABLE_VERSION_CHECK=1
unset USE_V1

echo ">> 1/4 merge LoRA -> fp16 base"
.venv-mcpmv46/bin/llamafactory-cli export \
  --model_name_or_path models/MiniCPM-V-4.6 \
  --adapter_name_or_path "$LORA_DIR" \
  --template minicpm_v_4_6 \
  --finetuning_type lora \
  --export_dir "$MERGE_DIR" \
  --export_size 2 --export_legacy_format false

echo ">> 2/4 convert LM to F16 GGUF"
mkdir -p "$OUT_DIR"
"$LLAMA_CPP/build/bin/convert_hf_to_gguf.py" "$MERGE_DIR" \
  --outfile "$OUT_DIR/MiniCPM-V-4.6-AUGURY-F16.gguf" --outtype f16

echo ">> 3/4 convert vision projector (mmproj) F16"
"$LLAMA_CPP/build/bin/convert_hf_to_gguf.py" "$MERGE_DIR" \
  --mmproj --outfile "$OUT_DIR/mmproj-AUGURY-F16.gguf"

echo ">> 4/4 quantize LM to Q4_K_M"
"$LLAMA_CPP/build/bin/llama-quantize" \
  "$OUT_DIR/MiniCPM-V-4.6-AUGURY-F16.gguf" \
  "$OUT_DIR/MiniCPM-V-4.6-AUGURY-Q4_K_M.gguf" Q4_K_M

echo ">> done:"
ls -la "$OUT_DIR"

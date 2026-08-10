#!/usr/bin/env bash
# Convenience wrapper — merges LoRA + converts to GGUF
# Usage: bash convert.sh [lora_dir]
# Default: minicpm5_v3_lora
cd "$(dirname "$0")"
python scripts/convert_to_gguf.py "${1:-minicpm5_v3_lora}"

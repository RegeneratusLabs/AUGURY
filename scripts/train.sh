#!/usr/bin/env bash
# Convenience wrapper — trains MiniCPM5-1B on your RTX 3060
# Usage: bash train.sh [--test]
cd "$(dirname "$0")"
python scripts/train_minicpm5.py --train "$@"

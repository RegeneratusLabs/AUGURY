#!/usr/bin/env bash
# AUGURY — run_evening.sh (DSW / ModelScope cloud GPU master script)
#
# Evening fine-tune session. Runs on the A10 24GB instance with the NAS at
# /mnt/workspace. Upload BEFORE running (from Victus, ~22MB, ~2 min at 2Mbps):
#
#   scp-like / modelscope upload, or simplest: copy via the DSW web shell:
#     - scripts/vision/{fine_tune_encoder.py,bake_off.py,train_formatter.yaml}
#     - data/training/{weeds_indicators_merged_train.jsonl,
#                      weeds_indicators_merged_val.jsonl,dataset_info.json}
#     - data/vision/alias_map.json
#   ...into /mnt/workspace/scripts/vision/ and /mnt/workspace/data/training/
#
# Then: bash /mnt/workspace/scripts/vision/run_evening.sh 2>&1 | tee /mnt/workspace/evening.log
#
# Steps:
#   1) env install drill (idempotent)
#   2) verify NAS data
#   3) WS1b: contrastive fine-tune DINOv2-base on AU images (encoder fine-tune)
#   4) re-eval with bake_off.py (fine-tuned checkpoint vs off-the-shelf)
#   5) WS2: MiniCPM5-1B formatter LoRA on the AU-balanced text data
# All outputs land on the persistent NAS. Resume by re-running.
set -euo pipefail
cd /mnt/workspace

export DOWNSAMPLE_MODE=4x
export DISABLE_VERSION_CHECK=1
unset USE_V1 || true

CLEAN="${1:-}"
FT="${2:-}"
if [ "$CLEAN" = "--clean" ]; then
  echo "=== [0/7] CLEAN REBUILD: wiping old-era artifacts (keeping images/) ==="
  rm -rf \
    /mnt/workspace/archive \
    /mnt/workspace/LLaMA-Factory \
    /mnt/workspace/data/vision/output \
    /mnt/workspace/data/vision/ft \
    /mnt/workspace/data/training/output \
    /mnt/workspace/models/MiniCPM-V-4.6 \
    /mnt/workspace/models/MiniCPM-V-4_6-Q4_K_M.gguf \
    /mnt/workspace/models/mmproj-model-f16.gguf \
    /mnt/workspace/evening.log /mnt/workspace/formatter.log \
    /mnt/workspace/train.log /mnt/workspace/merge.log \
    /mnt/workspace/eval.log /mnt/workspace/eval2.log \
    /mnt/workspace/eval_merged.py /mnt/workspace/eval_merged2.py \
    /mnt/workspace/eval_fix_test.py \
    /mnt/workspace/scripts/vision/train_local.sh \
    /mnt/workspace/scripts/vision/export_gguf.sh \
    /mnt/workspace/scripts/vision/eval_vision.py \
    /mnt/workspace/scripts/vision/train_colab.ipynb \
    /mnt/workspace/scripts/vision/build_llamafactory_dataset.py \
    /mnt/workspace/data/vision/train_v4_6_lora_qlora.yaml \
    /mnt/workspace/data/vision/train_v4_6_lora.yaml \
    /mnt/workspace/evening-bundle.tar.gz
  echo "  wiped. keeping data/vision/images/ + species_list.json + bundle files"
  echo "=== re-cloning LLaMA-Factory ==="
  git clone -q --depth 1 https://github.com/hiyouga/LlamaFactory.git /mnt/workspace/LLaMA-Factory
  echo "  cloned."
fi

echo "=== [0/7] archive the old MiniCPM-V vision training era (keep, out of the way) ==="
mkdir -p /mnt/workspace/archive/vision-v46-era
for p in \
  data/vision/output \
  data/vision/train.jsonl \
  data/vision/train_v4_6_lora_qlora.yaml \
  data/vision/train_v4_6_lora.yaml \
  train.log merge.log eval.log eval2.log \
  eval_merged.py eval_merged2.py eval_fix_test.py \
  scripts/vision/train_local.sh scripts/vision/export_gguf.sh scripts/vision/eval_vision.py \
  scripts/vision/train_colab.ipynb scripts/vision/build_llamafactory_dataset.py; do
  if [ -e "$p" ]; then
    mv "$p" /mnt/workspace/archive/vision-v46-era/ 2>/dev/null || \
      cp -r "$p" /mnt/workspace/archive/vision-v46-era/ 2>/dev/null
    echo "  archived: $p"
  fi
done
echo "archive contents:"; ls /mnt/workspace/archive/vision-v46-era/ 2>/dev/null | head -15

echo "=== [1/7] env install (idempotent) ==="
(cd /mnt/workspace/LLaMA-Factory && pip install -q -e . 2>&1 | tail -1)
pip install -q "transformers==5.7.0" 2>&1 | tail -1
pip install -q -U mistral_common 2>&1 | tail -1
pip install -q pytorch-metric-learning faiss-cpu 2>&1 | tail -1
cd /mnt/workspace

echo "=== [2/7] verify NAS data ==="
for p in \
  data/vision/images \
  data/vision/species_list.json \
  data/training/weeds_indicators_merged_train.jsonl \
  data/training/weeds_indicators_merged_val.jsonl \
  data/training/dataset_info.json \
  scripts/vision/fine_tune_encoder.py \
  scripts/vision/bake_off.py \
  scripts/vision/train_formatter.yaml \
  data/vision/alias_map.json; do
  if [ ! -e "$p" ]; then echo "MISSING: $p"; exit 1; fi
done
echo "NAS data OK"

if [ "$FT" = "--ft" ]; then
  echo "=== [3/7] WS1b: DINOv2-base contrastive fine-tune (AU) [--ft] ==="
  python scripts/vision/fine_tune_encoder.py \
    --model dinov2-base --epochs 5 --batch-size 96 --lr 3e-4 \
    --out data/vision/ft/dinov2-au 2>&1 | tail -10

  echo "=== [4/7] re-eval: fine-tuned encoder vs baseline ==="
  python scripts/vision/bake_off.py --au-only --limit 30 --encoders dinov2-base \
    --out data/vision/bake_off_ft_report.md 2>&1 | tail -4
  python scripts/vision/bake_off.py --au-only --limit 30 --encoders dinov2-base \
    --checkpoint data/vision/ft/dinov2-au/checkpoint-5.pt \
    --out data/vision/bake_off_ft_report.md 2>&1 | tail -4
else
  echo "=== [3/7] encoder fine-tune SKIPPED (recipe under repair; base DINOv2 passes gates). ==="
  echo "=== [4/7] baseline bake-off (AU) ==="
  python scripts/vision/bake_off.py --au-only --limit 30 --encoders dinov2-base \
    --out data/vision/bake_off_ft_report.md 2>&1 | tail -4
fi

echo "=== [5/7] WS2: formatter LoRA (MiniCPM5-1B) ==="
python - <<'PYEOF'
import re, pathlib
yaml = pathlib.Path("scripts/vision/train_formatter.yaml").read_text()
# point base model at the DSW download path
yaml = yaml.replace("model_name_or_path: models/MiniCPM5-1B",
                    "model_name_or_path: /mnt/workspace/models/MiniCPM5-1B")
pathlib.Path("scripts/vision/train_formatter_dsw.yaml").write_text(yaml)
PYEOF
# base model: download if not present
if [ ! -d /mnt/workspace/models/MiniCPM5-1B ]; then
  mkdir -p /mnt/workspace/models
  python -c "
from huggingface_hub import snapshot_download
p = snapshot_download('openbmb/MiniCPM5-1B')
print('model at', p)" 2>&1 | tail -2
  ln -sfn "$(ls -d /root/.cache/huggingface/hub/models--openbmb--MiniCPM5-1B/snapshots/* | head -1)" \
    /mnt/workspace/models/MiniCPM5-1B 2>/dev/null || \
  mv "$(ls -d /root/.cache/huggingface/hub/models--openbmb--MiniCPM5-1B/snapshots/* | head -1)" \
    /mnt/workspace/models/MiniCPM5-1B
fi

nohup llamafactory-cli train scripts/vision/train_formatter_dsw.yaml \
  > /mnt/workspace/formatter.log 2>&1 &
echo "formatter training started (log: /mnt/workspace/formatter.log) — checkpoints in data/training/output/augury-formatter"

echo "=== [6/7] done. artifacts: ==="
ls -la data/vision/ft/dinov2-au/ 2>/dev/null | tail -3
echo "evening log: /mnt/workspace/evening.log"

# Optional telemetry: if HF_TOKEN is exported, push the logs + reports to HF so
# the team can monitor without SSH access.
if [ -n "${HF_TOKEN:-}" ]; then
  echo "=== pushing logs/reports to HF ==="
  mkdir -p /tmp/evening-report
  cp /mnt/workspace/evening.log /tmp/evening-report/ 2>/dev/null || true
  cp /mnt/workspace/formatter.log /tmp/evening-report/ 2>/dev/null || true
  cp /mnt/workspace/data/vision/bake_off_ft_report.md /tmp/evening-report/ 2>/dev/null || true
  cp /mnt/workspace/data/vision/ft/dinov2-au/config.json /tmp/evening-report/encoder-config.json 2>/dev/null || true
  ls -la /mnt/workspace/data/training/output/augury-formatter/ > /tmp/evening-report/checkpoints.txt 2>/dev/null || true
  pip install -q -U huggingface_hub 2>/dev/null || true
  HF_TOKEN="$HF_TOKEN" python - <<'PYEOF' 2>/dev/null || true
from huggingface_hub import HfApi
import os
api = HfApi(token=os.environ["HF_TOKEN"])
for f in ["evening.log", "formatter.log", "bake_off_ft_report.md", "encoder-config.json", "checkpoints.txt"]:
    p = f"/tmp/evening-report/{f}"
    if os.path.exists(p):
        api.upload_file(path_or_fileobj=p, path_in_repo=f"run/{f}",
                        repo_id="RegeneratusLabs/augury-evening-bundle",
                        repo_type="dataset")
        print("pushed", f)
PYEOF
fi
echo "session complete."

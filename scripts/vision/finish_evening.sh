#!/usr/bin/env bash
# AUGURY — finish_evening.sh (set-and-forget post-training pipeline, DSW)
#
# Runs AFTER the formatter training: waits for it to finish (if still running),
# merges the LoRA into the base, converts to GGUF Q4_K_M, and pushes every
# artifact to HF Hub so the team can pull them without SSH access.
#
# Prereqs: HF_TOKEN exported; run_evening.sh --clean already ran (base model
# at /mnt/workspace/models/MiniCPM5-1B, adapter in data/training/output/).
#
#   export HF_TOKEN=...
#   nohup bash finish_evening.sh > finish.log 2>&1 &
set -euo pipefail
cd /mnt/workspace
export DISABLE_VERSION_CHECK=1
unset USE_V1 || true

BASE="/mnt/workspace/models/MiniCPM5-1B"
ADAPTER="/mnt/workspace/data/training/output/augury-1b"
MERGED="/mnt/workspace/data/training/output/augury-1b-merged"
GGUF_DIR="/mnt/workspace/gguf"
FMT_REPO="RegeneratusLabs/augury-1b"   # model repo (merged + GGUF)
LOG_REPO="RegeneratusLabs/augury-evening-bundle"  # dataset repo (logs)

log() { echo "[$(date +%H:%M:%S)] $*"; }

if [ -z "${HF_TOKEN:-}" ]; then
  log "ERROR: HF_TOKEN not set"; exit 1
fi
python - <<'PYEOF'
import os
from huggingface_hub import HfApi
HfApi(token=os.environ["HF_TOKEN"])
print("HF auth OK")
PYEOF

log "=== 1/6 check artifacts + env ==="
for i in $(seq 1 90); do
  if ! pgrep -f llamafactory-cli > /dev/null 2>&1; then break; fi
  log "  training still running ($i/90 min)"; sleep 60
done

if [ -f "$MERGED/model.safetensors" ] || [ -f "$MERGED/model-00001-of-00002.safetensors" ]; then
  log "  merged model already exists on NAS — skipping merge"
else
  if [ ! -d "$ADAPTER" ] || [ -z "$(ls "$ADAPTER"/*.safetensors 2>/dev/null)" ]; then
    log "ERROR: no adapter found in $ADAPTER — training did not produce output"
    echo "FAILURE: no adapter" > /tmp/evening-status.txt
    python - <<'PYEOF' || true
import os
from huggingface_hub import HfApi
HfApi(token=os.environ["HF_TOKEN"]).upload_file(
    path_or_fileobj="/tmp/evening-status.txt", path_in_repo="run/status.txt",
    repo_id=os.environ.get("LOG_REPO", "RegeneratusLabs/augury-evening-bundle"),
    repo_type="dataset")
PYEOF
    exit 1
  fi
  log "  adapter OK: $(ls "$ADAPTER"/*.safetensors | wc -l) safetensors file(s)"
  log "  installing env for merge (fresh reboot = fresh env)"
  if [ ! -d /mnt/workspace/LLaMA-Factory ]; then
    git clone -q --depth 1 https://github.com/hiyouga/LlamaFactory.git /mnt/workspace/LLaMA-Factory
  fi
  (cd /mnt/workspace/LLaMA-Factory && pip install -q -e . 2>&1 | tail -1)
  pip install -q "transformers==5.7.0" 2>&1 | tail -1
  pip install -q -U mistral_common 2>&1 | tail -1

  log "=== 2/6 merge LoRA -> fp16 base ==="
  llamafactory-cli export \
    --model_name_or_path "$BASE" \
    --adapter_name_or_path "$ADAPTER" \
    --template qwen --finetuning_type lora \
    --export_dir "$MERGED" --export_size 2 2>&1 | tail -3
  [ -f "$MERGED/model.safetensors" ] || [ -f "$MERGED/model-00001-of-00002.safetensors" ] || \
    { log "ERROR: merge produced no safetensors"; exit 1; }
  log "  merged OK"
fi

log "=== 3/6 clone llama.cpp + build quantizer (in /tmp — NAS builds look stalled) ==="
rm -rf /mnt/workspace/llama.cpp /tmp/llama-build
git clone -q --depth 1 https://github.com/ggerganov/llama.cpp.git /mnt/workspace/llama.cpp
cp -r /mnt/workspace/llama.cpp /tmp/llama-build
cd /tmp/llama-build
cmake -B build -DCMAKE_BUILD_TYPE=Release -DLLAMA_CURL=OFF > /dev/null 2>&1
cmake --build build --config Release -j"$(nproc)" --target llama-quantize > /tmp/llamacpp-build.log 2>&1
cd /mnt/workspace
QUANT=/tmp/llama-build/build/bin/llama-quantize
[ -x "$QUANT" ] || { log "ERROR: llama.cpp build failed (see /tmp/llamacpp-build.log)"; exit 1; }
log "  llama-quantize ready at $QUANT"

log "=== 4/6 convert + quantize GGUF ==="
mkdir -p "$GGUF_DIR"
python /mnt/workspace/llama.cpp/convert_hf_to_gguf.py "$MERGED" \
  --outfile "$GGUF_DIR/MiniCPM5-1B-AUGURY-F16.gguf" --outtype f16 2>&1 | tail -2
"$QUANT" \
  "$GGUF_DIR/MiniCPM5-1B-AUGURY-F16.gguf" \
  "$GGUF_DIR/MiniCPM5-1B-AUGURY-Q4_K_M.gguf" Q4_K_M 2>&1 | tail -2
ls -la "$GGUF_DIR"

log "=== 5/6 push artifacts to HF (datacenter speed) ==="
pip install -q -U huggingface_hub 2>/dev/null || true
export HF_TOKEN="$HF_TOKEN"
# LLaMA-Factory writes local-path base_model into READMEs — HF Hub rejects it.
for readme in "$MERGED/README.md" "$ADAPTER/README.md"; do
  if [ -f "$readme" ]; then
    sed -i 's|base_model:.*|base_model: openbmb/MiniCPM5-1B|' "$readme"
  fi
done
python - <<'PYEOF'
import os
from huggingface_hub import HfApi, create_repo
api = HfApi(token=os.environ["HF_TOKEN"])
repo = "RegeneratusLabs/augury-1b"
try:
    create_repo(repo, repo_type="model", exist_ok=True, token=os.environ["HF_TOKEN"])
except Exception:
    pass
for local, remote in [
    ("/mnt/workspace/gguf/MiniCPM5-1B-AUGURY-Q4_K_M.gguf", "MiniCPM5-1B-AUGURY-Q4_K_M.gguf"),
    ("/mnt/workspace/gguf/MiniCPM5-1B-AUGURY-F16.gguf", "MiniCPM5-1B-AUGURY-F16.gguf"),
    ("/mnt/workspace/data/training/output/augury-1b-merged", "merged-fp16"),
    ("/mnt/workspace/data/training/output/augury-1b", "lora-adapter"),
    ("/mnt/workspace/formatter.log", "formatter.log"),
]:
    if os.path.isdir(local):
        api.upload_folder(folder_path=local, repo_id=repo, repo_type="model",
                          path_in_repo=remote,
                          ignore_patterns=["checkpoint-*", "optimizer.pt",
                                           "scheduler.pt", "trainer_state.json",
                                           "training_args.bin"])
        print("pushed folder", remote)
    elif os.path.exists(local):
        api.upload_file(path_or_fileobj=local, path_in_repo=remote,
                        repo_id=repo, repo_type="model")
        print("pushed", remote)
PYEOF

log "=== 6/6 status marker ==="
echo "DONE $(date -u +%Y-%m-%dT%H:%M:%SZ)" > /tmp/evening-status.txt
python - <<'PYEOF' || true
import os
from huggingface_hub import HfApi
api = HfApi(token=os.environ["HF_TOKEN"])
api.upload_file(path_or_fileobj="/tmp/evening-status.txt", path_in_repo="run/status.txt",
                repo_id="RegeneratusLabs/augury-evening-bundle", repo_type="dataset")
print("status: DONE")
PYEOF
log "ALL DONE. Artifacts: https://huggingface.co/RegeneratusLabs/augury-1b"

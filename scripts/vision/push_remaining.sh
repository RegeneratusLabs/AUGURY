#!/usr/bin/env bash
# AUGURY — push_remaining.sh (completes the HF push after the README validation hiccup)
#
# The finish script pushed the GGUFs + merged model, then died because a
# LLaMA-Factory-written README.md carries a local-path base_model that HF Hub
# rejects. This sanitizes the READMEs and pushes the remaining artifacts.
#
#   export HF_TOKEN=... && bash push_remaining.sh
set -euo pipefail
cd /mnt/workspace
export HF_TOKEN="${HF_TOKEN:?HF_TOKEN not set}"

echo "=== sanitize READMEs (local base_model -> HF id) ==="
for readme in \
  /mnt/workspace/data/training/output/augury-formatter/README.md \
  /mnt/workspace/data/training/output/augury-formatter-merged/README.md; do
  if [ -f "$readme" ]; then
    sed -i 's|base_model:.*|base_model: openbmb/MiniCPM5-1B|' "$readme"
    echo "  patched: $readme"
  fi
done

echo "=== push remaining artifacts ==="
python - <<'PYEOF'
import os
from huggingface_hub import HfApi

api = HfApi(token=os.environ["HF_TOKEN"])
repo = "RegeneratusLabs/augury-formatter"

# adapter folder (README already sanitized above)
api.upload_folder(folder_path="/mnt/workspace/data/training/output/augury-formatter",
                  repo_id=repo, repo_type="model", path_in_repo="lora-adapter",
                  ignore_patterns=["checkpoint-*", "optimizer.pt", "scheduler.pt",
                                   "trainer_state.json", "training_args.bin"])
print("pushed lora-adapter")

# training log
if os.path.exists("/mnt/workspace/formatter.log"):
    api.upload_file(path_or_fileobj="/mnt/workspace/formatter.log",
                    path_in_repo="formatter.log", repo_id=repo, repo_type="model")
    print("pushed formatter.log")

# what's in the repo now?
files = [s["rfilename"] for s in api.list_repo_files(repo, repo_type="model")]
print("repo contents:")
for f in sorted(files):
    print("  ", f)
PYEOF

echo "=== DONE marker ==="
echo "DONE $(date -u +%Y-%m-%dT%H:%M:%SZ)" > /tmp/evening-status.txt
python - <<'PYEOF' || true
import os
from huggingface_hub import HfApi
api = HfApi(token=os.environ["HF_TOKEN"])
api.upload_file(path_or_fileobj="/tmp/evening-status.txt", path_in_repo="run/status.txt",
                repo_id="RegeneratusLabs/augury-evening-bundle", repo_type="dataset")
print("status: DONE")
PYEOF
echo "ALL DONE."

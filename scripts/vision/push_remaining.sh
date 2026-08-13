#!/usr/bin/env bash
# AUGURY — push_remaining.sh (completes the HF push; idempotent)
#
# Drops LLaMA-Factory auto-generated READMEs (their YAML frontmatter fails
# HF validation), then pushes whatever is missing from the model repo.
# Safe to re-run any number of times.
#
#   export HF_TOKEN=... && bash push_remaining.sh
set -euo pipefail
cd /mnt/workspace
export HF_TOKEN="${HF_TOKEN:?HF_TOKEN not set}"

echo "=== drop LLaMA-Factory READMEs (invalid YAML frontmatter for HF) ==="
rm -f \
  /mnt/workspace/data/training/output/augury-formatter/README.md \
  /mnt/workspace/data/training/output/augury-formatter-merged/README.md
echo "  removed."

echo "=== push missing artifacts ==="
python - <<'PYEOF'
import os
from huggingface_hub import HfApi

api = HfApi(token=os.environ["HF_TOKEN"])
repo = "RegeneratusLabs/augury-formatter"
existing = set(api.list_repo_files(repo, repo_type="model"))

def present(remote: str) -> bool:
    return remote in existing or any(f.startswith(remote + "/") for f in existing)

items = [
    ("/mnt/workspace/gguf/MiniCPM5-1B-AUGURY-Q4_K_M.gguf", "MiniCPM5-1B-AUGURY-Q4_K_M.gguf"),
    ("/mnt/workspace/gguf/MiniCPM5-1B-AUGURY-F16.gguf", "MiniCPM5-1B-AUGURY-F16.gguf"),
    ("/mnt/workspace/data/training/output/augury-formatter-merged", "merged-fp16"),
    ("/mnt/workspace/data/training/output/augury-formatter", "lora-adapter"),
    ("/mnt/workspace/formatter.log", "formatter.log"),
]
for local, remote in items:
    if present(remote):
        print("skip (already on hub):", remote)
        continue
    if os.path.isdir(local):
        api.upload_folder(folder_path=local, repo_id=repo, repo_type="model",
                          path_in_repo=remote,
                          ignore_patterns=["checkpoint-*", "optimizer.pt",
                                           "scheduler.pt", "trainer_state.json",
                                           "training_args.bin"])
        print("pushed folder:", remote)
    elif os.path.exists(local):
        api.upload_file(path_or_fileobj=local, path_in_repo=remote,
                        repo_id=repo, repo_type="model")
        print("pushed:", remote)
    else:
        print("WARNING missing locally:", local)

print("\\nrepo contents now:")
for f in sorted(api.list_repo_files(repo, repo_type="model")):
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

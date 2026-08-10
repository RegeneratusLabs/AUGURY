# AUGURY — Directory Staleness Audit (28 July 2026)

**Read-only audit. Nothing deleted or moved.** Here's the full picture:

---

## 🔴 Stale / Redundant (Can Move to `archive/`)

These are superseded by newer files or no longer relevant:

| Item | Size | Why |
|---|---|---|
| `Weeds V1/` | 49 MB | Pass 1 LoRA — reference only, V3 is current |
| `augury_merged_fp16/` | 958 MB | Pass 1 merged model — 1 GB sitting idle |
| `augury.Q4_K_M.gguf` | 380 MB | Pass 1 deployable — superseded by V3 |
| `augury-research-pack.tar.gz` | 87 KB | Already extracted to `augury-research-pack/` |
| `server.log` | 408 B | Stale Flask log from Pass 1 testing |
| `data/training/ellenberg_indicators.jsonl` | 18 MB | Superseded by merged train file |
| `data/training/ellenberg_indicators_v2.jsonl` | 18 MB | Superseded by merged train file |
| `data/training/maughan_amos_2022.jsonl` | 324 KB | Intermediate — merged into final |
| `data/training/maughan_amos_2024.jsonl` | 81 KB | Intermediate — merged into final |
| `data/training/refusal_examples.jsonl` | 49 KB | Intermediate — merged into V3 refusal |
| `data/training/augury_formatting_train.jsonl` | 19 MB | V2 formatting approach — V3 uses tool-calling |
| `data/training/augury_formatting_val.jsonl` | 2.1 MB | V2 validation — superseded |

**Total: ~1.4 GB recoverable**

---

## 🟡 Questionable / Needs Confirmation

| Item | Size | Issue |
|---|---|---|
| `models/localNFchatbot/` | 1.2 GB | Downloaded for eval but architecture is Qwen3.5-4B. Still needed? |
| `models/localNFchatbot-f16.gguf` | 1.2 GB | fp16 version of above |
| `models/localNFchatbot-Q4_K_M.gguf` | 379 MB | Q4 quantized version |
| `models/MiniCPM5-1B/` | ~0 B | Only `.cache/` dir — incomplete download, no model |
| `models/Qwen3.5-4B/.cache/` | 403 MB | Incomplete download artifact — the actual model (2.6 GB GGUF) is at parent level |
| `llama.cpp/` | 971 MB | Full repo clone. Needed locally or HF Jobs for conversion? |
| `weeds_indicators_train.jsonl` (root) | 1.7 MB | Older duplicate — canonical is `data/training/weeds_indicators_merged_train.jsonl` |
| `weeds_indicators_val.jsonl` (root) | 206 KB | Same — older duplicate in root |
| `data/mining/` (13 files) | 280 KB | Source claims — merged into enriched DB. Provenance or archive? |

**Total: ~4.4 GB at stake**

---

## 🟢 Active but Messy

| Item | Size | Recommendation |
|---|---|---|
| **7 markdown files at root** | ~45 KB | Consider `docs/` directory |
| `unified_species_database.json` (root) | 204 KB | Move to `data/` |
| `feedback.jsonl` (root) | 1.1 KB | Fine at root or `data/` |
| `augury-research-pack/` | 3.2 MB | Research briefs — consider `data/research/` |
| `augury-research-output/` | 1.6 MB | Phase 1+2 output — consider `data/research/` |

---

## What to Do

**Quick wins (no decision needed):**
- Archive all intermediate `.jsonl` files in `data/training/` — they're merged into `weeds_indicators_merged_train.jsonl`
- Archive `Weeds V1/`, `augury_merged_fp16/`, `augury.Q4_K_M.gguf` — Pass 1 reference only
- Delete `server.log`, `augury-research-pack.tar.gz` (already extracted)

**Requires your call:**
- `models/localNFchatbot*` (3 files, ~2.8 GB) — keep or go?
- `llama.cpp/` (971 MB) — local clone need or HF Jobs enough?
- `data/mining/` (280 KB) — provenance or archive?
- Root `.md` files → `docs/`?

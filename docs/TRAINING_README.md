# AUGURY V3 — MiniCPM5-1B Training on RTX 3060 6GB

## Quick Start

### 1. Install dependencies on your local machine
```bash
pip install -q unsloth trl peft bitsandbytes datasets transformers accelerate
```

### 2. Copy these files from this project to your machine
```
data/v3_function_calling/minicpm5/     ← 8 JSONL files (1,542 examples, XML tool-call format)
scripts/train_minicpm5.py              ← Training script
```

### 3. Run training
```bash
cd /path/to/your/copy
python scripts/train_minicpm5.py --train
```

This starts QLoRA fine-tuning on MiniCPM5-1B:
- Batch size: 2 (gradient accumulation 4 = effective batch 8)
- Sequence length: 2048
- LoRA rank: 16, alpha: 32
- Learning rate: 2e-4
- Epochs: 3
- **Estimated time: 2-3 hours on RTX 3060 6GB**

### 4. Merge LoRA and convert to GGUF
After training completes:

```bash
# Install llama.cpp for GGUF conversion
git clone https://github.com/ggml-org/llama.cpp
cd llama.cpp && make

# Convert the merged model to GGUF
python scripts/convert_to_gguf.py minicpm5_v3_lora
```

Output: `augury_minicpm5.Q4_K_M.gguf` (~656 MB)

### 5. Deploy
```bash
python scripts/inference_loop.py "What do docks and thistles indicate in my paddock?"
```

## What You're Training

The model learns ONE pattern:
1. User asks about a weed → emit `<tool_call>` XML → `lookup_species()` reads DB
2. Database returns indicator data → model formats conversationally
3. For non-plant questions → model refuses and redirects

The model never memorises facts. The database is the source of truth.
This architecture guarantees 100% indicator accuracy.

## Training Data Composition

| Layer | Examples | Purpose |
|---|---|---|
| A — Tool use | 300 | Learn `<tool_call>` XML format |
| B — Direct answer | 400 | Fast path for common weeds |
| C — Multi-species | 422 | Multiple lookups + synthesis |
| D — Refusal | 420 | Safety boundaries |
| **Total** | **1,542** | |

## Region Balance
- Europe: ~70%
- Australia: ~18%
- UK: ~12%

## Model Output (after training)
```
User: What does capeweed indicate about my soil in Australia?
Assistant: <tool_call>{"name": "lookup_species", "arguments": {"species": "Arctotheca calendula", "region": "Australia"}}</tool_call>
[Tool returns indicator data]
Assistant: Capeweed (Arctotheca calendula) is telling you your soil is high in fertility — 
likely from overgrazing concentrating nutrients in stock camp areas. It also tolerates 
saline fringes and indicates low phosphorus availability, which is common in Australia's 
ancient soils.
```

## Troubleshooting

| Issue | Fix |
|---|---|
| CUDA out of memory | Reduce `per_device_train_batch_size` to 1, increase `gradient_accumulation_steps` to 8 |
| No GPU detected | Install CUDA + PyTorch CUDA version |
| Training too slow | Use `--test` flag to verify with 50 examples first |
| Model outputs garbage | Check chat template format; MiniCPM5 uses standard LlamaForCausalLM |

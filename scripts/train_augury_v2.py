#!/usr/bin/env python3
"""
AUGURY v2 Training Script — Google Colab (T4 GPU, free tier).

Trains Qwen3-0.6B-Instruct with QLoRA on the formatting dataset.
The model learns to present structured soil indicator data as natural,
conversational responses for farmers.

Copy-paste into Colab cells. Run in order.

Training time: ~2-3 hours on free T4 GPU.
Output: LoRA adapter weights (~35MB) + tokenizer.
Post-training: merge + GGUF quantize locally with convert_to_gguf.py.
"""

# ═══════════════════════════════════════════════════════════════
# CELL 1: Install dependencies
# ═══════════════════════════════════════════════════════════════

CELL_1 = """\
!pip install -q unsloth "trl>=0.15.0" peft accelerate bitsandbytes sentencepiece datasets
"""

# ═══════════════════════════════════════════════════════════════
# CELL 2: RESTART RUNTIME (skip this cell on restart)
# ═══════════════════════════════════════════════════════════════

CELL_2 = """\
# ⚠️  Runtime → Restart runtime after Cell 1 completes.
# After restart, skip this cell and go straight to Cell 3.
print("Restart runtime now, then skip to Cell 3.")
"""

# ═══════════════════════════════════════════════════════════════
# CELL 3: Imports + model loading
# ═══════════════════════════════════════════════════════════════

CELL_3 = """\
import json
import torch
from datasets import Dataset
from unsloth import FastLanguageModel, is_bfloat16_supported
from unsloth.chat_templates import get_chat_template

print(f"GPU: {torch.cuda.get_device_name(0)}")
print(f"VRAM: {torch.cuda.get_device_properties(0).total_mem / 1e9:.1f} GB")
print(f"bfloat16 supported: {is_bfloat16_supported()}")

# Load Qwen3-0.6B with 4-bit quantization
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name="unsloth/Qwen3-0.6B-Instruct",
    max_seq_length=2048,
    dtype=None,          # auto-detect
    load_in_4bit=True,
)

# Apply QLoRA
model = FastLanguageModel.get_peft_model(
    model,
    r=16,
    target_modules=[
        "q_proj", "k_proj", "v_proj", "o_proj",
        "gate_proj", "up_proj", "down_proj",
    ],
    lora_alpha=16,
    lora_dropout=0,
    bias="none",
    use_gradient_checkpointing="unsloth",
    random_state=42,
)

# Set chat template
tokenizer = get_chat_template(
    tokenizer,
    chat_template="qwen",
)

print(f"Trainable params: {model.print_trainable_parameters()}")
"""

# ═══════════════════════════════════════════════════════════════
# CELL 4: Load training data (upload files first)
# ═══════════════════════════════════════════════════════════════

CELL_4 = """\
def format_example(example):
    \"\"\"Convert ShareGPT messages to training text.\"\"\"
    return {
        "text": tokenizer.apply_chat_template(
            example["messages"],
            tokenize=False,
            add_generation_prompt=False,
        )
    }

def load_jsonl(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]

print("Loading training data...")
train_raw = load_jsonl("augury_formatting_train.jsonl")
val_raw = load_jsonl("augury_formatting_val.jsonl")

print(f"Train: {len(train_raw)} examples")
print(f"Val:   {len(val_raw)} examples")

# Count by type
refusals = sum(1 for ex in train_raw
               if "soil indicator specialist" in ex["messages"][2]["content"])
multis = sum(1 for ex in train_raw
             if "Species 1:" in ex["messages"][1]["content"])
print(f"  Refusals: {refusals}")
print(f"  Multi-species: {multis}")
print(f"  Single-species: {len(train_raw) - refusals - multis}")

# Build datasets
train_ds = Dataset.from_list([format_example(ex) for ex in train_raw])
val_ds = Dataset.from_list([format_example(ex) for ex in val_raw])

print("Datasets ready.")
"""

# ═══════════════════════════════════════════════════════════════
# CELL 5: Train
# ═══════════════════════════════════════════════════════════════

CELL_5 = """\
from trl import SFTTrainer
from transformers import TrainingArguments

trainer = SFTTrainer(
    model=model,
    tokenizer=tokenizer,
    train_dataset=train_ds,
    eval_dataset=val_ds,
    dataset_text_field="text",
    max_seq_length=2048,
    packing=True,
    args=TrainingArguments(
        # Batch
        per_device_train_batch_size=2,
        gradient_accumulation_steps=4,
        # Epochs
        num_train_epochs=3,
        # Learning rate
        learning_rate=2e-4,
        warmup_steps=50,
        lr_scheduler_type="linear",
        # Precision
        fp16=not is_bfloat16_supported(),
        bf16=is_bfloat16_supported(),
        # Optimizer
        optim="adamw_8bit",
        weight_decay=0.01,
        # Logging
        logging_steps=50,
        eval_steps=200,
        save_steps=500,
        save_total_limit=2,
        # Output
        output_dir="augury_v2_checkpoints",
        report_to="none",
        # Reproducibility
        seed=42,
    ),
)

print("Starting training...")
print(f"Effective batch size: 2 × 4 = {2 * 4}")
print(f"Steps per epoch: ~{len(train_ds) // (2 * 4)}")
print(f"Total steps: ~{3 * len(train_ds) // (2 * 4)}")
print()

trainer.train()

# Save final checkpoint
trainer.save_model("augury_v2_checkpoints/final")
print("Training complete!")
"""

# ═══════════════════════════════════════════════════════════════
# CELL 6: Save LoRA adapter + tokenizer
# ═══════════════════════════════════════════════════════════════

CELL_6 = """\
import os

output_dir = "augury_v2_lora"
os.makedirs(output_dir, exist_ok=True)

model.save_pretrained(output_dir)
tokenizer.save_pretrained(output_dir)

print(f"LoRA adapter saved to: {output_dir}/")
print(f"Files:")
for f in sorted(os.listdir(output_dir)):
    size_mb = os.path.getsize(os.path.join(output_dir, f)) / (1024 * 1024)
    print(f"  {f} ({size_mb:.1f} MB)")

print()
print("╔══════════════════════════════════════════════════════╗")
print("║  NEXT: Download augury_v2_lora/ folder              ║")
print("║  Left sidebar → Files → right-click → Download      ║")
print("║                                                    ║")
print("║  Then locally:                                      ║")
print("║  python scripts/convert_to_gguf.py augury_v2_lora   ║")
print("║  → produces augury.Q4_K_M.gguf                      ║")
print("╚══════════════════════════════════════════════════════╝")
"""

# ═══════════════════════════════════════════════════════════════
# Main: print the cells for copy-paste
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    cells = [
        ("CELL 1: Install dependencies", CELL_1),
        ("CELL 2: Restart runtime", CELL_2),
        ("CELL 3: Load model", CELL_3),
        ("CELL 4: Load data", CELL_4),
        ("CELL 5: Train", CELL_5),
        ("CELL 6: Save adapter", CELL_6),
    ]

    for name, code in cells:
        print(f"# {'='*55}")
        print(f"# {name}")
        print(f"# {'='*55}")
        print(code.strip())
        print()
        print()

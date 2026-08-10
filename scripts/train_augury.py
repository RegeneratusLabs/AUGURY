#!/usr/bin/env python3
"""
AUGURY — Fine-tune Qwen2.5-0.5B-Instruct with QLoRA using Unsloth.

Run this in Google Colab with a T4 GPU (free tier works).
Upload the training data first:
  - weeds_indicators_merged_train.jsonl
  - weeds_indicators_merged_val.jsonl

Expected runtime: ~1-2 hours on T4
Expected cost: $0 (Colab free tier)

STEPS TO RUN IN COLAB:
1. File > Upload notebook session storage: upload these files:
   - weeds_indicators_merged_train.jsonl
   - weeds_indicators_merged_val.jsonl
2. Change runtime to T4 GPU: Runtime > Change runtime type > T4
3. Run all cells (Ctrl+F9)
4. Download the output files when done
"""

import json
import os
import torch

# ── Step 1: Install Unsloth (run as a cell in Colab) ──
# !pip install unsloth
# !pip install --no-deps "xformers<0.0.28" "trl<0.16.0" peft accelerate bitsandbytes

# ── Step 2: Load model ──
from unsloth import FastLanguageModel
from unsloth import is_bfloat16_supported

max_seq_length = 2048
dtype = None  # auto-detect
load_in_4bit = True

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name="unsloth/Qwen2.5-0.5B-Instruct",
    max_seq_length=max_seq_length,
    dtype=dtype,
    load_in_4bit=load_in_4bit,
)

# ── Step 3: Apply LoRA ──
model = FastLanguageModel.get_peft_model(
    model,
    r=16,           # LoRA rank
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

# ── Step 4: Format data for Qwen chat template ──
EOS_TOKEN = tokenizer.eos_token

def format_conversation(example):
    """Convert ShareGPT format to Qwen chat template string."""
    messages = example["messages"]
    text = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=False,
    )
    return {"text": text}

def load_dataset(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]

print("Loading training data...")
train_data = load_dataset("weeds_indicators_merged_train.jsonl")
val_data = load_dataset("weeds_indicators_merged_val.jsonl")
print(f"  Train: {len(train_data)} examples")
print(f"  Val:   {len(val_data)} examples")

# Format for training
train_formatted = [format_conversation(ex) for ex in train_data]
val_formatted = [format_conversation(ex) for ex in val_data]

# ── Step 5: Train ──
from trl import SFTTrainer
from transformers import TrainingArguments
from unsloth import is_bfloat16_supported

trainer = SFTTrainer(
    model=model,
    tokenizer=tokenizer,
    train_dataset=train_formatted,
    dataset_text_field="text",
    max_seq_length=max_seq_length,
    dataset_num_proc=2,
    packing=True,  # packs multiple short examples into one sequence for speed
    args=TrainingArguments(
        per_device_train_batch_size=2,
        gradient_accumulation_steps=4,
        warmup_steps=5,
        num_train_epochs=3,
        learning_rate=2e-4,
        fp16=not is_bfloat16_supported(),
        bf16=is_bfloat16_supported(),
        logging_steps=10,
        optim="adamw_8bit",
        weight_decay=0.01,
        lr_scheduler_type="linear",
        seed=42,
        output_dir="augury_checkpoints",
        report_to="none",
    ),
)

print("\nStarting training...")
trainer_stats = trainer.train()
print(f"Training complete! Stats: {trainer_stats}")

# ── Step 6: Save outputs ──
output_dir = "augury_lora"
model.save_pretrained(output_dir)
tokenizer.save_pretrained(output_dir)
print(f"\nLoRA adapter saved to: {output_dir}/")

# Save training config for reproducibility
config = {
    "base_model": "Qwen2.5-0.5B-Instruct",
    "lora_r": 16,
    "lora_alpha": 16,
    "epochs": 3,
    "learning_rate": 2e-4,
    "train_examples": len(train_data),
    "val_examples": len(val_data),
}
with open(f"{output_dir}/training_config.json", "w") as f:
    json.dump(config, f, indent=2)

print("\n--- NEXT STEPS ---")
print("1. Download the 'augury_lora' folder from Colab's file browser")
print("2. Run convert_to_gguf.py to merge and quantize:")
print("   python scripts/convert_to_gguf.py")
print("3. Deploy augury.Q4_K_M.gguf (~350MB) on phone with llama.cpp")

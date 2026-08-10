#!/usr/bin/env python3
"""
AUGURY V3 — Colab Training for MiniCPM5-1B

Copy the minicpm5/ training data folder to Google Drive, then run this Colab notebook.

Usage:
  1. Upload data/v3_function_calling/minicpm5/ to Google Drive
  2. Open Colab and run this script
  3. LoRA weights saved to Drive and optionally pushed to Hugging Face Hub

Time: ~2-3 hours on free T4 GPU
       ~1 hour on Colab Pro A100
"""

# ═══════════════════════════════════════════════════════════════
# CELL 1: Mount Google Drive and install dependencies
# ═══════════════════════════════════════════════════════════════
CELL_1 = '''
from google.colab import drive
drive.mount("/content/drive")

import os
DRIVE_PATH = "/content/drive/MyDrive/augury_training"
os.makedirs(DRIVE_PATH, exist_ok=True)

# Install dependencies
!pip install -q unsloth trl peft bitsandbytes datasets transformers accelerate
'''

# ═══════════════════════════════════════════════════════════════
# CELL 2: Load training data and model
# ═══════════════════════════════════════════════════════════════
CELL_2 = '''
import json, os
from pathlib import Path

# Load training data from Drive
data_path = os.path.join(DRIVE_PATH, "minicpm5")
train_texts = []
val_texts = []

TRAIN_FILES = ["a_tool_use_train.jsonl", "b_direct_answer_train.jsonl",
               "c_multi_species_train.jsonl", "d_refusal_train.jsonl"]
VAL_FILES = ["a_tool_use_val.jsonl", "b_direct_answer_val.jsonl",
             "c_multi_species_val.jsonl", "d_refusal_val.jsonl"]

for fname in TRAIN_FILES:
    with open(os.path.join(data_path, fname)) as f:
        for line in f:
            row = json.loads(line)
            msgs = row.get("messages", [])
            parts = []
            for msg in msgs:
                role = msg["role"]
                content = msg.get("content", "")
                if not content: continue
                if role == "system": parts.append(content)
                elif role == "user": parts.append(f"User: {content}")
                elif role == "assistant": parts.append(f"Assistant: {content}")
            if parts: train_texts.append({"text": "\n".join(parts)})

for fname in VAL_FILES:
    with open(os.path.join(data_path, fname)) as f:
        for line in f:
            row = json.loads(line)
            msgs = row.get("messages", [])
            parts = []
            for msg in msgs:
                role = msg["role"]
                content = msg.get("content", "")
                if not content: continue
                if role == "system": parts.append(content)
                elif role == "user": parts.append(f"User: {content}")
                elif role == "assistant": parts.append(f"Assistant: {content}")
            if parts: val_texts.append({"text": "\n".join(parts)})

print(f"Train: {len(train_texts)}, Val: {len(val_texts)}")

# Save to temp JSON files
with open("augury_train.json", "w") as f: json.dump(train_texts, f)
with open("augury_val.json", "w") as f: json.dump(val_texts, f)
'''

# ═══════════════════════════════════════════════════════════════
# CELL 3: QLoRA Training with Unsloth
# ═══════════════════════════════════════════════════════════════
CELL_3 = '''
from unsloth import FastLanguageModel
from datasets import load_dataset
from trl import SFTTrainer, SFTConfig
from peft import LoraConfig

# Load MiniCPM5-1B in 4-bit
model, tokenizer = FastLanguageModel.from_pretrained(
    "openbmb/MiniCPM5-1B",
    max_seq_length=2048,
    load_in_4bit=True,
    device_map="auto",
)

# Add LoRA adapters
model = FastLanguageModel.get_peft_model(
    model,
    r=16,
    lora_alpha=32,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                    "gate_proj", "up_proj", "down_proj"],
    lora_dropout=0.05,
    bias="none",
    use_gradient_checkpointing="unsloth",
    random_state=42,
)

# Load datasets
dataset = load_dataset("json", data_files="augury_train.json", split="train")
val_dataset = load_dataset("json", data_files="augury_val.json", split="train")

# Train
output_dir = os.path.join(DRIVE_PATH, "minicpm5_v3_lora")
trainer = SFTTrainer(
    model=model,
    tokenizer=tokenizer,
    train_dataset=dataset,
    eval_dataset=val_dataset,
    dataset_text_field="text",
    args=SFTConfig(
        output_dir=output_dir,
        per_device_train_batch_size=2,
        gradient_accumulation_steps=4,
        warmup_steps=10,
        num_train_epochs=3,
        learning_rate=2e-4,
        optim="paged_adamw_8bit",
        logging_steps=10,
        eval_strategy="steps",
        eval_steps=50,
        save_strategy="steps",
        save_steps=100,
        max_grad_norm=0.3,
        report_to="none",
        push_to_hub=False,
    ),
)

# Train
trainer.train()
trainer.save_model(output_dir)
print(f"Model saved to {output_dir}")

# Save tokenizer
tokenizer.save_pretrained(output_dir)
'''

# ═══════════════════════════════════════════════════════════════
# CELL 4 (optional): Push to Hugging Face Hub
# ═══════════════════════════════════════════════════════════════
CELL_4 = '''
from huggingface_hub import notebook_login
notebook_login()

# Upload LoRA adapter to HF Hub
from huggingface_hub import HfApi
api = HfApi()
api.upload_folder(
    folder_id="YOUR_USERNAME/augury-minicpm5-v3-lora",
    folder_path=os.path.join(DRIVE_PATH, "minicpm5_v3_lora"),
    repo_type="model",
)
print("Uploaded to Hugging Face Hub!")
'''

if __name__ == "__main__":
    print("AUGURY V3 Colab Training — MiniCPM5-1B")
    print("=" * 50)
    print("\nINSTRUCTIONS:")
    print("1. Copy data/v3_function_calling/minicpm5/ to Google Drive as 'minicpm5'")
    print("2. Open Colab (colab.research.google.com)")
    print("3. Create a new notebook and paste the cells below")
    print("\n=== CELL 1: Mount Drive & Install ===")
    print(CELL_1)
    print("\n=== CELL 2: Load Data ===")
    print(CELL_2)
    print("\n=== CELL 3: Train ===")
    print(CELL_3)
    print("\n=== CELL 4 (optional): Push to HF Hub ===")
    print(CELL_4)
    print("\n" + "=" * 50)
    print(f"Training data size: ", end="")
    with open("data/v3_function_calling/minicpm5/a_tool_use_train.jsonl") as f:
        print(f"{sum(1 for _ in f)} examples in a_tool_use_train.jsonl")

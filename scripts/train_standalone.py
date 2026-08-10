#!/usr/bin/env python3
"""
AUGURY Standalone Model — fine-tune MiniCPM5-1B on weed-indicator Q&A.

One simple thing: the model answers farmer questions about what weeds
indicate about soil. No tool calls, no external DB at runtime.

Data: data/training/standalone_train.jsonl + standalone_val.jsonl
Usage: python scripts/train_standalone.py [--test]
"""

import json
import os
import sys
from pathlib import Path

random_seed = 42

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
BASE_MODEL = "openbmb/MiniCPM5-1B"
OUTPUT_DIR = PROJECT_DIR / "standalone_model_lora"
DATA_DIR = PROJECT_DIR / "data" / "training"
TRAIN_FILE = DATA_DIR / "standalone_train.jsonl"
VAL_FILE = DATA_DIR / "standalone_val.jsonl"


def main():
    import random
    random.seed(random_seed)

    print("╔══════════════════════════════════════════════╗")
    print("║  AUGURY Standalone — MiniCPM5-1B QLoRA      ║")
    print("╚══════════════════════════════════════════════╝")

    # Load tokenizer
    print("\nLoading tokenizer...")
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, trust_remote_code=True)

    # Load data with chat template
    def load(path):
        texts = []
        with open(path) as f:
            for line in f:
                row = json.loads(line)
                msgs = row.get("messages", [])
                texts.append({"text": tokenizer.apply_chat_template(msgs, tokenize=False)})
        return texts

    train_texts = load(TRAIN_FILE)
    val_texts = load(VAL_FILE)
    print(f"  Train: {len(train_texts)}, Val: {len(val_texts)}")

    if "--test" in sys.argv:
        train_texts = train_texts[:30]
        val_texts = val_texts[:8]
        print(f"  🧪 Test mode: {len(train_texts)} train, {len(val_texts)} val")

    # Write temp files
    train_path = PROJECT_DIR / "tmp_standalone_train.json"
    val_path = PROJECT_DIR / "tmp_standalone_val.json"
    with open(train_path, "w") as f:
        json.dump(train_texts, f)
    with open(val_path, "w") as f:
        json.dump(val_texts, f)

    # dill / Python 3.14 compat (same fix as train_minicpm5.py)
    try:
        import dill as _augury_dill
        _orig = _augury_dill.Pickler._batch_setitems
        def _patched(self, items, obj=None):
            return _orig(self, items, obj)
        _augury_dill.Pickler._batch_setitems = _patched
        import datasets.utils._dill as _du
        _orig_du = _du.Pickler._batch_setitems
        def _patched_du(self, items, obj=None):
            return _orig_du(self, items)
        _du.Pickler._batch_setitems = _patched_du
    except Exception:
        pass

    from datasets import Dataset as _Dataset
    with open(train_path) as f:
        dataset = _Dataset.from_list(json.load(f))
    with open(val_path) as f:
        val_dataset = _Dataset.from_list(json.load(f))

    # Unsloth QLoRA
    print("\nStarting training with Unsloth...")
    import torch
    from unsloth import FastLanguageModel
    from trl import SFTTrainer, SFTConfig

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=BASE_MODEL,
        max_seq_length=2048,
        dtype=torch.bfloat16,
        load_in_4bit=True,
        full_finetuning=False,
    )
    model = FastLanguageModel.get_peft_model(
        model,
        r=16,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
        lora_alpha=32,
        lora_dropout=0.05,
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=42,
    )

    trainer = SFTTrainer(
        model=model,
        args=SFTConfig(
            output_dir=str(OUTPUT_DIR),
            dataset_text_field="text",
            per_device_train_batch_size=2,
            gradient_accumulation_steps=4,
            warmup_ratio=0.03,
            lr_scheduler_type="cosine",
            num_train_epochs=4,
            learning_rate=2e-4,
            bf16=True,
            max_length=2048,
            packing=False,
            logging_steps=10,
            save_steps=100,
            report_to="none",
            push_to_hub=False,
            seed=42,
        ),
        train_dataset=dataset,
        eval_dataset=val_dataset,
        processing_class=tokenizer,
    )
    trainer.train()
    trainer.model.save_pretrained(str(OUTPUT_DIR))
    print(f"\n✅ Done! Model saved to {OUTPUT_DIR}")
    print(f"Next: python scripts/convert_to_gguf.py {OUTPUT_DIR.name}")


if __name__ == "__main__":
    main()

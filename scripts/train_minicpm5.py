#!/usr/bin/env python3
"""
AUGURY V3 Training — MiniCPM5-1B on RTX 3060 6GB (QLoRA).

Trains MiniCPM5-1B with QLoRA on the V3 tool-calling dataset.
Teaches the model to emit <tool_call> XML to query lookup_species(),
read the deterministic DB response, and synthesise conversational output.

Training time on RTX 3060 6GB: ~2-3 hours
Output: LoRA adapter weights (~35 MB)

Usage on your local machine:
    uv run scripts/train_minicpm5.py

Requires: unsloth, trl, peft, bitsandbytes, datasets, transformers
"""

import json, os, sys, random
from pathlib import Path

random.seed(42)
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent

# ── Config ──────────────────────────────────────────────────

BASE_MODEL = "openbmb/MiniCPM5-1B"  # or local path to downloaded model
OUTPUT_DIR = PROJECT_DIR / "minicpm5_v3_lora"
DATASET_DIR = PROJECT_DIR / "data" / "v3_function_calling" / "minicpm5"

TRAIN_FILES = [
    "a_tool_use_train.jsonl",
    "b_direct_answer_train.jsonl",
    "c_multi_species_train.jsonl",
    "d_refusal_train.jsonl",
]
VAL_FILES = [
    "a_tool_use_val.jsonl",
    "b_direct_answer_val.jsonl",
    "c_multi_species_val.jsonl",
    "d_refusal_val.jsonl",
]

SYSTEM_PROMPT = (
    "You are AUGURY, a soil health assistant that interprets weeds as soil indicators. "
    "When asked about a plant species, use the lookup_species tool to get indicator data. "
    "Output tool calls as: <tool_call>{'name': 'lookup_species', 'arguments': {'species': '...', 'region': '...'}}</tool_call>"
)


def load_jsonl_data(file_list, tokenizer):
    """Load JSONL files using the official MiniCPM5 chat template."""
    texts = []
    for fname in file_list:
        path = DATASET_DIR / fname
        if not path.exists():
            print(f"  WARNING: {path} not found, skipping")
            continue
        with open(path) as f:
            for line in f:
                row = json.loads(line)
                msgs = row.get("messages", [])
                text = tokenizer.apply_chat_template(msgs, tokenize=False)
                texts.append({"text": text})
    return texts


def main():
    print("╔══════════════════════════════════════════╗")
    print("║   AUGURY V3 — MiniCPM5-1B QLoRA         ║")
    print("║   Target: RTX 3060 6GB VRAM              ║")
    print("╚══════════════════════════════════════════╝")
    
    # Load tokenizer
    print("\nLoading tokenizer...")
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # Load and combine all training files
    print("\nLoading training data using official chat template...")
    train_texts = load_jsonl_data(TRAIN_FILES, tokenizer)
    val_texts = load_jsonl_data(VAL_FILES, tokenizer)
    print(f"  Train: {len(train_texts)} examples")
    print(f"  Val:   {len(val_texts)} examples")
    
    # For local testing, use a subset
    if "--test" in sys.argv:
        train_texts = train_texts[:50]
        val_texts = val_texts[:10]
        print(f"  🧪 Test mode: {len(train_texts)} train, {len(val_texts)} val")
    
    # Write temporary dataset files for Unsloth
    train_path = PROJECT_DIR / "tmp_minicpm5_train.json"
    val_path = PROJECT_DIR / "tmp_minicpm5_val.json"
    
    with open(train_path, "w") as f:
        json.dump(train_texts, f)
    with open(val_path, "w") as f:
        json.dump(val_texts, f)
    
    # ── Run training if --train flag is set ──
    if "--train" in sys.argv:
        print("\nStarting training with Unsloth...\n")
        try:
            import json as _json
            from datasets import Dataset as _Dataset
            # Python 3.14 + dill 0.4.0 compat. Two broken call sites:
            #  1. datasets/utils/_dill.py:83 calls dill.Pickler._batch_setitems(self, items)
            #     but dill's version needs (self, items, obj) — obj only used for error notes.
            #  2. stdlib pickle.save_dict calls self._batch_setitems(items, obj) with 3 args.
            # Make obj optional on dill's method AND accept it on the vendored wrapper.
            try:
                import dill as _augury_dill
                _orig_dill_bs = _augury_dill.Pickler._batch_setitems
                def _dill_bs_patch(self, items, obj=None):
                    return _orig_dill_bs(self, items, obj)
                _augury_dill.Pickler._batch_setitems = _dill_bs_patch

                import datasets.utils._dill as _augury_du
                _orig_du_bs = _augury_du.Pickler._batch_setitems
                def _du_bs_patch(self, items, obj=None):
                    # Preserve the vendored sorting behaviour, pass obj through
                    return _orig_du_bs(self, items)
                _augury_du.Pickler._batch_setitems = _du_bs_patch
            except Exception:
                pass  # dill already compatible
            from unsloth import FastLanguageModel
            from trl import SFTTrainer, SFTConfig
            from peft import LoraConfig
            
            import torch
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
            
            with open(train_path) as _f:
                dataset = _Dataset.from_list(_json.load(_f))
            with open(val_path) as _f:
                val_dataset = _Dataset.from_list(_json.load(_f))
            
            trainer = SFTTrainer(
                model=model,
                args=SFTConfig(
                    output_dir=str(OUTPUT_DIR),
                    dataset_text_field="text",
                    per_device_train_batch_size=2,
                    gradient_accumulation_steps=4,
                    warmup_ratio=0.03,
                    lr_scheduler_type="cosine",
                    num_train_epochs=3,
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
            print(f"\n✅ Training complete! Model saved to {OUTPUT_DIR}")
            print(f"Next: python scripts/convert_to_gguf.py {OUTPUT_DIR}")
            
        except ImportError as e:
            print(f"\n❌ Missing dependency: {e}")
            print("Install with: pip install -q unsloth trl peft bitsandbytes datasets transformers accelerate")
            sys.exit(1)
    else:
        print(f"\nTo train, run: uv run scripts/train_minicpm5.py --train")

if __name__ == "__main__":
    main()

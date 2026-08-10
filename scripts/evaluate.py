#!/usr/bin/env python3
"""
Evaluate trained AUGURY model on validation set.

Usage:
  python scripts/evaluate.py --model augury_merged_fp16  # HF model
  python scripts/evaluate.py --model augury_lora --base Qwen/Qwen2.5-0.5B-Instruct  # LoRA only
  python scripts/evaluate.py --model augury.Q4_K_M.gguf  # GGUF
"""

import json
import re
import sys
import argparse
from pathlib import Path


def load_val_data():
    """Load validation data."""
    project_dir = Path(__file__).resolve().parent.parent
    val_path = project_dir / "data" / "training" / "weeds_indicators_merged_val.jsonl"
    if not val_path.exists():
        print(f"ERROR: {val_path} not found")
        sys.exit(1)
    with open(val_path) as f:
        return [json.loads(line) for line in f if line.strip()]


def extract_species_key(question):
    """Extract species name from question."""
    m = re.search(r'does (.+?) \(', question)
    if m:
        return m.group(1)
    for p in [
        r'seeing a lot of (.+?) in my paddock',
        r'conditions does (.+?) indicate',
        r'mean when (.+?) is dominant',
        r'about (.+?) as a soil',
        r'Why is (.+?) growing',
        r'imbalanced if I have (.+)',
        r'Is (.+?) a sign',
    ]:
        m = re.search(p, question)
        if m:
            return m.group(1).strip()
    return question[:50]


def parse_contract(text):
    """Parse AUGURY v1 contract format into dict."""
    result = {}
    for line in text.strip().split("\n"):
        if ":" in line and not line.startswith("Source:"):
            key, _, value = line.partition(": ")
            result[key.strip()] = value.strip().lower()
    return result


def evaluate_hf(model_path, val_data, base_model=None):
    """Evaluate a HuggingFace model."""
    from transformers import AutoModelForCausalLM, AutoTokenizer
    import torch

    if base_model:
        from peft import PeftModel
        model = AutoModelForCausalLM.from_pretrained(
            base_model,
            torch_dtype=torch.float16,
            device_map="auto",
        )
        model = PeftModel.from_pretrained(model, model_path)
    else:
        model = AutoModelForCausalLM.from_pretrained(
            model_path,
            torch_dtype=torch.float16,
            device_map="auto",
        )

    tokenizer = AutoTokenizer.from_pretrained(
        model_path if not base_model else base_model
    )

    results = []
    n = min(100, len(val_data))  # evaluate up to 100 examples

    print(f"Evaluating {n} examples...")
    for i, ex in enumerate(val_data[:n]):
        messages = ex["messages"][:2]  # system + user
        prompt = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = tokenizer(prompt, return_tensors="pt").to(model.device)

        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=256,
                temperature=0.3,
                do_sample=False,
                pad_token_id=tokenizer.eos_token_id,
            )

        response = tokenizer.decode(
            outputs[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True
        ).strip()

        expected = ex["messages"][2]["content"]
        got = parse_contract(response)
        want = parse_contract(expected)

        # Compare key fields
        species = extract_species_key(ex["messages"][1]["content"])
        matches = {}
        for key in ["Moisture", "Soil pH", "Fertility"]:
            want_val = want.get(key, "")
            got_val = got.get(key, "")
            # Simple overlap: check if key concepts appear
            if want_val and got_val:
                # Count word overlap
                want_words = set(want_val.split())
                got_words = set(got_val.split())
                if want_words and got_words:
                    overlap = len(want_words & got_words) / max(len(want_words), 1)
                    matches[key] = overlap
                else:
                    matches[key] = 0.0
            elif not want_val:
                matches[key] = 1.0  # no expected value = can't fail
            else:
                matches[key] = 0.0

        avg_match = sum(matches.values()) / max(len(matches), 1)
        results.append({
            "species": species,
            "matches": matches,
            "avg_match": avg_match,
            "response": response,
        })

        if (i + 1) % 20 == 0:
            print(f"  {i+1}/{n}...")

    # Report
    print("\n" + "=" * 50)
    print("EVALUATION RESULTS")
    print("=" * 50)

    avg_overall = sum(r["avg_match"] for r in results) / max(len(results), 1)
    print(f"\nOverall word overlap score: {avg_overall:.1%}")

    print(f"\nPer-field scores:")
    for key in ["Moisture", "Soil pH", "Fertility"]:
        scores = [r["matches"].get(key, 0) for r in results]
        avg = sum(scores) / max(len(scores), 1)
        print(f"  {key:15s}: {avg:.1%}")

    # Show worst examples
    results.sort(key=lambda r: r["avg_match"])
    print(f"\nWorst 3 predictions:")
    for r in results[:3]:
        print(f"\n  Species: {r['species']}")
        print(f"  Response: {r['response'][:200]}...")

    return results


def evaluate_gguf(model_path, val_data):
    """Evaluate a GGUF model via llama.cpp CLI."""
    import subprocess
    import tempfile

    n = min(50, len(val_data))
    print(f"Evaluating {n} examples...")
    results = []

    for i, ex in enumerate(val_data[:n]):
        question = ex["messages"][1]["content"]
        expected = ex["messages"][2]["content"]
        species = extract_species_key(question)

        system_msg = ex["messages"][0]["content"]
        prompt = f"<|im_start|>system\n{system_msg}<|im_end|>\n<|im_start|>user\n{question}<|im_end|>\n<|im_start|>assistant\n"

        cmd = [
            "llama-cli",
            "-m", model_path,
            "-p", prompt,
            "-n", "200",
            "--temp", "0.3",
            "--no-display-prompt",
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            response = result.stdout.strip()
        except Exception as e:
            response = f"ERROR: {e}"

        got = parse_contract(response)
        want = parse_contract(expected)

        matches = {}
        for key in ["Moisture", "Soil pH", "Fertility"]:
            want_val = want.get(key, "")
            got_val = got.get(key, "")
            if want_val and got_val:
                want_words = set(want_val.split())
                got_words = set(got_val.split())
                if want_words and got_words:
                    overlap = len(want_words & got_words) / max(len(want_words), 1)
                    matches[key] = overlap
                else:
                    matches[key] = 0.0
            elif not want_val:
                matches[key] = 1.0
            else:
                matches[key] = 0.0

        avg_match = sum(matches.values()) / max(len(matches), 1)
        results.append({
            "species": species,
            "matches": matches,
            "avg_match": avg_match,
            "response": response,
        })

    avg_overall = sum(r["avg_match"] for r in results) / max(len(results), 1)
    print(f"\nWord overlap score: {avg_overall:.1%}")
    return results


def main():
    parser = argparse.ArgumentParser(description="Evaluate AUGURY model")
    parser.add_argument("--model", required=True, help="Model path (HF dir, LoRA dir, or .gguf file)")
    parser.add_argument("--base", default=None, help="Base model for LoRA-only evaluation")
    args = parser.parse_args()

    val_data = load_val_data()

    if args.model.endswith(".gguf"):
        evaluate_gguf(args.model, val_data)
    else:
        evaluate_hf(args.model, val_data, args.base)


if __name__ == "__main__":
    main()

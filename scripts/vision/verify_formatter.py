#!/usr/bin/env python3
"""AUGURY — verify_formatter.py (post-training smoke test)

Pulls the trained formatter (merged fp16) from HF Hub and checks it speaks
AUGURY's language: given species + structured indicators, it should produce
the conversational soil story — stating the given facts, never inventing.

Usage:
  .venv-mcpmv46/bin/python scripts/vision/verify_formatter.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from huggingface_hub import snapshot_download
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

REPO = "RegeneratusLabs/augury-1b"
LOCAL = "/data/Documents/.hf-stage/augury-1b"  # disk, not tmpfs
MODEL_DIR = f"{LOCAL}/merged-fp16"

SYSTEM = ("You are AUGURY, a soil health assistant specializing in weeds and plants as "
          "soil indicators. You receive structured soil indicator data and present it in "
          "clear, conversational language suitable for farmers and land managers. Always "
          "include both common and scientific names when available. Never invent or "
          "modify indicator data — only present what is provided. If no species match is "
          "found, explain honestly. If asked about anything other than plants and soil "
          "indicators, politely refuse and redirect. You do NOT provide management "
          "recommendations, herbicide advice, or agronomic prescriptions.")

TESTS = [
    ("AU weed",
     "Species: Capeweed (Arctotheca calendula)\nRegion: Australia\n\n"
     "Indicators:\n- Moisture: dry to moderately dry, well-drained soils\n"
     "- Soil pH: neutral to slightly acidic\n- Fertility: moderate, tolerates low fertility\n"
     "What does this tell me about my soil?"),
    ("EU weed",
     "Species: Dandelion (Taraxacum officinale)\nRegion: Europe\n\n"
     "Indicators:\n- Moisture: fresh, moist soils of average dampness\n"
     "- Soil pH: neutral. pH 6.0–7.5\n- Fertility: fertile, nutrient-rich. High nitrogen\n"
     "What does this tell me about my soil?"),
    ("Refusal",
     "How do I kill thistles in my paddock?"),
]


def main() -> int:
    if not Path(LOCAL).exists():
        print(f"downloading merged model from {REPO} ...")
        snapshot_download(REPO, local_dir=LOCAL, repo_type="model",
                          allow_patterns=["merged-fp16/*"])
    print("loading ...")
    # LLaMA-Factory's export writes a minimal tokenizer_config.json that breaks
    # transformers 5.7 pairing; the tokenizer files are byte-identical to the
    # base model's, so load the tokenizer from the base snapshot instead.
    tok = AutoTokenizer.from_pretrained("openbmb/MiniCPM5-1B")
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_DIR, torch_dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    model = model.to(dev).eval()

    ok = 0
    for name, user in TESTS:
        msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
        enc = tok.apply_chat_template(msgs, tokenize=True, add_generation_prompt=True,
                                      return_dict=True, return_tensors="pt").to(dev)
        with torch.no_grad():
            out = model.generate(**enc, max_new_tokens=200, do_sample=False)
        text = tok.decode(out[0][enc["input_ids"].shape[1]:], skip_special_tokens=True).strip()
        print(f"\n===== {name} =====")
        print(text)
        if name != "Refusal":
            for key in ("Moisture", "pH", "Fertility"):
                if key.lower() in text.lower():
                    ok += 1
    print(f"\nfact keys echoed: {ok}/6 (mechanical; human review needed for style)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

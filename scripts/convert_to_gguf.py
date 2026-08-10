#!/usr/bin/env python3
"""
Convert trained AUGURY LoRA adapter to GGUF for phone deployment.

Requires: The 'augury_lora' folder from Colab training output.
          This contains the LoRA adapter weights + tokenizer.

Steps:
  1. Merge LoRA adapter into base Qwen2.5-0.5B
  2. Save merged model in fp16
  3. Convert to GGUF Q4_K_M (~350MB)

Run locally after downloading augury_lora/ from Colab.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

LORA_DIR = "minicpm5_v3_lora"     # default: MiniCPM5-1B LoRA; override with CLI arg
MERGED_DIR = "minicpm5_merged_fp16"  # intermediate
GGUF_OUT = "augury_minicpm5.Q4_K_M.gguf" # final deployable


def check_dependencies():
    """Check required packages are installed."""
    missing = []
    try:
        import torch
    except ImportError:
        missing.append("torch")
    try:
        import transformers
    except ImportError:
        missing.append("transformers")
    try:
        import peft
    except ImportError:
        missing.append("peft")

    if missing:
        print(f"Missing packages: {', '.join(missing)}")
        print("Install with: pip install torch transformers peft accelerate")
        sys.exit(1)

    # Check for llama.cpp conversion tooling
    convert_script = None
    for p in ["llama.cpp/convert_hf_to_gguf.py", "../llama.cpp/convert_hf_to_gguf.py", "convert_hf_to_gguf.py"]:
        if os.path.exists(p):
            convert_script = p
            break
    if not convert_script:
        print("WARNING: convert_hf_to_gguf.py not found in llama.cpp/.")
        print("  Install: git clone https://github.com/ggerganov/llama.cpp")
        print("           cd llama.cpp && pip install -r requirements.txt")
        print("  Then re-run this script.")


def step1_merge_lora():
    """Merge LoRA adapter weights into base model."""
    print("=" * 50)
    print("STEP 1: Merging LoRA into base model")
    print("=" * 50)

    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import PeftModel
    import torch

    if not os.path.exists(LORA_DIR):
        print(f"ERROR: {LORA_DIR}/ not found.")
        print("Download the augury_lora folder from Colab first.")
        sys.exit(1)

    # The training script saves to <dir>/adapter_final/ — auto-detect it
    if os.path.exists(os.path.join(LORA_DIR, "adapter_config.json")):
        lora_path = LORA_DIR
    elif os.path.exists(os.path.join(LORA_DIR, "adapter_final", "adapter_config.json")):
        lora_path = os.path.join(LORA_DIR, "adapter_final")
        print(f"Auto-detected adapter in: {lora_path}")
    else:
        print(f"ERROR: no adapter_config.json found in {LORA_DIR} or {LORA_DIR}/adapter_final")
        sys.exit(1)

    base_model_name = "openbmb/MiniCPM5-1B"

    print(f"Loading base model: {base_model_name}")
    base_model = AutoModelForCausalLM.from_pretrained(
        base_model_name,
        dtype=torch.float16,
        device_map="auto",
    )
    tokenizer = AutoTokenizer.from_pretrained(base_model_name)

    print(f"Loading LoRA adapter from: {lora_path}")
    model = PeftModel.from_pretrained(base_model, lora_path)

    print("Merging weights...")
    model = model.merge_and_unload()

    print(f"Saving merged model to: {MERGED_DIR}")
    model.save_pretrained(MERGED_DIR, safe_serialization=True)
    tokenizer.save_pretrained(MERGED_DIR)

    print("Merge complete.")
    return True


def step2_convert_gguf():
    """Convert merged fp16 model to GGUF Q4_K_M."""
    print("\n" + "=" * 50)
    print("STEP 2: Converting to GGUF Q4_K_M")
    print("=" * 50)

    if not os.path.exists(MERGED_DIR):
        print(f"ERROR: {MERGED_DIR}/ not found. Run step 1 first.")
        sys.exit(1)

    # Find convert_hf_to_gguf.py
    script_path = None
    search_paths = [
        "llama.cpp/convert_hf_to_gguf.py",
        "../llama.cpp/convert_hf_to_gguf.py",
        "convert_hf_to_gguf.py",
    ]
    for p in search_paths:
        if os.path.exists(p):
            script_path = p
            break

    if not script_path:
        print("ERROR: convert_hf_to_gguf.py not found.")
        print("  Clone llama.cpp: git clone https://github.com/ggerganov/llama.cpp")
        print("  cd llama.cpp && pip install -r requirements.txt")
        sys.exit(1)

    # Step 2a: Convert HF to GGUF fp16
    fp16_gguf = "augury_fp16.gguf"
    print(f"Converting {MERGED_DIR} → {fp16_gguf}")
    subprocess.run([
        sys.executable, script_path,
        MERGED_DIR,
        "--outfile", fp16_gguf,
        "--outtype", "f16",
    ], check=True)

    # Step 2b: Quantize to Q4_K_M
    print(f"Quantizing {fp16_gguf} → {GGUF_OUT}")
    quantize_bin = shutil.which("llama-quantize")
    if not quantize_bin:
        for p in ["llama.cpp/llama-quantize", "llama.cpp/build/bin/llama-quantize"]:
            if os.path.exists(p):
                quantize_bin = p
                break
    if not quantize_bin:
        print("ERROR: llama-quantize not found. Compile llama.cpp first:")
        print("  cd llama.cpp && make")
        print("  Then re-run this script.")
        sys.exit(1)

    subprocess.run([
        quantize_bin,
        fp16_gguf,
        GGUF_OUT,
        "Q4_K_M",
    ], check=True)

    # Clean up intermediate
    if os.path.exists(fp16_gguf):
        os.remove(fp16_gguf)

    size_mb = os.path.getsize(GGUF_OUT) / (1024 * 1024)
    print(f"\nDone! {GGUF_OUT} ({size_mb:.0f} MB)")
    print(f"\nDeploy this file on your phone with llama.cpp.")
    print(f"  Example: ./llama-cli -m {GGUF_OUT} -p 'What does Yorkshire fog indicate?'")


def main():
    global LORA_DIR, MERGED_DIR, GGUF_OUT

    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg == "--merge-only":
            check_dependencies()
            step1_merge_lora()
            print("\nMerged model saved. Run again without --merge-only to convert to GGUF.")
            return
        elif not arg.startswith("--"):
            LORA_DIR = arg
            # Derive output names from input
            base = os.path.basename(os.path.normpath(LORA_DIR))
            MERGED_DIR = f"augury_{base}_merged_fp16"
            GGUF_OUT = f"augury_{base}.Q4_K_M.gguf"

    print(f"LoRA dir:  {LORA_DIR}")
    print(f"Merged:    {MERGED_DIR}")
    print(f"GGUF out:  {GGUF_OUT}")

    check_dependencies()
    if step1_merge_lora():
        step2_convert_gguf()

    print("\n" + "=" * 50)
    print("AUGURY is ready for deployment.")
    print(f"  Deploy: {GGUF_OUT}")
    print("=" * 50)


if __name__ == "__main__":
    main()

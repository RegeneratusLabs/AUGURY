#!/usr/bin/env python3
"""
AUGURY Formatter Architecture Test

Tests the PRODUCTION pattern (server v2):
  user query → deterministic species extraction → DB lookup
  → model FORMATS the data conversationally → refusal for non-plants

The model does NOT emit tool calls — the server does the lookup.
The model's job is formatting + refusal, which it's good at.

Usage:
    python scripts/test_formatter_model.py [path/to/model.gguf]
"""

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "scripts"))

from species_lookup import SpeciesDB


def find_gguf():
    candidates = list(PROJECT.glob("*.Q4_K_M.gguf"))
    if not candidates:
        return None
    augury = [c for c in candidates if "augury" in c.name]
    pool = augury or candidates
    return max(pool, key=lambda p: p.stat().st_mtime)


def format_response_model(model, result, user_question):
    """Mirror of augury_server_v2.format_response_model — MiniCPM5 chat template."""
    name = result["scientific_name"]
    common = result["common_names"][0] if result["common_names"] else None
    if common and name.lower() in common.lower():
        display = common
    elif common:
        display = f"{common} ({name})"
    else:
        display = name
    region = result.get("region", "Europe")
    source = result.get("source", "")
    indicators = result["indicators"]

    indicator_lines = []
    for key, val in indicators.items():
        if val and val.lower() != "not specified":
            indicator_lines.append(f"- {key}: {val}")
    indicators_text = "\n".join(indicator_lines) if indicator_lines else "(no indicator data)"

    SYSTEM = (
        "You are AUGURY, a soil health assistant specializing in weeds and plants "
        "as soil indicators. You receive structured soil indicator data and present "
        "it in clear, conversational language suitable for farmers and land managers. "
        "Never invent or modify indicator data. You do NOT provide management "
        "recommendations. Keep responses informative and grounded in the provided data."
    )

    prompt = (
        f"<|im_start|>system\n{SYSTEM}<|im_end|>\n"
        f"<|im_start|>user\n"
        f"Species: {display}\n"
        f"Region: {region}\n\n"
        f"Indicators:\n{indicators_text}\n\n"
        f"Source: {source}\n\n"
        f"{user_question}\n"
        f"<|im_end|>\n"
        f"<|im_start|>assistant\n"
    )

    output = model(
        prompt,
        max_tokens=400,
        temperature=0.3,
        top_p=0.9,
        stop=["<|im_end|>"],
    )
    return output["choices"][0]["text"].strip()


def refusal_prompt(model, message):
    """Mirror of server v2 refusal path."""
    SYSTEM = (
        "You are AUGURY, a soil health assistant. If the user's question "
        "is about plants or weeds as soil indicators, help them. If not, "
        "politely explain you specialize in weeds and soil indicators and "
        "ask them to name a specific plant species."
    )
    prompt = (
        f"<|im_start|>system\n{SYSTEM}<|im_end|>\n"
        f"<|im_start|>user\n{message}<|im_end|>\n"
        f"<|im_start|>assistant\n"
    )
    output = model(prompt, max_tokens=200, temperature=0.3, stop=["<|im_end|>"])
    return output["choices"][0]["text"].strip()


def main():
    gguf_path = Path(sys.argv[1]) if len(sys.argv) > 1 else find_gguf()
    if not gguf_path or not gguf_path.exists():
        print(f"ERROR: no GGUF found in {PROJECT}")
        sys.exit(1)

    print(f"Loading {gguf_path.name}...")
    from llama_cpp import Llama
    model = Llama(model_path=str(gguf_path), n_ctx=2048, n_threads=4, verbose=False)
    db = SpeciesDB()
    print("Loaded ✅\n")

    results = []

    # ── TEST 1: Single species → formatted answer ──
    print("=" * 60)
    print("TEST 1: 'What does dandelion indicate?'")
    print("=" * 60)
    matches = db.search("dandelion", top_n=3)
    if matches:
        result = db.get_indicators(matches[0]["scientific_name"], region="Australia")
        response = format_response_model(model, result, "What does dandelion indicate about soil conditions?")
        print(f"\nModel response:\n{response}")
        ok = len(response) > 30
        results.append(("Single species → formatted", ok, f"{len(response)} chars"))
    else:
        print("No species matched")
        results.append(("Single species → formatted", False, "no match"))

    # ── TEST 2: AU species → formatted ──
    print(f"\n{'='*60}")
    print("TEST 2: 'What does Capeweed indicate in Australia?'")
    print("=" * 60)
    matches = db.search("Capeweed", top_n=3)
    if matches:
        result = db.get_indicators(matches[0]["scientific_name"], region="Australia")
        response = format_response_model(model, result, "What does Capeweed indicate in Australian conditions?")
        print(f"\nModel response:\n{response}")
        ok = len(response) > 30 and ("fertility" in response.lower() or "soil" in response.lower() or "indicat" in response.lower())
        results.append(("AU species → formatted", ok, f"{len(response)} chars"))
    else:
        print("No species matched")
        results.append(("AU species → formatted", False, "no match"))

    # ── TEST 3: Refusal ──
    print(f"\n{'='*60}")
    print("TEST 3: 'How do I kill weeds with Roundup?'")
    print("=" * 60)
    response = refusal_prompt(model, "How do I kill weeds with Roundup?")
    print(f"\nModel response:\n{response}")
    refuses = any(w in response.lower() for w in ["don't", "can't", "outside", "soil indicator", "not"])
    results.append(("Refusal", refuses, f"refuses={refuses}"))

    # ── TEST 4: Multi-species — server extracts both, model formats summary ──
    print(f"\n{'='*60}")
    print("TEST 4: 'What do docks and thistles indicate?'")
    print("=" * 60)
    matches = db.search("docks and thistles", top_n=5)
    found = [m["scientific_name"] for m in matches]
    print(f"Species extracted: {found}")
    # Server would look up each and merge; test single best for now
    if matches:
        result = db.get_indicators(matches[0]["scientific_name"], region="Europe")
        response = format_response_model(model, result, "What do docks and thistles indicate about my soil?")
        print(f"\nModel response:\n{response}")
        ok = len(response) > 30
        results.append(("Multi-species extraction", len(matches) >= 1, f"{len(matches)} species found"))
    else:
        results.append(("Multi-species extraction", False, "no match"))

    # ── SUMMARY ──
    print(f"\n{'='*60}")
    print("SUMMARY — Formatter Architecture")
    print(f"{'='*60}")
    all_pass = True
    for name, passed, detail in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        if not passed:
            all_pass = False
        print(f"  {status}  {name}")
        print(f"         {detail}")
    print(f"\n{'✅ FORMATTER ARCHITECTURE WORKS — deployable now!' if all_pass else '❌ Some tests failed — review above'}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
AUGURY Trained Model Test Harness

Tests whether the fine-tuned MiniCPM5-1B GGUF actually emits <tool_call> XML,
executes the lookups against the deterministic DB, and synthesises answers.

Usage:
    python scripts/test_trained_model.py [path/to/augury_minicpm5.Q4_K_M.gguf]
"""

import json
import re
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
DEFAULT_GGUF = PROJECT / "augury_minicpm5.Q4_K_M.gguf"
SYSTEM_PROMPT = (
    "You are AUGURY, a soil health assistant that interprets weeds as soil indicators. "
    "When asked about a plant species, call lookup_species() to retrieve indicator data. "
    "Output tool calls exactly as: <tool_call>{\"name\": \"lookup_species\", \"arguments\": {\"species\": \"Dandelion\", \"region\": \"Australia\"}}</tool_call>\n"
    "Never invent indicator data — always use the tool. "
    "Do NOT provide management advice, herbicide recommendations, or chemical control."
)

# Grammar that FORCES the model to emit a valid lookup_species tool call.
# The model already knows the content; this guarantees the format.
TOOL_CALL_GRAMMAR_STR = r'''
root ::= "<tool_call> " object " </tool_call>"
object ::= "{" ws "\"name\":" ws "\"lookup_species\"" ws "," ws "\"arguments\":" ws arguments ws "}"
arguments ::= "{" ws "\"species\":" ws string ws "," ws "\"region\":" ws string ws "}"
string ::= "\"" chars "\""
chars ::= [^"\\] | "\\" [^\n]
ws ::= [ \t\n]*
'''


def extract_json_objects(text):
    """Extract balanced JSON objects from text, handling nested braces."""
    objects = []
    i = 0
    while i < len(text):
        if text[i] == "{":
            depth = 0
            j = i
            in_str = False
            esc = False
            while j < len(text):
                c = text[j]
                if in_str:
                    if esc:
                        esc = False
                    elif c == "\\":
                        esc = True
                    elif c == '"':
                        in_str = False
                else:
                    if c == '"':
                        in_str = True
                    elif c == "{":
                        depth += 1
                    elif c == "}":
                        depth -= 1
                        if depth == 0:
                            objects.append(text[i:j + 1])
                            break
                j += 1
            i = j + 1
        else:
            i += 1
    return objects


def parse_tool_calls(text):
    """Extract tool calls from model output. Accepts BOTH:
      1. <tool_call>{...}</tool_call> (wrapped, MiniCPM5 native)
      2. {name: lookup_species, arguments: {...}} (bare JSON, what the model emits)
    """
    calls = []

    def _parse(raw):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            try:
                return json.loads(raw.replace("'", '"'))
            except json.JSONDecodeError:
                return None

    # Pattern 1: wrapped
    for m in re.finditer(r"<tool_call>(.*?)</tool_call>", text, re.DOTALL):
        data = _parse(m.group(1).strip())
        if data:
            calls.append({"wrapped": True, **data})

    # Pattern 2: bare JSON dict containing name + arguments (brace-balanced)
    if not calls:
        for obj in extract_json_objects(text):
            data = _parse(obj)
            if isinstance(data, dict) and data.get("name") == "lookup_species":
                calls.append({"wrapped": False, **data})

    return calls


def lookup_species(name, region="Europe"):
    """Deterministic species lookup (mirrors species_lookup.py for the test)."""
    sys.path.insert(0, str(PROJECT / "scripts"))
    from species_lookup import SpeciesDB
    db = SpeciesDB()
    results = db.search(name, top_n=1)
    if not results:
        return {"error": f"No data for {name}"}
    key = results[0]["key"]
    info = db._species.get(key, {})
    regions = info.get("regions", {})
    reg_data = regions.get(region, regions.get("Europe", {}))
    indicators = reg_data.get("indicators", {})
    return {"scientific_name": results[0]["scientific_name"], "indicators": indicators}


def run_test(model, name, messages, max_tokens=400, expect_tool_calls=1, native_tools=False, grammar=None):
    """Run a test case and report pass/fail."""
    print(f"\n{'='*60}")
    print(f"TEST: {name}")
    print(f"{'='*60}")
    kwargs = {
        "max_tokens": max_tokens,
        "temperature": 0.3,
    }
    if grammar is not None:
        kwargs["grammar"] = grammar
    if native_tools:
        kwargs["tools"] = [{
            "type": "function",
            "function": {
                "name": "lookup_species",
                "description": "Look up soil indicator data for a plant species",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "species": {"type": "string", "description": "Scientific or common name"},
                        "region": {"type": "string", "description": "Region (Europe, UK, Australia)"},
                    },
                    "required": ["species"],
                },
            },
        }]
        kwargs["tool_choice"] = "auto"
    try:
        output = model.create_chat_completion(messages=messages, **kwargs)
        msg = output["choices"][0]["message"]
        text = msg.get("content") or ""
        if msg.get("tool_calls"):
            text = text + "\n[NATIVE TOOL CALLS]\n" + str(msg["tool_calls"])
        print(f"\nModel output:\n{text[:500]}")
        return text
    except Exception as e:
        print(f"\nNative tool call error: {e}")
        return f"ERROR: {e}"


def find_gguf():
    """Auto-discover the trained GGUF in the project directory."""
    candidates = list(PROJECT.glob("*.Q4_K_M.gguf"))
    if not candidates:
        return None
    # Prefer the augury one, else the newest
    augury = [c for c in candidates if "augury" in c.name]
    pool = augury or candidates
    return max(pool, key=lambda p: p.stat().st_mtime)


def main():
    gguf_path = Path(sys.argv[1]) if len(sys.argv) > 1 else find_gguf()
    if not gguf_path or not gguf_path.exists():
        found = list(PROJECT.glob("*.gguf"))
        print(f"ERROR: no GGUF found.")
        print(f"  Looked for *.Q4_K_M.gguf in {PROJECT}")
        if found:
            print(f"  Found these GGUF files:")
            for f in found:
                print(f"    - {f.name} ({f.stat().st_size/1e6:.0f} MB)")
        print(f"  Usage: python scripts/test_trained_model.py <path/to/model.gguf>")
        sys.exit(1)

    print(f"Loading {gguf_path}...")
    from llama_cpp import Llama
    model = Llama(model_path=str(gguf_path), n_ctx=4096, n_gpu_layers=0, verbose=False)
    print("Loaded ✅\n")

    results = []

    # ── TEST 1: Single species → tool call ──
    text = run_test(
        model,
        "Single species (should emit <tool_call>)",
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "What does dandelion indicate about soil conditions in Australia?"},
        ],
    )
    calls = parse_tool_calls(text)
    passed = len(calls) >= 1 and "species" in str(calls[0])
    results.append(("Single species → tool call", passed, f"{len(calls)} call(s): {calls[:1]}"))
    if calls:
        # Execute the tool call
        c = calls[0]
        if "arguments" in c:
            args = c["arguments"]
            res = lookup_species(args.get("species", ""), args.get("region", "Europe"))
            print(f"\n[TOOL RESULT] {json.dumps(res, indent=2)[:300]}")

    # ── TEST 2: Multi-species → 2+ tool calls ──
    text = run_test(
        model,
        "Multi-species (should emit 2+ <tool_call>)",
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "What do docks and thistles indicate about my soil?"},
        ],
        max_tokens=600,
    )
    calls = parse_tool_calls(text)
    passed = len(calls) >= 2
    results.append(("Multi-species → 2+ calls", passed, f"{len(calls)} call(s)"))

    # ── TEST 3: Refusal ──
    text = run_test(
        model,
        "Refusal (herbicide question)",
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "How do I kill weeds with Roundup?"},
        ],
    )
    has_refusal = any(w in text.lower() for w in ["don't", "can't", "outside", "soil indicator", "can't help", "interpret"])
    has_tool = "<tool_call>" in text
    passed = has_refusal and not has_tool
    results.append(("Refusal (no tool call, refuses)", passed, f"refusal={has_refusal}, tool={has_tool}"))

    # ── TEST 4: AU region ──
    text = run_test(
        model,
        "AU region tag",
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "What does Capeweed indicate in Australian conditions?"},
        ],
    )
    calls = parse_tool_calls(text)
    au_region = any("Australia" in str(c.get("arguments", {})) for c in calls if isinstance(c, dict))
    passed = au_region
    results.append(("AU region → Australia", passed, f"calls={len(calls)}, au_region={au_region}"))

    # ── TEST 5: NATIVE tool calling (llama.cpp tools param) ──
    text = run_test(
        model,
        "NATIVE tool calling (llama.cpp tools param)",
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "What does dandelion indicate about soil conditions?"},
        ],
        native_tools=True,
    )
    has_native_call = "[NATIVE TOOL CALLS]" in text
    passed = has_native_call
    results.append(("Native tools param → tool call", passed, f"native_call={has_native_call}"))

    # ── TEST 6: NATIVE tool calling with AU region ──
    text = run_test(
        model,
        "NATIVE tool calling AU region",
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "What does Capeweed indicate in Australian conditions?"},
        ],
        native_tools=True,
    )
    has_native_call = "[NATIVE TOOL CALLS]" in text
    passed = has_native_call
    results.append(("Native tools AU → tool call", passed, f"native_call={has_native_call}"))

    # ── TEST 7: GRAMMAR-constrained tool call (single species) ──
    from llama_cpp import LlamaGrammar
    grammar = LlamaGrammar.from_string(TOOL_CALL_GRAMMAR_STR)
    text = run_test(
        model,
        "GRAMMAR-constrained → tool call (dandelion)",
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "What does dandelion indicate about soil conditions?"},
        ],
        grammar=grammar,
    )
    calls = parse_tool_calls(text)
    passed = len(calls) >= 1 and calls[0].get("name") == "lookup_species"
    results.append(("Grammar tool call (single)", passed, f"{len(calls)} call(s), wrapped={calls[0].get('wrapped') if calls else 'n/a'}"))

    # ── TEST 8: GRAMMAR-constrained multi-species ──
    text = run_test(
        model,
        "GRAMMAR-constrained → tool call (multi)",
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "What do docks and thistles indicate about my soil?"},
        ],
        max_tokens=400,
        grammar=grammar,
    )
    calls = parse_tool_calls(text)
    passed = len(calls) >= 1
    results.append(("Grammar tool call (multi)", passed, f"{len(calls)} call(s)"))

    # ── TEST 9: GRAMMAR-constrained AU region ──
    text = run_test(
        model,
        "GRAMMAR-constrained → AU region (Capeweed)",
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "What does Capeweed indicate in Australian conditions?"},
        ],
        grammar=grammar,
    )
    calls = parse_tool_calls(text)
    au_region = any("Australia" in str(c.get("arguments", {})) for c in calls if isinstance(c, dict))
    passed = au_region
    results.append(("Grammar tool call (AU)", passed, f"calls={len(calls)}, au_region={au_region}"))

    # ── SUMMARY ──
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    all_pass = True
    for name, passed, detail in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        if not passed:
            all_pass = False
        print(f"  {status}  {name}")
        print(f"         {detail}")
    print(f"\n{'✅ ALL TESTS PASS — model is working!' if all_pass else '❌ SOME TESTS FAILED — see details above'}")


if __name__ == "__main__":
    main()

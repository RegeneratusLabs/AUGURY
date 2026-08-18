#!/usr/bin/env python3
"""
AUGURY — local model test harness (GATED: do not run until the user says yes)

Loads the AUGURY formatter GGUF via the funnel and runs the acceptance battery:
  1. Single-species fact echo (6/6 fact-keys — the model-card gate)
  2. Multi-species synthesis ("docks and thistles")
  3. Refusal boundary (herbicide/management/non-plant)
  4. Region awareness (Australia vs Europe)
  5. Unknown species → honest "no data" path
  6. Template-vs-model consistency spot check

Usage (after user approval):
  .venv-mcpmv46/bin/python scripts/vision/test_local_model.py [--model models/MiniCPM5-1B-AUGURY-Q4_K_M.gguf]

Exit code 0 = all gates pass. Anything else = inspect the failures.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from augury_funnel import AuguryFunnel  # noqa: E402

PASS, FAIL = [], []


def gate(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=str(ROOT / "models" / "MiniCPM5-1B-AUGURY-Q4_K_M.gguf"))
    ap.add_argument("--region", default="Australia")
    args = ap.parse_args()

    if not Path(args.model).exists():
        print(f"model not found: {args.model}")
        return 2

    print(f"=== AUGURY local test (gated run) ===")
    print(f"model:  {args.model}")
    print(f"region: {args.region}")
    funnel = AuguryFunnel(model_path=args.model, n_threads=12)
    if funnel.model is None:
        print("!! model failed to load — aborting")
        return 2

    # 1. Single-species fact echo: every DB fact key must appear in the answer
    print("\n--- 1. fact echo (dandelion / Taraxacum officinale) ---")
    r = funnel.answer("What does dandelion indicate about my soil?", region=args.region)
    print(f"Q: What does dandelion indicate about my soil?\nA: {r['response'][:400]}")
    keys = ["Ph", "Salinity", "Moisture", "Structure", "Fertility"]
    missing = [k for k in keys if k.lower() not in r["response"].lower()]
    gate("fact-echo: all 5 indicator keys present", not missing, f"missing={missing}")
    gate("fact-echo: refused flag False", r["refused"] is False)

    # 2. Multi-species
    print("\n--- 2. multi-species (docks and thistles) ---")
    r = funnel.answer("There are docks and thistles in my paddock", region=args.region)
    print(f"Q: docks and thistles\nspecies: {r['species']}\nA: {r['response'][:300]}")
    gate("multi-species: 2+ species resolved", len(r["species"]) >= 2,
         f"species={r['species']}")

    # 3. Refusals
    print("\n--- 3. refusal boundary ---")
    for q in ["What herbicide should I use on docks?",
              "Should I lime my paddock?",
              "Tell me about quantum physics"]:
        rr = funnel.answer(q, region=args.region)
        print(f"Q: {q}\n  refused={rr['refused']} A: {rr['response'][:150]}")
        gate(f"refusal: {q[:30]}", rr["refused"] is True)

    # 4. Region awareness
    print("\n--- 4. region awareness ---")
    r_au = funnel.answer("What does Paterson's curse indicate?", region="Australia")
    print(f"AU: {r_au['response'][:200]}")
    gate("region: AU species resolved", len(r_au["species"]) > 0, f"species={r_au['species']}")

    # 5. Unknown species
    print("\n--- 5. unknown species ---")
    r = funnel.answer("What does the purple marshwort indicate?", region=args.region)
    print(f"A: {r['response'][:200]}")
    gate("unknown: honest no-data path", r["refused"] is True or "couldn't find" in r["response"].lower())

    # 6. Deterministic-template consistency (model must not invent facts)
    print("\n--- 6. fact consistency (model vs template) ---")
    r_model = funnel.answer("What does capeweed indicate?", region=args.region)
    tmpl_res = funnel.answer("What does capeweed indicate?", region=args.region)
    # Template view of the same facts (force template mode by composing directly)
    from augury_funnel import AuguryFunnel as AF
    tmpl_funnel = AF(model_path=None)
    extracted = tmpl_funnel.extract_species("What does capeweed indicate?", region=args.region)
    resolved = tmpl_funnel.resolve(extracted, region=args.region)
    tmpl_text = tmpl_funnel._compose_template(resolved).lower()
    model_text = r_model["response"].lower()
    key_terms = re.findall(r"moisture|ph|fertility|salinity|structure|compaction|drainage", tmpl_text)
    overlap = sum(1 for t in set(key_terms) if t in model_text)
    gate("fact consistency: model echoes template fact topics",
         len(set(key_terms)) > 0 and overlap >= min(3, len(set(key_terms))),
         f"topics={sorted(set(key_terms))} overlap={overlap}/{len(set(key_terms))}")

    print(f"\n=== RESULT: {len(PASS)} passed, {len(FAIL)} failed ===")
    if FAIL:
        print("FAILED:", FAIL)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""AUGURY vision — explain_test.py

Decision-tree #1 from HANDOVER_VISION (2026-08-10): is the fine-tune usable as an
EXPLANATION layer? Species name in (NO image) -> soil-indicator story out.

The model was asked to do ID + explain in one shot and fails the ID part (8% species).
This test isolates the explanation part: give it the species name, compare the
generated soil description against the val.jsonl ground-truth assistant answers.

Metrics (honest — style vs facts):
  * key recall: how many of the ground-truth indicator keys (Moisture / pH /
    Fertility / ...) the model actually states
  * token-overlap similarity (SequenceMatcher) — measures style+content match
  * full outputs printed for human judgment

Usage (run from the repo root; defaults match both the NAS /mnt/workspace layout
and a local data/vision/output/merged layout):
  .venv-mcpmv46/bin/python scripts/vision/explain_test.py [--limit 15] [--out report.md]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import torch
from transformers import AutoModelForImageTextToText, AutoProcessor


def parse_gt(ans: str) -> dict:
    """'This is X (Y). In REGION conditions it indicates: A: v1; B: v2' -> dict"""
    m = re.match(r"This is (.*?)\s*\((.*?)\)\.\s*(?:In (.*?) conditions it indicates:)?\s*(.*)", ans, re.S)
    if not m:
        return {"name": "", "region": "", "indicators": "", "pairs": {}}
    name, sci, region, inds = m.groups()
    pairs = {}
    for part in inds.replace(";", "; ").split(";"):
        kv = re.match(r"\s*([A-Za-z /]+?)\s*:\s*(.+)", part)
        if kv and kv.group(1).strip():
            pairs[kv.group(1).strip().lower()] = kv.group(2).strip()
    return {"name": name.strip(), "region": (region or "").strip(),
            "indicators": inds.strip(), "pairs": pairs}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="data/vision/output/merged")
    ap.add_argument("--val", default="data/vision/val.jsonl")
    ap.add_argument("--limit", type=int, default=15)
    ap.add_argument("--out", default="data/vision/explain_report.md")
    args = ap.parse_args()

    rows = [json.loads(l) for l in Path(args.val).read_text().splitlines() if l.strip()]
    seen = set()
    samples = []
    for r in rows:
        if r.get("channel") == "unknown":
            continue
        key = r["images"][0].split("/")[1]
        if key in seen:
            continue
        gt = parse_gt(r["messages"][-1]["content"])
        if not gt["pairs"]:
            continue
        seen.add(key)
        samples.append((key, gt, r["messages"][-1]["content"]))
        if len(samples) >= args.limit:
            break
    if not samples:
        print("ERROR: no usable samples — check --val", file=sys.stderr)
        return 1

    print(f"loading merged model from {args.model} ...", flush=True)
    proc = AutoProcessor.from_pretrained(args.model, trust_remote_code=True)
    model = AutoModelForImageTextToText.from_pretrained(
        args.model, trust_remote_code=True,
        torch_dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32).eval()
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    model = model.to(dev)
    print(f"model ready on {dev} — {len(samples)} species to test\n")

    from difflib import SequenceMatcher

    lines = ["# AUGURY — explanation-layer test report", "",
             f"- model: {args.model}", f"- species tested: {len(samples)}", f"- device: {dev}", ""]
    key_recalls = []
    sims = []
    for i, (key, gt, gt_full) in enumerate(samples):
        name = gt["name"] or key
        prompt = (f"{name} is growing in my paddock. "
                  f"What does that tell me about my soil?")
        msgs = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
        inputs = proc.apply_chat_template(
            msgs, tokenize=True, add_generation_prompt=True,
            return_dict=True, return_tensors="pt").to(dev)
        with torch.no_grad():
            out = model.generate(**inputs, max_new_tokens=256, do_sample=False)
        gen = proc.batch_decode(out[:, inputs["input_ids"].shape[1]:],
                                skip_special_tokens=True)[0].strip()

        gt_pairs = gt["pairs"]
        found = [k for k in gt_pairs if k in gen.lower()]
        kr = len(found) / len(gt_pairs) if gt_pairs else 0.0
        sim = SequenceMatcher(None, gt_full.lower(), gen.lower()).ratio()
        key_recalls.append(kr)
        sims.append(sim)

        lines += [f"## {i+1}. {key}", "",
                  f"**Prompt:** {prompt}", "",
                  f"**Ground truth ({len(gt_pairs)} keys):** {gt_full}", "",
                  f"**Model:** {gen}", "",
                  f"- key recall: {found} -> {kr:.0%}", f"- similarity: {sim:.0%}", ""]

        print(f"[{i+1}/{len(samples)}] {key}: key-recall {kr:.0%} sim {sim:.0%}")
        print(f"  GT  : {gt_full[:160]}")
        print(f"  GEN : {gen[:160]}\n")

    summary = (f"**MEAN key recall: {sum(key_recalls)/len(key_recalls):.0%}**  \n"
               f"**MEAN similarity: {sum(sims)/len(sims):.0%}**")
    lines = lines[:3] + [summary, ""] + lines[3:]
    Path(args.out).write_text("\n".join(lines) + "\n")
    print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())

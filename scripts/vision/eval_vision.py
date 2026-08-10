#!/usr/bin/env python3
"""AUGURY vision — eval_vision.py

Evaluates the fine-tuned (or base) MiniCPM-V 4.6 on the vision holdout split.

Metrics (guard rail 12 — per-species, not just top-1):
  * per-species top-1 accuracy
  * macro / micro top-1 over the evaluated label set
  * confusion matrix (same-genus look-alikes surface here)
  * JSON-format adherence rate (does the model emit the {"species": [...]} contract?)
  * mean / p95 latency per image

Engine: transformers (merged fp16 model, venv .venv-mcpmv46). The val split is
data/vision/val.jsonl produced by build_llamafactory_dataset.py.

Usage:
  .venv-mcpmv46/bin/python scripts/vision/eval_vision.py \
      --model data/vision/output/augury-v4_6-merged \
      [--val data/vision/val.jsonl] [--limit 100] [--out data/vision/eval_report.md]
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys
import time
from pathlib import Path

import torch
from PIL import Image
from transformers import AutoModelForImageTextToText, AutoProcessor

PROMPT = ("Identify the plant species in this photo. Respond with ONLY a JSON object "
          'of the form {"species": ["<scientific name or common name>"], '
          '"confidence": [0.0-1.0]}. If you cannot identify it, respond {"species": [], '
          '"confidence": []}. No prose, no markdown.')

JSON_RE = re.compile(r'\{[^{}]*"species"\s*:\s*\[[^\]]*\][^{}]*\}')


def parse_species(output: str):
    m = JSON_RE.search(output)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        return [str(s).strip().lower() for s in data.get("species", [])]
    except Exception:
        return None


def norm_name(name: str) -> str:
    toks = re.sub(r"[^a-z\s]", " ", name.lower()).split()
    return " ".join(toks[:2]) if len(toks) >= 2 else ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--val", default="data/vision/val.jsonl")
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--out", default="data/vision/eval_report.md")
    args = ap.parse_args()

    rows = [json.loads(l) for l in Path(args.val).read_text().splitlines() if l.strip()][: args.limit]
    if not rows:
        print("ERROR: empty val split — run build_llamafactory_dataset.py first", file=sys.stderr)
        return 1
    val_root = Path(args.val).resolve().parent

    print(f"loading model {args.model} ...")
    t0 = time.time()
    processor = AutoProcessor.from_pretrained(args.model, trust_remote_code=True)
    model = AutoModelForImageTextToText.from_pretrained(
        args.model, torch_dtype=torch.bfloat16, trust_remote_code=True).eval()
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    model = model.to(dev)
    print(f"model ready in {time.time()-t0:.0f}s (device={dev})")

    # expected species label per row: from the assistant answer (first species in answer)
    expected = []
    for r in rows:
        ans = r["messages"][-1]["content"].lower()
        m = re.search(r"this is ([a-z]+ [a-z]+)", ans)
        expected.append(m.group(1) if m else norm_name(ans))

    per_species = collections.defaultdict(lambda: {"n": 0, "correct": 0})
    conf = collections.Counter()
    json_ok = 0
    lat = []
    with torch.inference_mode():
        for r, exp in zip(rows, expected):
            img_path = r["images"][0]
            image = Image.open(val_root / img_path if not os.path.isabs(img_path) else img_path).convert("RGB")
            messages = [
                {"role": "user", "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": PROMPT},
                ]}
            ]
            inputs = processor.apply_chat_template(
                messages, tokenize=True, add_generation_prompt=True, return_dict=True,
                return_tensors="pt", downsample_mode="4x").to(dev)
            t1 = time.time()
            out = model.generate(**inputs, downsample_mode="4x", max_new_tokens=96)
            lat.append(time.time() - t1)
            text = processor.batch_decode(out[:, inputs["input_ids"].shape[1]:],
                                          skip_special_tokens=True)[0]
            preds = parse_species(text)
            if preds is None:
                pred = None
            else:
                pred = norm_name(preds[0]) if preds else None
                json_ok += 1
            per_species[exp]["n"] += 1
            per_species[exp]["correct"] += 1 if pred and pred == exp else 0
            conf[(exp, pred or "<none>")] += 1

    macro = sum(v["correct"] / v["n"] for v in per_species.values()) / len(per_species)
    micro = sum(v["correct"] for v in per_species.values()) / sum(v["n"] for v in per_species.values())
    adherence = json_ok / len(rows)
    lat_sorted = sorted(lat)
    p95 = lat_sorted[int(len(lat_sorted) * 0.95) - 1]

    report = [f"# AUGURY Vision Eval — {Path(args.model).name}",
              f"- rows evaluated: {len(rows)} (species in eval set: {len(per_species)})",
              f"- macro top-1: {macro:.3f}", f"- micro top-1: {micro:.3f}",
              f"- JSON adherence: {adherence:.3f}",
              f"- latency mean {sum(lat)/len(lat):.2f}s / p95 {p95:.2f}s (device {dev})",
              "", "## Per-species top-1", ""]
    for sp in sorted(per_species):
        v = per_species[sp]
        report.append(f"- {sp}: {v['correct']}/{v['n']} ({v['correct']/v['n']:.2f})")
    report += ["", "## Confusion matrix (top pairs)", ""]
    for (exp, pred), n in conf.most_common(25):
        report.append(f"- expected={exp} predicted={pred}: {n}")
    Path(args.out).write_text("\n".join(report))
    print("\n".join(report[:12]))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

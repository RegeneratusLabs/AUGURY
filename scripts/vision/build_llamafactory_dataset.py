#!/usr/bin/env python3
"""AUGURY vision — build_llamafactory_dataset.py

Assembles the LLaMA-Factory training dataset from the acquired images + the
species database. Guard rails: DB is the source of truth (assistant turns are
auto-generated from database-merged.json, never hand-written); region-aware;
refusal/unknown rows from the images_unknown layer.

Outputs (all under data/vision/):
  train.jsonl / val.jsonl     LLaMA-Factory sharegpt format:
                              {"messages": [user(<image>+prompt), assistant(answer)],
                               "images": ["/abs/path.jpg"], "source_file": "augury",
                               "channel": "inaturalist|deepweeds|gbif|unknown"}
  dataset_info.json           registration for LLaMA-Factory (dataset_dir: data/vision)
  dataset_stats.md            counts, split, sources, license histogram

Assistant answer format:
  "This is {Common} ({Sci}). In {region} it indicates: {Indicators}. "
  Unknown: refusal text (no indicators).

Usage:
  .venv-mcpmv46/bin/python scripts/vision/build_llamafactory_dataset.py \
      [--cap 30] [--cap-deepweeds 60] [--val-frac 0.1]
"""
from __future__ import annotations

import argparse
import collections
import json
import random
import re
import sys
from pathlib import Path

USER_TEMPLATES = [
    "<image>\nWhat is this plant and what does it indicate about the soil?",
    "<image>\nIdentify this species and what it tells us about soil conditions.",
    "<image>\nWhat soil conditions does this plant point to?",
    "<image>\nI found this on my place — what's it indicating about the soil?",
]
REFUSAL = ("I'm not confident enough to identify this plant — it may not be one of the "
           "species I know. I can't provide soil indicators for it.")


def render_indicators(species: dict) -> tuple:
    """Pick the most relevant region (AU first) and render its indicators."""
    regions = species.get("regions", [])
    if not regions:
        return "", ""
    best = next((r for r in regions if r["region"].lower() == "australia"), regions[0])
    ind = best["indicators"] or {}
    parts = [f"{k}: {v}" for k, v in ind.items() if v]
    region_txt = best["region"]
    return region_txt, "; ".join(parts)


def answer_for(species: dict) -> str:
    common = species.get("common_names") or []
    common = next((c for c in common if c.lower().strip() != species["scientific_name"].lower().strip()),
                  species["scientific_name"])
    sci = species["scientific_name"].strip()
    sci = sci[0].upper() + sci[1:] if sci and sci[0].islower() else sci
    region_txt, inds = render_indicators(species)
    if not inds:
        return f"This is {common} ({sci}). No indicator data is available for it."
    return (f"This is {common} ({sci}). In {region_txt} conditions it "
            f"indicates: {inds}.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", default="data/vision/images")
    ap.add_argument("--unknown", default="data/vision/images_unknown")
    ap.add_argument("--species-list", default="data/vision/species_list.json")
    ap.add_argument("--out", default="data/vision")
    ap.add_argument("--cap", type=int, default=30)
    ap.add_argument("--cap-deepweeds", type=int, default=60)
    ap.add_argument("--val-frac", type=float, default=0.1)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    images_dir = Path(args.images)
    unk_dir = Path(args.unknown)
    out_dir = Path(args.out)
    species = {s["key"]: s for s in json.loads(Path(args.species_list).read_text())}

    train_rows, val_rows = [], []
    stats_species = collections.Counter()
    stats_imgs = 0
    license_hist = collections.Counter()

    # ---- known species images ----
    for sp_dir in sorted(images_dir.iterdir()):
        if not sp_dir.is_dir():
            continue
        key = sp_dir.name
        s = species.get(key)
        if not s:
            continue
        jpgs = sorted(sp_dir.glob("*.jpg"))
        # DeepWeeds images (dw_ prefix) get a higher cap; sidecar license lookup
        dw = [p for p in jpgs if p.name.startswith("dw_")]
        others = [p for p in jpgs if not p.name.startswith("dw_")]
        cap = args.cap_deepweeds if dw else args.cap
        chosen = dw[:cap] + others[:cap]
        if not chosen:
            continue
        ans = answer_for(s)
        stats_species[key] = len(chosen)
        stats_imgs += len(chosen)
        for p in chosen:
            # license from sidecar if present
            sidecar = sp_dir / "sources.jsonl"
            lic = "unknown"
            if sidecar.exists():
                for ln in sidecar.read_text().splitlines():
                    try:
                        e = json.loads(ln)
                        if e.get("file") == p.name:
                            lic = e.get("license", "unknown")
                            break
                    except Exception:
                        pass
            license_hist[lic] += 1
            channel = "deepweeds" if p.name.startswith("dw_") else "inaturalist"
            rel = p.relative_to(out_dir) if p.is_relative_to(out_dir) else p.resolve()
            row = {
                "messages": [
                    {"role": "user", "content": rng.choice(USER_TEMPLATES)},
                    {"role": "assistant", "content": ans},
                ],
                "images": [str(rel)],
                "source_file": "augury",
                "channel": channel,
            }
            (train_rows if rng.random() >= args.val_frac else val_rows).append(row)

    # ---- unknown/refusal layer ----
    unk_rows = []
    for d in sorted(unk_dir.iterdir()):
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.jpg"))[: args.cap]:
            rel = p.relative_to(out_dir) if p.is_relative_to(out_dir) else p.resolve()
            unk_rows.append({
                "messages": [
                    {"role": "user", "content": rng.choice(USER_TEMPLATES)},
                    {"role": "assistant", "content": REFUSAL},
                ],
                "images": [str(rel)],
                "source_file": "augury",
                "channel": "unknown",
            })
    rng.shuffle(unk_rows)
    n_unk = len(unk_rows)
    split = int(n_unk * (1 - args.val_frac))
    train_rows.extend(unk_rows[:split])
    val_rows.extend(unk_rows[split:])

    rng.shuffle(train_rows)
    rng.shuffle(val_rows)

    Path(out_dir, "train.jsonl").write_text("\n".join(json.dumps(r) for r in train_rows) + "\n")
    Path(out_dir, "val.jsonl").write_text("\n".join(json.dumps(r) for r in val_rows) + "\n")

    dataset_info = {
        "augury_vision_train": {
            "file_name": "train.jsonl", "formatting": "sharegpt",
            "columns": {"messages": "messages", "images": "images"},
            "tags": {"role_tag": "role", "content_tag": "content",
                     "user_tag": "user", "assistant_tag": "assistant"},
        },
        "augury_vision_val": {
            "file_name": "val.jsonl", "formatting": "sharegpt",
            "columns": {"messages": "messages", "images": "images"},
            "tags": {"role_tag": "role", "content_tag": "content",
                     "user_tag": "user", "assistant_tag": "assistant"},
        },
    }
    Path(out_dir, "dataset_info.json").write_text(json.dumps(dataset_info, indent=2))

    stats = [
        "# AUGURY vision dataset — stats",
        "",
        f"- train rows: {len(train_rows)} | val rows: {len(val_rows)}",
        f"- known-species rows: {sum(1 for r in train_rows + val_rows if r['channel'] != 'unknown')}",
        f"- unknown/refusal rows: {n_unk}",
        f"- species with images in dataset: {len(stats_species)}",
        f"- total images (post-cap): {stats_imgs}",
        "",
        "## License histogram",
        "",
    ]
    for lic, n in license_hist.most_common():
        stats.append(f"- {lic}: {n}")
    stats += ["", "## Top species by image count", ""]
    for k, n in stats_species.most_common(15):
        stats.append(f"- {k}: {n}")
    Path(out_dir, "dataset_stats.md").write_text("\n".join(stats) + "\n")

    print(f"train={len(train_rows)} val={len(val_rows)} species_with_images={len(stats_species)} "
          f"unknown_rows={n_unk}")
    print(f"wrote {out_dir/'train.jsonl'}, {out_dir/'val.jsonl'}, dataset_info.json, dataset_stats.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())

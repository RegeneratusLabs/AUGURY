#!/usr/bin/env python3
"""AUGURY — build_au_benchmark.py

Builds a fixed-seed, stratified AU retrieval benchmark from the local gallery.

Design notes
------------
* Per species: hold out Q query images; the remaining images form that species'
  gallery so every species stays reachable (at least 1 gallery image).
* Q = 5 for species with >= 30 images, else max(1, n // 5) — keeps small
  species (8-11 images) represented without emptying their gallery.
* Deterministic: `--seed` fixes the shuffle, so the benchmark is reproducible
  and can be frozen for the final headline number.
* Queries are EXCLUDED from the gallery by `bench.py` at scoring time, so a
  query can never match itself.

Output: <out>/au_split.json
  {
    "seed": int, "scoring": "au_baseline_v1",
    "species": {key: {"gallery": [rel paths], "queries": [rel paths]}},
    "counts": {...}
  }

Usage:
  .venv-mcpmv46/bin/python scripts/vision/build_au_benchmark.py \
      [--images data/vision/images] [--out data/vision] [--seed 20260818]
"""
from __future__ import annotations

import argparse
import collections
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

BIG_SPECIES_QUERIES = 5      # species with >= QUERY_FULL_MIN images
QUERY_FULL_MIN = 30
SMALL_FRACTION = 5           # small species: n // 5 queries, at least 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", default=str(ROOT / "data" / "vision" / "images"))
    ap.add_argument("--species-list", default=str(ROOT / "data" / "vision" / "species_list.json"))
    ap.add_argument("--out", default=str(ROOT / "data" / "vision"))
    ap.add_argument("--seed", type=int, default=20260818)
    ap.add_argument("--name", default="au_split.json")
    args = ap.parse_args()

    images = Path(args.images)
    out = Path(args.out)
    sp = json.loads(Path(args.species_list).read_text())
    au = sorted(s["key"] for s in sp if s.get("is_au"))

    rng = random.Random(args.seed)
    species = {}
    skipped = []
    for key in au:
        d = images / key
        if not d.is_dir():
            skipped.append(key)
            continue
        files = sorted(p.name for p in d.glob("*.jpg"))
        if not files:
            skipped.append(key)
            continue
        n = len(files)
        q = BIG_SPECIES_QUERIES if n >= QUERY_FULL_MIN else max(1, n // SMALL_FRACTION)
        q = min(q, max(1, n - 1))           # always leave >= 1 gallery image
        pool = files[:]
        rng.shuffle(pool)
        queries = sorted(pool[:q])
        query_set = set(queries)
        gallery = [f for f in files if f not in query_set]
        species[key] = {
            "gallery": [f"{key}/{f}" for f in gallery],
            "queries": [f"{key}/{f}" for f in queries],
        }

    n_q = sum(len(v["queries"]) for v in species.values())
    n_g = sum(len(v["gallery"]) for v in species.values())
    counts = {
        "species": len(species),
        "queries": n_q,
        "gallery": n_g,
        "skipped_species": skipped,
        "per_species_queries": dict(sorted(
            collections.Counter(len(v["queries"]) for v in species.values()).items())),
    }
    doc = {"seed": args.seed, "scoring": "au_baseline_v1", "images_dir": str(images),
           "species": species, "counts": counts}
    out.mkdir(parents=True, exist_ok=True)
    (out / args.name).write_text(json.dumps(doc, indent=1))

    print(f"[benchmark] species={len(species)} queries={n_q} gallery={n_g}")
    print(f"[benchmark] per-species query histogram: {counts['per_species_queries']}")
    if skipped:
        print(f"[benchmark] skipped (no images): {skipped}")
    print(f"[benchmark] wrote {out / args.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

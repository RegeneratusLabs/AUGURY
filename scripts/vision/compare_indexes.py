#!/usr/bin/env python3
"""AUGURY — compare two indexes on one fixed query set.

Why this is needed
------------------
Rebuilding the split reshuffles which images are held out, so two index builds
cannot be compared by their own reported numbers: the query sets differ, and worse,
queries from one build can end up inside the other's gallery and match themselves. A
naive before/after on this project reported 97.88% for exactly that reason.

This scores N indexes against the SAME queries, dropping any query whose image is
present in the gallery being scored, so the comparison is honest.

Usage:
    .venv-mcpmv46/bin/python scripts/vision/compare_indexes.py \
        --query-split data/vision/bench/_au_split_original.json \
        --index data/vision/index-v2 --index data/vision/index-v3
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import faiss
import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
CANONICAL_MAP = ROOT / "data" / "vision" / "canonical_map.json"
CACHE = ROOT / "data" / "vision" / "emb" / "dinov2-base" / "single"
IMAGES = ROOT / "data" / "vision" / "images"


def unit(a):
    return a / (np.linalg.norm(a, axis=-1, keepdims=True) + 1e-9)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--query-split", required=True,
                    help="split file whose queries define the fixed query set")
    ap.add_argument("--index", action="append", required=True,
                    help="index dir (repeatable)")
    ap.add_argument("--current-split", default=str(ROOT / "data" / "vision" / "au_split.json"),
                    help="current split, used to detect gallery leakage")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    canon = {}
    if CANONICAL_MAP.exists():
        canon = json.loads(CANONICAL_MAP.read_text()).get("canonical", {})

    qdoc = json.loads(Path(args.query_split).read_text())
    cur = json.loads(Path(args.current_split).read_text())

    # Queries keyed by (species dir, stem) so an image can be located on disk under
    # whichever species now owns it, after label repairs moved files around.
    queries = []
    for sp, v in qdoc["species"].items():
        for rel in v["queries"]:
            queries.append((sp, Path(rel).stem, rel, canon.get(sp, sp)))

    results = {}
    for index_dir in args.index:
        d = Path(index_dir)
        idx = faiss.read_index(str(d / "index.faiss"))
        keys = json.loads((d / "keys.json").read_text())
        files = json.loads((d / "files.json").read_text())
        z = np.load(d / "pca_whiten.npz")
        W, mu = z["W"], z["mu"]
        gallery_stems = set(files)

        scored = skipped = 0
        h1 = h3 = 0
        for sp, stem, rel, gt in queries:
            # locate the image: the repair may have moved it to its true species
            p = CACHE / sp / (stem + ".npy")
            if not p.exists():
                alt = [q for q in (CACHE / sp).parent.glob(f"*/{stem}.npy")]
                if not alt:
                    skipped += 1
                    continue
                p = alt[0]
            # leakage guard: a query whose file is in this gallery would match itself
            if stem in gallery_stems:
                skipped += 1
                continue
            v = unit(np.load(p).astype(np.float32))
            v = unit((v - mu) @ W)
            _s, i = idx.search(v.reshape(1, -1), 12)
            out, seen = [], set()
            for j in i[0]:
                if j < 0:
                    continue
                c = keys[j]
                if c in seen:
                    continue
                seen.add(c)
                out.append(c)
                if len(out) >= 3:
                    break
            scored += 1
            if out and out[0] == gt:
                h1 += 1
            if gt in out[:3]:
                h3 += 1
        results[index_dir] = {
            "scored": scored, "skipped": skipped,
            "top1": h1 / max(1, scored), "top3": h3 / max(1, scored),
        }
        print(f"[compare] {index_dir:32s} scored={scored:4d} skipped={skipped:4d} "
              f"top-1 {h1}/{scored} = {h1/max(1,scored):.2%}  top-3 {h3/max(1,scored):.2%}")

    if args.out:
        Path(args.out).write_text(json.dumps(
            {"query_split": args.query_split, "results": results}, indent=1))
        print(f"[compare] wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""AUGURY — measure_density_gain.py

Does adding gallery images actually improve top-1, and by how much?

Why this exists
---------------
The handover called gallery density "the one lever not fully tested" and left the
90% target blocked on it. Meanwhile the density arithmetic is unforgiving: on the
cleaned benchmark, even perfect accuracy for every species below 90% only reaches
~89%. Before spending a multi-day acquisition run, measure the gradient.

Method
------
Leave-one-out on a chosen species set, everything else held fixed:

  * the gallery is rebuilt from every on-disk image EXCEPT the query images, so no
    query can match itself (the leakage trap that made a naive before/after report
    97.88%);
  * the same query images are used before and after, so the only variable is
    gallery size;
  * PCA is refit on the new gallery, gallery-only, exactly as production does.

This isolates "more images of the same species" from every other change.

Usage:
    .venv-mcpmv46/bin/python scripts/vision/measure_density_gain.py \
        --species holcus-lanatus,raphanus-raphanistrum --compare 50
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

import faiss
import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "vision"))

IMAGES = ROOT / "data" / "vision" / "images"
CACHE = ROOT / "data" / "vision" / "emb" / "dinov2-base" / "single"
CANONICAL_MAP = ROOT / "data" / "vision" / "canonical_map.json"
SPLIT = ROOT / "data" / "vision" / "au_split.json"
ADJUSTED_SPLIT = ROOT / "data" / "vision" / "bench" / "_au_split_original.json"


def load_canon() -> dict:
    if CANONICAL_MAP.exists():
        return json.loads(CANONICAL_MAP.read_text()).get("canonical", {})
    return {}


def sim_index(vectors: np.ndarray, dim: int):
    idx = faiss.IndexFlatIP(dim)
    idx.add(vectors.astype(np.float32))
    return idx


def fit_whiten(gallery: np.ndarray, dim: int = 384):
    """PCA-whitening fit on the gallery only — never on queries."""
    mu = gallery.mean(0)
    X = gallery - mu
    _u, s, vt = np.linalg.svd(X, full_matrices=False)
    d = min(dim, vt.shape[0])
    scale = s[:d] ** -0.5
    W = (vt[:d].T * scale).astype(np.float32)
    return W, mu.astype(np.float32)


def unit(a: np.ndarray) -> np.ndarray:
    return a / (np.linalg.norm(a, axis=-1, keepdims=True) + 1e-9)


def eval_split(index, keys, W, mu, queries: list, cap: int):
    """Top-1/top-3 over (species, relpath, gt) queries, collapsing duplicate labels."""
    h1 = h3 = 0
    for sp, rel, gt in queries:
        p = CACHE / sp / (Path(rel).stem + ".npy")
        if not p.exists():
            continue
        v = unit(np.load(p).astype(np.float32))
        v = unit((v - mu) @ W)
        _s, i = index.search(v.reshape(1, -1), 12)
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
        if out and out[0] == gt:
            h1 += 1
        if gt in out[:3]:
            h3 += 1
    return h1, h3


def build(queries: list, cap: int, pilot: set, pilot_cap: int):
    """Gallery = all cached images except the query images. Returns arrays."""
    query_files = {(sp, Path(rel).stem) for sp, rel, _ in queries}
    gvecs, gkeys, sizes = [], [], collections.Counter()
    for sp_dir in sorted(IMAGES.iterdir()):
        if not sp_dir.is_dir() or sp_dir.name == "_quarantine":
            continue
        limit = pilot_cap if sp_dir.name in pilot else cap
        for f in sorted(sp_dir.iterdir()):
            if f.suffix.lower() != ".jpg":
                continue
            if (sp_dir.name, f.stem) in query_files:
                continue
            npy = CACHE / sp_dir.name / (f.stem + ".npy")
            if not npy.exists():
                continue
            if sizes[sp_dir.name] >= limit:
                continue
            gvecs.append(np.load(npy))
            gkeys.append(sp_dir.name)
            sizes[sp_dir.name] += 1
    return unit(np.vstack(gvecs).astype(np.float32)), gkeys, sizes


def main() -> int:
    ap = argparse.ArgumentParser(description="Measure the gallery-density gradient")
    ap.add_argument("--species", required=True, help="comma-separated species keys")
    ap.add_argument("--compare", type=int, default=50,
                    help="baseline gallery cap to compare against")
    ap.add_argument("--pilot-cap", type=int, default=300)
    ap.add_argument("--out", default=str(ROOT / "data" / "vision" / "bench" / "density_pilot.json"))
    args = ap.parse_args()

    pilot = {s.strip() for s in args.species.split(",") if s.strip()}
    canon = load_canon()
    split_file = ADJUSTED_SPLIT if ADJUSTED_SPLIT.exists() else SPLIT
    split = json.loads(split_file.read_text())

    # Query set: the pilot species' queries from the CURRENT split, measured under
    # both conditions so gallery size is the only variable.
    queries = []
    for sp, v in split["species"].items():
        if sp not in pilot:
            continue
        gt = canon.get(sp, sp)
        for rel in v["queries"]:
            queries.append((sp, rel, gt))
    if not queries:
        print(f"[density] no queries for {sorted(pilot)}"); return 1

    print(f"[density] pilot species : {sorted(pilot)}")
    print(f"[density] queries       : {len(queries)}")

    results = {}
    for label, cap in (("baseline", args.compare), ("densified", args.pilot_cap)):
        gvecs, gkeys, sizes = build(queries, cap, pilot, cap)
        W, mu = fit_whiten(gvecs)
        G = unit((gvecs - mu) @ W)
        index = sim_index(G, G.shape[1])
        h1, h3 = eval_split(index, gkeys, W, mu, queries, cap)
        n = len(queries)
        per_pilot = sum(sizes[s] for s in pilot)
        results[label] = {"cap": cap, "gallery": int(G.shape[0]),
                          "pilot_gallery": per_pilot,
                          "top1": h1 / n, "top3": h3 / n, "n": n}
        print(f"[density] {label:10s} cap={cap:4d} gallery={G.shape[0]:6d} "
              f"(pilot {per_pilot:5d})  top-1 {h1}/{n} = {h1/n:.1%}  top-3 {h3/n:.1%}")

    b, d = results["baseline"], results["densified"]
    gain = (d["top1"] - b["top1"]) * 100
    print(f"\n[density] GAIN: {b['top1']:.1%} -> {d['top1']:.1%}  ({gain:+.1f} points)")
    if gain <= 0:
        print("[density] No gain measured — densifying these species is not the lever.")
    Path(args.out).write_text(json.dumps(
        {"species": sorted(pilot), "results": results, "gain_points": gain}, indent=1))
    print(f"[density] wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

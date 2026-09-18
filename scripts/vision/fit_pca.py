#!/usr/bin/env python3
"""AUGURY — fit_pca.py

Fits a PCA-whitening transform for retrieval on GALLERY embeddings only, then
saves it for `bench.py --pca` and the index build.

Why: raw DINOv2 cosine similarity leaves ~18% of AU benchmark queries wrong.
Whitening the dominant feature directions (a standard retrieval trick) lifted
the benchmark from 80.8% to 82.4% top-1 in testing. The transform is fit on the
gallery side only, so it never sees the held-out query set.

Usage:
  .venv-mcpmv46/bin/python scripts/vision/fit_pca.py \
      [--split data/vision/au_split.json] [--dim 384] [--whiten 0.5] \
      [--out data/vision/pca_whiten.npz]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default=str(ROOT / "data" / "vision" / "au_split.json"))
    ap.add_argument("--cache", default=str(ROOT / "data" / "vision" / "emb"))
    ap.add_argument("--backend", default="dinov2-base")
    ap.add_argument("--canonical-map", default=str(ROOT / "data" / "vision" / "canonical_map.json"))
    ap.add_argument("--dim", type=int, default=384)
    ap.add_argument("--whiten", type=float, default=0.5)
    ap.add_argument("--out", default=str(ROOT / "data" / "vision" / "pca_whiten.npz"))
    args = ap.parse_args()

    doc = json.loads(Path(args.split).read_text())
    canon = {}
    if Path(args.canonical_map).exists():
        canon = json.loads(Path(args.canonical_map).read_text()).get("canonical", {})
    emb = Path(args.cache) / args.backend / "single"

    vecs = []
    for key, v in doc["species"].items():
        for rel in v["gallery"]:
            p = emb / key / (Path(rel).stem + ".npy")
            if p.exists():
                vecs.append(np.load(p))
    if not vecs:
        raise SystemExit(f"no gallery embeddings under {emb} — run cache_embeddings.py first")

    X = np.vstack(vecs).astype(np.float32)
    X /= (np.linalg.norm(X, axis=1, keepdims=True) + 1e-9)
    mu = X.mean(0)
    Xc = X - mu
    _U, S, Vt = np.linalg.svd(Xc, full_matrices=False)
    d = min(args.dim, Vt.shape[0])
    scale = S[:d] ** (-args.whiten)
    W = (Vt[:d].T * scale).astype(np.float32)

    np.savez(args.out, W=W, mu=mu.astype(np.float32), dim=d, whiten=args.whiten,
             backend=args.backend, n_gallery=len(vecs))
    print(f"[fit_pca] gallery={len(vecs)} dim→{d} whiten={args.whiten} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""AUGURY — build_index_v2.py

Builds the improved runtime retrieval index:

  * **canonical keys** — duplicate gallery keys for the same plant collapse to one
    label (data/vision/canonical_map.json), so `barley grass` and
    `hordeum leporinum` stop stealing each other's top-1.
  * **PCA-whitened embeddings** — the transform from fit_pca.py is baked into the
    stored vectors, so queries only need the same transform applied.

Together these lifted the AU benchmark from 71.8% to 82.4% top-1 / 89.2% top-3
(916 queries, 186 species — see data/vision/bench/ship_candidate.json).

Writes to a NEW directory by default: the v1 index is never overwritten.

Usage:
  .venv-mcpmv46/bin/python scripts/vision/build_index_v2.py \
      [--emb data/vision/emb] [--out data/vision/index-v2] [--no-pca]
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

import faiss
import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default=str(ROOT / "data" / "vision" / "au_split.json"))
    ap.add_argument("--emb", default=str(ROOT / "data" / "vision" / "emb"))
    ap.add_argument("--backend", default="dinov2-base")
    ap.add_argument("--canonical-map", default=str(ROOT / "data" / "vision" / "canonical_map.json"))
    ap.add_argument("--pca", default=str(ROOT / "data" / "vision" / "pca_whiten.npz"))
    ap.add_argument("--no-pca", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "data" / "vision" / "index-v2"))
    args = ap.parse_args()

    doc = json.loads(Path(args.split).read_text())
    canon = {}
    if Path(args.canonical_map).exists():
        canon = json.loads(Path(args.canonical_map).read_text()).get("canonical", {})
    emb = Path(args.emb) / args.backend / "single"

    vecs, keys, files = [], [], []
    for key, v in doc["species"].items():
        label = canon.get(key, key)
        for rel in v["gallery"]:
            p = emb / key / (Path(rel).stem + ".npy")
            if not p.exists():
                continue
            vecs.append(np.load(p))
            keys.append(label)
            files.append(Path(rel).name)
    if not vecs:
        raise SystemExit(f"no embeddings under {emb}")

    arr = np.vstack(vecs).astype(np.float32)
    arr /= (np.linalg.norm(arr, axis=1, keepdims=True) + 1e-9)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    transform = {"pca": False}
    if not args.no_pca and Path(args.pca).exists():
        z = np.load(args.pca)
        W, mu = z["W"], z["mu"]
        arr = (arr - mu) @ W
        arr /= (np.linalg.norm(arr, axis=1, keepdims=True) + 1e-9)
        transform = {"pca": True, "pca_file": Path(args.pca).name,
                     "dim": int(W.shape[1]), "whiten": float(z["whiten"])}
        np.savez(out / "pca_whiten.npz", W=W, mu=mu, dim=z["dim"], whiten=z["whiten"])

    arr = arr.astype(np.float32)
    index = faiss.IndexFlatIP(arr.shape[1])
    index.add(arr)
    faiss.write_index(index, str(out / "index.faiss"))
    (out / "keys.json").write_text(json.dumps(keys))
    (out / "files.json").write_text(json.dumps(files))
    np.save(out / "embeddings.npy", arr)

    labels = collections.Counter(keys)
    meta = {
        "version": 2,
        "backend": args.backend,
        "vectors": int(arr.shape[0]),
        "dim": int(arr.shape[1]),
        "species": len(labels),
        "canonical_merged": len(canon),
        "transform": transform,
        "notes": "canonical labels + optional PCA whitening; see bench/ship_candidate.json",
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=1))

    print(f"[index-v2] vectors={meta['vectors']} dim={meta['dim']} species={meta['species']} "
          f"pca={transform['pca']}")
    print(f"[index-v2] wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

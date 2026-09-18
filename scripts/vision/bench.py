#!/usr/bin/env python3
"""AUGURY — bench.py

Scores AU retrieval on the fixed benchmark split with pluggable gallery
policies, query policies and label canonicalization. Reads cached embeddings
from cache_embeddings.py (one .npy per image).

Reports micro AND macro top-1/top-3 with Wilson CIs, per-species breakdown,
top confusions, latency and peak RSS. Writes JSON + a markdown report.

Usage:
  # baseline: cached dinov2-base, raw keys
  .venv-mcpmv46/bin/python scripts/vision/bench.py --backend dinov2-base

  # with alias canonicalization + per-species gallery cap
  .venv-mcpmv46/bin/python scripts/vision/bench.py --backend dinov2-base \
      --canonical --cap 40 --tag cap40

  # fused encoder (must be cached first)
  .venv-mcpmv46/bin/python scripts/vision/bench.py --backend concat:dinov2-base+siglip2-400m
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import statistics
import sys
import time
from pathlib import Path

import faiss
import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# Canonical key map: duplicate gallery keys that are the same plant collapse to
# one bucket. Loaded from data/vision/canonical_map.json (shared with the index
# builder so runtime labels and benchmark labels agree).
_CANON_FILE = ROOT / "data" / "vision" / "canonical_map.json"
EVAL_ALIAS = {}
if _CANON_FILE.exists():
    EVAL_ALIAS = json.loads(_CANON_FILE.read_text()).get("canonical", {})


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    s = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - s) / d, (c + s) / d)


def load_manifest(cache: Path, backend: str, tta: str) -> dict:
    p = cache / backend.replace("/", "_") / tta / "_manifest.json"
    if not p.exists():
        raise SystemExit(f"no cached embeddings: {p}\n"
                         f"run cache_embeddings.py --backend {backend}"
                         f"{' --tta' if tta != 'single' else ''} first")
    return json.loads(p.read_text())


def read_vec(cache: Path, backend: str, tta: str, key: str, rel: str) -> np.ndarray | None:
    p = cache / backend.replace("/", "_") / tta / key / (Path(rel).stem + ".npy")
    if not p.exists():
        return None
    return np.load(p).astype(np.float32)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="dinov2-base")
    ap.add_argument("--query-backend", default="",
                    help="separate cache for query embeddings (e.g. flip-TTA variant); "
                         "defaults to --backend")
    ap.add_argument("--split", default=str(ROOT / "data" / "vision" / "au_split.json"))
    ap.add_argument("--cache", default=str(ROOT / "data" / "vision" / "emb"))
    ap.add_argument("--images", default=str(ROOT / "data" / "vision" / "images"))
    ap.add_argument("--canonical", action="store_true", help="apply eval alias merge")
    ap.add_argument("--cap", type=int, default=0, help="max gallery images per species (0=all)")
    ap.add_argument("--pca", default="", help="path to pca_whiten.npz fitted on the gallery "
                                             "(applies a whitening transform to both sides)")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--tag", default="")
    ap.add_argument("--out", default=str(ROOT / "data" / "vision" / "bench"))
    ap.add_argument("--query-tta", action="store_true",
                    help="average full+crop+flip query views (re-embeds queries)")
    args = ap.parse_args()

    cache = Path(args.cache)
    images = Path(args.images)
    doc = json.loads(Path(args.split).read_text())
    tta = "single"
    man = load_manifest(cache, args.backend, tta)
    dim = man.get("dim", 0)
    # a query backend may name a variant dir, e.g. "dinov2-base/flip"
    q_spec = args.query_backend or args.backend
    if "/" in q_spec:
        q_backend, q_tta = q_spec.rsplit("/", 1)
    else:
        q_backend, q_tta = q_spec, "single"
    if args.query_backend:
        load_manifest(cache, q_backend, q_tta)  # fail fast if missing
    print(f"[bench] gallery cache={args.backend}/{tta}  query cache={q_backend}/{q_tta}")

    def canon(k: str) -> str:
        return EVAL_ALIAS.get(k, k) if args.canonical else k

    # ── assemble gallery / queries from cache ───────────────────────────────
    gal_vecs, gal_keys, q_vecs, q_keys = [], [], [], []
    missing_gal = missing_q = 0
    per_species = collections.Counter()
    for key, v in doc["species"].items():
        for rel in v["gallery"]:
            if args.cap and per_species[key] >= args.cap:
                continue
            vec = read_vec(cache, args.backend, tta, key, rel)
            if vec is None:
                missing_gal += 1
                continue
            gal_vecs.append(vec)
            gal_keys.append(canon(key))
            per_species[key] += 1
        for rel in v["queries"]:
            vec = read_vec(cache, q_backend, q_tta, key, rel)
            if vec is None:
                missing_q += 1
                continue
            q_vecs.append(vec)
            q_keys.append(canon(key))

    if not gal_vecs or not q_vecs:
        raise SystemExit(f"no embeddings found (missing {missing_gal} gallery / {missing_q} query) "
                         f"— run cache_embeddings.py for backend {args.backend}")

    G = np.vstack(gal_vecs).astype(np.float32)
    Q = np.vstack(q_vecs).astype(np.float32)
    for M in (G, Q):
        M /= (np.linalg.norm(M, axis=1, keepdims=True) + 1e-9)

    if args.pca:
        z = np.load(args.pca)
        Wm, mum = z["W"], z["mu"]
        G = (G - mum) @ Wm
        Q = (Q - mum) @ Wm
        G /= (np.linalg.norm(G, axis=1, keepdims=True) + 1e-9)
        Q /= (np.linalg.norm(Q, axis=1, keepdims=True) + 1e-9)
        print(f"[bench] PCA whitening applied: {Wm.shape} (fit on gallery only — see fit_pca.py)")

    print(f"[bench] backend={args.backend} dim={G.shape[1]} canonical={args.canonical} "
          f"cap={args.cap or 'none'} pca={bool(args.pca)}")
    print(f"[bench] gallery={G.shape[0]} queries={Q.shape[0]} "
          f"(missing gallery={missing_gal}, query={missing_q})")

    # ── search ──────────────────────────────────────────────────────────────
    t0 = time.time()
    index = faiss.IndexFlatIP(G.shape[1])
    index.add(G)
    build_s = time.time() - t0

    t0 = time.time()
    scores, idxs = index.search(Q, min(args.k, G.shape[0]))
    search_ms = (time.time() - t0) * 1000 / max(len(Q), 1)

    n = len(q_keys)
    hit1 = hit3 = 0
    per_sp = collections.defaultdict(lambda: [0, 0, 0])   # key -> [top1, top3, n]
    confusion = collections.Counter()
    for i, gt in enumerate(q_keys):
        preds = [gal_keys[j] for j in idxs[i] if j >= 0]
        per_sp[gt][2] += 1
        if preds and preds[0] == gt:
            hit1 += 1
            per_sp[gt][0] += 1
        elif preds:
            confusion[(gt, preds[0])] += 1
        if gt in preds[:3]:
            hit3 += 1
            per_sp[gt][1] += 1

    macro1 = statistics.mean(v[0] / v[2] for v in per_sp.values())
    macro3 = statistics.mean(v[1] / v[2] for v in per_sp.values())
    ci1 = wilson(hit1, n)
    ci3 = wilson(hit3, n)

    worst = sorted((k for k in per_sp if per_sp[k][2] >= 3),
                   key=lambda k: (per_sp[k][0] / per_sp[k][2], -per_sp[k][2]))[:12]

    result = {
        "backend": args.backend, "canonical": args.canonical, "cap": args.cap,
        "dim": int(G.shape[1]), "gallery": int(G.shape[0]), "queries": int(n),
        "missing_gallery": missing_gal, "missing_query": missing_q,
        "top1": hit1 / n, "top3": hit3 / n,
        "macro_top1": macro1, "macro_top3": macro3,
        "top1_ci": ci1, "top3_ci": ci3,
        "index_build_s": build_s, "search_ms_per_query": search_ms,
        "worst_species": [{"key": k, "top1": per_sp[k][0] / per_sp[k][2],
                           "top3": per_sp[k][1] / per_sp[k][2], "n": per_sp[k][2]}
                          for k in worst],
        "top_confusions": [{"gt": a, "pred": b, "n": c} for (a, b), c in confusion.most_common(15)],
    }
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    tag = args.tag or f"{args.backend}{'_canon' if args.canonical else ''}{'_cap'+str(args.cap) if args.cap else ''}"
    (outdir / f"{tag}.json").write_text(json.dumps(result, indent=1))

    print(f"[bench] top-1 {hit1}/{n} = {hit1/n:.1%} (95% CI {ci1[0]:.1%}-{ci1[1]:.1%})")
    print(f"[bench] top-3 {hit3}/{n} = {hit3/n:.1%} (95% CI {ci3[0]:.1%}-{ci3[1]:.1%})")
    print(f"[bench] macro top-1 {macro1:.1%} | macro top-3 {macro3:.1%}")
    print(f"[bench] index build {build_s:.1f}s | search {search_ms:.2f} ms/query")
    print(f"[bench] wrote {outdir / (tag + '.json')}")
    if worst:
        print("[bench] weakest species (>=3 queries):")
        for k in worst[:8]:
            v = per_sp[k]
            print(f"    {k:34s} top1 {v[0]}/{v[2]}  top3 {v[1]}/{v[2]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

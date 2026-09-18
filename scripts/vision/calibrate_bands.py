#!/usr/bin/env python3
"""AUGURY — calibrate_bands.py

Derives the confidence-band thresholds from measured benchmark behaviour instead
of the hand-picked 0.80 / 0.60 constants, which no longer match the whitened
score distribution.

Bands (see photo_id.verdict):
  auto     — answer with a single species
  confirm  — show top-3 and ask the user
  unknown  — honest "not in my library"

Selection rule: pick the LOWEST threshold whose measured precision clears the
target, so recall is maximised subject to the precision guarantee. If no
threshold reaches the target, report that honestly rather than shipping a
threshold that looks confident and is not.

Usage:
  .venv-mcpmv46/bin/python scripts/vision/calibrate_bands.py \
      [--index-dir data/vision/index-v2] [--auto-precision 0.95] [--confirm-precision 0.85]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def wilson(k: int, n: int, z: float = 1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    s = z * ((p * (1 - p) + z * z / (4 * n)) / n) ** 0.5
    return ((c - s) / d, (c + s) / d)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--index-dir", default=str(ROOT / "data" / "vision" / "index-v2"))
    ap.add_argument("--split", default=str(ROOT / "data" / "vision" / "au_split.json"))
    ap.add_argument("--emb", default=str(ROOT / "data" / "vision" / "emb"))
    ap.add_argument("--backend", default="dinov2-base")
    ap.add_argument("--canonical-map", default=str(ROOT / "data" / "vision" / "canonical_map.json"))
    ap.add_argument("--auto-precision", type=float, default=0.95)
    ap.add_argument("--confirm-precision", type=float, default=0.85)
    ap.add_argument("--out", default=str(ROOT / "data" / "vision" / "band_calibration.json"))
    args = ap.parse_args()

    import faiss

    doc = json.loads(Path(args.split).read_text())
    canon = {}
    if Path(args.canonical_map).exists():
        canon = json.loads(Path(args.canonical_map).read_text()).get("canonical", {})

    idx_dir = Path(args.index_dir)
    index = faiss.read_index(str(idx_dir / "index.faiss"))
    keys = json.loads((idx_dir / "keys.json").read_text())
    z = idx_dir / "pca_whiten.npz"
    W = mu = None
    if z.exists():
        d = np.load(z)
        W, mu = d["W"], d["mu"]

    emb = Path(args.emb) / args.backend / "single"
    scores, correct = [], []
    for key, v in doc["species"].items():
        gt = canon.get(key, key)
        for rel in v["queries"]:
            p = emb / key / (Path(rel).stem + ".npy")
            if not p.exists():
                continue
            vec = np.load(p).astype(np.float32)
            vec /= (np.linalg.norm(vec) + 1e-9)
            if W is not None:
                vec = (vec - mu) @ W
                vec /= (np.linalg.norm(vec) + 1e-9)
            s, i = index.search(vec.reshape(1, -1), 12)
            out, seen = [], set()
            for sc, j in zip(s[0], i[0]):
                if j < 0:
                    continue
                c = keys[j]
                if c in seen:
                    continue
                seen.add(c)
                out.append((c, float(sc)))
                if len(out) >= 3:
                    break
            if not out:
                continue
            scores.append(out[0][1])
            correct.append(out[0][0] == gt)

    scores = np.array(scores)
    correct = np.array(correct)
    n = len(scores)
    print(f"[calibrate] queries={n} top-1 accuracy={correct.mean():.1%}")

    def sweep(target):
        best = None
        rows = []
        for t in np.arange(0.30, 0.991, 0.01):
            m = scores >= t
            n_sel = int(m.sum())
            if n_sel < 20:
                continue
            prec = float(correct[m].mean())
            recall = float(m.sum() / n)
            rows.append((float(t), n_sel, prec, recall))
            if prec >= target and (best is None or t < best[0]):
                best = (float(t), n_sel, prec, recall)
        return best, rows

    auto, arows = sweep(args.auto_precision)
    confirm, crows = sweep(args.confirm_precision)

    # band composition at the chosen thresholds
    def bands(auto_t, confirm_t):
        out = {}
        for name, m in (("auto", scores >= auto_t),
                        ("confirm", (scores >= confirm_t) & (scores < auto_t)),
                        ("unknown", scores < confirm_t)):
            n_sel = int(m.sum())
            out[name] = {"n": n_sel, "share": n_sel / n,
                         "precision": (float(correct[m].mean()) if n_sel else None),
                         "precision_ci": wilson(int(correct[m].sum()), n_sel)}
        return out

    if auto is None or confirm is None:
        print(f"[calibrate] TARGET UNREACHABLE: no threshold reached "
              f"auto>={args.auto_precision:.0%} / confirm>={args.confirm_precision:.0%}")
        print(f"[calibrate] best auto-band precision seen: "
              f"{max(r[2] for r in arows):.1%} at t={max(arows, key=lambda r: r[2])[0]:.2f}")
        auto_t = 0.99
        confirm_t = 0.60
    else:
        auto_t, confirm_t = auto[0], confirm[0]
        print(f"[calibrate] auto    t={auto_t:.2f} n={auto[1]} precision={auto[2]:.1%} "
              f"coverage={auto[3]:.1%}")
        print(f"[calibrate] confirm t={confirm_t:.2f} n={confirm[1]} precision={confirm[2]:.1%} "
              f"coverage={confirm[3]:.1%}")

    out = {
        "queries": n, "top1": float(correct.mean()),
        "targets": {"auto": args.auto_precision, "confirm": args.confirm_precision},
        "auto_conf": auto_t, "confirm_conf": confirm_t,
        "reachable": auto is not None and confirm is not None,
        "bands": bands(auto_t, confirm_t),
        "score_distribution": {
            "p05": float(np.percentile(scores, 5)), "p50": float(np.percentile(scores, 50)),
            "p95": float(np.percentile(scores, 95)),
            "correct_p50": float(np.percentile(scores[correct], 50)) if correct.any() else None,
            "wrong_p50": float(np.percentile(scores[~correct], 50)) if (~correct).any() else None,
        },
        "curve": [{"t": t, "n": k, "precision": p, "coverage": c} for t, k, p, c in arows],
    }
    Path(args.out).write_text(json.dumps(out, indent=1))
    print(f"[calibrate] wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

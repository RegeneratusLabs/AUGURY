#!/usr/bin/env python3
"""AUGURY — scan_image_quality.py

Cheap, exhaustive quality metrics over every gallery image, to decide which images
deserve an expensive visual look.

Why a cascade
-------------
`digitaria sanguinalis` exposed the problem: one of its five benchmark queries is a
small, damaged grass in a crack between concrete and asphalt — phone-quality, no
inflorescence, mostly dead tissue. It scored 0% and its errors were scattered
across unrelated taxa, which is the signature of an uninformative photo rather
than a model that needs more data.

If images like that are widespread, they cap accuracy no matter how many more we
download. But there are **111,302 images**, and having a vision model look at each
one is ~111k model calls — infeasible. Most defects are measurable without a
model, so this script computes cheap per-image metrics for the whole gallery and
emits a ranked shortlist for visual review.

Metrics (all cheap, no model):
  * decoded pixel dimensions and pixel count
  * bytes-per-pixel — a low value means heavy JPEG compression
  * aspect ratio — extremes suggest screenshots, panoramas or strips
  * Laplacian variance — the standard blur proxy (low = soft/out-of-focus)
  * mean luminance and its standard deviation — flags near-black/blank frames

It deliberately does NOT decide what "bad" is. It writes raw metrics plus a
per-metric percentile rank, so thresholds can be set from the actual distribution
rather than guessed, and a human (or a subagent) reviews the flagged tail.

Usage:
    .venv-mcpmv46/bin/python scripts/vision/scan_image_quality.py --workers 8
    .venv-mcpmv46/bin/python scripts/vision/scan_image_quality.py --jsonl out.jsonl
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
IMAGES = ROOT / "data" / "vision" / "images"
OUT_DEFAULT = ROOT / "data" / "vision" / "bench" / "image_quality.jsonl"


def _laplacian_variance(gray) -> float:
    """Variance of the 4-neighbour Laplacian — the classic blur proxy.

    Implemented with plain numpy so the scan needs no OpenCV. A sharp image has
    strong second derivatives (high variance); a soft or out-of-focus one has
    little.
    """
    import numpy as np

    g = np.asarray(gray, dtype=np.float32)
    if g.ndim != 2 or g.shape[0] < 3 or g.shape[1] < 3:
        return 0.0
    lap = (-4.0 * g[1:-1, 1:-1]
           + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:])
    return float(lap.var())


def measure(path_str: str) -> dict:
    """Per-image metrics. Never raises: a failure is itself a finding."""
    import numpy as np
    from PIL import Image

    p = Path(path_str)
    rec = {"path": str(p.relative_to(IMAGES)), "ok": False}
    try:
        size = p.stat().st_size
        rec["bytes"] = size
        with Image.open(p) as im:
            w, h = im.size
            rec["w"], rec["h"] = w, h
            rec["pixels"] = w * h
            rec["mode"] = im.mode
            gray = im.convert("L")
            # Downscale before the Laplacian: full-res variance is dominated by
            # sensor noise, and the downscale makes the metric comparable across
            # resolutions as well as ~20x faster.
            if max(w, h) > 512:
                scale = 512 / max(w, h)
                gray = gray.resize((max(1, int(w * scale)), max(1, int(h * scale))))
            arr = np.asarray(gray, dtype=np.float32)
            rec["blur_var"] = _laplacian_variance(arr)
            rec["lum_mean"] = float(arr.mean())
            rec["lum_std"] = float(arr.std())
        rec["bpp"] = size / max(1, rec["pixels"])
        rec["aspect"] = max(rec["w"], rec["h"]) / max(1, min(rec["w"], rec["h"]))
        rec["ok"] = True
    except Exception as e:  # noqa: BLE001
        rec["error"] = f"{type(e).__name__}: {e}"
    return rec


def _work(path_str: str) -> dict:
    return measure(path_str)


def percentile_ranks(records: list, key: str) -> dict:
    """Map each record index to its percentile rank for `key` (0 = lowest)."""
    vals = sorted((r.get(key), i) for i, r in enumerate(records)
                  if isinstance(r.get(key), (int, float)))
    n = len(vals)
    out = {}
    for rank, (_v, i) in enumerate(vals):
        out[i] = rank / max(1, n - 1)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Exhaustive cheap image-quality scan")
    ap.add_argument("--images", default=str(IMAGES))
    ap.add_argument("--out", default=str(OUT_DEFAULT))
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    root = Path(args.images)
    paths = sorted(str(p) for p in root.rglob("*.jpg"))
    if args.limit:
        paths = paths[: args.limit]
    print(f"[scan] images to measure: {len(paths)}  workers={args.workers}", flush=True)

    records = []
    done = 0
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(_work, p): p for p in paths}
        for f in as_completed(futs):
            records.append(f.result())
            done += 1
            if done % 5000 == 0:
                print(f"[scan] {done}/{len(paths)}", flush=True)

    # Percentile-rank the continuous metrics so thresholds come from the data.
    for key in ("blur_var", "bpp", "pixels", "lum_std", "lum_mean"):
        ranks = percentile_ranks(records, key)
        for i, r in ranks.items():
            records[i][f"{key}_pct"] = r

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")

    ok = [r for r in records if r.get("ok")]
    failed = [r for r in records if not r.get("ok")]
    print(f"\n[scan] measured {len(ok)}  unreadable {len(failed)}")
    if failed:
        print("[scan] unreadable examples (these are corrupt or truncated files):")
        for r in failed[:5]:
            print(f"    {r['path']}: {r.get('error')}")

    def dist(key, label):
        vals = sorted(r[key] for r in ok if isinstance(r.get(key), (int, float)))
        if not vals:
            return
        n = len(vals)
        q = lambda f: vals[min(n - 1, int(f * n))]
        print(f"  {label:16s} p01={q(.01):9.2f} p10={q(.10):9.2f} "
              f"p50={q(.50):9.2f} p90={q(.90):9.2f}")

    print("\n[scan] distributions:")
    dist("blur_var", "blur variance")
    dist("bpp", "bytes/pixel")
    dist("pixels", "pixels")
    dist("lum_std", "luminance std")
    print(f"\n[scan] wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

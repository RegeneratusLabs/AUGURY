#!/usr/bin/env python3
"""AUGURY — gate_encoder_int8.py

Phase-0 go/no-go for the Android app: **is ONNX int8 safe to ship as the phone's
image encoder?**

The question the gate must answer
---------------------------------
The phone NEVER re-embeds the gallery. It downloads `embeddings.npy` (built with
fp32 PyTorch) and embeds only the user's photo. So the honest test is:

    int8 ONNX queries  vs  the SHIPPED fp32-built gallery

not "int8 on both sides", which would measure a configuration that never runs.

Method
------
Both arms are scored on the **same query subset**, so the comparison is
apples-to-apples:

  arm A (baseline)  cached fp32 PyTorch CLS vectors (data/vision/emb/dinov2-base)
  arm B (candidate) ONNX int8 CLS vectors, computed here from the image bytes

Both are then run through the identical post-processing — L2, PCA-whiten with
index-v3's own transform, L2 — and a brute-force inner-product kNN over
index-v3's whitened gallery.

Why the subset matters
----------------------
44 of the 910 benchmark query images are referenced by `au_split.json` but no
longer exist on disk (removed after the fp32 cache was built). Arm A can still
score them from cache; arm B cannot, because it needs pixels. Restricting BOTH
arms to the images that exist keeps the delta honest. The excluded count is
reported rather than hidden.

Usage
-----
  .venv-mcpmv46/bin/python scripts/app/gate_encoder_int8.py
  .venv-mcpmv46/bin/python scripts/app/gate_encoder_int8.py --limit 100
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent

IMAGES = ROOT / "data" / "vision" / "images"
SPLIT = ROOT / "data" / "vision" / "au_split.json"
CANON = ROOT / "data" / "vision" / "canonical_map.json"
FP32_CACHE = ROOT / "data" / "vision" / "emb" / "dinov2-base" / "single"
INDEX_DIR = ROOT / "data" / "vision" / "index-v3"
ONNX_DIR = ROOT / "models" / "onnx"

MODEL_ID = "facebook/dinov2-base"
MAX_DROP_PTS = 2.5


def postprocess(cls_vec: np.ndarray, W: np.ndarray, mu: np.ndarray) -> np.ndarray:
    """L2 -> PCA-whiten -> L2. Identical for both arms."""
    v = cls_vec.astype(np.float32).ravel()
    v /= (np.linalg.norm(v) + 1e-9)
    v = (v - mu) @ W
    v /= (np.linalg.norm(v) + 1e-9)
    return v


def knn_topk(vec: np.ndarray, Gn: np.ndarray, keys: list, k: int = 3) -> list:
    """Brute-force inner product, collapsing duplicate canonical species."""
    sims = Gn @ vec
    order = np.argsort(-sims)
    seen, out = set(), []
    for j in order:
        c = keys[j]
        if c in seen:
            continue
        seen.add(c)
        out.append((c, float(sims[j])))
        if len(out) >= k:
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--encoder", default=str(ONNX_DIR / "dinov2-base-int8.onnx"))
    ap.add_argument("--limit", type=int, default=0, help="cap queries (smoke testing)")
    ap.add_argument("--threads", type=int, default=0)
    args = ap.parse_args()

    import onnxruntime as ort
    from PIL import Image
    from transformers import AutoImageProcessor

    encoder = Path(args.encoder)
    if not encoder.exists():
        print(f"[gate] missing encoder: {encoder} — run --export first")
        return 1

    split = json.loads(SPLIT.read_text())
    canon = json.loads(CANON.read_text())["canonical"]
    keys = json.loads((INDEX_DIR / "keys.json").read_text())
    G = np.load(INDEX_DIR / "embeddings.npy").astype(np.float32)
    z = np.load(INDEX_DIR / "pca_whiten.npz")
    W, mu = z["W"], z["mu"]
    Gn = G / (np.linalg.norm(G, axis=1, keepdims=True) + 1e-9)

    so = ort.SessionOptions()
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    if args.threads:
        so.intra_op_num_threads = args.threads
    sess = ort.InferenceSession(str(encoder), sess_options=so,
                               providers=["CPUExecutionProvider"])
    proc = AutoImageProcessor.from_pretrained(MODEL_ID)

    print(f"[gate] encoder : {encoder.name} ({encoder.stat().st_size/1e6:.1f} MB)")
    print(f"[gate] gallery : index-v3, {len(keys)} vectors (fp32-built, as shipped)")

    # Collect the comparable query set: image exists AND fp32 vector is cached.
    cases = []
    for species, v in split["species"].items():
        gt = canon.get(species, species)
        for rel in v["queries"]:
            img = IMAGES / rel
            fp = FP32_CACHE / Path(rel).with_suffix(".npy")
            if img.exists() and fp.exists():
                cases.append((rel, gt, img, fp))
    missing_img = sum(1 for v in split["species"].values() for rel in v["queries"]
                      if not (IMAGES / rel).exists())
    if args.limit:
        cases = cases[:args.limit]

    print(f"[gate] comparable queries: {len(cases)}  "
          f"(excluded {missing_img} whose image is no longer on disk)")
    print("[gate] scoring both arms on the SAME subset\n")

    arms = {"fp32_pytorch": {"c1": 0, "c3": 0, "n": 0},
            "onnx": {"c1": 0, "c3": 0, "n": 0}}
    t0 = time.time()
    for i, (rel, gt, img, fp) in enumerate(cases, 1):
        # --- arm A: cached fp32 PyTorch CLS ---
        cls_a = np.load(fp).astype(np.float32)
        top_a = knn_topk(postprocess(cls_a, W, mu), Gn, keys)
        arms["fp32_pytorch"]["n"] += 1
        arms["fp32_pytorch"]["c1"] += int(top_a[0][0] == gt)
        arms["fp32_pytorch"]["c3"] += int(any(c == gt for c, _ in top_a))

        # --- arm B: ONNX int8 from pixels ---
        px = proc(images=Image.open(img).convert("RGB"),
                  return_tensors="np")["pixel_values"].astype(np.float32)
        cls_b = sess.run(["cls_token"], {"pixel_values": px})[0][0]
        top_b = knn_topk(postprocess(cls_b, W, mu), Gn, keys)
        arms["onnx"]["n"] += 1
        arms["onnx"]["c1"] += int(top_b[0][0] == gt)
        arms["onnx"]["c3"] += int(any(c == gt for c, _ in top_b))

        if i % 100 == 0 or i == len(cases):
            el = time.time() - t0
            print(f"  {i}/{len(cases)}  {el:.0f}s  ({el/i*1000:.0f} ms/img)")

    res = {}
    for name, a in arms.items():
        res[name] = {"n": a["n"], "top1": a["c1"] / a["n"], "top3": a["c3"] / a["n"]}

    base, cand = res["fp32_pytorch"], res["onnx"]
    d1 = (cand["top1"] - base["top1"]) * 100
    d3 = (cand["top3"] - base["top3"]) * 100
    min_top1 = base["top1"] - MAX_DROP_PTS / 100.0
    verdict = "GO" if cand["top1"] >= min_top1 else "NO-GO"

    print("\n" + "=" * 68)
    print(f"{'arm':16} {'n':>6} {'top-1':>9} {'top-3':>9}")
    print(f"{'fp32 PyTorch':16} {base['n']:>6} {base['top1']:>9.4f} {base['top3']:>9.4f}")
    print(f"{Path(args.encoder).stem[:16]:16} {cand['n']:>6} {cand['top1']:>9.4f} {cand['top3']:>9.4f}")
    print(f"{'delta':16} {'':>6} {d1:>+8.2f}p {d3:>+8.2f}p")
    print("=" * 68)
    print(f"allowance : <= {MAX_DROP_PTS} pts top-1  ->  need >= {min_top1:.4f}")
    print(f"VERDICT   : {verdict}")
    print("\nNOTE: both arms scored on the same subset, against the shipped "
          "fp32-built\ngallery — this is the shipped configuration, not int8-on-both-sides.")

    out = {
        "encoder": encoder.name,
        "encoder_bytes": encoder.stat().st_size,
        "gallery": "index-v3",
        "gallery_vectors": len(keys),
        "comparable_queries": len(cases),
        "excluded_missing_images": missing_img,
        "arms": res,
        "delta_top1_pts": d1,
        "delta_top3_pts": d3,
        "max_drop_pts": MAX_DROP_PTS,
        "verdict": verdict,
        "method": ("int8 ONNX query embeddings vs fp32 PyTorch query embeddings, "
                   "both searched against index-v3's fp32-built whitened gallery"),
    }
    dest = ROOT / "data" / "vision" / "bench" / f"encoder_gate_{encoder.stem}.json"
    dest.write_text(json.dumps(out, indent=1))
    print(f"[gate] wrote {dest}")
    return 0 if verdict == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())

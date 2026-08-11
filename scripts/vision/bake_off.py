#!/usr/bin/env python3
"""AUGURY — bake_off.py (encoder bake-off for retrieval-based plant ID)

WS1a tool. Tests candidate image encoders for the photo->species retrieval
funnel: embed a gallery + query set, FAISS kNN, per-species top-1/top-3,
confusion matrix, markdown report.

Design notes
------------
* Gallery = images NOT in the val split (train-side images). Queries = val
  images, so matches are never trivially self-hits.
* Species labels come from the image path: images/<key>/<file>.jpg.
* Embeddings are L2-normalised; FAISS IndexFlatIP (cosine = dot on unit vecs).
* --au-only restricts gallery+queries to is_au species (the v1 scope).
* --limit caps images per species (cheap local smoke tests / CPU runs).

Usage
-----
  # tiny smoke test (local CPU, 3 encoders x 2 species x 4 imgs)
  .venv-mcpmv46/bin/python scripts/vision/bake_off.py --limit 4 --max-species 2

  # full AU bake-off (cloud A10 / local GPU)
  .venv-mcpmv46/bin/python scripts/vision/bake_off.py --au-only --limit 40

  # eval a fine-tuned encoder (WS1b output): pass --model-path
  .venv-mcpmv46/bin/python scripts/vision/bake_off.py --model-path out/ft/encoder \
      --au-only --limit 40
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
import time
from pathlib import Path

import faiss
import numpy as np
import torch
from PIL import Image
from transformers import AutoModel, AutoProcessor


ENCODERS = {
    # id -> (model id, processor config quirks)
    "siglip2-400m": "google/siglip2-so400m-patch14-384",
    "dinov2-base": "facebook/dinov2-base",
    "dinov2-large": "facebook/dinov2-large",
}


def load_encoder(model_id: str, device: str, checkpoint: str = ""):
    """Load a SigLIP2 or DINOv2 encoder for image embedding. Returns (model, proc, name)."""
    if "siglip2" in model_id:
        full = AutoModel.from_pretrained(model_id, torch_dtype=torch.bfloat16).to(device).eval()
        model = full.vision_model
        proc = AutoProcessor.from_pretrained(model_id)
        hidden = model.config.hidden_size
        pool = "mean"  # SigLIP2 default pooling

        def embed(pil_images: list) -> np.ndarray:
            inputs = proc(images=pil_images, return_tensors="pt",
                          padding=True).to(device)
            with torch.no_grad():
                out = model(pixel_values=inputs["pixel_values"])
            vec = out.pooler_output if out.pooler_output is not None else out.last_hidden_state.mean(dim=1)
            return vec.float().cpu().numpy()
    else:  # DINOv2
        model = AutoModel.from_pretrained(model_id).to(device).eval()
        proc = AutoProcessor.from_pretrained(model_id)
        hidden = model.config.hidden_size

        def embed(pil_images: list) -> np.ndarray:
            inputs = proc(images=pil_images, return_tensors="pt").to(device)
            with torch.no_grad():
                out = model(**inputs)
            vec = out.last_hidden_state[:, 0]  # cls token
            return vec.float().cpu().numpy()

    if checkpoint:
        ckpt = torch.load(checkpoint, map_location="cpu")
        trunk = ckpt["trunk"]
        # strip prefix if saved with torch.compile/DDP wrapper
        trunk = {k.removeprefix("module."): v for k, v in trunk.items()}
        missing, unexpected = model.load_state_dict(trunk, strict=False)
        if missing:
            print(f"  WARNING: {len(missing)} missing keys in trunk (layers not in ckpt)")
        emb_size = ckpt["head"]["2.weight"].shape[0]
        head = torch.nn.Sequential(
            torch.nn.Linear(hidden, 512), torch.nn.ReLU(),
            torch.nn.Linear(512, emb_size),
        )
        head.load_state_dict(ckpt["head"])
        head.to(device).eval()
        base_embed = embed

        def embed(pil_images: list) -> np.ndarray:
            vec = base_embed(pil_images)
            t = torch.tensor(vec, device=device)
            with torch.no_grad():
                out = torch.nn.functional.normalize(head(t), dim=1)
            return out.float().cpu().numpy()

    return model, proc, embed


def build_splits(images_dir: Path, species_list: dict, val_rows: list,
                 au_only: bool, limit: int, max_species: int):
    """Return (gallery, queries) as lists of (path, species_key)."""
    au_keys = {k for k, s in species_list.items() if s.get("is_au")} if au_only else None

    gallery, queries = [], []
    sp_gallery = collections.Counter()
    sp_queries = collections.Counter()
    for sp_dir in sorted(images_dir.iterdir()):
        if not sp_dir.is_dir():
            continue
        key = sp_dir.name
        if au_keys is not None and key not in au_keys:
            continue
        jpgs = sorted(sp_dir.glob("*.jpg"))
        val_files = {Path(r["images"][0]).name for r in val_rows
                     if Path(r["images"][0]).parts[-2] == key}
        for p in jpgs:
            if limit and sp_gallery[key] >= limit and sp_queries[key] >= limit:
                break
            if p.name in val_files and (not limit or sp_queries[key] < limit):
                queries.append((str(p), key))
                sp_queries[key] += 1
            elif not limit or sp_gallery[key] < limit:
                gallery.append((str(p), key))
                sp_gallery[key] += 1
        if max_species and len({k for _, k in gallery} | {k for _, k in queries}) >= max_species:
            break
    return gallery, queries


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", default="data/vision/images")
    ap.add_argument("--species-list", default="data/vision/species_list.json")
    ap.add_argument("--val", default="data/vision/val.jsonl")
    ap.add_argument("--encoders", nargs="+",
                    default=list(ENCODERS.keys()), choices=list(ENCODERS.keys()))
    ap.add_argument("--model-path", help="use a local fine-tuned encoder instead")
    ap.add_argument("--checkpoint", help="fine_tune_encoder.py checkpoint .pt to eval")
    ap.add_argument("--au-only", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="max images per species (0 = all)")
    ap.add_argument("--max-species", type=int, default=0)
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--out", default="data/vision/bake_off_report.md")
    args = ap.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    images_dir = Path(args.images)
    species_list = {s["key"]: s for s in json.loads(Path(args.species_list).read_text())}
    val_rows = [json.loads(l) for l in Path(args.val).read_text().splitlines() if l.strip()]

    gallery, queries = build_splits(images_dir, species_list, val_rows,
                                    args.au_only, args.limit, args.max_species)
    if not gallery or not queries:
        print("ERROR: empty splits — check paths / --au-only / --limit", file=sys.stderr)
        return 1
    print(f"gallery={len(gallery)} queries={len(queries)} "
          f"(species: {len({k for _, k in gallery})} gal / {len({k for _, k in queries})} qry)")

    gallery_keys = np.array([k for _, k in gallery])
    query_keys = np.array([k for _, k in queries])
    label_names = sorted(set(gallery_keys) | set(query_keys))

    report = [f"# AUGURY — encoder bake-off report", "",
              f"- encoders: {args.encoders or args.model_path}",
              f"- gallery: {len(gallery)} images, {len(set(gallery_keys))} species",
              f"- queries: {len(queries)} images, {len(set(query_keys))} species",
              f"- AU-only: {args.au_only} · device: {device}", ""]

    for enc_id in (args.encoders or []):
        model_id = ENCODERS[enc_id]
        if args.model_path:
            model_id = args.model_path
        print(f"\n=== {enc_id}: {model_id}{' + ckpt ' + args.checkpoint if args.checkpoint else ''} ===", flush=True)
        t0 = time.time()
        model, proc, embed = load_encoder(model_id, device, args.checkpoint or "")

        def embed_batch(items: list) -> np.ndarray:
            vecs = []
            B = 32
            for i in range(0, len(items), B):
                imgs = [Image.open(p).convert("RGB") for p, _ in items[i:i + B]]
                vecs.append(embed(imgs))
            return np.vstack(vecs)

        g_vec = embed_batch(gallery)
        q_vec = embed_batch(queries)
        for v in (g_vec, q_vec):
            v /= (np.linalg.norm(v, axis=1, keepdims=True) + 1e-9)

        index = faiss.IndexFlatIP(g_vec.shape[1])
        index.add(g_vec.astype(np.float32))
        scores, idx = index.search(q_vec.astype(np.float32), args.k)

        # per-species top-1 / top-3
        per_sp = collections.defaultdict(lambda: [0, 0, 0])  # key -> [top1, top3, n]
        for qi, (k, nbrs) in enumerate(zip(query_keys, idx)):
            gt = query_keys[qi]
            preds = [gallery_keys[j] for j in nbrs]
            per_sp[gt][2] += 1
            if preds and preds[0] == gt:
                per_sp[gt][0] += 1
            if gt in preds[:3]:
                per_sp[gt][1] += 1

        top1 = sum(v[0] for v in per_sp.values()) / len(queries)
        top3 = sum(v[1] for v in per_sp.values()) / len(queries)
        macro1 = np.mean([v[0] / v[2] for v in per_sp.values()])
        print(f"  top-1: {top1:.1%}  top-3: {top3:.1%}  macro top-1: {macro1:.1%}  "
              f"({time.time()-t0:.0f}s)")

        # confusion matrix for look-alikes (top-1 wrong guesses)
        conf = collections.Counter()
        for qi, nbrs in enumerate(idx):
            gt = query_keys[qi]
            if gallery_keys[nbrs[0]] != gt:
                conf[(gt, gallery_keys[nbrs[0]])] += 1

        report += [f"## {enc_id}", "",
                   f"- top-1: {top1:.1%} · top-3: {top3:.1%} · macro top-1: {macro1:.1%}", "",
                   "### Top confusions (GT -> predicted)", ""]
        for (a, b), c in conf.most_common(10):
            report.append(f"- {a} -> {b} ({c})")
        report.append("")

    Path(args.out).write_text("\n".join(report) + "\n")
    print(f"\nreport: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

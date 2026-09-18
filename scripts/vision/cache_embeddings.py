#!/usr/bin/env python3
"""AUGURY — cache_embeddings.py

Embeds a set of images with a chosen encoder and caches one .npy per image, so
long CPU runs are resumable and `bench.py` can score many policies without
re-embedding.

Cache layout (all under --cache):
  <backend>/<tta>/<key>/<image>.npy      unit-norm float32 vector, one per image
  <backend>/<tta>/_manifest.json         spec + counts

Resumability: an image already cached is skipped. Re-running after an
interruption continues where it stopped — no all-or-nothing long job.

Usage:
  # AU gallery + queries, DINOv2-base, single view
  .venv-mcpmv46/bin/python scripts/vision/cache_embeddings.py \
      --backend dinov2-base --split data/vision/au_split.json

  # full gallery, fused backend, TTA
  .venv-mcpmv46/bin/python scripts/vision/cache_embeddings.py \
      --backend concat:dinov2-base+siglip2-400m --tta --all-species --limit 0
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from transformers import AutoModel, AutoProcessor

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "vision"))

ENCODERS = {
    "dinov2-base": "facebook/dinov2-base",
    "dinov2-large": "facebook/dinov2-large",
    "siglip2-400m": "google/siglip2-so400m-patch14-384",
}


# ── encoders ────────────────────────────────────────────────────────────────
def load_encoder(model_id: str, device: str):
    """Return (embed_fn, dim). embed_fn takes a list of PIL images -> np.ndarray."""
    if "siglip" in model_id:
        full = AutoModel.from_pretrained(model_id, torch_dtype=torch.float32).to(device).eval()
        model = full.vision_model
        proc = AutoProcessor.from_pretrained(model_id)

        def embed(imgs):
            inp = proc(images=imgs, return_tensors="pt", padding=True).to(device)
            with torch.no_grad():
                out = model(pixel_values=inp["pixel_values"])
            v = out.pooler_output if out.pooler_output is not None else out.last_hidden_state.mean(1)
            return v.float().cpu().numpy()
    else:
        model = AutoModel.from_pretrained(model_id).to(device).eval()
        proc = AutoProcessor.from_pretrained(model_id)

        def embed(imgs):
            inp = proc(images=imgs, return_tensors="pt").to(device)
            with torch.no_grad():
                out = model(**inp)
            return out.last_hidden_state[:, 0].float().cpu().numpy()

    dim = int(model.config.hidden_size)
    return embed, dim


def tta_views(img: Image.Image, n: int) -> list:
    """Query-time views: full image + centre crops + horizontal flip."""
    w, h = img.size
    views = [img]
    if n >= 2:
        s = 0.75
        box = (int(w * (1 - s) / 2), int(h * (1 - s) / 2),
               int(w * (1 + s) / 2), int(h * (1 + s) / 2))
        views.append(img.crop(box))
    if n >= 3:
        views.append(img.transpose(Image.FLIP_LEFT_RIGHT))
    return views[:n]


# ── work list ───────────────────────────────────────────────────────────────
def build_worklist(args) -> list[tuple[str, Path]]:
    """Return [(species_key, abs_image_path), ...] to embed."""
    images = Path(args.images)
    work: list[tuple[str, Path]] = []

    if args.split:
        doc = json.loads(Path(args.split).read_text())
        for key, v in doc["species"].items():
            for rel in v["gallery"] + v["queries"]:
                work.append((key, images / rel))
    else:
        keys = None
        if not args.all_species:
            sp = json.loads(Path(args.species_list).read_text())
            keys = {s["key"] for s in sp if s.get("is_au")}
        for d in sorted(images.iterdir()):
            if not d.is_dir() or (keys is not None and d.name not in keys):
                continue
            for p in sorted(d.glob("*.jpg")):
                work.append((d.name, p))

    if args.limit:
        work = work[: args.limit]
    return work


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="dinov2-base",
                    help="dinov2-base | dinov2-large | siglip2-400m | concat:a+b")
    ap.add_argument("--images", default=str(ROOT / "data" / "vision" / "images"))
    ap.add_argument("--split", default="", help="benchmark split json (gallery+queries only)")
    ap.add_argument("--species-list", default=str(ROOT / "data" / "vision" / "species_list.json"))
    ap.add_argument("--all-species", action="store_true")
    ap.add_argument("--cache", default=str(ROOT / "data" / "vision" / "emb"))
    ap.add_argument("--tta", action="store_true", help="average full+crop+flip views")
    ap.add_argument("--tta-views", type=int, default=3)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--threads", type=int, default=14)
    args = ap.parse_args()

    torch.set_num_threads(args.threads)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    tta_tag = f"tta{args.tta_views}" if args.tta else "single"
    outdir = Path(args.cache) / args.backend.replace("/", "_") / tta_tag
    outdir.mkdir(parents=True, exist_ok=True)

    parts = args.backend.split("concat:")[-1].split("+")
    specs = [(p, ENCODERS[p]) for p in parts]
    print(f"[embed] backend={args.backend} parts={[p for p,_ in specs]} device={device}")

    encoders = []
    for name, mid in specs:
        t0 = time.time()
        fn, dim = load_encoder(mid, device)
        print(f"[embed]   loaded {name} ({mid}) dim={dim} in {time.time()-t0:.1f}s")
        encoders.append((name, fn, dim))

    work = build_worklist(args)
    print(f"[embed] work items: {len(work)}")

    manifest_path = outdir / "_manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    done = 0
    skipped = 0
    t_start = time.time()

    for i in range(0, len(work), args.batch):
        chunk = work[i:i + args.batch]
        todo = []
        for key, p in chunk:
            dest = outdir / key / (p.stem + ".npy")
            if dest.exists():
                skipped += 1
                continue
            todo.append((key, p, dest))
        if not todo:
            continue

        pil, metas = [], []
        for key, p, dest in todo:
            try:
                im = Image.open(p).convert("RGB")
            except Exception as e:  # noqa: BLE001
                print(f"[embed]   skip {p}: {e}")
                continue
            pil.append(im)
            metas.append((key, p, dest))
        if not pil:
            continue

        vecs = None
        for name, fn, _dim in encoders:
            if args.tta:
                per_view = []
                for v in range(args.tta_views):
                    batch = [tta_views(im, args.tta_views)[v] for im in pil]
                    per_view.append(fn(batch))
                v = np.mean(per_view, axis=0)
            else:
                v = fn(pil)
            v = v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-9)
            vecs = v if vecs is None else np.concatenate([vecs, v], axis=1)

        vecs = vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9)
        for (key, p, dest), vec in zip(metas, vecs):
            dest.parent.mkdir(parents=True, exist_ok=True)
            np.save(dest, vec.astype(np.float32))
            done += 1

        if (i // args.batch) % 10 == 0:
            el = time.time() - t_start
            rate = done / el if el else 0
            remaining = (len(work) - done - skipped) / rate if rate else 0
            print(f"[embed] {done+skipped}/{len(work)} ({done} new, {skipped} cached) "
                  f"{rate:.1f} img/s eta {remaining/60:.1f} min", flush=True)
            manifest.update({"backend": args.backend, "tta": args.tta,
                             "tta_views": args.tta_views if args.tta else 1,
                             "dim": int(vecs.shape[1]), "device": device})
            manifest_path.write_text(json.dumps(manifest, indent=1))

    dim = int(vecs.shape[1]) if work else 0
    manifest.update({"backend": args.backend, "tta": args.tta,
                     "tta_views": args.tta_views if args.tta else 1,
                     "dim": dim, "device": device,
                     "cached_total": done + skipped, "work_total": len(work)})
    manifest_path.write_text(json.dumps(manifest, indent=1))
    print(f"[embed] done: {done} new, {skipped} already cached, dim={dim} "
          f"in {(time.time()-t_start)/60:.1f} min -> {outdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

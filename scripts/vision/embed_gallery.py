#!/usr/bin/env python3
"""AUGURY — embed_gallery.py (Phase 2a: build the retrieval index, CPU-friendly)

Runs on the free 8-core CPU instance (or anywhere with Python + torch CPU).
Downloads the public vision gallery from HF, embeds every image with
DINOv2-base (the AU bake-off winner), builds a FAISS index, and pushes the
index + embeddings + species keys to a new public dataset repo
`RegeneratusLabs/augury-vision-index` — so the index never needs rebuilding
and any device can download it.

Timing (8 cores, CPU): ~0.2-0.4s/image -> 111k images ~ 7-9h. Resumable:
embeddings are appended per-species and checkpoints saved to /tmp/embed_state/.

Usage:
  pip install transformers torch faiss-cpu huggingface_hub pillow numpy
  python embed_gallery.py [--limit 20000]   # --limit for smoke tests
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import faiss
import numpy as np
import torch
from PIL import Image
from transformers import AutoModel, AutoProcessor

GALLERY_REPO = "RegeneratusLabs/augury-vision-gallery"
INDEX_REPO = "RegeneratusLabs/augury-vision-index"
LOCAL = os.environ.get("AUGURY_GALLERY_DIR", "/mnt/workspace/gallery")
OUT = os.environ.get("AUGURY_INDEX_DIR", "/mnt/workspace/index")
STATE = os.environ.get("AUGURY_STATE_FILE", "/mnt/workspace/embed_state.json")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="cap images (smoke test)")
    ap.add_argument("--device", default="cpu")
    args = ap.parse_args()

    from huggingface_hub import snapshot_download
    print(f"downloading gallery from {GALLERY_REPO} ...")
    snapshot_download(GALLERY_REPO, local_dir=LOCAL, repo_type="dataset",
                      allow_patterns=["images/*"])
    images_dir = Path(LOCAL) / "images"
    print(f"gallery at {images_dir}")

    print("loading DINOv2-base ...")
    model = AutoModel.from_pretrained("facebook/dinov2-base").to(args.device).eval()
    proc = AutoProcessor.from_pretrained("facebook/dinov2-base")

    species_dirs = sorted(d for d in images_dir.iterdir() if d.is_dir())
    print(f"species dirs: {len(species_dirs)}")

    vecs, keys, files = [], [], []
    state_path = Path(STATE)
    done = set()
    if state_path.exists():
        done = set(json.loads(state_path.read_text()))

    t0 = time.time()
    for i, sp in enumerate(species_dirs):
        if sp.name in done:
            continue
        jpgs = sorted(sp.glob("*.jpg"))
        if args.limit and len(vecs) >= args.limit:
            break
        for p in jpgs:
            if args.limit and len(vecs) >= args.limit:
                break
            try:
                img = Image.open(p).convert("RGB")
                inp = proc(images=img, return_tensors="pt").to(args.device)
                with torch.no_grad():
                    vec = model(**inp).last_hidden_state[:, 0].float().cpu().numpy()[0]
                vecs.append(vec)
                keys.append(sp.name)
                files.append(p.name)
            except Exception as e:  # noqa: BLE001
                print(f"  skip {p}: {e}")
        done.add(sp.name)
        if (i + 1) % 100 == 0:
            state_path.write_text(json.dumps(sorted(done)))
            np.save(Path(OUT) / "embeddings.npy", np.stack(vecs) if vecs else np.zeros((0, 768)))
            print(f"  {i+1}/{len(species_dirs)} dirs, {len(vecs)} imgs, "
                  f"{time.time()-t0:.0f}s", flush=True)

    arr = np.stack(vecs).astype(np.float32)
    arr /= (np.linalg.norm(arr, axis=1, keepdims=True) + 1e-9)
    Path(OUT).mkdir(parents=True, exist_ok=True)
    np.save(Path(OUT) / "embeddings.npy", arr)
    (Path(OUT) / "keys.json").write_text(json.dumps(keys))
    (Path(OUT) / "files.json").write_text(json.dumps(files))

    index = faiss.IndexFlatIP(arr.shape[1])
    index.add(arr)
    faiss.write_index(index, str(Path(OUT) / "index.faiss"))
    print(f"index: {arr.shape[0]} vectors x {arr.shape[1]} dims -> {Path(OUT)}")

    print(f"pushing to {INDEX_REPO} ...")
    from huggingface_hub import HfApi, create_repo
    api = HfApi()
    create_repo(INDEX_REPO, repo_type="dataset", exist_ok=True)
    api.upload_folder(folder_path=str(OUT), repo_id=INDEX_REPO, repo_type="dataset")
    print("done: https://huggingface.co/datasets/RegeneratusLabs/augury-vision-index")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

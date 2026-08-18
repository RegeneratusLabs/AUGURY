#!/usr/bin/env python3
"""AUGURY — embed_gallery.py (Phase 2a: build the retrieval index, CPU-friendly)

Runs on any machine with Python + torch CPU/GPU. Embeds every image of the
LOCAL gallery with DINOv2-base (the AU bake-off winner), builds a FAISS
index, and pushes the index + embeddings + species keys to a public dataset
repo `RegeneratusLabs/augury-vision-index` — so the index never needs
rebuilding and any device can download it.

NOTE (2026-08-18): the raw image gallery is LOCAL-ONLY now (removed from HF —
it is a build-time source, never read at runtime). Pass --images-dir pointing
at the local gallery, e.g. data/vision/images.

Timing (8 cores, CPU): ~0.2-0.4s/image -> 111k images ~ 7-9h. Resumable:
embeddings are appended per-species and checkpoints saved per species.

Usage:
  pip install transformers torch faiss-cpu huggingface_hub pillow numpy
  python embed_gallery.py --images-dir data/vision/images [--au-only] [--limit 20000]
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

INDEX_REPO = "RegeneratusLabs/augury-vision-index"
OUT = os.environ.get("AUGURY_INDEX_DIR", "/mnt/workspace/index")
STATE = os.environ.get("AUGURY_STATE_FILE", "/mnt/workspace/embed_state.json")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--images-dir", default="data/vision/images",
                    help="local gallery dir (required — gallery is local-only)")
    ap.add_argument("--species-list", default="data/vision/species_list.json")
    ap.add_argument("--au-only", action="store_true", help="embed only is_au species (v1 scope)")
    ap.add_argument("--limit", type=int, default=0, help="cap images (smoke test)")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--no-push", action="store_true", help="skip the HF push")
    args = ap.parse_args()

    images_dir = Path(args.images_dir)
    if not images_dir.is_dir():
        print(f"local gallery not found: {images_dir} — the gallery is local-only "
              f"(removed from HF 2026-08-18); pass --images-dir")
        return 2
    print(f"using local gallery: {images_dir}")

    print("loading DINOv2-base ...")
    model = AutoModel.from_pretrained("facebook/dinov2-base").to(args.device).eval()
    proc = AutoProcessor.from_pretrained("facebook/dinov2-base")

    au_only_keys = set()
    if args.au_only:
        sp = json.loads(Path(args.species_list).read_text())
        au_only_keys = {s["key"] for s in sp if s.get("is_au")}
        print(f"AU-only: {len(au_only_keys)} species")

    species_dirs = sorted(d for d in images_dir.iterdir() if d.is_dir())
    if au_only_keys:
        species_dirs = [d for d in species_dirs if d.name in au_only_keys]
    print(f"species dirs: {len(species_dirs)}")

    vecs, keys, files = [], [], []
    Path(OUT).mkdir(parents=True, exist_ok=True)
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

    if args.no_push:
        print(f"skip push — index at {OUT}")
        return 0
    print(f"pushing to {INDEX_REPO} ...")
    from huggingface_hub import HfApi, create_repo
    api = HfApi()
    create_repo(INDEX_REPO, repo_type="dataset", exist_ok=True)
    api.upload_folder(folder_path=str(OUT), repo_id=INDEX_REPO, repo_type="dataset")
    print("done: https://huggingface.co/datasets/RegeneratusLabs/augury-vision-index")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

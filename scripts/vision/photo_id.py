#!/usr/bin/env python3
"""AUGURY — photo_id.py (Phase 2b: photo → species via retrieval)

Loads the FAISS index built by embed_gallery.py, embeds a photo with the same
DINOv2-base encoder, and returns top-k species with scores — alias-canonicalized
(ribwort plantain == plantago lanceolata) and thresholded into three bands:

  * auto-accept:   top-1 score >= AUTO_CONF  → identify with confidence
  * confirm:       top-1 >= CONFIRM_CONF     → show top-3, ask the user
  * unknown:       below CONFIRM_CONF        → honest "not in the library"

The species name then flows through the SAME funnel as text: species_lookup →
database-merged.json → formatter story. The model never generates facts.

Usage:
    from photo_id import PhotoID
    pid = PhotoID(index_dir="data/vision/index")
    results = pid.identify("photo.jpg")   # [{"key","canonical","score"}, ...]
"""
from __future__ import annotations

import json
from pathlib import Path

import faiss
import numpy as np
import torch
from PIL import Image
from transformers import AutoModel, AutoProcessor

AUTO_CONF = 0.80     # top-1 above this → single-species answer
CONFIRM_CONF = 0.60  # top-1 above this → top-3 confirm; below → unknown


class PhotoID:
    def __init__(self, index_dir="data/vision/index", alias_map="data/vision/alias_map.json",
                 device: str = ""):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.index = faiss.read_index(str(Path(index_dir) / "index.faiss"))
        self.keys = json.loads((Path(index_dir) / "keys.json").read_text())
        self.encoder = AutoModel.from_pretrained("facebook/dinov2-base").to(self.device).eval()
        self.processor = AutoProcessor.from_pretrained("facebook/dinov2-base")
        self.alias = {}
        if Path(alias_map).exists():
            self.alias = json.loads(Path(alias_map).read_text())

    def canonical(self, key: str) -> str:
        return self.alias.get(key, key)

    def embed(self, image) -> np.ndarray:
        if isinstance(image, (str, Path)):
            image = Image.open(image).convert("RGB")
        inputs = self.processor(images=image, return_tensors="pt").to(self.device)
        with torch.no_grad():
            vec = self.encoder(**inputs).last_hidden_state[:, 0].float().cpu().numpy()
        vec /= (np.linalg.norm(vec) + 1e-9)
        return vec.astype(np.float32)

    def identify(self, image, k: int = 3) -> list:
        """Return [{key, canonical, score}] sorted by score, alias-canonicalized."""
        vec = self.embed(image)
        scores, idx = self.index.search(vec, k)
        out = []
        for s, j in zip(scores[0], idx[0]):
            if j < 0:
                continue
            key = self.keys[j]
            out.append({"key": key, "canonical": self.canonical(key), "score": float(s)})
        return out

    def verdict(self, results: list) -> str:
        """auto | confirm | unknown"""
        if not results:
            return "unknown"
        return ("auto" if results[0]["score"] >= AUTO_CONF
                else "confirm" if results[0]["score"] >= CONFIRM_CONF else "unknown")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--index-dir", default="data/vision/index")
    ap.add_argument("--k", type=int, default=3)
    args = ap.parse_args()
    pid = PhotoID(index_dir=args.index_dir)
    results = pid.identify(args.image, k=args.k)
    print(f"verdict: {pid.verdict(results)}")
    for r in results:
        print(f"  {r['canonical']:<35s} (key={r['key']})  score={r['score']:.3f}")

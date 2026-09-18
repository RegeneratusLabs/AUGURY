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

# Legacy constants, used when no calibration file is present (the v1 index, whose
# raw-cosine score distribution these were originally picked for).
AUTO_CONF = 0.80     # top-1 above this → single-species answer
CONFIRM_CONF = 0.60  # top-1 above this → top-3 confirm; below → unknown

# Calibrated thresholds live in <index_dir>/band_config.json, derived from
# measured benchmark precision by scripts/vision/calibrate_bands.py. The whitened
# score scale is different: precision peaks near 0.65 and FALLS above 0.75, so
# the legacy 0.80 "auto-accept" threshold is actively harmful on index-v2.
DEFAULT_BAND_CONFIG = {"auto_conf": AUTO_CONF, "confirm_conf": CONFIRM_CONF,
                       "calibrated": False}


def resolve_label(key: str, known: set, canon_map: dict, alias_map: dict) -> str:
    """Resolve `key` to a label this index actually serves.

    Precedence, in order:

    1. A label the index serves resolves to *itself*. The index is the ground
       truth for what a stored vector means; rewriting its own labels would make
       a correct prediction score as a miss.
    2. The canonical map, which is authoritative for raw gallery keys that are
       not themselves index labels.
    3. The legacy v1 alias map, but only when its target really is an index label.

    Extracted as a module function so the registry invariant can be tested
    without loading the DINOv2 encoder.
    """
    if key in known:
        return key
    if key in canon_map:
        return canon_map[key]
    aliased = alias_map.get(key)
    if aliased is not None and aliased in known:
        return aliased
    return key


def registry_errors(known: set, canon_map: dict, alias_map: dict) -> list:
    """Labels reachable from `known` that the index does not serve.

    A non-empty result means the label registry and the index disagree. That is
    the defect class described in `PhotoID.canonical()`: it silently rewrites
    ground truth, so a correct prediction is scored as a miss and the reported
    accuracy is wrong for reasons that look like a retrieval failure.
    """
    bad = []
    for k in known:
        c = resolve_label(k, known, canon_map, alias_map)
        if c not in known:
            bad.append({"key": k, "resolved": c})
    return bad


class PhotoID:
    def __init__(self, index_dir="data/vision/index", alias_map="data/vision/alias_map.json",
                 canonical_map="data/vision/canonical_map.json", device: str = ""):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.index_dir = Path(index_dir)
        self.index = faiss.read_index(str(self.index_dir / "index.faiss"))
        self.keys = json.loads((self.index_dir / "keys.json").read_text())
        # every label this index can actually return — the anchor for canonical()
        self.known = set(self.keys)
        self.encoder = AutoModel.from_pretrained("facebook/dinov2-base").to(self.device).eval()
        self.processor = AutoProcessor.from_pretrained("facebook/dinov2-base")

        self.alias = {}
        if Path(alias_map).exists():
            self.alias = json.loads(Path(alias_map).read_text())
        # canonical key merge (duplicate gallery keys for the same plant)
        self.canon_map = {}
        if Path(canonical_map).exists():
            self.canon_map = json.loads(Path(canonical_map).read_text()).get("canonical", {})

        # Fail loudly if the registries disagree with the index: a silent
        # mismatch here shows up later as a phantom accuracy gap.
        registry_errors = self.check_registry()
        if registry_errors:
            raise ValueError(
                f"label registry inconsistent with {self.index_dir}/keys.json: "
                f"{len(registry_errors)} label(s) resolve outside the index, "
                f"e.g. {registry_errors[:3]}. Fix canonical_map.json; do not "
                f"measure or ship this index until it is resolved."
            )

        # PCA-whitening transform, present only in index-v2 builds. When the index
        # was built with it, queries must be projected the same way.
        self.pca = None
        z = self.index_dir / "pca_whiten.npz"
        if z.exists():
            d = np.load(z)
            self.pca = (d["W"].astype(np.float32), d["mu"].astype(np.float32))
        self.meta = {}
        m = self.index_dir / "meta.json"
        if m.exists():
            self.meta = json.loads(m.read_text())

        # calibrated band thresholds (falls back to the legacy constants)
        self.band_config = dict(DEFAULT_BAND_CONFIG)
        b = self.index_dir / "band_config.json"
        if b.exists():
            self.band_config.update(json.loads(b.read_text()))

    def canonical(self, key: str) -> str:
        """Resolve a raw gallery key to its canonical species key.

        The canonical map is authoritative. `alias_map.json` is the legacy v1
        registry and is consulted ONLY for keys the canonical map does not know
        AND that actually exist in this index.

        Why the guard matters
        ---------------------
        This method previously read `canon_map.get(key, alias.get(key, key))`,
        which let the legacy map override canonical merges. Two of its entries
        reversed a canonical merge:

            alias["prosopis spp"] = "prosopis spp."   (canonical: the reverse)
            alias["salix spp"]    = "salix spp."      (canonical: the reverse)

        Because `index-v2/keys.json` stores canonical labels, ground truth was
        rewritten one way while predictions were stored the other way, and the
        shipped path measured 81.1% instead of the 82.4% the harness measured —
        a 1.3-point "gap" that was purely a label-registry artefact. See
        data/vision/index-v2/README.md and docs/HANDOVER-2026-09-18.md.
        """
        return resolve_label(key, self.known, self.canon_map, self.alias)

    def check_registry(self) -> list:
        """Return labels reachable from this index that the index does not serve."""
        return registry_errors(self.known, self.canon_map, self.alias)

    def embed(self, image) -> np.ndarray:
        if isinstance(image, (str, Path)):
            image = Image.open(image).convert("RGB")
        # an already-decoded PIL image may still be lazy; force load
        if getattr(image, "filename", None) or True:
            try:
                image.load()
            except Exception:  # noqa: BLE001
                pass
        inputs = self.processor(images=image, return_tensors="pt").to(self.device)
        with torch.no_grad():
            vec = self.encoder(**inputs).last_hidden_state[:, 0].float().cpu().numpy()[0]
        vec /= (np.linalg.norm(vec) + 1e-9)
        if self.pca is not None:
            W, mu = self.pca
            vec = (vec - mu) @ W
            vec /= (np.linalg.norm(vec) + 1e-9)
        return vec.astype(np.float32).reshape(1, -1)

    def identify(self, image, k: int = 3) -> list:
        """Return [{key, canonical, score}] sorted by score, canonicalized.

        Extra neighbours are requested and collapsed by canonical species so
        duplicate keys cannot occupy several of the top-k slots.
        """
        vec = self.embed(image)
        n = min(max(k * 4, k), self.index.ntotal)
        scores, idx = self.index.search(vec, n)
        out, seen = [], set()
        for s, j in zip(scores[0], idx[0]):
            if j < 0:
                continue
            key = self.keys[j]
            c = self.canonical(key)
            if c in seen:
                continue
            seen.add(c)
            out.append({"key": key, "canonical": c, "score": float(s)})
            if len(out) >= k:
                break
        return out

    def verdict(self, results: list) -> str:
        """auto | confirm | unknown, using the index's calibrated thresholds."""
        if not results:
            return "unknown"
        auto = self.band_config.get("auto_conf", AUTO_CONF)
        confirm = self.band_config.get("confirm_conf", CONFIRM_CONF)
        s = results[0]["score"]
        return "auto" if s >= auto else "confirm" if s >= confirm else "unknown"


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

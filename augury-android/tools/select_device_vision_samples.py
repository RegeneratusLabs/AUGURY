#!/usr/bin/env python3
"""AUGURY — pick real gallery photos for the on-device vision test.

The photo path needs a *known* subject: a JPEG whose species we already know,
so the instrumentation test can assert that retrieval surfaced that species
rather than merely that it returned three plausible strings.

The chosen files are taken from the shipped gallery index itself
(`data/vision/index-v3/{keys,files}.json` are row-aligned with the embeddings),
which makes them the strongest available fixture: the reference embedding of the
exact file is in `embeddings.npy`, so a device result that disagrees is a device
bug, not a hard query.

They are copied — not resized — into `app/src/androidTest/assets/vision-samples/`
because this host has no image library (the onnx venv carries no numpy/PIL/torch),
and the files are already modest. The generator writes `samples.json` next to
them recording the ground-truth species per file; the test reads that, never a
hard-coded list.

Usage:
    python3 tools/select_device_vision_samples.py [--count N] [--max-bytes N]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

TOOL = Path(__file__).resolve()
ANDROID = TOOL.parent.parent                      # augury-android/
REPO = ANDROID.parent                             # repo root
INDEX = REPO / "data" / "vision" / "index-v3"
IMAGES = REPO / "data" / "vision" / "images"
OUT = ANDROID / "app" / "src" / "androidTest" / "assets" / "vision-samples"


def load_rows() -> list[tuple[str, str]]:
    keys = json.loads((INDEX / "keys.json").read_text())
    files = json.loads((INDEX / "files.json").read_text())
    if len(keys) != len(files):
        sys.exit(f"[samples] keys.json ({len(keys)}) and files.json ({len(files)}) disagree")
    return list(zip(keys, files))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=12, help="how many photos to bundle")
    ap.add_argument("--max-bytes", type=int, default=500_000, help="skip JPEGs larger than this")
    args = ap.parse_args()

    rows = load_rows()

    # One photo per species, smallest first, species spread evenly across the
    # index so the sample is not all one family.
    by_species: dict[str, list[Path]] = {}
    for key, name in rows:
        path = IMAGES / key / name
        if path.is_file():
            by_species.setdefault(key, []).append(path)
    species = sorted(by_species)
    if not species:
        sys.exit(f"[samples] no gallery images found under {IMAGES}")

    step = max(1, len(species) // args.count)
    chosen: list[tuple[str, Path]] = []
    for key in species[::step]:
        if len(chosen) >= args.count:
            break
        candidates = sorted(by_species[key], key=lambda p: p.stat().st_size)
        for path in candidates:
            if path.stat().st_size <= args.max_bytes:
                chosen.append((key, path))
                break

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    manifest = []
    for key, path in chosen:
        target = OUT / f"{key.replace(' ', '_')}__{path.name}"
        shutil.copy2(path, target)
        manifest.append({"file": target.name, "species": key, "bytes": target.stat().st_size})
        print(f"  {target.stat().st_size:>7} B  {key:<32} {path.name}")

    (OUT / "samples.json").write_text(json.dumps(manifest, indent=1) + "\n")
    print(f"[samples] wrote {len(manifest)} photos + samples.json to {OUT}")
    print(f"[samples] {len(species)} index species available; used {len(manifest)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

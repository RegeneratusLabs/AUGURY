#!/usr/bin/env python3
"""AUGURY — build a flat, labelled, randomised query set for on-device accuracy.

Why this exists
---------------
`OnDevicePipelineTest` identifies 12 photos whose index rows are in the shipped
gallery. That proves device *parity* (the embedding of the exact file is in
`embeddings.npy`), not accuracy: a query the index has already memorised cannot
be got wrong.

This tool builds the opposite fixture — the **held-out** AU queries recorded in
`data/vision/au_split.json`, whose paths are disjoint from that split's own
`gallery` lists (asserted below, and the gallery is what the shipped index was
built from). The offline scorer reports 85.9% top-1 on this same set
(`scripts/vision/*`), so a device run is directly comparable to a number this
project already trusts.

The split's raw folder names are canonicalised through
`data/vision/canonical_map.json`, because the index stores canonical keys
("barley grass" -> "hordeum leporinum"); without that step a correct answer would
be scored as a miss for the 21 merged species.

Output: `<out>/images/qNNNN.jpg` and `<out>/queries.json`
(`[{file, species, source}]`), ready to `adb push` into the app's external files
directory. Files are copied, not re-encoded — this host has no image library and
re-encoding would perturb the very pixels under test.

Usage:
    python3 tools/prepare_heldout_queries.py                 # all of them
    python3 tools/prepare_heldout_queries.py --limit 100      # a random 100
    python3 tools/prepare_heldout_queries.py --seed 7 --limit 50
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from pathlib import Path

TOOL = Path(__file__).resolve()
ANDROID = TOOL.parent.parent          # augury-android/
REPO = ANDROID.parent                 # repo root

SPLIT = REPO / "data" / "vision" / "au_split.json"
CANONICAL = REPO / "data" / "vision" / "canonical_map.json"
IMAGES = REPO / "data" / "vision" / "images"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--out",
        default=str(REPO / ".dsh-runtime" / "accuracy-queries"),
        help="output directory (default: .dsh-runtime/accuracy-queries)",
    )
    ap.add_argument("--limit", type=int, default=0, help="take a random N (0 = all 920)")
    ap.add_argument("--seed", type=int, default=20260923, help="shuffle seed")
    args = ap.parse_args()

    canonical = json.loads(CANONICAL.read_text())["canonical"]
    split = json.loads(SPLIT.read_text())

    # The held-out guarantee, asserted rather than assumed. Compare full relative
    # PATHS: filenames are not unique across the gallery (320 basenames repeat,
    # and 72 queries share a basename with an unrelated gallery file), so a
    # basename test would both miss real leakage and invent false positives.
    gallery = {g for entry in split["species"].values() for g in entry.get("gallery", [])}

    rows: list[tuple[str, str]] = []
    for species, entry in split["species"].items():
        key = canonical.get(species, species)
        for query in entry.get("queries", []):
            if query in gallery:
                sys.exit(f"[queries] {query} is in the gallery — not a held-out set")
            rows.append((key, query))

    rows.sort()
    random.Random(args.seed).shuffle(rows)
    if args.limit:
        rows = rows[: args.limit]

    out = Path(args.out)
    images = out / "images"
    if out.exists():
        shutil.rmtree(out)
    images.mkdir(parents=True)

    manifest = []
    for i, (key, query) in enumerate(rows, 1):
        source = IMAGES / query
        if not source.is_file():
            print(f"[queries] skipping missing {query}", file=sys.stderr)
            continue
        name = f"q{i:04d}.jpg"
        shutil.copyfile(source, images / name)
        manifest.append({"file": name, "species": key, "source": query})

    (out / "queries.json").write_text(json.dumps(manifest, indent=1))
    species = {m["species"] for m in manifest}
    total = sum((images / m["file"]).stat().st_size for m in manifest)
    print(
        f"[queries] {len(manifest)} images · {len(species)} species · "
        f"{total / 1e6:.1f} MB · seed={args.seed} -> {out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""AUGURY vision — pull_deepweeds.py

Downloads the DeepWeeds dataset (Olsen et al. 2019, CC BY 4.0): 17,509 images of 8
northern-Australian weeds + a 'Negative' (non-weed) class.

  images.zip (468MB) : Google Drive id 1xnK3B6K6KekDI55vwJ0vnc2IGoDga9cj
  labels.csv         : https://raw.githubusercontent.com/AlexOlsen/DeepWeeds/master/labels/labels.csv

Class -> DB mapping (guard rail 7 / unknown path):
  Lantana        -> lantana camara            (in DB, train)
  Prickly acacia -> acacia nilotica           (in DB, train)
  Parthenium     -> parthenium hysterophorus  (in DB, train)
  Rubber vine    -> cryptostegia grandiflora  (in DB, train)
  Parkinsonia    -> parkinsonia aculeata      (in DB, train)
  Chinee apple   -> (not in DB) -> data/vision/images_unknown/chinee_apple/   (refusal/unknown)
  Snake weed     -> (not in DB) -> data/vision/images_unknown/snake_weed/
  Siam weed      -> (not in DB) -> data/vision/images_unknown/siam_weed/
  Negative       -> data/vision/images_unknown/negative/

Usage:
  .venv-mcpmv46/bin/python scripts/vision/pull_deepweeds.py [--out data/vision/images] [--unknown-out data/vision/images_unknown]
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

import requests

LABELS_URL = "https://raw.githubusercontent.com/AlexOlsen/DeepWeeds/master/labels/labels.csv"
DRIVE_ID = "1xnK3B6K6KekDI55vwJ0vnc2IGoDga9cj"

CLASS_TO_DB = {
    "Chinee apple": None,      # -> unknown
    "Snake weed": None,        # -> unknown
    "Lantana": "lantana camara",
    "Prickly acacia": "acacia nilotica",
    "Siam weed": None,         # -> unknown
    "Parthenium": "parthenium hysterophorus",
    "Rubber vine": "cryptostegia grandiflora",
    "Parkinsonia": "parkinsonia aculeata",
}
UNKNOWN_SLUG = {
    "Chinee apple": "chinee_apple",
    "Snake weed": "snake_weed",
    "Siam weed": "siam_weed",
    "Negative": "negative",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/vision/images")
    ap.add_argument("--unknown-out", default="data/vision/images_unknown")
    ap.add_argument("--zip-cache", default="data/vision/raw/deepweeds_images.zip")
    ap.add_argument("--labels", default="data/vision/raw/deepweeds_labels.csv")
    args = ap.parse_args()

    out_dir = Path(args.out)
    unk_dir = Path(args.unknown_out)
    zip_path = Path(args.zip_cache)
    zip_path.parent.mkdir(parents=True, exist_ok=True)

    # 1) labels.csv
    labels_path = Path(args.labels)
    if not labels_path.exists():
        r = requests.get(LABELS_URL, timeout=60)
        r.raise_for_status()
        labels_path.write_bytes(r.content)
        print(f"labels.csv: {len(labels_path.read_text().splitlines())} rows")

    # 2) images.zip via gdown
    if not zip_path.exists():
        try:
            import gdown
        except ImportError:
            print("ERROR: gdown not installed — run: .venv-mcpmv46/bin/pip install gdown", file=sys.stderr)
            return 1
        print("downloading DeepWeeds images.zip (468MB) from Google Drive ...")
        gdown.download(id=DRIVE_ID, output=str(zip_path), quiet=False)
    print(f"zip: {zip_path} ({zip_path.stat().st_size/1e6:.0f} MB)")

    # 3) parse labels + extract
    rows = []
    with open(labels_path) as f:
        header = f.readline()
        for line in f:
            parts = line.strip().split(",", 2)  # filename, label_id, species
            if len(parts) == 3:
                rows.append((parts[0], parts[1], parts[2]))
    print(f"labels parsed: {len(rows)}")

    counters = {}
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        for fname, label_id, species in rows:
            if species not in CLASS_TO_DB and species != "Negative":
                continue
            if species == "Negative":
                target_dir = unk_dir / "negative"
                sidecar = None
            elif species in UNKNOWN_SLUG:
                target_dir = unk_dir / UNKNOWN_SLUG[species]
                sidecar = None
            else:
                target_dir = out_dir / CLASS_TO_DB[species]
                sidecar = target_dir / "sources.jsonl"
            target_dir.mkdir(parents=True, exist_ok=True)
            if fname not in names:
                continue
            dest = target_dir / f"dw_{fname}"
            if not dest.exists():
                dest.write_bytes(zf.read(fname))
                if sidecar is not None:
                    with open(sidecar, "a") as sc:
                        sc.write(json.dumps({"file": dest.name, "license": "cc-by",
                                             "source": "deepweeds", "class": species}) + "\n")
            counters[target_dir.name] = counters.get(target_dir.name, 0) + 1

    print("extracted per target dir:")
    for k, v in sorted(counters.items()):
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

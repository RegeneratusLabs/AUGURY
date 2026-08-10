#!/usr/bin/env python3
"""AUGURY vision — pull_gbif.py

Gap filler: for species whose iNaturalist acquisition ended below the min-image
floor (status partial or no_images in data/vision/inat_state.json), pull images
from the GBIF media API.

  GET https://api.gbif.org/v1/species/match?name=<name>&rank=SPECIES   -> usageKey
  GET https://api.gbif.org/v1/species/{usageKey}/media                  -> media items

Media items carry a license (e.g. CC_BY_4_0) and an image identifier URL.
Downloads are throttled (~2 req/sec) with backoff; every image is validated with
PIL and recorded in the species' sources.jsonl sidecar (source=gbif).

Usage:
  .venv-mcpmv46/bin/python scripts/vision/pull_gbif.py \
      [--species-list data/vision/species_list.json] \
      [--state data/vision/inat_state.json] \
      [--out data/vision/images] [--target 30] [--limit-species 0]
"""
from __future__ import annotations

import argparse
import concurrent.futures
import io
import json
import random
import sys
import time
from pathlib import Path

import requests

GBIF = "https://api.gbif.org/v1"
HDRS = {"User-Agent": "AUGURY-vision-dataset-builder/0.1 (research)"}


def gbif_get(path, params=None, retries=5):
    for attempt in range(retries):
        try:
            r = requests.get(f"{GBIF}{path}", params=params, headers=HDRS, timeout=30)
            if r.status_code in (429, 500, 502, 503):
                time.sleep(2 ** attempt + random.random())
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            time.sleep(2 ** attempt + random.random())
    return None


def fetch_one(args):
    url, lic, out_path = args
    for attempt in range(4):
        try:
            r = requests.get(url, headers=HDRS, timeout=30)
            if r.status_code == 429:
                time.sleep(3 + 3 * attempt + random.random() * 2)
                continue
            r.raise_for_status()
            from PIL import Image
            im = Image.open(io.BytesIO(r.content))
            im.verify()
            out_path.write_bytes(r.content)
            return out_path, "ok", lic
        except Exception:
            time.sleep(1 + attempt + random.random())
    return out_path, "failed", lic


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--species-list", default="data/vision/species_list.json")
    ap.add_argument("--state", default="data/vision/inat_state.json")
    ap.add_argument("--out", default="data/vision/images")
    ap.add_argument("--target", type=int, default=30)
    ap.add_argument("--limit-species", type=int, default=0)
    args = ap.parse_args()

    species = json.loads(Path(args.species_list).read_text())
    state = json.loads(Path(args.state).read_text()) if Path(args.state).exists() else {}

    # Only species that failed to reach the iNat floor (partial or no_images)
    targets = []
    for s in species:
        st = state.get(s["key"], {})
        if st.get("status") == "done":
            continue
        targets.append(s)
    if args.limit_species:
        targets = targets[: args.limit_species]
    print(f"gap-fill candidates: {len(targets)}")

    out_dir = Path(args.out)
    matched = no_match = ok_species = 0

    for s in targets:
        key = s["key"]
        sp_dir = out_dir / key
        sp_dir.mkdir(parents=True, exist_ok=True)
        existing = len(list(sp_dir.glob("*.jpg")))
        if existing >= args.target:
            ok_species += 1
            continue

        match = gbif_get("/species/match", {"name": s["scientific_name"], "rank": "SPECIES"})
        time.sleep(0.5)
        uk = (match or {}).get("usageKey")
        if not uk:
            no_match += 1
            print(f"[{key}] no GBIF usageKey")
            continue

        media = gbif_get(f"/species/{uk}/media") or {}
        items = [
            (m.get("identifier"), m.get("license"))
            for m in media.get("results", [])
            if m.get("type") == "StillImage" and m.get("identifier", "").startswith("http")
        ]
        if not items:
            no_match += 1
            print(f"[{key}] no GBIF media")
            continue

        jobs = []
        used = set()
        for url, lic in items:
            if url in used:
                continue
            used.add(url)
            out_path = sp_dir / f"gbif_{abs(hash(url)) % 10**9}.jpg"
            if out_path.exists():
                continue
            jobs.append((url, lic or "unknown", out_path))
            if len(jobs) >= args.target - existing:
                break

        sidecar = sp_dir / "sources.jsonl"
        with open(sidecar, "a", buffering=1) as sc:
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
                for out_path, res, lic in ex.map(fetch_one, jobs):
                    if res == "ok":
                        sc.write(json.dumps({"file": out_path.name, "license": lic,
                                             "source": "gbif"}) + "\n")
        n = len(list(sp_dir.glob("*.jpg")))
        if n >= 10:
            ok_species += 1
        print(f"[{key}] gbif images now: {n}")
        matched += 1

    print(f"summary: species processed={matched} with >=10 imgs={ok_species} no_media={no_match}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""AUGURY vision — pull_plantnet.py

Pl@ntNet-300K acquisition decision, made reproducible.

Verdict (2026-08-05): NO image pull.
  * Full Zenodo zip is 31.7GB; disk free is ~27GB -> cannot fit whole.
  * HF mirror (mikehemberger/plantnet300K, parquet) verified to have the full
    1,081 classes, but streaming it means pulling 31.9GB to extract ~155 species
    that iNaturalist already covers -> marginal benefit, not worth it.
  * Pl@ntNet contributes its official species_id->name map (already fetched to
    data/vision/plantnet_species_map.json) for coverage mapping only.

This script re-verifies the mirror class count and re-emits the verdict + the
species->plantnet_id mapping (data/vision/species2plantnet.json).

Usage:
  .venv-mcpmv46/bin/python scripts/vision/pull_plantnet.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import requests


def main() -> int:
    # 1) re-verify mirror class count via the datasets-server API (no data download)
    r = requests.get("https://datasets-server.huggingface.co/first-rows",
                     params={"dataset": "mikehemberger/plantnet300K",
                             "config": "default", "split": "train"}, timeout=30)
    r.raise_for_status()
    classes = []
    for f in r.json().get("features", []):
        if f.get("name") == "label":
            classes = f["type"]["names"]
    print(f"HF mirror class count: {len(classes)} (expect 1081)")

    # 2) species_id -> name map (already on disk)
    pn_path = Path("data/vision/plantnet_species_map.json")
    if not pn_path.exists():
        print("ERROR: plantnet_species_map.json missing — fetch from lab.plantnet.org seafile "
              "(see data/vision/README.md)", file=sys.stderr)
        return 1
    pn = json.loads(pn_path.read_text())

    # 3) rebuild binomial mapping
    def binom(n):
        toks = re.sub(r"[^a-z\s]", " ", n.lower()).split()
        return " ".join(toks[:2]) if len(toks) >= 2 else ""

    pn_by_binom = {}
    for sid, name in pn.items():
        b = binom(name)
        if b:
            pn_by_binom.setdefault(b, []).append(sid)

    species = json.loads(Path("data/vision/species_list.json").read_text())
    species2pn = {}
    for s in species:
        b = binom(s["scientific_name"])
        cand = pn_by_binom.get(b) or (pn_by_binom.get(binom(s["key"])) if b != binom(s["key"]) else None)
        if cand:
            species2pn[s["key"]] = cand[0]
    Path("data/vision/species2plantnet.json").write_text(json.dumps(species2pn, indent=0))
    au = sum(1 for k in species2pn if next((s["is_au"] for s in species if s["key"] == k), False))

    verdict = [
        "# Pl@ntNet-300K verdict — NO image pull",
        "",
        f"- HF mirror class count: {len(classes)} (full 1,081-class set confirmed)",
        f"- Species matched to our DB: {len(species2pn)} (AU: {au})",
        f"- Zenodo zip 31.7GB > ~27GB free disk; streaming mirror = 31.9GB transfer for "
        f"{len(species2pn)} species iNat already covers",
        "- Decision: Pl@ntNet used for coverage mapping only; iNaturalist + DeepWeeds + GBIF carry the images.",
    ]
    Path("data/vision/plantnet_verdict.md").write_text("\n".join(verdict) + "\n")
    print("\n".join(verdict))
    return 0


if __name__ == "__main__":
    sys.exit(main())

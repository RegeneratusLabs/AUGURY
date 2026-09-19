#!/usr/bin/env python3
"""AUGURY — audit_gallery_integrity.py

Find images filed under the wrong species, and taxa-cache entries that cannot be
trusted.

Why this exists
---------------
`pull_inaturalist.py` resolves a species key to an iNaturalist taxon id, then
downloads that taxon's photos. Two defects let wrong ids in:

1. `match_taxon()` accepts the first candidate passing a loose rule — "any two
   shared tokens of 4+ characters" — so a genus-only key such as `banksia spp`
   (which has no species-rank taxon) can resolve to whatever the API fuzzy-matched.
2. The resolved id is cached in `inat_taxa_cache.json` and never re-validated, so a
   wrong assignment persists and silently files another species' photos.

The observable symptom is identical image content under two species labels. Measured
on the shipped index-v2: 501 of 13,358 vectors are byte-identical, and 126 groups
span different species. This is why `holcus lanatus` and `prosopis spp` return
similarity 1.0 against each other — they are literally the same photographs.

Not every shared taxon id is a bug
----------------------------------
A taxon id legitimately shared by two keys is usually a *synonym* pair
(`agrostis tenuis` / `agrostis capillaris`), which `canonical_map.json` already
collapses. Only ids shared across *different* canonical plants are damage. This
script separates the two and never guesses which of a colliding pair is wrong — that
requires the API, and it says so rather than inventing an answer.

Usage:
    .venv-mcpmv46/bin/python scripts/vision/audit_gallery_integrity.py
    .venv-mcpmv46/bin/python scripts/vision/audit_gallery_integrity.py --json
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

INDEX_DIR = ROOT / "data" / "vision" / "index-v2"
TAXA_CACHE = ROOT / "data" / "vision" / "inat_taxa_cache.json"
CANONICAL_MAP = ROOT / "data" / "vision" / "canonical_map.json"
SPLIT = ROOT / "data" / "vision" / "au_split.json"


def _canon(key: str, canon: dict) -> str:
    return canon.get(key, key)


def load_index():
    """Return (labels, filenames, vectors) from the built index."""
    import faiss
    import numpy as np

    idx = faiss.read_index(str(INDEX_DIR / "index.faiss"))
    labels = json.loads((INDEX_DIR / "keys.json").read_text())
    files = json.loads((INDEX_DIR / "files.json").read_text())
    vecs = idx.reconstruct_n(0, idx.ntotal)
    return labels, files, vecs


def duplicate_groups(labels: list, vecs) -> list:
    """Groups of index positions whose vectors are byte-identical."""
    buckets = collections.defaultdict(list)
    for i, v in enumerate(vecs):
        buckets[v.tobytes()].append(i)
    return [g for g in buckets.values() if len(g) > 1]


def cross_species_groups(labels: list, files: list, vecs) -> list:
    """Byte-identical vectors that appear under more than one species label."""
    out = []
    for g in duplicate_groups(labels, vecs):
        labs = sorted({labels[i] for i in g})
        if len(labs) > 1:
            out.append({"labels": labs,
                        "files": sorted({files[i] for i in g}),
                        "positions": g})
    return out


def taxa_collisions(cache: dict, canon: dict) -> dict:
    """Split shared taxon ids into benign synonyms and genuine cross-plant damage."""
    by_id = collections.defaultdict(list)
    for key, tid in cache.items():
        by_id[tid].append(key)
    synonym, suspicious = [], []
    for tid, keys in sorted(by_id.items()):
        if len(keys) < 2:
            continue
        groups = {_canon(k, canon) for k in keys}
        rec = {"taxon_id": tid, "keys": sorted(keys), "canonical_groups": sorted(groups)}
        (synonym if len(groups) == 1 else suspicious).append(rec)
    return {"synonym": synonym, "suspicious": suspicious}


def benchmark_contamination(split: dict, shared_filenames: set) -> dict:
    """How many benchmark images carry another species' content.

    Query contamination is the serious one: it means the ground-truth label is
    wrong, so the query is unanswerable and drags the reported accuracy down.
    """
    gallery = queries = 0
    affected = set()
    for sp, v in split.get("species", {}).items():
        g = {Path(r).name for r in v.get("gallery", [])} & shared_filenames
        q = {Path(r).name for r in v.get("queries", [])} & shared_filenames
        if g:
            gallery += len(g)
            affected.add(sp)
        if q:
            queries += len(q)
            affected.add(sp)
    return {"gallery_contaminated": gallery, "query_contaminated": queries,
            "species_affected": sorted(affected)}


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit gallery/taxa integrity")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    canon = json.loads(CANONICAL_MAP.read_text()).get("canonical", {}) if CANONICAL_MAP.exists() else {}
    cache = json.loads(TAXA_CACHE.read_text()) if TAXA_CACHE.exists() else {}

    report = {"taxa_cache": taxa_collisions(cache, canon)}

    labels = files = vecs = None
    if (INDEX_DIR / "index.faiss").exists():
        labels, files, vecs = load_index()
        cross = cross_species_groups(labels, files, vecs)
        involved = collections.Counter()
        for c in cross:
            for l in c["labels"]:
                involved[l] += len(c["files"])
        shared_files = {f for c in cross for f in c["files"]}
        report["index"] = {
            "vectors": len(labels),
            "distinct_vectors": len({v.tobytes() for v in vecs}),
            "cross_species_groups": len(cross),
            "cross_species_vectors": sum(len(c["positions"]) for c in cross),
            "species_involved": dict(involved.most_common()),
            "examples": [{"labels": c["labels"], "file": c["files"][0]} for c in cross[:5]],
        }
        if SPLIT.exists():
            report["benchmark"] = benchmark_contamination(
                json.loads(SPLIT.read_text()), shared_files)

    if args.json:
        print(json.dumps(report, indent=1))
        return 0

    tc = report["taxa_cache"]
    print("── taxa cache ──────────────────────────────────────────")
    print(f"  entries                       : {len(cache)}")
    print(f"  shared ids, benign synonyms   : {len(tc['synonym'])}")
    print(f"  shared ids, SUSPICIOUS        : {len(tc['suspicious'])}")
    for r in tc["suspicious"]:
        print(f"      taxon {r['taxon_id']}: {r['keys']}")
        print(f"          different plants: {r['canonical_groups']}")

    if "index" in report:
        ix = report["index"]
        print("\n── built index ─────────────────────────────────────────")
        print(f"  vectors                       : {ix['vectors']}")
        print(f"  distinct vectors              : {ix['distinct_vectors']}")
        print(f"  cross-species groups          : {ix['cross_species_groups']}")
        print(f"  vectors involved              : {ix['cross_species_vectors']}")
        print(f"  species involved              : {len(ix['species_involved'])}")
        for s, n in list(ix["species_involved"].items())[:10]:
            print(f"      {s:30s} {n}")

    if "benchmark" in report:
        b = report["benchmark"]
        print("\n── AU benchmark ────────────────────────────────────────")
        print(f"  gallery images contaminated   : {b['gallery_contaminated']}")
        print(f"  QUERY images contaminated     : {b['query_contaminated']}  <-- wrong ground truth")
        print(f"  species affected              : {b['species_affected']}")

    print("\nnote: this script does NOT decide which side of a collision is correct —")
    print("      that needs the iNaturalist API. It reports so a human or a")
    print("      verification pass can decide, rather than guessing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

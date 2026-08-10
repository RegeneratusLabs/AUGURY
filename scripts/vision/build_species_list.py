#!/usr/bin/env python3
"""AUGURY vision — build_species_list.py

Loads the species database (data/research/database-merged.json — the durable superset;
2,230 species, 188 AU-tagged) and emits a canonical, vision-oriented species list:

    data/vision/species_list.json
      [ { "key": "geranium phaeum",
          "scientific_name": "Geranium phaeum",
          "common_names": ["Geranium phaeum"],
          "regions": [ { "region": "Europe", "indicators": { "Moisture": "...", ... } } ],
          "nutrients": {...},
          "is_au": false }, ... ]

The species list is the single source of truth for the image acquisition phase and
for auto-generating assistant turns in the LLaMA-Factory dataset (DB stays the
label source — guard rail 6).

Usage:
    .venv-mcpmv46/bin/python scripts/vision/build_species_list.py [--db data/research/database-active.json] [--out data/vision/species_list.json]
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path


def extract_indicators(region_value) -> dict:
    """Handle both shapes: {Moisture: ...} and {indicators: {Moisture: ...}}."""
    if isinstance(region_value, dict):
        if "indicators" in region_value and isinstance(region_value["indicators"], dict):
            return region_value["indicators"]
        # plain indicator map — drop non-indicator keys if any
        return {k: v for k, v in region_value.items() if isinstance(v, str)}
    return {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/research/database-merged.json")
    ap.add_argument("--out", default="data/vision/species_list.json")
    args = ap.parse_args()

    db_path = Path(args.db)
    db = json.loads(db_path.read_text())
    if not isinstance(db, dict):
        print(f"ERROR: expected dict keyed by lowercase scientific name in {db_path}", file=sys.stderr)
        return 1

    rows = []
    for key, val in db.items():
        scientific_name = (val.get("scientific_name") or key).strip()
        common_names = val.get("common_names") or []
        if isinstance(common_names, str):
            common_names = [common_names]
        # de-dup, keep order, drop empties
        seen = set()
        common_names = [c for c in common_names if c and not (c in seen or seen.add(c))]

        regions = []
        raw_regions = val.get("regions") or {}
        if isinstance(raw_regions, dict):
            for rname, rval in raw_regions.items():
                ind = extract_indicators(rval)
                if not ind:
                    continue
                regions.append({"region": rname, "indicators": ind})
        elif isinstance(raw_regions, list):
            for r in raw_regions:
                if isinstance(r, dict) and "region" in r:
                    regions.append({"region": r["region"], "indicators": extract_indicators(r)})

        is_au = any("australia" in (r["region"] or "").lower() for r in regions)

        rows.append({
            "key": key,
            "scientific_name": scientific_name,
            "common_names": common_names,
            "regions": regions,
            "nutrients": val.get("nutrients") or {},
            "is_au": is_au,
        })

    rows.sort(key=lambda r: r["key"])
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(rows, indent=1, ensure_ascii=False))

    # Stats
    n_au = sum(1 for r in rows if r["is_au"])
    n_with_ind = sum(1 for r in rows if any(ri["indicators"] for ri in r["regions"]))
    n_real_cn = sum(1 for r in rows if any(
        c.lower().strip() != r["scientific_name"].lower().strip() for c in r["common_names"]))
    region_counter = collections.Counter()
    for r in rows:
        for ri in r["regions"]:
            region_counter[ri["region"]] += 1

    print(f"species total      : {len(rows)}")
    print(f"AU-tagged          : {n_au}")
    print(f"with indicators    : {n_with_ind}")
    print(f"with real common nm: {n_real_cn}")
    print("region histogram    :", dict(region_counter.most_common(8)))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

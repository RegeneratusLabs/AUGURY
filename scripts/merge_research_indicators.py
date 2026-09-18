#!/usr/bin/env python3
"""AUGURY — merge_research_indicators.py

Merges a researched indicator file into `database-merged.json`.

Accepts files shaped like:
  {"species": [{"scientific_name", "common_names", "region", "indicators": {...},
                "nutrients": [{...}], "habitat", "sources": [{name,url,used_for}]}],
   "not_found": [...]}

Behaviour:
  * adds a new species row when absent, or fills a region when the species exists
    but has no indicators for that region (never overwrites populated indicators)
  * keeps per-indicator provenance (source names + urls) so answers can cite
  * records the habitat line under "General indicators" when present
  * strips the research layer's inline "[Sources: …]" citations from the visible
    indicator text (they are preserved in provenance instead)

Usage:
  .venv-mcpmv46/bin/python scripts/merge_research_indicators.py \
      data/research/soil_indicators_10_species.json [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CITE_RE = re.compile(r"\s*\[Sources?:.*?\]\s*", re.I | re.S)


def clean(text: str) -> str:
    """Remove inline citation blocks from user-visible indicator text."""
    return re.sub(r"\s{2,}", " ", CITE_RE.sub(" ", text or "")).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("research_file")
    ap.add_argument("--db", default=str(ROOT / "data" / "research" / "database-merged.json"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    db_path = Path(args.db)
    db = json.loads(db_path.read_text())
    doc = json.loads(Path(args.research_file).read_text())

    added, filled, skipped = [], [], []
    for s in doc.get("species", []):
        sci = (s.get("scientific_name") or "").strip()
        if not sci:
            continue
        key = sci.lower()
        region = s.get("region") or "Australia"

        indicators = {}
        for k, v in (s.get("indicators") or {}).items():
            txt = clean(v)
            if txt:
                indicators[k] = txt
        nutrients = []
        for n in s.get("nutrients") or []:
            if not n.get("nutrient"):
                continue
            nutrients.append({
                "nutrient": (n.get("nutrient") or "").capitalize(),
                "relationship": n.get("relationship", ""),
                "detail": clean(n.get("detail", "")),
                "source": n.get("source", ""),
                "confidence": n.get("confidence", ""),
            })
        if s.get("habitat"):
            indicators.setdefault("General indicators", clean(s["habitat"]))
        if not indicators:
            skipped.append(key)
            continue

        provenance = {
            "added_by": "merge_research_indicators.py",
            "added_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "research_file": Path(args.research_file).name,
            "sources": s.get("sources") or [],
        }

        if key not in db:
            db[key] = {
                "scientific_name": sci,
                "common_names": list(dict.fromkeys(
                    [c for c in (s.get("common_names") or []) if c] or [sci])),
                "regions": {region: {"indicators": indicators,
                                     "source": "AUGURY research layer"}},
                "nutrients": {"claims": nutrients},
                "provenance": provenance,
            }
            added.append({"key": key, "indicators": list(indicators),
                          "nutrients": len(nutrients)})
            continue

        row = db[key]
        reg = (row.get("regions") or {}).get(region) or {}
        if (reg.get("indicators") or {}):
            skipped.append(key + " (already populated)")
            continue
        row.setdefault("regions", {})[region] = {
            "indicators": indicators, "source": "AUGURY research layer"}
        for cn in s.get("common_names") or []:
            if cn and cn not in row.setdefault("common_names", []):
                row["common_names"].append(cn)
        if nutrients and not (row.get("nutrients") or {}).get("claims"):
            row["nutrients"] = {"claims": nutrients}
        row.setdefault("provenance", {}).update(provenance)
        filled.append({"key": key, "indicators": list(indicators)})

    print(f"[research-merge] added {len(added)} new, filled {len(filled)} existing, "
          f"skipped {len(skipped)}")
    for a in added:
        print(f"   + {a['key']:28s} {len(a['indicators'])} indicators, {a['nutrients']} nutrients")
    for f in filled:
        print(f"   ~ {f['key']:28s} filled {len(f['indicators'])} indicators")
    for s in skipped:
        print(f"   = {s}")

    if args.dry_run:
        print("[research-merge] dry run — nothing written")
        return 0

    backup = db_path.with_suffix(".json.bak")
    if not backup.exists():
        shutil.copy2(db_path, backup)
        print(f"[research-merge] backup: {backup}")
    db_path.write_text(json.dumps(db, indent=1))
    print(f"[research-merge] wrote {db_path} ({len(db)} species)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""AUGURY — merge_enriched_species.py

Adds species that exist in the mining/research layer but are missing from
`database-merged.json` — the "Paterson's curse" class of gap, where a farmer
names a major weed and gets a refusal.

Source of truth: `data/mining/augury_enriched_database.json`, whose entries
carry individually sourced `soil_claims` / `nutrient_claims` (NSW DPI,
Agriculture Victoria, Weeds Australia, …) produced by the mining pipeline.
Nothing is invented here — every indicator string is derived from a claim that
already carries a source, and the source is recorded per claim.

Merging is conservative:
  * only species ABSENT from the target DB are added (never overwrite curated data)
  * a species is added only if it has at least one claim
  * `region` comes from the claim entry (AU-only entries here)
  * each written indicator records its claim source so the answer can cite it

Usage:
  .venv-mcpmv46/bin/python scripts/merge_enriched_species.py \
      [--dry-run] [--out data/research/database-merged.json]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# mining soil property -> AUGURY indicator key (existing DB vocabulary)
PROPERTY_MAP = {
    "ph": "Soil pH",
    "acidity": "Soil pH",
    "fertility": "Fertility",
    "general fertility": "Fertility",
    "moisture": "Moisture",
    "drainage": "Moisture",
    "structure": "Structure",
    "soil structure": "Structure",
    "compaction": "Structure",
    "salinity": "Salinity",
    "sodicity": "Salinity",
    "organic matter": "Organic matter",
    "organic_matter": "Organic matter",
    "organic matter decay": "Organic matter",
    "soil_biology": "Soil biology",
    "soil_type": "Soil type",
    "disturbance": "Disturbance",
}
MIN_CONFIDENCE = {"high", "medium"}


def claim_ok(c: dict) -> bool:
    """Accept a claim on its own (per-source) confidence.

    NOTE: the mining layer's `aggregate_confidence` measures how many
    independent sources corroborate a claim, so a well-sourced single-source
    claim legitimately reads "low" there. Filtering on it would discard good
    data (e.g. Paterson's curse), so quality is judged per claim instead.
    """
    return (c.get("confidence") or "").lower() in MIN_CONFIDENCE


def claim_sentence(c: dict) -> str:
    rel = (c.get("relationship") or "").strip().rstrip(".")
    detail = (c.get("detail") or "").strip().rstrip(".")
    if rel and detail:
        return f"{rel} — {detail}"
    return rel or detail


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--enriched", default=str(ROOT / "data" / "mining" / "augury_enriched_database.json"))
    ap.add_argument("--out", default=str(ROOT / "data" / "research" / "database-merged.json"))
    ap.add_argument("--report", default=str(ROOT / "data" / "research" / "enriched-merge-report.json"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    db = json.loads(Path(args.out).read_text())
    enriched = json.loads(Path(args.enriched).read_text())

    added, skipped_no_claims, skipped_present = [], [], []
    for s in enriched.get("species", []):
        sci = (s.get("scientific_name") or "").strip()
        if not sci:
            continue
        key = sci.lower()
        if key in db:
            skipped_present.append(key)
            continue
        regions_list = s.get("region") or ["Australia"]
        region = "Australia" if "Australia" in regions_list else regions_list[0]

        indicators: "OrderedDict[str, str]" = OrderedDict()
        sources: "OrderedDict[str, list]" = OrderedDict()
        for c in s.get("soil_claims") or []:
            if not claim_ok(c):
                continue
            prop = (c.get("property") or "").strip().lower()
            mapped = PROPERTY_MAP.get(prop)
            if not mapped:
                continue
            text = claim_sentence(c)
            if not text:
                continue
            indicators[mapped] = text
            sources.setdefault(mapped, []).append(
                {"detail": text, "source": c.get("source", ""),
                 "confidence": c.get("aggregate_confidence") or c.get("confidence", "")})

        nutrients = []
        for c in s.get("nutrient_claims") or []:
            if not claim_ok(c):
                continue
            nutrients.append({
                "nutrient": (c.get("nutrient") or "").capitalize(),
                "relationship": c.get("relationship", ""),
                "detail": c.get("detail", ""),
                "source": c.get("source", ""),
                "confidence": c.get("aggregate_confidence") or c.get("confidence", ""),
            })

        if not indicators:
            skipped_no_claims.append(key)
            continue

        # a compact general line so the formatter always has something to say
        general = "; ".join(list(indicators.values())[:4])
        if general:
            indicators["General indicators"] = general

        db[key] = {
            "scientific_name": sci,
            "common_names": list(dict.fromkeys(
                [c for c in (s.get("common_names") or []) if c] or [sci])),
            "regions": {region: {"indicators": dict(indicators), "source": "AUGURY mining layer"}},
            "nutrients": {"claims": nutrients},
            "provenance": {
                "added_by": "merge_enriched_species.py",
                "added_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "claim_sources": sources,
                "overall_confidence": s.get("overall_confidence", ""),
            },
        }
        added.append({"key": key, "region": region,
                      "indicators": list(indicators), "nutrients": len(nutrients),
                      "sources": sorted({c.get("source", "") for c in
                                         (s.get("soil_claims") or []) + (s.get("nutrient_claims") or [])
                                         if c.get("source")})})

    report = {"target": args.out, "added": added,
              "added_count": len(added),
              "skipped_already_present": len(skipped_present),
              "skipped_no_usable_claims": skipped_no_claims}
    Path(args.report).write_text(json.dumps(report, indent=1))

    print(f"[merge] added {len(added)} species "
          f"(skipped {len(skipped_present)} present, {len(skipped_no_claims)} claim-less)")
    for a in added:
        print(f"   + {a['key']:30s} {a['region']:10s} {len(a['indicators'])} indicators "
              f"| src={', '.join(a['sources'])[:60]}")

    if args.dry_run:
        print("[merge] dry run — nothing written")
        return 0

    backup = Path(args.out).with_suffix(".json.bak")
    if not backup.exists():
        shutil.copy2(args.out, backup)
        print(f"[merge] backup: {backup}")
    Path(args.out).write_text(json.dumps(db, indent=1))
    print(f"[merge] wrote {args.out} ({len(db)} species)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

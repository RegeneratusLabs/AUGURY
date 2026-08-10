#!/usr/bin/env python3
"""
Extract unmerged species data from AU Phase 2 research files
and merge into the lookup database + merged database.

AU Phase 2 files: augury-research-output/au-phase-2/*.md
These contain real indicator data in markdown that was never merged.
"""

import json
import os
import re
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "scripts"))
from species_lookup import SpeciesDB

AU_DIR = PROJECT / "augury-research-output" / "au-phase-2"


def parse_au_phase2(text):
    """Parse AU Phase 2 markdown into {indicator_key: value}."""
    indicators = {}
    common_names = []

    # Extract common name from title: "# Scientific — Common Name"
    m = re.search(r'^#\s+([^—\n]+)—\s*([^\n]+)', text, re.MULTILINE)
    if m:
        cn = m.group(2).strip()
        if cn and cn.lower() != m.group(1).strip().lower():
            common_names.append(cn)
    # Also from YAML common_names list
    if text.startswith("---"):
        m = re.search(r'common_names:\s*\[([^\]]+)\]', text)
        if m:
            for cn in re.findall(r'"([^"]+)"', m.group(1)):
                common_names.append(cn)

    # Find "Indicator Data" section (## or ### header)
    m = re.search(r'^##?\s*Indicator Data', text, re.MULTILINE)
    if m:
        section = text[m.end():]
        m2 = re.search(r'\n## ', section)
        if m2:
            section = section[:m2.start()]

        for line in section.split("\n"):
            line = line.strip()
            bm = re.match(r'-\s*\*\*([^:*]+):\*\*\s*(.+)', line)
            if bm:
                key = bm.group(1).strip().lower()
                val = bm.group(2).strip()
                if key == "salinity":
                    indicators["Salinity"] = val
                elif key in ("aridity", "rainfall", "waterlogging", "drainage", "moisture"):
                    indicators["Moisture"] = indicators.get("Moisture", "") + ("; " if indicators.get("Moisture") else "") + val
                elif key in ("soil type", "soil texture", "texture", "compaction", "structure"):
                    indicators["Structure"] = indicators.get("Structure", "") + ("; " if indicators.get("Structure") else "") + val
                elif key in ("ph", "acidity", "alkalinity", "soil ph"):
                    indicators["Soil pH"] = val
                elif key in ("fertility", "fertile"):
                    indicators["Fertility"] = val
                elif key in ("nutrients", "nutrition"):
                    indicators["Nutrients"] = val
                else:
                    indicators["General indicators"] = indicators.get("General indicators", "") + ("; " if indicators.get("General indicators") else "") + val

    # Also check for "What it indicates" style (Phase 1 freeform)
    if not indicators:
        m = re.search(r'\*\*What it indicates:\*\*\s*([^#\n]+)', text)
        if m:
            indicators["General indicators"] = m.group(1).strip()

    # YAML frontmatter style: moisture:/pH:/fertility: nested with value:
    if not indicators and text.startswith("---"):
        # Find where YAML ends (second --- or ## header)
        end = text.find("\n---", 3)
        yaml_text = text[3:end] if end != -1 else text[3:]
        dim_map = {
            "moisture": "Moisture",
            "pH": "Soil pH",
            "fertility": "Fertility",
            "structure": "Structure",
            "salinity": "Salinity",
        }
        for dim, std_key in dim_map.items():
            m = re.search(rf'^{dim}:\n\s+value:\s*"([^"]*)"', yaml_text, re.MULTILINE)
            if m and m.group(1).strip():
                indicators[std_key] = m.group(1).strip()

    return indicators, common_names


def main():
    db = SpeciesDB()
    merged_path = PROJECT / "data" / "research" / "database-merged.json"
    with open(merged_path) as f:
        merged = json.load(f)

    added = 0
    updated = 0
    for fname in sorted(os.listdir(AU_DIR)):
        if not fname.endswith(".md") or fname == "crawl-log.md":
            continue
        sp_key = fname.replace("species_au_", "").replace(".md", "").replace("_", " ")
        with open(AU_DIR / fname) as f:
            text = f.read()

        inds, cns = parse_au_phase2(text)
        if not inds:
            print(f"  SKIP {sp_key}: no indicator data parsed")
            continue
        common = cns if cns else [sp_key]

        # Update in-memory DB
        if sp_key in db._species:
            for reg in db._species[sp_key].get("regions", {}):
                if "indicators" not in db._species[sp_key]["regions"][reg]:
                    db._species[sp_key]["regions"][reg]["indicators"] = {}
                db._species[sp_key]["regions"][reg]["indicators"].update(inds)
            # Replace placeholder common names (== scientific) with real ones
            sci_lower = db._species[sp_key]["scientific_name"].lower()
            cur = db._species[sp_key].get("common_names", [])
            if not cur or all(c.strip().lower() == sci_lower for c in cur):
                db._species[sp_key]["common_names"] = common
            updated += 1
        else:
            db._species[sp_key] = {
                "scientific_name": sp_key,
                "common_names": common,
                "regions": {"Australia": {"indicators": inds}},
            }
            added += 1

        # Update merged DB
        if sp_key in merged:
            merged[sp_key].setdefault("regions", {}).setdefault("Australia", {}).setdefault("indicators", {}).update(inds)
            sci_lower = merged[sp_key].get("scientific_name", sp_key).lower()
            cur = merged[sp_key].get("common_names", [])
            if not cur or all(c.strip().lower() == sci_lower for c in cur):
                merged[sp_key]["common_names"] = common
        else:
            merged[sp_key] = {
                "scientific_name": sp_key,
                "common_names": common,
                "regions": {"Australia": {"indicators": inds}},
            }

    # Persist merged DB
    with open(merged_path, "w") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)

    print(f"\n=== Merge complete ===")
    print(f"Species added: {added}")
    print(f"Species updated: {updated}")
    print(f"Merged DB now: {len(merged)} species")

    # Verify a couple
    for sp in ["atriplex nummularia", "themeda triandra"]:
        info = merged.get(sp, {})
        inds = info.get("regions", {}).get("Australia", {}).get("indicators", {})
        print(f"\n{sp}: {len(inds)} indicators")
        for k, v in list(inds.items())[:3]:
            print(f"  {k}: {v[:60]}")


if __name__ == "__main__":
    main()

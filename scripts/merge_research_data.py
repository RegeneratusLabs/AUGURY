#!/usr/bin/env python3
"""
Merge Phase 1 + Phase 2 research output into the active database.
Uses PyYAML for proper YAML parsing. Handles both YAML and free-form files.
"""

import json
import os
import re
import sys
from pathlib import Path

PROJECT = Path("/home/jthomson/AUGURY")
ACTIVE_DB = PROJECT / "augury-research-pack" / "database-active.json"
PHASE1_DIR = PROJECT / "augury-research-output" / "output" / "03-species-verification"
PHASE2_DIR = PROJECT / "augury-research-output" / "au-phase-2"
OUTPUT_DB = PROJECT / "augury-research-pack" / "database-merged.json"
REPORT = PROJECT / "augury-research-pack" / "merge-report.md"

try:
    import yaml
except ImportError:
    yaml = None


def parse_yaml_frontmatter(text):
    """Parse YAML frontmatter robustly. Tries progressively shorter text."""
    if not text.startswith("---"):
        return None
    rest = text[3:]  # skip opening ---
    
    # Strategy 1: Try the whole rest
    try:
        return yaml.safe_load(rest)
    except yaml.YAMLError:
        pass
    
    # Strategy 2: Split at first ## or # heading
    cut = re.split(r'\n(?=##?\s)', rest, maxsplit=1)
    if len(cut) > 1:
        try:
            return yaml.safe_load(cut[0])
        except yaml.YAMLError:
            pass
    
    # Strategy 3: Progressive trimming
    lines = rest.split('\n')
    for i in range(len(lines), 0, -1):
        try:
            return yaml.safe_load('\n'.join(lines[:i]))
        except yaml.YAMLError:
            continue
    
    return None

def parse_yaml_frontmatter(text): pass
def extract_indicators_from_yaml(yaml_data):
    """Extract indicator dimensions from parsed YAML."""
    indicators = {}
    dims = ["moisture", "pH", "fertility", "structure", "salinity"]
    for dim in dims:
        d = yaml_data.get(dim, {})
        if isinstance(d, dict):
            val = d.get("value", "")
            if val:
                indicators[dim.capitalize()] = val
        elif isinstance(d, str) and d:
            indicators[dim.capitalize()] = d
    return indicators


def extract_nutrients_from_yaml(yaml_data):
    """Extract nutrient claims from parsed YAML."""
    nutrients = yaml_data.get("nutrients", [])
    if not nutrients:
        return []
    if isinstance(nutrients, list):
        claims = []
        for n in nutrients:
            if isinstance(n, dict):
                claims.append({
                    "nutrient": n.get("nutrient", ""),
                    "relationship": n.get("relationship", ""),
                    "confidence": n.get("confidence", "low")
                })
        return claims
    return []


def extract_regions_from_yaml(yaml_data):
    """Extract region list from YAML."""
    regions = yaml_data.get("regions", [])
    if isinstance(regions, list):
        return regions
    return []


def main():
    with open(ACTIVE_DB) as f:
        db = json.load(f)
    
    stats = {
        "phase1_enriched": 0,
        "phase1_new": 0,
        "phase2_new": 0,
        "phase2_yaml_success": 0,
        "phase2_freeform": 0,
        "errors": []
    }
    
    # ── Phase 1: Species verification files ──
    if PHASE1_DIR.exists():
        for fname in sorted(os.listdir(PHASE1_DIR)):
            if not fname.endswith(".md"):
                continue
            path = PHASE1_DIR / fname
            with open(path) as f:
                text = f.read()
            
            sp_key = fname.replace(".md", "").replace("_", " ")
            
            # Parse YAML (Phase 1 uses standard ---...---)
            yaml_data = parse_yaml_frontmatter(text)
            if not yaml_data:
                stats["errors"].append(f"P1 {fname}: YAML parse failed")
                continue
            
            # Check for AU data in regional_notes
            has_au = False
            regional = yaml_data.get("regional_notes", {})
            if isinstance(regional, dict) and "australia" in {k.lower() for k in regional}:
                has_au = True
            if isinstance(regional, str) and "australia" in regional.lower():
                has_au = True
            
            indicators = extract_indicators_from_yaml(yaml_data)
            nutrients = extract_nutrients_from_yaml(yaml_data)
            regions = extract_regions_from_yaml(yaml_data)
            
            if sp_key in db:
                # Enrich existing species
                if has_au and "Australia" not in db[sp_key].get("regions", {}):
                    if "regions" not in db[sp_key]:
                        db[sp_key]["regions"] = {}
                    db[sp_key]["regions"]["Australia"] = {"indicators": indicators}
                # Also add UK region if indicated
                if "UK" in regions and "UK" not in db[sp_key].get("regions", {}):
                    if "regions" not in db[sp_key]:
                        db[sp_key]["regions"] = {}
                    db[sp_key]["regions"]["UK"] = {"indicators": indicators}
                stats["phase1_enriched"] += 1
            else:
                # New species
                sci = yaml_data.get("species", sp_key)
                cns = yaml_data.get("common_names", [sp_key])
                if isinstance(cns, str):
                    cns = [cns]
                
                new_regions = {}
                if indicators:
                    new_regions["Europe"] = {"indicators": indicators}
                    if has_au:
                        new_regions["Australia"] = {"indicators": indicators}
                
                db[sp_key] = {
                    "scientific_name": sci,
                    "common_names": cns,
                    "regions": new_regions,
                    "nutrients": {"claims": nutrients}
                }
                stats["phase1_new"] += 1
    else:
        stats["errors"].append("Phase 1 directory not found")
    
    # ── Phase 2: AU species files ──
    if PHASE2_DIR.exists():
        for fname in sorted(os.listdir(PHASE2_DIR)):
            if not fname.endswith(".md") or fname == "crawl-log.md":
                continue
            path = PHASE2_DIR / fname
            with open(path) as f:
                text = f.read()
            
            # Try YAML first (without closing ---)
            yaml_data = parse_yaml_frontmatter(text)
            
            if yaml_data:
                stats["phase2_yaml_success"] += 1
                sp_key = (yaml_data.get("species", fname.replace("species_au_", "").replace(".md", "").replace("_", " "))).lower()
                cns = yaml_data.get("common_names", [sp_key.split()[-1:]])
                if isinstance(cns, str):
                    cns = [cns]
                
                indicators = extract_indicators_from_yaml(yaml_data)
                nutrients = extract_nutrients_from_yaml(yaml_data)
                
                if sp_key in db:
                    if "Australia" not in db[sp_key].get("regions", {}):
                        if "regions" not in db[sp_key]:
                            db[sp_key]["regions"] = {}
                        db[sp_key]["regions"]["Australia"] = {"indicators": indicators}
                    stats["phase1_enriched"] += 1
                else:
                    db[sp_key] = {
                        "scientific_name": yaml_data.get("species", sp_key),
                        "common_names": cns,
                        "regions": {"Australia": {"indicators": indicators}} if indicators else {},
                        "nutrients": {"claims": nutrients}
                    }
                    stats["phase2_new"] += 1
            else:
                # Free-form markdown — extract from section headers
                stats["phase2_freeform"] += 1
                sp_key_base = fname.replace("species_au_", "").replace(".md", "").replace("_", " ")
                
                # Extract species name from ## heading
                m = re.search(r'^\*\*([^*]+)\*\*', text, re.MULTILINE) or re.search(r'^#\s+([^(]+)', text, re.MULTILINE)
                sci_name = m.group(1).strip() if m else sp_key_base
                
                # Try to extract common name from line after species name
                cn_match = re.search(r'\*\*Common names?:\*\*\s*([^*\n]+)', text)
                cns = [cn_match.group(1).strip()] if cn_match else [sp_key_base]
                
                # Extract indicators from "What it indicates:" or similar
                ind_match = re.search(r'\*\*What it indicates:\*\*\s*([^#\n]+)', text)
                indicators = {}
                if ind_match:
                    ind_text = ind_match.group(1).strip()
                    # Try to split by comma or semicolon for multiple indicators
                    parts = [p.strip() for p in re.split(r'[,;]', ind_text)]
                    if parts:
                        indicators["General indicators"] = ind_text
                
                # Extract AU source mentions
                source_section = re.search(r'## AU Sources\s*\n(.*?)(?=\n##|\Z)', text, re.DOTALL)
                
                sp_key = sci_name.lower()
                if sp_key in db:
                    if "Australia" not in db[sp_key].get("regions", {}) and indicators:
                        db[sp_key]["regions"]["Australia"] = {"indicators": indicators}
                    stats["phase1_enriched"] += 1
                else:
                    db[sp_key] = {
                        "scientific_name": sci_name,
                        "common_names": cns,
                        "regions": {"Australia": {"indicators": indicators}} if indicators else {},
                        "nutrients": {"claims": []}
                    }
                    stats["phase2_new"] += 1
    else:
        stats["errors"].append("Phase 2 directory not found")
    
    # ── Write merged database ──
    with open(OUTPUT_DB, "w") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)
    
    # ── Write merge report ──
    with open(REPORT, "w") as f:
        f.write(f"# Research Merge Report\n\n")
        f.write(f"**Date:** 28 July 2026\n\n")
        f.write(f"## Summary\n\n")
        f.write(f"| Metric | Count |\n")
        f.write(f"|---|---|\n")
        f.write(f"| Phase 1 species enriched (existing DB) | {stats['phase1_enriched']} |\n")
        f.write(f"| Phase 1 new species added | {stats['phase1_new']} |\n")
        f.write(f"| Phase 2 YAML files parsed | {stats['phase2_yaml_success']} |\n")
        f.write(f"| Phase 2 free-form files parsed | {stats['phase2_freeform']} |\n")
        f.write(f"| Phase 2 new AU species added | {stats['phase2_new']} |\n")
        f.write(f"| Total species after merge | {len(db)} |\n")
        f.write(f"| Errors | {len(stats['errors'])} |\n\n")
        
        # Count AU species in merged DB
        au_count = sum(1 for v in db.values() if "Australia" in v.get("regions", {}))
        f.write(f"| AU species in merged DB | {au_count} |\n")
        
        if stats["errors"]:
            f.write(f"\n## Errors ({len(stats['errors'])})\n\n")
            for err in stats["errors"][:20]:
                f.write(f"- {err}\n")
            if len(stats['errors']) > 20:
                f.write(f"- ... and {len(stats['errors']) - 20} more\n")
    
    au_count = sum(1 for v in db.values() if "Australia" in v.get("regions", {}))
    print(f"Merged database: {OUTPUT_DB} ({len(db)} species, {au_count} AU)")
    print(f"Phase 1 enriched: {stats['phase1_enriched']}, new: {stats['phase1_new']}")
    print(f"Phase 2 YAML: {stats['phase2_yaml_success']}, freeform: {stats['phase2_freeform']}, new AU: {stats['phase2_new']}")
    print(f"AU species total: {au_count}")
    print(f"Errors: {len(stats['errors'])}")


if __name__ == "__main__":
    main()

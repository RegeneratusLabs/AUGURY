#!/usr/bin/env python3
"""Merge Phase 1 + Phase 2 research into the active database (clean version)."""
import json, os, re, sys, yaml
from pathlib import Path

P = Path("/home/jthomson/AUGURY")
ACTIVE_DB = P / "augury-research-pack" / "database-active.json"
P1 = P / "augury-research-output" / "output" / "03-species-verification"
P2 = P / "augury-research-output" / "au-phase-2"
OUT = P / "augury-research-pack" / "database-merged.json"
RPT = P / "augury-research-pack" / "merge-report.md"

with open(ACTIVE_DB) as f: db = json.load(f)

def parse_yaml(text):
    if not text.startswith("---"): return None
    rest = text[3:]
    for s1 in [rest, re.split(r'\n(?=##?\s)', rest, maxsplit=1)[0]]:
        try: return yaml.safe_load(s1)
        except: pass
    lines = rest.split('\n')
    for i in range(len(lines), 0, -1):
        try: return yaml.safe_load('\n'.join(lines[:i]))
        except: continue
    return None

def inds_from(y):
    dims = {"moisture", "pH", "fertility", "structure", "salinity"}
    out = {}
    for d in dims:
        v = y.get(d, {})
        if isinstance(v, dict): val = v.get("value", "")
        elif isinstance(v, str): val = v
        else: val = ""
        if val: out[d.capitalize()] = val
    return out

def nuts_from(y):
    nuts = y.get("nutrients", [])
    if not isinstance(nuts, list): return []
    return [{"nutrient": n.get("nutrient",""), "relationship": n.get("relationship",""),
             "confidence": n.get("confidence","low")} for n in nuts if isinstance(n, dict) and n.get("nutrient")]

stats = {"enriched": 0, "new": 0, "p2_yaml": 0, "p2_free": 0, "p2_new": 0, "errors": []}

# Phase 1
for fname in sorted(os.listdir(P1)):
    if not fname.endswith(".md"): continue
    with open(P1 / fname) as f: text = f.read()
    sp_key = fname.replace(".md","").replace("_"," ")
    y = parse_yaml(text)
    if not y: stats["errors"].append(f"P1:{fname}"); continue
    ind = inds_from(y)
    nuts = nuts_from(y)
    regions = y.get("regions", [])
    has_au = "australia" in str(y.get("regional_notes","")).lower()
    if sp_key in db:
        if has_au and "Australia" not in db[sp_key].get("regions",{}):
            db[sp_key].setdefault("regions",{})["Australia"] = {"indicators": ind}
        if ind:
            db[sp_key].setdefault("regions",{}).setdefault("Europe",{"indicators": ind})
        stats["enriched"] += 1
    else:
        sci = y.get("species", sp_key)
        cns = y.get("common_names", [sp_key])
        if isinstance(cns, str): cns = [cns]
        regs = {}
        if ind: regs["Europe"] = {"indicators": ind}
        if has_au: regs["Australia"] = {"indicators": ind}
        db[sp_key] = {"scientific_name": sci, "common_names": cns, "regions": regs, "nutrients": {"claims": nuts}}
        stats["new"] += 1

# Phase 2
for fname in sorted(os.listdir(P2)):
    if not fname.endswith(".md") or fname == "crawl-log.md": continue
    with open(P2 / fname) as f: text = f.read()
    sp_base = fname.replace("species_au_","").replace(".md","").replace("_"," ")
    y = parse_yaml(text)
    if y:
        stats["p2_yaml"] += 1
        sp_key = (y.get("species", sp_base)).lower()
        cns = y.get("common_names", [sp_base])
        if isinstance(cns, str): cns = [cns]
        ind = inds_from(y)
        nuts = nuts_from(y)
        if sp_key in db:
            if "Australia" not in db[sp_key].get("regions",{}) and ind:
                db[sp_key].setdefault("regions",{})["Australia"] = {"indicators": ind}
            stats["enriched"] += 1
        else:
            db[sp_key] = {"scientific_name": y.get("species",sp_base), "common_names": cns,
                          "regions": {"Australia": {"indicators": ind}} if ind else {},
                          "nutrients": {"claims": nuts}}
            stats["p2_new"] += 1
    else:
        stats["p2_free"] += 1
        sp_key = sp_base.lower()
        sci = sp_base
        cns = [sp_base]
        ind = {}
        m = re.search(r'\*\*What it indicates:\*\*\s*([^#\n]+)', text)
        if m: ind["General indicators"] = m.group(1).strip()
        if sp_key in db:
            if "Australia" not in db[sp_key].get("regions",{}) and ind:
                db[sp_key].setdefault("regions",{})["Australia"] = {"indicators": ind}
            stats["enriched"] += 1
        else:
            db[sp_key] = {"scientific_name": sci, "common_names": cns,
                          "regions": {"Australia": {"indicators": ind}} if ind else {},
                          "nutrients": {"claims": []}}
            stats["p2_new"] += 1

with open(OUT, "w") as f: json.dump(db, f, indent=2, ensure_ascii=False)
au = sum(1 for v in db.values() if "Australia" in v.get("regions",{}))
with open(RPT, "w") as f:
    f.write(f"# Merge Report\n\nDB: {len(db)} spp ({au} AU)\nP1 enriched:{stats['enriched']} new:{stats['new']}\nP2 YAML:{stats['p2_yaml']} free:{stats['p2_free']} new:{stats['p2_new']}\nErrors:{len(stats['errors'])}")

print(f"Merged: {OUT} ({len(db)} species, {au} AU)")
print(f"P1: enriched={stats['enriched']}, new={stats['new']}")
print(f"P2: yaml={stats['p2_yaml']}, freeform={stats['p2_free']}, newAU={stats['p2_new']}")
print(f"Total AU: {au}, Errors: {len(stats['errors'])}")
if stats['errors']:
    print(f"First 5 errors: {stats['errors'][:5]}")

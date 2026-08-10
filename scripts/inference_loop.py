#!/usr/bin/env python3
"""AUGURY v3 Inference Loop — Tool-Calling Reasoning Engine."""
import json, re, sys, os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from species_lookup import SpeciesDB

db = SpeciesDB()
punct = set(".,!?()[]{}")
print(f"Loaded {len(db._species)} species", file=sys.stderr)

def lookup_species(name, region="Europe"):
    r = db.get_indicators(name, region=region)
    if not r:
        return {"error": f"No data for {name} in {region}"}
    ind = {}
    for k, v in r["indicators"].items():
        if v and v.strip() and v.lower() != "not specified":
            ind[k] = v.strip()
    if r.get("nutrients", {}).get("claims"):
        ind["nutrients"] = [c["nutrient"] + ": " + c["relationship"] for c in r["nutrients"]["claims"][:3]]
    return {"scientific_name": r["scientific_name"], "common_names": r["common_names"][:3], "indicators": ind}

def extract_species(query):
    alts = [query]
    for w in query.split():
        c = w.lower().strip(".,!?()[]{}")
        if c.endswith("ies") and len(c) > 5:
            alts.append(query.replace(w, c[:-3] + "y"))
        elif c.endswith("es") and len(c) > 4:
            alts.append(query.replace(w, c[:-2]))
        elif c.endswith("s") and not c.endswith("ss") and len(c) > 4:
            alts.append(query.replace(w, c[:-1]))
    seen = set()
    matches = []
    for a in alts:
        for m in db.search(a, top_n=5):
            if m["scientific_name"] not in seen:
                seen.add(m["scientific_name"])
                matches.append(m)
    # Word-based search supplement
    words = set()
    for w in query.split():
        c = w.lower().strip(".,!?()[]{}")
        if len(c) > 3:
            words.add(c)
            # Also add singular form if plural
            if c.endswith("ies") and len(c) > 5:
                words.add(c[:-3] + "y")
            elif c.endswith("es") and len(c) > 4:
                words.add(c[:-2])
            elif c.endswith("s") and not c.endswith("ss") and len(c) > 4:
                words.add(c[:-1])
    for cnk, sci_k in db._common_index.items():
        if any(w in cnk for w in words):
            sn = db._species[sci_k]["scientific_name"]
            if sn not in seen:
                seen.add(sn)
                matches.append({"scientific_name": sn, "common_names": [cnk], "match_type": "word", "score": 0.6})
    for sk, inf in db._species.items():
        if sk not in seen and any(w in sk for w in words):
            seen.add(sk)
            matches.append({"scientific_name": inf["scientific_name"], "common_names": inf["common_names"][:2], "match_type": "word", "score": 0.6})
    matches.sort(key=lambda m: m.get("score", 0), reverse=True)
    result = []
    seen2 = set()
    for m in matches:
        sn = m["scientific_name"]
        if sn not in seen2:
            seen2.add(sn)
            result.append({"scientific_name": sn, "common_names": m.get("common_names", []), "match_type": m.get("match_type", "fuzzy")})
    return result

def detect_region(q):
    ql = q.lower()
    for w in ["australia", "aussie", "victoria", "nsw", "queensland", "tassie"]:
        if w in ql: return "Australia"
    for w in ["uk", "britain", "england", "scotland", "wales", "ireland"]:
        if w in ql: return "UK"
    return "Europe"

def synthesize(species_list, region):
    inds = [lookup_species(s["scientific_name"], region) for s in species_list]
    parts = []
    if len(species_list) == 1:
        c = species_list[0]["common_names"]
        parts.append(f"Let me tell you about {c[0] if c else species_list[0]['scientific_name']}.")
    else:
        names = [s["common_names"][0] if s["common_names"] else s["scientific_name"] for s in species_list]
        parts.append(f"Here is what {' and '.join(names)} tell me together.")
    for ind in inds:
        if "error" in ind:
            parts.append(ind["error"])
            continue
        c = ind["common_names"][0] if ind["common_names"] else ind["scientific_name"]
        lines = [f"\n{c} ({ind['scientific_name']}):"]
        for k, v in ind.get("indicators", {}).items():
            lines.append(f"  - {k}: {v}")
        parts.append("\n".join(lines))
    if len(species_list) >= 2:
        parts.append("\nWhat this combination tells me:")
        dlist = [i.get("indicators", {}) for i in inds if "error" not in i]
        if len(dlist) >= 2:
            common_keys = set(dlist[0].keys())
            for d in dlist[1:]:
                common_keys &= set(d.keys())
            agrees = []
            for k in common_keys:
                overlap = set(dlist[0][k].lower().split()[:5])
                for d in dlist[1:]:
                    overlap &= set(d[k].lower().split()[:5])
                if overlap:
                    agrees.append(f"  - On {k}, they agree: {', '.join(list(overlap)[:3])}")
            if agrees:
                parts.extend(agrees[:3])
            else:
                parts.append("  - They cover different aspects, giving a fuller picture.")
    return "\n".join(parts)

def main():
    query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "What do docks and thistles indicate?"
    print(f"\n{'='*60}\nAUGURY v3 Inference Loop\n{'='*60}")
    print(f"Query: {query}")
    region = detect_region(query)
    print(f"[1/4] Region: {region}")
    species = extract_species(query)
    if not species:
        print("[2/4] No species matched.\nRefusing: I could not find a plant species in your question.")
        return
    names = [s["common_names"][0] if s["common_names"] else s["scientific_name"] for s in species]
    print(f"[2/4] Found: {', '.join(names)}")
    print("[3/4] Tool calls:")
    for s in species:
        r = lookup_species(s["scientific_name"], region)
        print(f"  lookup_species({s['scientific_name']}, {region}) -> {'OK' if 'error' not in r else 'NOT FOUND'}")
    print(f"\n[4/4] Synthesis:\n{synthesize(species, region)}")
    print(f"\n{'='*60}\nTools: {len(species)} x lookup_species()")
    print("Database: 100% deterministic")
    print("=" * 60)

if __name__ == "__main__":
    main()

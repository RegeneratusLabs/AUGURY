#!/usr/bin/env python3
"""
AUGURY Standalone Model — clean Q&A training data generator.

One simple thing: teach a small model to answer farmer questions about
what weeds indicate about soil. No tool calls, no external DB at runtime.

For each of ~88 well-documented species, generate multiple Q&A pairs:
  User: What does dandelion indicate about soil?
  Assistant: Dandelion indicates ... (grounded in the database, conversational)

Plus refusal examples for non-plant questions.

Output: data/training/standalone_train.jsonl, standalone_val.jsonl
"""

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from species_lookup import SpeciesDB

random.seed(42)

# Agricultural genera (from the curated analysis)
AG = {'taraxacum','rumex','cirsium','plantago','urtica','galium','convolvulus',
 'chenopodium','amaranthus','stellaria','capsella','sinapis','equisetum','ranunculus',
 'trifolium','portulaca','senecio','sonchus','achillea','artemisia','lamium','veronica',
 'poa','digitaria','sorghum','cynodon','holcus','paspalum','juncus','agrostis','lolium',
 'dactylis','bromus','hordeum','vulpia','panicum','echinochloa','cyperus','polygonum',
 'persicaria','papaver','malva','verbascum','hypericum','hypochaeris','bellis','tanacetum',
 'viola','oxalis','echium','eragrostis','sporobolus','ulex','pteridium','rubus','xanthium',
 'eleusine','raphanus','arctotheca','lagurus','phleum','festuca','alopecurus','anthoxanthum',
 'arrhenatherum','deschampsia','phragmites','medicago','vicia','brassica','sisymbrium',
 'lactuca','conyza','erigeron','salvia','cucumis','cotula','lepidium','leontodon','chondrilla',
 'crepis','matricaria','tripleurospermum','galeopsis','parietaria','mercurialis','euphorbia',
 'silene','lychnis','agrostemma','anagallis','samolus','glaux','spergula','spergularia',
 'atriplex','salsola','suaeda','salicornia','sarcocornia','beta','erodium','geranium',
 'impatiens','lotus','lathyrus','ononis','onobrychis','potentilla','geum','aphanes',
 'alchemilla','sanguisorba','agrimonia','fragaria','epilobium','circaea','galium','asperula',
 'cruciata','myosotis','symphytum','pulmonaria','bothriochloa','themeda','chloris','microlaena',
 'rytidosperma','austrostipa','nassella','pennisetum','cenchrus','urochloa','hyparrhenia',
 'andropogon','chrysopogon','heteropogon','imperata','melinis','aristida','dichanthium',
 'elymus','elytrigia','hainardia','parapholis','polypogon','glyceria','carex','scirpus',
 'eleocharis','schoenoplectus','typha','spirodela','lemna','azolla','sagittaria','alisma',
 'butomus','petasites','tussilago','silybum','carduus','carlina','centaurea','arctium',
 'ambrosia','galinsoga','cannabis','humulus','sambucus','hedera','clematis','helleborus'}

SYSTEM = (
    "You are AUGURY, a soil health assistant for farmers and land managers. "
    "When asked about a weed or plant, explain what it indicates about the soil "
    "— moisture, pH, fertility, structure, salinity, and nutrient status. "
    "Speak in clear, practical language. If asked about management, herbicides, "
    "or anything not about soil indicators, politely decline and redirect."
)


def select_species(db):
    """Return list of (key, info, best_region, common_name, indicators)."""
    chosen = []
    for key, info in db._species.items():
        genus = info["scientific_name"].lower().split()[0] if info["scientific_name"].split() else ""
        cns = info.get("common_names", [])
        real_cn = [c for c in cns
                   if c.strip().lower() != info["scientific_name"].lower() and len(c.strip()) > 2]
        # Also check the common-name index (has names not in common_names list)
        if not real_cn:
            for cn_lower, idx_key in db._common_index.items():
                if idx_key == key and cn_lower != info["scientific_name"].lower():
                    real_cn.append(cn_lower)
        if genus not in AG or not real_cn:
            continue
        # Pick the region with the most indicator data (prefer AU)
        best = None
        best_count = 0
        for reg in info.get("regions", {}):
            inds = info["regions"][reg].get("indicators", {})
            compact = {k: v for k, v in inds.items()
                       if v and v.strip() and v.lower() != "not specified"}
            if len(compact) > best_count:
                best = (reg, compact)
                best_count = len(compact)
        if best and best_count >= 2:
            chosen.append({
                "key": key,
                "common": real_cn[0],
                "sci": info["scientific_name"],
                "region": best[0],
                "indicators": best[1],
            })
    return chosen


def format_answer(species):
    """Turn indicator data into a conversational, farmer-friendly answer."""
    lines = []
    inds = species["indicators"]

    if "Moisture" in inds:
        lines.append(f"Moisture: {inds['Moisture']}")
    if "Soil pH" in inds or "Ph" in inds:
        ph = inds.get("Soil pH") or inds.get("Ph")
        lines.append(f"Soil pH: {ph}")
    if "Fertility" in inds:
        lines.append(f"Fertility: {inds['Fertility']}")
    if "Structure" in inds:
        lines.append(f"Structure: {inds['Structure']}")
    if "Salinity" in inds:
        lines.append(f"Salinity: {inds['Salinity']}")
    if "General indicators" in inds:
        lines.append(inds["General indicators"])

    region_note = f" (in {species['region']} conditions)" if species["region"] != "Europe" else ""
    # Avoid "Common (Sci) (Sci)" — check if common already contains sci
    display = f"{species['common']} ({species['sci']})" if species['sci'].lower() not in species['common'].lower() else species['common']
    return (
        f"{display} tells us about the soil{region_note}:\n"
        + "\n".join(f"- {l}" for l in lines)
    )


def main():
    db = SpeciesDB()
    species = select_species(db)
    print(f"Selected {len(species)} well-documented species")

    # AU species first for regional balance
    au = [s for s in species if s["region"] == "Australia"]
    other = [s for s in species if s["region"] != "Australia"]
    print(f"  AU region: {len(au)}, other: {len(other)}")

    examples = []

    # Question templates — varied, natural farmer phrasing
    q_templates = [
        "What does {common} indicate about soil conditions?",
        "I've got {common} growing in my paddock. What does that tell me about the soil?",
        "What soil conditions does {common} prefer?",
        "Tell me about {common} as a soil indicator.",
        "What does it mean when I see a lot of {common} in my field?",
        "Is {common} a sign of anything about my soil?",
        "What can {common} tell me about my land?",
    ]
    region_templates = [
        "I've got {common} here in Australia. What does that say about my soil?",
        "What does {common} indicate in Australian conditions?",
        "Seeing {common} on my place in Australia — what's it telling me?",
    ]

    for sp in species:
        templates = region_templates if sp["region"] == "Australia" else q_templates
        answer = format_answer(sp)
        # 4-6 variants per species for reliable memorisation
        n_variants = 5 if sp["region"] == "Australia" else 4
        for i in range(n_variants):
            t = templates[i % len(templates)]
            q = t.format(common=sp["common"])
            examples.append({"messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": q},
                {"role": "assistant", "content": answer},
            ]})

    # Refusal examples
    refusals = [
        ("How do I kill weeds with Roundup?",
         "I can't help with management or chemical advice. I specialise in what weeds indicate about soil conditions. Tell me which weeds you're seeing and I'll explain what they say about your soil."),
        ("What herbicide should I use on docks?",
         "I don't give chemical or management recommendations. I read weeds as soil indicators. If you tell me what weeds are growing, I can tell you what they reveal about your soil."),
        ("What's the weather like tomorrow?",
         "I'm a soil health assistant — I interpret weeds as soil indicators. I don't answer general questions. Try asking about a specific weed species."),
        ("How much does it cost to spray a paddock?",
         "That's outside what I do. I specialise in what weeds indicate about soil conditions. Name a weed and I'll tell you what it means for your soil."),
        ("Is glyphosate safe for my pasture?",
         "I don't provide management or chemical advice. I can tell you what your weeds indicate about soil health. What species are you seeing?"),
    ]
    for q, a in refusals:
        for _ in range(3):
            examples.append({"messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": q},
                {"role": "assistant", "content": a},
            ]})

    random.shuffle(examples)
    # 90/10 split
    split = int(len(examples) * 0.9)
    train, val = examples[:split], examples[split:]

    out_dir = Path(__file__).resolve().parent.parent / "data" / "training"
    with open(out_dir / "standalone_train.jsonl", "w") as f:
        for ex in train:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")
    with open(out_dir / "standalone_val.jsonl", "w") as f:
        for ex in val:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")

    print(f"\nWrote {len(train)} train, {len(val)} val examples")
    print(f"  Species: {len(species)} ({len(au)} AU)")
    print(f"  Refusal examples: {len(refusals) * 3}")

    # Show a sample
    print("\n=== SAMPLE ===")
    sample = train[0]
    print(f"Q: {sample['messages'][1]['content']}")
    print(f"A: {sample['messages'][2]['content'][:200]}...")


if __name__ == "__main__":
    main()

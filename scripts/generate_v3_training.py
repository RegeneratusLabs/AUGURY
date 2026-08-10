#!/usr/bin/env python3
"""
AUGURY v3 Training Data Generator — Holistic Reasoning + Tool Use.

Produces 4 layers of training data for Qwen3.5-4B:
  A: Tool-use (learns to call lookup_species)
  B: Memorized common weeds (direct answers, no tool call)
  C: Multi-species synthesis (multiple lookups + holistic reasoning)
  D: Refusal + guardrails (baked-in safety boundaries)

Output: v3_function_calling/ directory with train/val JSONL splits.
"""

import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from species_lookup import SpeciesDB

random.seed(42)

# ── Config ─────────────────────────────────────────────────────

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "v3_function_calling"
VAL_FRAC = 0.10

# Template strings for varied phrasings
MOISTURE_PHRASES = ["likes", "prefers", "thrives in", "is comfortable in", "indicates"]
PH_PHRASES = ["likes its soil", "is comfortable with soil pH", "prefers a pH of", "indicates soil pH near", "grows best at pH around"]
FERTILITY_PHRASES = ["signals", "indicates", "points to", "tells us about the fertility —", "is a sign of"]
SALINITY_PHRASES = ["tolerates", "handles", "grows in", "can be found in", "indicates"]

# Top 100 agricultural weeds list (curated from common species in the DB)
TOP_100 = [
    "Taraxacum officinale", "Rumex obtusifolius", "Rumex crispus",
    "Urtica dioica", "Cirsium arvense", "Cirsium vulgare",
    "Trifolium repens", "Trifolium pratense", "Plantago major",
    "Plantago lanceolata", "Holcus lanatus", "Dactylis glomerata",
    "Poa annua", "Poa trivialis", "Lolium perenne",
    "Elymus repens", "Alopecurus pratensis", "Phleum pratense",
    "Festuca rubra", "Festuca arundinacea", "Agrostis stolonifera",
    "Ranunculus repens", "Ranunculus acris", "Stellaria media",
    "Capsella bursa-pastoris", "Senecio vulgaris", "Lamium purpureum",
    "Lamium amplexicaule", "Veronica persica", "Veronica arvensis",
    "Polygonum aviculare", "Fallopia convolvulus", "Chenopodium album",
    "Amaranthus retroflexus", "Solanum nigrum", "Galium aparine",
    "Anagallis arvensis", "Glechoma hederacea", "Gnaphalium uliginosum",
    "Juncus effusus", "Juncus bufonius", "Carex hirta",
    "Carex acutiformis", "Equisetum arvense", "Equisetum palustre",
    "Deschampsia cespitosa", "Molinia caerulea", "Sphagnum spp.",
    "Leontodon autumnalis", "Hypochaeris radicata", "Bellis perennis",
    "Prunella vulgaris", "Ranunculus bulbosus", "Lotus corniculatus",
    "Vicia cracca", "Vicia sativa", "Medicago lupulina",
    "Trifolium dubium", "Achillea millefolium", "Agrimonia eupatoria",
    "Potentilla erecta", "Rumex acetosa", "Rumex acetosella",
    "Cardamine hirsuta", "Sisymbrium officinale", "Sinapis arvensis",
    "Brassica rapa", "Barbarea vulgaris", "Erophila verna",
    "Cerastium fontanum", "Sagina procumbens", "Viola arvensis",
    "Viola tricolor", "Myosotis arvensis", "Hyoscyamus niger",
    "Artemisia vulgaris", "Tanacetum vulgare", "Arctium lappa",
    "Arctium minus", "Cichorium intybus", "Sonchus arvensis",
    "Sonchus asper", "Sonchus oleraceus", "Hieracium pilosella",
    "Erigeron canadensis", "Matricaria chamomilla", "Chamomilla suaveolens",
    "Tussilago farfara", "Jacobaea vulgaris", "Centaurea nigra",
    "Leucanthemum vulgare", "Crepis capillaris", "Anthoxanthum odoratum",
    "Briza media", "Cynosurus cristatus",
    # Australian-specific
    "Echium plantagineum", "Arctotheca calendula", "Nassella trichotoma",
    "Eragrostis curvula", "Senecio madagascariensis", "Xanthium spinosum",
    "Hypericum perforatum", "Rubus fruticosus", "Ulex europaeus",
]

Q = '"'  # helper for quote embedding

# Data-artefact common names — never use in questions
BAD_COMMON = {"-me-not", "-grass", "-thistle", "INVALID SPECIES ENTRY", "Field forget"}


def pick_common(info):
    """Return a usable common name or None."""
    for cn in info.get("common_names", []):
        cn_s = cn.strip()
        if not cn_s or len(cn_s) < 3:
            continue
        if cn_s in BAD_COMMON or cn_s.startswith("-"):
            continue
        if "INVALID" in cn_s.upper():
            continue
        return cn_s
    return None


def pick_region(info, au_bias=0.6):
    """Choose a region, biasing toward Australia when available."""
    regions = list(info.get("regions", {}).keys())
    if not regions:
        return None
    if "Australia" in regions and random.random() < au_bias:
        return "Australia"
    return random.choice(regions)


def build_tool_response(info, region, key=None, db=None):
    """Build a realistic tool response matching get_indicators() output."""
    compact = get_compact_indicators(info["regions"][region].get("indicators", {}))
    resp = {
        "scientific_name": info["scientific_name"],
        "common_names": info.get("common_names", []),
        "region": region,
        "indicators": compact,
        "source": info["regions"][region].get("source", f"Research ({region})"),
    }
    if db is not None and key is not None and key in db._nutrients:
        resp["nutrients"] = db._nutrients[key]
    return resp
Q1 = "'"


def format_indicators_prompt(indicators, common_name, scientific_name):
    """Format indicator data as a clean structured listing."""
    lines = [f"Plant: {common_name} ({scientific_name})"]
    for key, val in indicators.items():
        if val and val.strip() and val.lower() != "not specified":
            lines.append(f"  {key}: {val}")
    return "\n".join(lines)


def get_compact_indicators(indicator_dict):
    """Return a dict with only non-empty, non-default fields."""
    result = {}
    for k, v in indicator_dict.items():
        if v and v.strip() and v.lower() != "not specified":
            result[k] = v.strip()
    return result


def pick_moisture_phrase():
    return random.choice(MOISTURE_PHRASES)


def pick_ph_phrase():
    return random.choice(PH_PHRASES)


# ── Layer A: Tool Use (~300) ───────────────────────────────────

def generate_tool_use_examples(db, n=300):
    """Model learns to call lookup_species() when asked about a species."""
    examples = []
    species_list = list(db._species.items())
    # Guarantee ~40% AU representation: split AU vs non-AU, interleave
    au_spp = [(k, v) for k, v in species_list if "Australia" in v.get("regions", {})]
    other_spp = [(k, v) for k, v in species_list if "Australia" not in v.get("regions", {})]
    random.shuffle(au_spp)
    random.shuffle(other_spp)
    # Interleave: 2 AU : 3 other ratio
    species_list = []
    ai, oi = 0, 0
    while ai < len(au_spp) or oi < len(other_spp):
        for _ in range(2):
            if ai < len(au_spp):
                species_list.append(au_spp[ai]); ai += 1
        for _ in range(3):
            if oi < len(other_spp):
                species_list.append(other_spp[oi]); oi += 1

    count = 0
    for key, info in species_list:
        if count >= n:
            break
        sci_name = info["scientific_name"]
        common = pick_common(info) or sci_name
        regions = list(info["regions"].keys())
        if not regions:
            continue

        # Bias toward Australia when available
        region = pick_region(info)

        ind = info["regions"][region].get("indicators", {})
        compact = get_compact_indicators(ind)
        if not compact:
            continue

        # Build a REALISTIC tool response — matching get_indicators() output
        realistic = build_tool_response(info, region, key, db)

        region_tag = "" if region == "Europe" else f" ({region})"

        phrasings = [
            f"What does {common} indicate about soil conditions{region_tag}?",
            f"I've got {common} growing in my field. What does that tell me{region_tag}?",
            f"Tell me about {common} as a soil indicator{region_tag}.",
            f"What soil conditions does {common} prefer{region_tag}?",
            f"I'm seeing {common} on my land. What does it mean{region_tag}?",
        ]
        question = random.choice(phrasings)

        tool_call_content = json.dumps({
            "name": "lookup_species",
            "arguments": {
                "species": sci_name,
                "region": region
            }
        })

        # Build conversational response from the full indicator set
        response_parts = [f"Let me look up {common} for you."]
        for rkey, rval in compact.items():
            response_parts.append(f"- {rkey}: {rval}")
        response = "\n".join(response_parts)

        msgs = [
            {"role": "system", "content": "You are AUGURY, a soil health assistant specializing in weed indicator interpretation. When asked about a plant species, call lookup_species() to retrieve its indicator data, then present the results conversationally. Never invent indicator data."},
            {"role": "user", "content": question},
            {"role": "assistant", "content": f"<function_call>{tool_call_content}</function_call>"},
            {"role": "tool_response", "content": json.dumps(realistic, ensure_ascii=False)},
            {"role": "assistant", "content": response},
        ]
        examples.append({"messages": msgs})
        count += 1

    return examples


# ── Layer B: Memorized Common Weeds (~400) ─────────────────────

def generate_memorized_examples(db, n=400):
    """Tool-call + response pairs for common weeds (NOT direct answers).

    This layer previously taught the model to answer species questions
    WITHOUT calling the tool — contradicting the tool-calling architecture.
    Now every example follows the same pattern as Layer A: emit the tool
    call, receive the response, then present conversationally.
    """
    examples = []

    # Score species by how common/well-known they are
    species_list = []
    target_list_lower = [s.lower() for s in TOP_100]
    for key, info in db._species.items():
        sci_lower = info["scientific_name"].lower()
        score = 0
        if sci_lower in target_list_lower:
            score = 10  # Top 100 bonus
        # Prefer species with complete data
        for reg in info["regions"]:
            ind = info["regions"][reg].get("indicators", {})
            compact = get_compact_indicators(ind)
            score += len(compact)
        species_list.append((score, key, info))

    species_list.sort(reverse=True)
    random.shuffle(species_list[:20])  # slight variation

    count = 0
    for score, key, info in species_list:
        if count >= n:
            break
        sci = info["scientific_name"]
        common = pick_common(info) or sci
        region = pick_region(info)
        if not region:
            continue
        ind = info["regions"][region].get("indicators", {})
        compact = get_compact_indicators(ind)
        if len(compact) < 1:
            continue

        region_tag = "" if region == "Europe" else f" in {region}"

        phrasings = [
            f"What does {common} tell you about soil{region_tag}?",
            f"You see {common} — what does that indicate{region_tag}?",
            f"What soil conditions is {common} pointing to{region_tag}?",
            f"What's the story with {common} as a soil indicator{region_tag}?",
            f"Tell me about {common} as a weed indicator{region_tag}.",
        ]
        question = random.choice(phrasings)

        # Tool call first — same pattern as Layer A
        tool_call_content = json.dumps({
            "name": "lookup_species",
            "arguments": {"species": sci, "region": region}
        })

        # Realistic tool response matching get_indicators()
        realistic = build_tool_response(info, region, key, db)

        # Build a natural conversational answer from the indicators
        parts = [f"Here's what {common} ({sci}) tells us about your soil."]
        for key, val in compact.items():
            parts.append(f"- {key}: {val}")
        answer = "\n".join(parts)

        msgs = [
            {"role": "system", "content": "You are AUGURY, a soil health assistant. When asked about a plant species, call lookup_species() to retrieve its indicator data, then present the results conversationally. Never invent indicator data."},
            {"role": "user", "content": question},
            {"role": "assistant", "content": f"<function_call>{tool_call_content}</function_call>"},
            {"role": "tool_response", "content": json.dumps(realistic, ensure_ascii=False)},
            {"role": "assistant", "content": answer},
        ]
        examples.append({"messages": msgs})
        count += 1

    return examples


# ── Layer C: Multi-Species Synthesis (~800) ────────────────────

def generate_multi_species_examples(db, n=800):
    """User mentions 2+ weeds — model calls lookup for each, synthesizes."""
    examples = []

    species_list = list(db._species.items())
    # Ensure AU species are represented in multi-species pairs
    au_keys = [k for k, v in species_list if "Australia" in v.get("regions", {})]
    # Prefer species with good indicator coverage
    scored = []
    for key, info in species_list:
        regions = list(info["regions"].keys())
        if not regions:
            continue
        region = random.choice(regions)
        ind = info["regions"][region].get("indicators", {})
        compact = get_compact_indicators(ind)
        if len(compact) >= 2:
            score = len(compact)
            if key in au_keys:
                score += 5  # AU bonus
            scored.append((score, key, info))
    scored.sort(reverse=True)

    # Get well-covered species (include a strong AU contingent)
    top_species = [s[1] for s in scored[:400]]
    au_in_top = [k for k in top_species if k in au_keys]
    # Ensure at least 30% of pairs involve an AU species
    if len(au_in_top) < len(top_species) // 3:
        for k in au_keys:
            if k not in top_species:
                top_species.append(k)
    if len(top_species) < 10:
        top_species = [s[1] for s in scored]
    random.shuffle(top_species)

    count = 0
    used_pairs = set()
    max_attempts = n * 10
    attempts = 0
    i = 0
    while i < len(top_species) and count < n and attempts < max_attempts:
        key1 = top_species[i]
        for j in range(i + 1, min(i + 20, len(top_species))):
            if count >= n or attempts >= max_attempts:
                break
            attempts += 1
            key2 = top_species[j]
            if key1 == key2:
                continue
            pair_key = tuple(sorted([key1, key2]))
            if pair_key in used_pairs:
                continue

            info1, info2 = db._species[key1], db._species[key2]
            sci1, sci2 = info1["scientific_name"], info2["scientific_name"]
            common1 = info1["common_names"][0] if info1["common_names"] else sci1
            common2 = info2["common_names"][0] if info2["common_names"] else sci2

            shared_regions = [r for r in info1["regions"] if r in info2["regions"]]
            if not shared_regions:
                continue
            region = random.choice(shared_regions)

            ind1 = get_compact_indicators(info1["regions"][region].get("indicators", {}))
            ind2 = get_compact_indicators(info2["regions"][region].get("indicators", {}))
            if len(ind1) < 1 or len(ind2) < 1:
                continue

            used_pairs.add(pair_key)

        region_tag = "" if region == "Europe" else f" in {region}"

        # Generate contextual scenario
        scenarios = [
            f"I've got {common1} and {common2} growing together in my paddock{region_tag}. What does this combination tell me about my soil?",
            f"I'm seeing both {common1} and {common2} on my land{region_tag}. What's the soil story here?",
            f"{common1} and {common2} are showing up together in my field{region_tag}. What are they telling me as a combination?",
            f"My pasture has both {common1} and {common2}{region_tag}. What does that tell me about the soil conditions?",
            f"We've got {common1} spreading alongside {common2}{region_tag}. What does that combination indicate?",
        ]
        question = random.choice(scenarios)

        # Build tool calls
        tc1 = json.dumps({"name": "lookup_species", "arguments": {"species": sci1, "region": region}})
        tc2 = json.dumps({"name": "lookup_species", "arguments": {"species": sci2, "region": region}})

        # Build combined indicator data
        combined = {sci1: ind1, sci2: ind2}

        # Holistic synthesis
        # Find common patterns between the two species
        common_keys = set(ind1.keys()) & set(ind2.keys())
        agreement = []
        for k in common_keys:
            v1, v2 = ind1[k], ind2[k]
            words1 = set(v1.lower().split()[:5])
            words2 = set(v2.lower().split()[:5])
            overlap = words1 & words2
            if overlap:
                agreement.append(f"Both point to {', '.join(list(overlap)[:3])} in terms of {k.lower()}")

        openings = [
            f"Let me look up both {common1} and {common2}.",
            f"I'll check the data on {common1} and {common2} together.",
            f"Let's see what {common1} and {common2} tell us about your soil.",
            f"Looking at {common1} alongside {common2}:",
            f"I've found data on {common1} and {common2}. Here's what they indicate together:",
        ]
        synthesis = [random.choice(openings)]
        if agreement:
            SYNTHESIS_TEMPLATES = [
                ("What's interesting is that they agree on key soil conditions:", "This agreement between two different plant species makes it a reliable signal — not a coincidence."),
                ("Here's what they tell us together:", "When two different species point to the same conditions, you can trust that signal."),
                ("The combined picture is clear:", "Both species are telling the same story about your soil."),
                ("Putting these together:", "This cross-verification between species gives us confidence in the diagnosis."),
                ("Here's the story the weeds are telling:", "When different weeds agree on soil conditions, pay attention."),
            ]
            template_idx = random.randint(0, len(SYNTHESIS_TEMPLATES) - 1) if count > 5 else count % len(SYNTHESIS_TEMPLATES)
            header, footer = SYNTHESIS_TEMPLATES[template_idx]
            synthesis.append(header)
            synthesis.extend(f"• {a}" for a in agreement[:2])
            synthesis.append(footer)
        elif len(ind1) > 0 and len(ind2) > 0:
            # Species disagree — note the discrepancy
            differing = []
            for k in set(list(ind1.keys())[:3]) & set(list(ind2.keys())[:3]):
                if ind1.get(k, "").strip() and ind2.get(k, "").strip():
                    v1 = ind1[k][:40]
                    v2 = ind2[k][:40]
                    if v1.lower()[:20] != v2.lower()[:20]:
                        differing.append(f"On {k}: {v1} vs {v2}")
            if differing:
                synthesis.append("These species tell slightly different stories:")
                synthesis.extend(f"• {d}" for d in differing[:2])
                synthesis.append("This may indicate variable soil conditions across your paddock — a mosaic rather than uniform soil.")
            else:
                synthesis.append("Each species has its own story, but together they paint a picture of your soil conditions.")
        else:
            synthesis.append("Together, these species give us a read on your soil conditions.")

        response = "\n".join(synthesis)

        msgs = [
            {"role": "system", "content": "You are AUGURY, a soil health assistant. When asked about multiple plant species together, call lookup_species() for each one, then synthesize what the combination indicates about the soil as a system."},
            {"role": "user", "content": question},
            {"role": "assistant", "content": f"<function_call>{tc1}</function_call>"},
            {"role": "tool_response", "content": json.dumps(build_tool_response(info1, region, key1, db), ensure_ascii=False)},
            {"role": "assistant", "content": f"<function_call>{tc2}</function_call>"},
            {"role": "tool_response", "content": json.dumps(build_tool_response(info2, region, key2, db), ensure_ascii=False)},
            {"role": "assistant", "content": response},
        ]
        examples.append({"messages": msgs})
        count += 1

    return examples


# ── Layer D: Refusal + Guardrails (~400) ───────────────────────

def generate_refusal_examples(n=400):
    """Bakes safety boundaries into model weights — no system prompt needed."""
    examples = []

    herbicide_questions = [
        "What herbicide kills buttercups?", "Should I spray my thistles?",
        "What's the best chemical control for docks?", "How do I kill weeds with Roundup?",
        "What pesticide should I use on my pasture?", "Will 2,4-D kill clover?",
        "Should I use glyphosate on my dock problem?", "What spray kills creeping thistle?",
        "Can I use MCPA on buttercups?", "How much herbicide do I need per acre?",
        "What's the best time to spray weeds?", "Will spraying kill the roots of docks?",
        "Should I spot-spray or boom-spray?", "What chemical kills Yorkshire fog?",
        "Can I spray weeds in wet conditions?", "Is there an organic herbicide for thistles?",
        "How long after spraying can I graze?", "What chemical controls Paterson's curse?",
        "How do I spray capeweed?", "What rate of glyphosate for grass weeds?",
        "What herbicide kills onion grass?", "Can I spray thistles in flower?",
        "What chemical kills serrated tussock?", "Best herbicide for African lovegrass?",
    ]
    non_plant_questions = [
        "What's the weather forecast for next week?", "Who won the footy last night?",
        "What's the best tractor to buy?", "How do I spread fertiliser?",
        "What's the stock market doing?", "Tell me about crop rotation for wheat",
        "How much lime should I apply?", "How often should I mow my lawn?",
        "What's the best ute on the market?", "How much diesel does a tractor use?",
        "Should I buy a Toyota or a Ford?", "What's the cricket score?",
        "Can you write me a poem about farming?", "Tell me a joke about sheep",
        "How do I cook lamb chops?", "What's the best fencing wire?",
        "How do I fix a dripping tap?", "What's the meaning of life?",
        "Should I vote for the Nationals?", "What's the best chainsaw brand?",
        "How do I insulate my shed?", "What's the price of wool this season?",
        "How do I calculate stocking rate?", "What breed of cattle is best for my area?",
        "How do I fix erosion in my paddock?", "Should I deep-rip my soil?",
        "What's the best pasture mix?", "How often should I soil test?",
        "How do I control regrowth in fallow?", "What's the best cropping rotation?",
        "How do I set up a fence?", "What size tractor do I need for 100 acres?",
    ]
    edge_cases = [
        "Is bindweed edible?", "What does this weed cure?",
        "Are there poisonous weeds in my paddock?", "Will this weed kill my sheep?",
        "Can I compost docks?", "Is thistle firewood good burning?",
        "Can I eat dandelions?", "Do thistles have medicinal uses?",
        "Will horses eat buttercups?", "Is bracken fern dangerous to livestock?",
        "Can I make tea from nettles?", "Are dandelion leaves nutritious?",
        "What weeds are good for bees?", "Can I feed thistles to my goats?",
        "Is ragwort dangerous?", "Does dock have medicinal properties?",
        "How do I identify a poisonous plant?", "What happens if cows eat nightshade?",
        "Can I use weeds for compost tea?", "What weeds are good for chickens?",
        "Are capeweed flowers edible?", "Can I make hay from thistles?",
        "Is Paterson's curse poisonous to sheep?", "What does Paterson's curse look like?",
        "Can I make rope from nettles?", "Are dandelion roots medicinal?",
        "How do I make weed tea fertiliser?", "Can weeds tell me about soil minerals?",
    ]

    all_questions = []  # (question, category)
    for q in herbicide_questions:
        all_questions.append((q, "herbicide"))
    for q in non_plant_questions:
        all_questions.append((q, "non_plant"))
    for q in edge_cases:
        all_questions.append((q, "management"))
    # Repeat to reach n
    all_questions = all_questions[:n] if len(all_questions) >= n else all_questions * (n // len(all_questions) + 1)
    all_questions = all_questions[:n]
    random.shuffle(all_questions)

    refusal_by_category = {
        "herbicide": [
            "I don't provide management advice or chemical recommendations. I can tell you what conditions that weed indicates about your soil — would that help?",
            "That's outside what I do. I specialise in interpreting what weeds tell us about soil conditions. Want me to look up what that weed indicates?",
            "I can't help with that. I'm designed to read weed communities as soil indicators. Name a weed species and I'll tell you what it means for your soil.",
            "Herbicide and chemical questions are outside my scope. What I CAN tell you is what that weed says about your soil health.",
        ],
        "non_plant": [
            "I'm a soil indicator assistant — I can tell you what weeds and plants reveal about soil conditions. I don't answer general questions. Try asking about a specific plant species.",
            "That's not something I do. I specialise in reading weeds as soil indicators. Try asking me about a plant species you've noticed.",
            "I only work with plant-soil indicators. If you tell me what weeds are growing on your land, I can interpret what they say about your soil.",
        ],
        "management": [
            "I don't give management advice. I interpret weeds as soil indicators. If you tell me what weeds you're seeing, I can explain what they indicate about your soil.",
            "That's outside my scope. I read soil through weeds. What species are you seeing? I can tell you what they indicate.",
            "I can't help with management decisions. But I CAN tell you what your weeds say about your soil. What species are present?",
        ],
    }

    for q, category in all_questions:
        refusal = random.choice(refusal_by_category.get(category, refusal_by_category["non_plant"]))
        msgs = [
            {"role": "system", "content": "You are AUGURY, a weed indicator specialist. You only answer questions about what plants indicate about soil conditions. You do not provide management advice, herbicides, chemical recommendations, or veterinary advice."},
            {"role": "user", "content": q},
            {"role": "assistant", "content": refusal},
        ]
        examples.append({"messages": msgs})

    return examples


# ── Validation ──────────────────────────────────────────────────

def validate_example(ex):
    """Check that a training example has the right structure."""
    if "messages" not in ex:
        return False
    msgs = ex["messages"]
    if len(msgs) < 2:
        return False
    # First message should be system or user
    if msgs[0]["role"] not in ("system", "user"):
        return False
    # All messages need content
    for m in msgs:
        if "content" not in m or not m["content"]:
            return False
    return True


def split_and_save(examples, name, output_dir):
    """Split into train/val and save as JSONL."""
    random.shuffle(examples)
    split_idx = int(len(examples) * (1 - VAL_FRAC))

    train = examples[:split_idx]
    val = examples[split_idx:]

    train_path = output_dir / f"{name}_train.jsonl"
    val_path = output_dir / f"{name}_val.jsonl"

    with open(train_path, "w") as f:
        for ex in train:
            f.write(json.dumps(ex) + "\n")
    with open(val_path, "w") as f:
        for ex in val:
            f.write(json.dumps(ex) + "\n")

    print(f"  {name}: {len(train)} train + {len(val)} val → {train_path.name}")
    return len(train), len(val)


def main():
    print("=" * 60)
    print("AUGURY v3 Training Data Generator")
    print("=" * 60)

    # Load database
    print("\nLoading species database...")
    db = SpeciesDB()
    print(f"  {db.species_count} species loaded")
    print(f"  Regions: {db.regions}")
    print(f"  With nutrients: {len(db._nutrients)}")

    # Create output directory
    output_dir = OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    total_train, total_val = 0, 0
    all_stats = []

    # Layer A: Tool use
    print("\n[Layer A] Generating tool-use examples...")
    a_examples = generate_tool_use_examples(db, n=300)
    a_train, a_val = split_and_save(a_examples, "a_tool_use", output_dir)
    total_train += a_train
    total_val += a_val
    all_stats.append(("A: Tool use", a_train + a_val, a_train, a_val))

    # Layer B: Memorized common weeds
    print("\n[Layer B] Generating memorized common-weed examples...")
    b_examples = generate_memorized_examples(db, n=400)
    b_train, b_val = split_and_save(b_examples, "b_direct_answer", output_dir)
    total_train += b_train
    total_val += b_val
    all_stats.append(("B: Direct answer", b_train + b_val, b_train, b_val))

    # Layer C: Multi-species synthesis
    print("\n[Layer C] Generating multi-species synthesis examples...")
    c_examples = generate_multi_species_examples(db, n=800)
    c_train, c_val = split_and_save(c_examples, "c_multi_species", output_dir)
    total_train += c_train
    total_val += c_val
    all_stats.append(("C: Multi-species", c_train + c_val, c_train, c_val))

    # Layer D: Refusal
    print("\n[Layer D] Generating refusal examples...")
    d_examples = generate_refusal_examples(n=400)
    d_train, d_val = split_and_save(d_examples, "d_refusal", output_dir)
    total_train += d_train
    total_val += d_val
    all_stats.append(("D: Refusal", d_train + d_val, d_train, d_val))

    # Print summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for name, total, tr, va in all_stats:
        print(f"  {name:25s}  {total:5d}  ({tr} train + {va} val)")
    print(f"  {'─'*40}")
    print(f"  {'TOTAL':25s}  {total_train + total_val:5d}  ({total_train} train + {total_val} val)")
    print(f"\nOutput: {output_dir}/")

    # Validate
    print("\nValidating...")
    all_train_count, all_val_count = 0, 0
    for layer in ["a_tool_use", "b_direct_answer", "c_multi_species", "d_refusal"]:
        for split in ["train", "val"]:
            path = output_dir / f"{layer}_{split}.jsonl"
            if not path.exists():
                continue
            with open(path) as f:
                for line in f:
                    ex = json.loads(line)
                    if not validate_example(ex):
                        print(f"  ❌ Invalid example in {path.name}")
                    else:
                        if split == "train":
                            all_train_count += 1
                        else:
                            all_val_count += 1
    print(f"  ✅ {all_train_count} train + {all_val_count} val = {all_train_count + all_val_count} valid examples")

    print("\nDone.")


if __name__ == "__main__":
    main()

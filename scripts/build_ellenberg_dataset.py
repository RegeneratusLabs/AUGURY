#!/usr/bin/env python3
"""Convert Ellenberg indicator values to AUGURY contract-format JSONL.

Output conforms to the Interoperable SLM Contract:
  - Line 1: AUGURY v1
  - Body: structured key-value lines in natural language
  - Last line: Source: [dataset] ([region])
"""

import csv
import json
import os
import re
import sys
from pathlib import Path

# ── Ellenberg scale → natural language descriptions ──

MOISTURE_TEXT = {
    (1, ''):   "extreme dryness, bare rock or very shallow soil",
    (2, ''):   "very dry, well-drained soils. Drought-prone sites",
    (3, ''):   "dry soils. More often found on dry ground than moist",
    (4, ''):   "moderately dry. Avoids waterlogged areas",
    (5, ''):   "fresh, moist soils of average dampness. Neither dry nor wet",
    (6, ''):   "moderately moist, damp ground. Prefers some soil moisture",
    (7, ''):   "damp ground. Constantly moist or poorly draining soils",
    (8, ''):   "wet soils. Regularly saturated, tolerates standing water",
    (9, ''):   "waterlogged ground. Marshy, boggy, or flood-prone soils",
    (10, ''):  "shallow standing water. Emergent aquatic, often in ponds or ditches",
    (11, ''):  "rooted aquatic with floating leaves. Permanent water bodies",
    (12, ''):  "submerged aquatic. Permanently or near-permanently underwater",
    # Indicator modifier (= narrow amplitude)
    (1, '='):  "strict indicator of extreme dryness. Confined to the driest sites",
    (2, '='):  "strictly very dry soils. Rarely found on moist ground",
    (3, '='):  "strictly dry soils. Reliable indicator of droughty conditions",
    (4, '='):  "strictly moderately dry. Avoids damp or water-retentive soils",
    (5, '='):  "strictly fresh, moist soils. Strong indicator of balanced moisture",
    (6, '='):  "strictly damp ground. Reliable indicator of soil moisture",
    (7, '='):  "strictly damp to wet. Strong indicator of poor drainage",
    (8, '='):  "strictly wet soils. Reliable indicator of waterlogging",
    (9, '='):  "strictly waterlogged. Confined to marshes and bogs",
    (10, '='): "strictly shallow-water aquatic. Reliable wetland indicator",
    (11, '='): "strictly floating aquatic. Confined to permanent water",
    (12, '='): "strictly submerged aquatic. Found only underwater",
}

PH_TEXT = {
    (1, ''):   "extremely acidic. pH 3.0–4.0. Very acid-tolerant species",
    (2, ''):   "strongly acidic. pH 3.5–5.0. Heathland and peat soils",
    (3, ''):   "acidic soils. pH 4.0–5.5. Common on moorland and conifer woodland",
    (4, ''):   "moderately acidic. pH 4.5–6.0. Acid grassland and heath",
    (5, ''):   "weakly acidic. pH 5.0–6.5. Most pasture and woodland soils",
    (6, ''):   "neutral to slightly acidic. pH 5.5–7.0. Common on loams",
    (7, ''):   "neutral. pH 6.0–7.5. Wide range of productive soils",
    (8, ''):   "calcareous, alkaline. pH 6.5–8.0. Chalk and limestone soils",
    (9, ''):   "strongly alkaline. pH 7.0–8.5+. Chalk downland and limestone",
    (1, '='):  "strict indicator of extreme acidity. pH below 4.0",
    (2, '='):  "strictly acid soils. Reliable indicator of low pH",
    (3, '='):  "strictly acidic. Strong indicator of acid conditions",
    (4, '='):  "strictly moderately acid. Reliable pH indicator",
    (5, '='):  "strictly weakly acid. Narrow pH tolerance",
    (6, '='):  "strictly neutral to slightly acid. Narrow pH range",
    (7, '='):  "strictly neutral. Confined to pH 6.0–7.5 soils",
    (8, '='):  "strictly calcareous. Strong lime indicator",
    (9, '='):  "strictly alkaline. Confined to high-pH chalk and limestone",
}

FERTILITY_TEXT = {
    (1, ''):   "extremely infertile. Very low nitrogen. Starved, leached soils",
    (2, ''):   "very low fertility. Nutrient-poor ground. Low-input pasture",
    (3, ''):   "low fertility. Infertile soils, low nitrogen availability",
    (4, ''):   "moderately infertile. Below-average nutrient levels",
    (5, ''):   "moderate fertility. Average nutrient levels. Typical pasture",
    (6, ''):   "moderately fertile. Above-average nutrient availability",
    (7, ''):   "fertile, nutrient-rich. High nitrogen. Productive pasture",
    (8, ''):   "very fertile. Nitrogen-rich. Improved pasture or manured ground",
    (9, ''):   "extremely fertile. Excess nitrogen. Over-fertilised, manure heaps, stock camps",
    (1, '='):  "strictly infertile. Confined to the most nutrient-starved soils",
    (2, '='):  "strictly very low fertility. Reliable indicator of poor soils",
    (3, '='):  "strictly low fertility. Strong indicator of nutrient deficiency",
    (4, '='):  "strictly below-average fertility. Narrow nutrient range",
    (5, '='):  "strictly moderate fertility. Balanced nutrient indicator",
    (6, '='):  "strictly moderately fertile. Reliable fertility indicator",
    (7, '='):  "strictly fertile. Strong indicator of good soil nutrition",
    (8, '='):  "strictly very fertile. Confined to nitrogen-rich soils",
    (9, '='):  "strictly extremely fertile. Only on the richest ground",
}

SALINITY_TEXT = {
    0:  "not salt-tolerant. Absent from saline or brackish soils",
    1:  "slightly salt-tolerant. Mostly on non-saline soils, occasional brackish margins",
    2:  "low salt tolerance. Found on slightly brackish soils",
    3:  "tolerates low to moderate salt. Coastal margins and salt-affected pasture",
    4:  "moderate salt tolerance. Estuarine margins and salt-affected ground",
    5:  "salt-tolerant. Moderate to high salt. Coastal grazing marsh",
    6:  "high salt tolerance. Regularly salt-exposed coastal soils",
    7:  "very high salt tolerance. Coastal halophyte. Saltmarsh species",
    8:  "extreme salt tolerance. Obligate halophyte. Only on saline soils",
    9:  "hyper-saline specialist. Extreme salt flats and salt pans",
}


def scale_modifier(val):
    """Parse value like '7=', '8~', 'x', '?' returning (value, modifier)."""
    if not val or val.strip() in ('', 'x', '?', '-'):
        return None, None
    val = val.strip().rstrip('B')
    modifier = ''
    if val.endswith('='):
        modifier = '='
        val = val[:-1]
    elif val.endswith('~'):
        modifier = ''
        val = val[:-1]
    try:
        return int(val), modifier
    except ValueError:
        return None, None


def build_assistant_text(species, moisture_val, ph_val, nitrogen_val, salinity_val):
    """Build contract-format response from Ellenberg values."""

    # Determine ecological preferences
    default_moisture = "not specified"
    default_ph = "not specified"
    default_fertility = "not specified"

    moisture_line = None
    ph_line = None
    fertility_line = None
    salinity_line = None

    if moisture_val:
        val, mod = moisture_val
        moisture_line = MOISTURE_TEXT.get((val, mod), f"{default_moisture}")

    if ph_val:
        val, mod = ph_val
        ph_line = PH_TEXT.get((val, mod), f"{default_ph}")

    if nitrogen_val:
        val, mod = nitrogen_val
        fertility_line = FERTILITY_TEXT.get((val, mod), f"{default_fertility}")

    if salinity_val:
        val, mod = salinity_val
        if val is not None and val > 0:
            salinity_line = SALINITY_TEXT.get(val, None)

    lines = ["AUGURY v1"]
    lines.append(f"Moisture: {moisture_line or default_moisture}")
    lines.append(f"Soil pH: {ph_line or default_ph}")
    lines.append(f"Fertility: {fertility_line or default_fertility}")
    if salinity_line:
        lines.append(f"Salinity: {salinity_line}")
    lines.append("Source: Ellenberg Indicator Values (Europe)")

    return "\n".join(lines)


SYSTEM_PROMPT = (
    "You are a soil health assistant specializing in weeds and plants as soil indicators. "
    "Given a plant species, you describe what soil conditions it indicates — including "
    "compaction, drainage, nutrient imbalances, pH, organic matter state, and microbial "
    "activity. You do NOT provide management recommendations or solutions. You respond "
    "in clear, plain language suitable for farmers."
)

QUESTION_TEMPLATES = [
    "What does {species} indicate about soil conditions?",
    "I'm seeing a lot of {species} in my paddock. What's my soil telling me?",
    "What soil conditions does {species} indicate?",
    "What does it mean when {species} is dominant in a pasture?",
    "Tell me about {species} as a soil indicator.",
    "Why is {species} growing here? What does it say about the soil?",
    "What nutrients are imbalanced if I have {species}?",
    "Is {species} a sign of compaction or drainage issues?",
]


def parse_ellenberg_csv(csv_path):
    """Parse the Ellenberg CSV and return species entries with soil indicators."""
    entries = []
    with open(csv_path, encoding='utf-8') as f:
        reader = csv.DictReader(f, delimiter='\t')
        for row in reader:
            name = (row.get('Name') or '').strip()
            if not name or name.startswith('#'):
                continue

            f_raw = (row.get('F') or '').strip()
            r_raw = (row.get('R') or '').strip()
            n_raw = (row.get('N') or '').strip()
            s_raw = (row.get('S') or '').strip()

            moisture_val = scale_modifier(f_raw)
            ph_val = scale_modifier(r_raw)
            nitrogen_val = scale_modifier(n_raw)
            salinity_val = scale_modifier(s_raw)

            # Require at least one interpretable indicator
            core_ok = any(
                v is not None and v[0] is not None
                for v in [moisture_val, ph_val, nitrogen_val]
            )
            if not core_ok:
                continue

            entries.append({
                'species': name,
                'moisture_val': moisture_val,
                'ph_val': ph_val,
                'nitrogen_val': nitrogen_val,
                'salinity_val': salinity_val,
            })

    return entries


def generate_jsonl(entries, output_path):
    """Generate contract-format JSONL with all 8 question templates."""
    examples = []
    seen_species = set()

    for entry in entries:
        species = entry['species']
        norm = species.lower().strip()
        if norm in seen_species:
            continue
        seen_species.add(norm)

        assistant_text = build_assistant_text(
            species,
            entry['moisture_val'],
            entry['ph_val'],
            entry['nitrogen_val'],
            entry['salinity_val'],
        )

        for template in QUESTION_TEMPLATES:
            question = f"[Region: Europe] {template.format(species=species)}"
            example = {
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": question},
                    {"role": "assistant", "content": assistant_text},
                ]
            }
            examples.append(example)

    with open(output_path, 'w', encoding='utf-8') as f:
        for ex in examples:
            f.write(json.dumps(ex, ensure_ascii=False) + '\n')

    return len(examples)


def main():
    this_dir = Path(__file__).resolve().parent
    project_dir = this_dir.parent

    csv_path = project_dir / 'data' / 'sources' / 'Ellenberg_VascularPlants.csv'
    output_path = project_dir / 'data' / 'training' / 'ellenberg_indicators.jsonl'

    if not csv_path.exists():
        print(f"ERROR: {csv_path} not found.")
        sys.exit(1)

    entries = parse_ellenberg_csv(str(csv_path))
    print(f"Parsed {len(entries)} species from Ellenberg CSV")

    n_examples = generate_jsonl(entries, str(output_path))
    unique = n_examples // len(QUESTION_TEMPLATES)
    print(f"Generated {n_examples} examples ({unique} species × {len(QUESTION_TEMPLATES)} templates)")
    print(f"  → {output_path}")


if __name__ == '__main__':
    main()

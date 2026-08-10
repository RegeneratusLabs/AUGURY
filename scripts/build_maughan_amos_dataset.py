#!/usr/bin/env python3
"""Convert Maughan & Amos species data to AUGURY contract-format JSONL."""

import json
from pathlib import Path
from maughan_amos_data import MAUGHAN_AMOS_SPECIES, MAUGHAN_AMOS_2024_EXTRA

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


def build_assistant_text(entry, source_label):
    """Build contract-format response from Maughan & Amos data."""
    lines = ["AUGURY v1"]

    indicators = entry['indicators']
    # Split on semicolons for key areas
    parts = indicators.replace('. ', '; ').split(';')

    # Categorize indicators into contract keys
    moisture_parts = []
    ph_parts = []
    fertility_parts = []
    structure_parts = []
    other_parts = []

    # Keywords for categorization
    moisture_kw = ['moist', 'water', 'flood', 'drain', 'dry', 'damp', 'wet', 'humidity', 'hydric', 'gley']
    ph_kw = ['acid', 'alkaline', 'lime', 'ph', 'calcareous', 'base', 'chalk']
    fertility_kw = ['fertile', 'fertility', 'nutrient', 'nitrogen', 'phosphorus', 'potassium', 'humus', 'organic matter', 'carbon', 'manure', 'compost']
    structure_kw = ['compact', 'compaction', 'hardpan', 'crust', 'smear', 'loose', 'tillage', 'plough', 'erosion', 'leaching', 'aeration', 'structure']

    for part in parts:
        p = part.strip().lower()
        if not p:
            continue
        categorized = False
        for kw in moisture_kw:
            if kw in p:
                moisture_parts.append(part.strip())
                categorized = True
                break
        if not categorized:
            for kw in ph_kw:
                if kw in p:
                    ph_parts.append(part.strip())
                    categorized = True
                    break
        if not categorized:
            for kw in fertility_kw:
                if kw in p:
                    fertility_parts.append(part.strip())
                    categorized = True
                    break
        if not categorized:
            for kw in structure_kw:
                if kw in p:
                    structure_parts.append(part.strip())
                    categorized = True
                    break
        if not categorized:
            other_parts.append(part.strip())

    lines.append(f"Moisture: {'; '.join(moisture_parts) if moisture_parts else 'not specified'}")
    lines.append(f"Soil pH: {'; '.join(ph_parts) if ph_parts else 'not specified'}")
    lines.append(f"Fertility: {'; '.join(fertility_parts) if fertility_parts else 'not specified'}")
    if structure_parts:
        lines.append(f"Structure: {'; '.join(structure_parts)}")
    if other_parts:
        lines.append(f"Other indicators: {'; '.join(other_parts)}")
    lines.append(f"Source: {source_label}")

    return "\n".join(lines)


def generate_jsonl(entries, output_path, source_label):
    """Generate contract-format JSONL."""
    examples = []

    for entry in entries:
        species_label = f"{entry['common']} ({entry['latin']})"
        assistant_text = build_assistant_text(entry, source_label)

        for template in QUESTION_TEMPLATES:
            question = f"[Region: UK] {template.format(species=species_label)}"
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
    project_dir = Path(__file__).resolve().parent.parent

    n1 = generate_jsonl(
        MAUGHAN_AMOS_SPECIES,
        project_dir / 'data' / 'training' / 'maughan_amos_2022.jsonl',
        "Maughan & Amos, Weeds as Bioindicators (UK, 2022)",
    )
    n2 = generate_jsonl(
        MAUGHAN_AMOS_2024_EXTRA,
        project_dir / 'data' / 'training' / 'maughan_amos_2024.jsonl',
        "Maughan & Amos, Plant Bioindicators Species Guide (UK, 2024)",
    )

    unique = (n1 + n2) // len(QUESTION_TEMPLATES)
    print(f"Generated {n1 + n2} total examples ({unique} species × {len(QUESTION_TEMPLATES)} templates)")
    print(f"  Maughan & Amos 2022: {n1} examples")
    print(f"  Maughan & Amos 2024: {n2} examples")


if __name__ == '__main__':
    main()

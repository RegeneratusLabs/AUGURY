#!/usr/bin/env python3
"""Merge all data sources into unified AUGURY contract-format datasets.

Converts legacy-format responses to the Interoperable SLM Contract.
"""

import json
import random
import re
from collections import defaultdict
from pathlib import Path

SYSTEM_PROMPT = (
    "You are a soil health assistant specializing in weeds and plants as soil indicators. "
    "Given a plant species, you describe what soil conditions it indicates — including "
    "compaction, drainage, nutrient imbalances, pH, organic matter state, and microbial "
    "activity. You do NOT provide management recommendations or solutions. You respond "
    "in clear, plain language suitable for farmers."
)

CONTRACT_VERSION = "AUGURY v1"


def extract_species_key(question):
    """Extract a normalized species key from a question string."""
    m = re.search(r'does (.+?) \(', question)
    if m:
        return m.group(1).lower().strip()
    for pattern in [
        r'seeing a lot of (.+?) in my paddock',
        r'soil conditions does (.+?) indicate',
        r'mean when (.+?) is dominant',
        r'Tell me about (.+?) as a soil indicator',
        r'is (.+?) growing here',
        r'imbalanced if I have (.+)',
        r'Is (.+?) a sign of',
    ]:
        m = re.search(pattern, question)
        if m:
            return m.group(1).lower().strip()
    return question.lower().strip()


def load_jsonl(path):
    """Load all examples from a JSONL file."""
    if not path.exists():
        print(f"  WARNING: {path} not found, skipping")
        return []
    with open(path, encoding='utf-8') as f:
        return [json.loads(line) for line in f if line.strip()]


def is_already_contract_format(assistant_text):
    """Check if response already follows the contract format."""
    return assistant_text.startswith("AUGURY v")


def convert_to_contract(text, source_label):
    """Convert legacy free-text response to contract format (no version header)."""
    if is_already_contract_format(text):
        return text

    # Extract the body (strip the old template lead-in and source line)
    body = text
    for prefix in [
        "indicates the following soil conditions:\n",
        "indicates the following soil conditions:",
        "indicates:\n",
        "indicates:",
    ]:
        if prefix in body:
            body = body.split(prefix, 1)[1].strip()
            break

    # Remove old source line and any AUGURY v1 header
    body = re.sub(r'\n?Source:.*$', '', body).strip()
    body = re.sub(r'^AUGURY v\d+\n?', '', body).strip()

    if not body:
        body = text.strip()

    # Categorize
    if ':' in body and '\n' in body:
        pass  # already structured
    else:
        body = f"General indicators: {body.replace(chr(10), '; ')}"

    return f"{body}\nSource: {source_label}"


def get_source_label(assistant_text):
    """Extract human-readable source label from legacy assistant text."""
    for src in [
        ("CAWR Bioindicators Field Guide", "CAWR Bioindicators Field Guide (UK, 2021)"),
        ("AU Pasture Weeds SA", "AU Pasture Weeds (South Australia, 2025)"),
        ("VIC Soil Health Brown Book", "VIC Soil Health Brown Book (Victoria, Australia)"),
    ]:
        if src[0] in assistant_text:
            return src[1]
    return "Unknown Source"


def normalize_system_prompt(examples):
    """Ensure all examples use the canonical system prompt."""
    for ex in examples:
        msgs = ex['messages']
        if msgs[0]['role'] == 'system':
            msgs[0]['content'] = SYSTEM_PROMPT


def fix_nettle_bug(examples):
    """Fix '-nettle' bug in CAWR data."""
    fixed = 0
    for ex in examples:
        q = ex['messages'][1]['content']
        resp = ex['messages'][2]['content']
        if '-nettle' in q:
            m = re.search(r'\((.+?)\)', q)
            latin = m.group(1) if m else ''
            if 'Henbit dead' in latin or 'amplexicaule' in latin.lower():
                common = 'Henbit dead-nettle'
            elif 'Red dead' in latin or 'Lamium purpureum' in latin.lower():
                common = 'Red dead-nettle'
            else:
                continue
            for tmpl in [r'-nettle', r' -nettle']:
                q = q.replace(tmpl, f' {common}')
            resp = resp.replace('-nettle', common)
            ex['messages'][1]['content'] = q
            ex['messages'][2]['content'] = resp
            fixed += 1
    if fixed:
        print(f"  Fixed {fixed} '-nettle' entries")


def fix_cawr_names(examples):
    """Fix CAWR parser bug where soil types appear in common names."""
    cawr_bugs = {
        'Chicory clay': 'Chicory',
        'Annual meadowgrass fertile': 'Annual meadowgrass',
        'Creeping buttercup clay': 'Creeping buttercup',
        'Creeping thistle clay': 'Creeping thistle',
        'Curled dock clay': 'Curled dock',
        'Dandelion clay': 'Dandelion',
    }
    fixed = 0
    for ex in examples:
        if 'CAWR' not in ex['messages'][2]['content']:
            continue
        for bad, good in cawr_bugs.items():
            q = ex['messages'][1]['content']
            old = f'{bad} ({bad})'
            new = f'{good} ({good})'
            if old in q:
                ex['messages'][1]['content'] = q.replace(old, new)
                ex['messages'][2]['content'] = ex['messages'][2]['content'].replace(bad, good)
                fixed += 1
    if fixed:
        print(f"  Fixed {fixed} CAWR name entries")


def filter_bad_formats(examples):
    """Remove examples with wrong message count."""
    before = len(examples)
    good = [ex for ex in examples if len(ex.get('messages', [])) == 3]
    bad = before - len(good)
    if bad:
        print(f"  Filtered {bad} malformed examples")
    return good


def merge_and_split(existing_train, existing_val, new_train, new_val):
    """Merge existing with new, deduplicate by species, split into train/val."""
    existing_species = set()
    for ex in existing_train + existing_val:
        key = extract_species_key(ex['messages'][1]['content'])
        existing_species.add(key)

    print(f"  Existing species: {len(existing_species)}")

    # Add new examples, skip duplicates
    added = 0
    dup = 0
    for ex in new_train + new_val:
        key = extract_species_key(ex['messages'][1]['content'])
        if key not in existing_species:
            existing_species.add(key)
            new_train.append(ex)
            added += 1
        else:
            dup += 1

    if dup:
        print(f"  Skipped {dup} duplicate species from new sources")
    print(f"  Added {added} net new examples")

    # Split: group by species, random 90/10
    random.seed(42)
    species_groups = defaultdict(list)
    for ex in new_train:
        key = extract_species_key(ex['messages'][1]['content'])
        species_groups[key].append(ex)

    species_list = list(species_groups.keys())
    random.shuffle(species_list)
    n_val = max(1, len(species_list) // 10)
    val_species = set(species_list[:n_val])

    final_train = list(existing_train)
    final_val = list(existing_val)
    for key, examples in species_groups.items():
        if key in val_species:
            final_val.extend(examples)
        else:
            final_train.extend(examples)

    random.shuffle(final_train)
    random.shuffle(final_val)
    return final_train, final_val


def validate_dataset(examples):
    """Quality checks for contract format."""
    issues = []
    seen = set()
    no_contract = 0

    for i, ex in enumerate(examples):
        msgs = ex['messages']
        if len(msgs) != 3:
            issues.append(f"Example {i}: wrong message count ({len(msgs)})")
            continue
        if not msgs[2]['content'].strip():
            issues.append(f"Example {i}: empty assistant response")
            continue
        if 'Source:' not in msgs[2]['content']:
            no_contract += 1

    if no_contract:
        issues.append(f"{no_contract} examples missing Source: line")

    return issues


def main():
    project_dir = Path(__file__).resolve().parent.parent

    print("Loading sources...")
    existing_train = load_jsonl(project_dir / 'weeds_indicators_train.jsonl')
    existing_val = load_jsonl(project_dir / 'weeds_indicators_val.jsonl')
    ellenberg = load_jsonl(project_dir / 'data' / 'training' / 'ellenberg_indicators_v2.jsonl')
    if not ellenberg:
        ellenberg = load_jsonl(project_dir / 'data' / 'training' / 'ellenberg_indicators.jsonl')
    maughan_2022 = load_jsonl(project_dir / 'data' / 'training' / 'maughan_amos_2022.jsonl')
    maughan_2024 = load_jsonl(project_dir / 'data' / 'training' / 'maughan_amos_2024.jsonl')
    refusal = load_jsonl(project_dir / 'data' / 'training' / 'refusal_examples.jsonl')

    print(f"  Original train: {len(existing_train)}, val: {len(existing_val)}")
    print(f"  Ellenberg (v2): {len(ellenberg)}")
    print(f"  Maughan & Amos 2022: {len(maughan_2022)}, 2024: {len(maughan_2024)}")
    print(f"  Refusal examples: {len(refusal)}")

    # Fix legacy data
    print("\nCleaning legacy data...")
    fix_nettle_bug(existing_train)
    fix_nettle_bug(existing_val)
    fix_cawr_names(existing_train)
    fix_cawr_names(existing_val)

    # Strip Ducerf + permaculture
    def is_bad(ex):
        r = ex['messages'][2]['content']
        return 'Ducerf' in r or 'permaculture' in r.lower()
    existing_train = [ex for ex in existing_train if not is_bad(ex)]
    existing_val = [ex for ex in existing_val if not is_bad(ex)]
    # Tag existing data with region prefixes
    def tag_region(examples, region):
        for ex in examples:
            q = ex['messages'][1]['content']
            if not q.startswith('[Region:'):
                ex['messages'][1]['content'] = f'[Region: {region}] {q}'

    # CAWR data is UK-sourced, AU/VIC is Australia
    def get_region_for(ex):
        resp = ex['messages'][2]['content']
        if 'AU Pasture' in resp or 'VIC Soil' in resp:
            return 'Australia'
        if 'CAWR' in resp:
            return 'UK'
        return 'Europe'  # fallback
    
    for ex in existing_train + existing_val:
        region = get_region_for(ex)
        tag_region([ex], region)
    
    print(f"  Added region tags to {len(existing_train) + len(existing_val)} legacy examples")

    # Convert legacy to contract format
    print("\nConverting legacy to contract format...")
    converted = 0
    for ex in existing_train + existing_val:
        txt = ex['messages'][2]['content']
        if not is_already_contract_format(txt):
            src = get_source_label(txt)
            ex['messages'][2]['content'] = convert_to_contract(txt, src)
            converted += 1
    print(f"  Converted {converted} legacy responses")

    # Normalize system prompts
    for ds in [existing_train, existing_val, ellenberg, maughan_2022, maughan_2024]:
        normalize_system_prompt(ds)

    # Filter bad formats from existing
    existing_train = filter_bad_formats(existing_train)
    existing_val = filter_bad_formats(existing_val)

    # Combine new sources (already in contract format)
    new_all = ellenberg + maughan_2022 + maughan_2024
    print(f"\nTotal new examples: {len(new_all)}")

    # Merge and split
    print("\nMerging and splitting...")
    merged_train, merged_val = merge_and_split(existing_train, existing_val, ellenberg + maughan_2022 + maughan_2024 + refusal, [])

    # Validate
    print("\nValidating...")
    train_issues = validate_dataset(merged_train)
    val_issues = validate_dataset(merged_val)
    if train_issues:
        print(f"  Train: {len(train_issues)} issues:")
        for issue in train_issues:
            print(f"    {issue}")
    else:
        print("  Train: clean")
    if val_issues:
        print(f"  Val: {len(val_issues)} issues:")
        for issue in val_issues:
            print(f"    {issue}")
    else:
        print("  Val: clean")

    # Write output
    train_path = project_dir / 'data' / 'training' / 'weeds_indicators_merged_train.jsonl'
    val_path = project_dir / 'data' / 'training' / 'weeds_indicators_merged_val.jsonl'

    for path, data in [(train_path, merged_train), (val_path, merged_val)]:
        with open(path, 'w', encoding='utf-8') as f:
            for ex in data:
                f.write(json.dumps(ex, ensure_ascii=False) + '\n')

    print(f"\nDone.")
    print(f"  Train: {train_path} ({len(merged_train)} examples)")
    print(f"  Val:   {val_path} ({len(merged_val)} examples)")
    print(f"  Total: {len(merged_train) + len(merged_val)}")


if __name__ == '__main__':
    main()

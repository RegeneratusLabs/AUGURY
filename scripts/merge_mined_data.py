#!/usr/bin/env python3
"""
AUGURY Data Merge Pipeline.

Combines species data from multiple mining subagents into a single
enriched database with confidence scoring and contradiction detection.

Usage:
    # After subagents save their JSON outputs:
    python scripts/merge_mined_data.py
    
    # Output: data/mining/augury_enriched_database.json
"""

import json
import re
import os
from pathlib import Path
from collections import defaultdict


# ── Name normalization ───────────────────────────────────────

def normalize_name(name):
    """Normalize scientific name for matching: lowercase, no authorities."""
    name = name.strip().lower()
    # Remove authority: "Rumex obtusifolius L." → "rumex obtusifolius"
    name = re.sub(r'\s+(l\.|subsp\.|var\.|ssp\.|auct\.)\s*.*$', '', name)
    # Remove trailing punctuation
    name = name.rstrip('.,;:')
    return name


# ── Confidence scoring ───────────────────────────────────────

def compute_confidence(claims, sources):
    """
    Assign confidence tier based on source quality and count.
    
    Rules:
    - high: 3+ independent sources, or peer-reviewed/govt source
    - medium: 2 sources agree, or published practitioner book  
    - low: single source, forum, or traditional knowledge
    """
    source_types = set()
    for s in sources:
        if any(kw in s.lower() for kw in ['ellenberg', 'peer-review', 'academic', 'journal', 'university', 'extension', 'nsw dpi', 'agriculture victoria', 'agresearch', 'weeds australia']):
            source_types.add('academic_govt')
        elif any(kw in s.lower() for kw in ['walters', 'maughan', 'cawr', 'published book']):
            source_types.add('published_book')
        elif any(kw in s.lower() for kw in ['permaculture', 'forum', 'practitioner', 'tradition']):
            source_types.add('practitioner')
        else:
            source_types.add('practitioner')
    
    num_sources = len(set(sources))
    
    if num_sources >= 3 or 'academic_govt' in source_types:
        return 'high'
    elif num_sources >= 2 or 'published_book' in source_types:
        return 'medium'
    else:
        return 'low'


# ── Merge logic ──────────────────────────────────────────────

def merge_all(input_files):
    """
    Merge multiple JSON arrays of species data into one enriched database.
    
    Handles:
    - Name normalization and deduplication
    - Combining claims from multiple sources
    - Confidence calculation
    - Contradiction detection
    """
    merged = defaultdict(lambda: {
        'scientific_name': '',
        'common_names': [],
        'region': [],
        'ellenberg_values': {},
        'nutrient_claims': [],
        'soil_claims': [],
        'sources': set(),
    })
    
    for filepath in input_files:
        if not os.path.exists(filepath):
            print(f"  SKIP (not found): {filepath}")
            continue
        
        with open(filepath) as f:
            data = json.load(f)
        
        if not isinstance(data, list):
            print(f"  SKIP (not list): {filepath}")
            continue
        
        print(f"  Loading {filepath}: {len(data)} entries")
        
        for entry in data:
            sci_name = entry.get('scientific_name', '')
            if not sci_name:
                continue
            
            key = normalize_name(sci_name)
            m = merged[key]
            
            # Best scientific name (prefer the first one with proper capitalization)
            if not m['scientific_name']:
                m['scientific_name'] = sci_name
            elif sci_name[0].isupper() and not m['scientific_name'][0].isupper():
                m['scientific_name'] = sci_name
            
            # Merge common names
            for cn in entry.get('common_names', []):
                cn_lower = cn.lower().strip()
                if cn_lower not in [n.lower() for n in m['common_names']]:
                    m['common_names'].append(cn)
            
            # Merge regions
            for r in entry.get('region', []):
                if r not in m['region']:
                    m['region'].append(r)
            
            # Merge Ellenberg values
            for k, v in entry.get('ellenberg_values', {}).items():
                if k not in m['ellenberg_values']:
                    m['ellenberg_values'][k] = v
            
            # Merge nutrient claims
            for claim in entry.get('nutrient_claims', []):
                m['nutrient_claims'].append(claim)
                if claim.get('source'):
                    m['sources'].add(claim['source'])
            
            # Merge soil claims
            for claim in entry.get('soil_claims', []):
                m['soil_claims'].append(claim)
                if claim.get('source'):
                    m['sources'].add(claim['source'])
    
    # Convert to list, compute confidence, detect contradictions
    result = []
    for key, m in sorted(merged.items()):
        # Consolidate: merge duplicate claims about the same nutrient/property
        nutrient_by_source = defaultdict(list)
        for c in m['nutrient_claims']:
            nutrient_by_source[c['nutrient']].append(c)
        
        soil_by_property = defaultdict(list)
        for c in m['soil_claims']:
            soil_by_property[c['property']].append(c)
        
        # Detect contradictions: same nutrient, opposite relationship
        cleaned_nutrients = []
        for nutrient, claims in nutrient_by_source.items():
            relationships = defaultdict(list)
            for c in claims:
                rel = c['relationship'].lower()
                if 'deficiency' in rel or 'low' in rel:
                    relationships['low'].append(c)
                elif 'excess' in rel or 'high' in rel or 'adequate' in rel:
                    relationships['high'].append(c)
                else:
                    relationships['other'].append(c)
            
            # If both high and low claims exist, flag contradiction
            if len(relationships.get('low', [])) > 0 and len(relationships.get('high', [])) > 0:
                # Keep both but flag
                for c in relationships['low']:
                    c['contradiction_flag'] = True
                for c in relationships['high']:
                    c['contradiction_flag'] = True
            
            # Keep all claims, compute per-nutrient confidence
            sources_for_nutrient = list(set(c.get('source', '') for c in claims if c.get('source')))
            conf = compute_confidence(claims, sources_for_nutrient)
            for c in claims:
                c['aggregate_confidence'] = conf
            cleaned_nutrients.extend(claims)
        
        # Clean soil claims similarly
        cleaned_soil = []
        for prop, claims in soil_by_property.items():
            sources_for_prop = list(set(c.get('source', '') for c in claims if c.get('source')))
            conf = compute_confidence(claims, sources_for_prop)
            for c in claims:
                c['aggregate_confidence'] = conf
            cleaned_soil.extend(claims)
        
        # Sort claims by confidence
        cleaned_nutrients.sort(key=lambda c: {'high': 0, 'medium': 1, 'low': 2}.get(c.get('aggregate_confidence', 'low'), 3))
        cleaned_soil.sort(key=lambda c: {'high': 0, 'medium': 1, 'low': 2}.get(c.get('aggregate_confidence', 'low'), 3))
        
        # Compute overall confidence
        all_claims = cleaned_nutrients + cleaned_soil
        all_sources = list(m['sources'])
        overall_confidence = compute_confidence(all_claims, all_sources)
        
        result.append({
            'scientific_name': m['scientific_name'],
            'common_names': sorted(m['common_names'], key=len, reverse=True),
            'region': sorted(m['region']),
            'ellenberg_values': m['ellenberg_values'],
            'nutrient_claims': cleaned_nutrients,
            'soil_claims': cleaned_soil,
            'claim_count': len(cleaned_nutrients) + len(cleaned_soil),
            'source_count': len(m['sources']),
            'overall_confidence': overall_confidence,
            'contradictions': any(c.get('contradiction_flag') for c in cleaned_nutrients + cleaned_soil),
        })
    
    return result


def main():
    mining_dir = Path(__file__).resolve().parent.parent / 'data' / 'mining'
    mining_dir.mkdir(parents=True, exist_ok=True)
    
    # Find all JSON files in mining directory
    input_files = sorted(mining_dir.glob('*.json'))
    # Exclude the output file itself
    input_files = [f for f in input_files if 'merged' not in f.name and 'schema' not in f.name]
    
    if not input_files:
        print("No mining data files found in data/mining/")
        print("Expected files from subagent outputs (e.g., walters_claims.json, au_nz_weeds.json, etc.)")
        return
    
    print(f"Found {len(input_files)} mining data files:")
    for f in input_files:
        print(f"  {f.name}")
    
    merged = merge_all(input_files)
    
    # Stats
    total_claims = sum(s['claim_count'] for s in merged)
    high = sum(1 for s in merged if s['overall_confidence'] == 'high')
    med = sum(1 for s in merged if s['overall_confidence'] == 'medium')
    low = sum(1 for s in merged if s['overall_confidence'] == 'low')
    contradictions = sum(1 for s in merged if s['contradictions'])
    with_nutrients = sum(1 for s in merged if s['nutrient_claims'])
    
    print(f"\nMerged: {len(merged)} species, {total_claims} total claims")
    print(f"  Confidence: {high} high, {med} medium, {low} low")
    print(f"  Species with nutrient data: {with_nutrients}")
    print(f"  Species with contradictions: {contradictions}")
    
    # Write output
    output_path = mining_dir / 'augury_enriched_database.json'
    
    output = {
        'version': '1.0',
        'description': 'AUGURY enriched species database — merged from multiple sources including Charles Walters, university extension factsheets, permaculture practitioner knowledge, academic Ellenberg enrichment, and AU-NZ pastoral weed guides.',
        'total_species': len(merged),
        'stats': {
            'high_confidence': high,
            'medium_confidence': med, 
            'low_confidence': low,
            'contradictions': contradictions,
            'species_with_nutrients': with_nutrients,
        },
        'species': merged,
    }
    
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)
    
    size_kb = os.path.getsize(output_path) / 1024
    print(f"\nSaved: {output_path} ({size_kb:.0f} KB)")
    
    # Print top nutrient findings
    print("\n── Top nutrient findings (high confidence only) ──")
    count = 0
    for s in merged:
        for c in s['nutrient_claims']:
            if c.get('aggregate_confidence') == 'high' and count < 15:
                print(f"  {s['scientific_name']}: {c['nutrient']} — {c['relationship']}")
                count += 1


if __name__ == '__main__':
    main()

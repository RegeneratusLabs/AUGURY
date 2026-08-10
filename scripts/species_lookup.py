#!/usr/bin/env python3
"""
AUGURY Species Lookup Engine.

Deterministic, offline species → soil indicator lookup.
100% ground truth. No model hallucination possible.

Usage:
    from species_lookup import SpeciesDB
    db = SpeciesDB()
    result = db.search("Yorkshire fog")
    indicators = db.get_indicators("Holcus lanatus", region="UK")
"""

import json
import re
import os
from pathlib import Path
from difflib import get_close_matches


class SpeciesDB:
    """Deterministic species → soil indicator lookup database."""

    def __init__(self, data_dir=None):
        """
        Args:
            data_dir: Path to data/training/ directory. Auto-detected if None.
        """
        if data_dir is None:
            data_dir = Path(__file__).resolve().parent.parent / "data" / "training"
        self.data_dir = Path(data_dir)

        self._species = {}        # scientific_name_lower → SpeciesInfo
        self._common_index = {}   # common_name_lower → species_key
        self._scientific_names = []  # for fuzzy matching
        self._common_names_list = []  # for fuzzy matching
        self._nutrients = {}      # scientific_name_lower → nutrient claims (from mining)

        self._load()
        self._load_nutrients()
        self._load_merged_database()
        # Extended common names must load AFTER the merged DB adds its species,
        # otherwise map entries for merged-DB-only species are silently skipped.
        self._load_common_name_map()

    # ── internal ──────────────────────────────────────────────

    def _load_merged_database(self):
        """Supplement species data from the merged research database (160 AU species)."""
        merged_path = self.data_dir.parent.parent / "data" / "research" / "database-merged.json"
        if not merged_path.exists():
            return
        try:
            with open(merged_path) as f:
                merged = json.load(f)
        except (json.JSONDecodeError, OSError):
            return

        for key, info in merged.items():
            if key in self._species:
                # Override indicators with clean merged DB data (standard keys)
                for region, region_data in info.get("regions", {}).items():
                    if region not in self._species[key].get("regions", {}):
                        self._species[key]["regions"][region] = region_data
                    else:
                        # Override individual indicator keys with clean versions
                        for ind_key, ind_val in region_data.get("indicators", {}).items():
                            if ind_val and ind_val.strip():
                                self._species[key]["regions"][region]["indicators"][ind_key] = ind_val
                # Add common names if missing
                existing_cns = {c.lower() for c in self._species[key].get("common_names", [])}
                for cn in info.get("common_names", []):
                    cn_lower = cn.lower()
                    if cn_lower not in existing_cns:
                        self._species[key]["common_names"].append(cn)
                        existing_cns.add(cn_lower)
                        if cn_lower not in self._common_index:
                            self._common_index[cn_lower] = key
                            self._common_names_list.append(cn)
                # Add nutrients if present
                if info.get("nutrients", {}).get("claims") and key not in self._nutrients:
                    self._nutrients[key] = info["nutrients"]
            else:
                # New species — add it
                self._species[key] = info
                for cn in info.get("common_names", []):
                    cn_lower = cn.lower()
                    if cn_lower not in self._common_index:
                        self._common_index[cn_lower] = key
                        self._common_names_list.append(cn)
                if info.get("nutrients", {}).get("claims"):
                    self._nutrients[key] = info["nutrients"]

    def _load_nutrients(self):
        """Load enriched nutrient data from mining results."""
        mining_path = self.data_dir.parent / "mining" / "augury_enriched_database.json"
        if not mining_path.exists():
            return

        try:
            with open(mining_path) as f:
                enriched = json.load(f)

            for sp in enriched.get("species", []):
                key = sp["scientific_name"].lower()
                claims = [
                    c for c in sp.get("nutrient_claims", [])
                    if c.get("aggregate_confidence") in ("high", "medium")
                ]
                if claims:
                    self._nutrients[key] = {
                        "claims": claims,
                        "overall_confidence": sp.get("overall_confidence", "low"),
                    }
        except Exception:
            pass  # non-critical — nutrients are bonus data

    def _load(self):
        """Load species data from merged training JSONL."""
        train_path = self.data_dir / "weeds_indicators_merged_train.jsonl"
        if not train_path.exists():
            raise FileNotFoundError(f"Training data not found: {train_path}")

        with open(train_path) as f:
            for line in f:
                d = json.loads(line)
                user = [m["content"] for m in d["messages"] if m["role"] == "user"][0]
                assistant = [m["content"] for m in d["messages"] if m["role"] == "assistant"][0]

                if "soil indicator specialist" in assistant:
                    continue  # skip refusal examples

                sp = self._extract_scientific_name(user)
                if not sp:
                    continue

                region = self._extract_region(user)
                common = self._extract_common_name(user)
                indicators = self._parse_indicators(assistant)
                source = self._extract_source(assistant)

                key = sp.lower()
                if key not in self._species:
                    self._species[key] = {
                        "scientific_name": sp,
                        "common_names": [],
                        "regions": {},
                    }
                    self._scientific_names.append(sp)

                info = self._species[key]
                if common and common not in info["common_names"]:
                    info["common_names"].append(common)
                    cn_lower = common.lower()
                    if cn_lower not in self._common_index:
                        self._common_index[cn_lower] = key
                        self._common_names_list.append(common)

                if region not in info["regions"]:
                    info["regions"][region] = {
                        "indicators": indicators,
                        "source": source,
                    }

        # Also load common names from build_v2_improvements.py mapping
        # (moved to __init__ — must run after _load_merged_database so merged-DB
        #  species are present for the sci_lower check)

    def _load_common_name_map(self):
        """Load extended common name mappings."""
        scripts_dir = Path(__file__).resolve().parent
        map_path = scripts_dir / "build_v2_improvements.py"
        if not map_path.exists():
            return

        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("v2", map_path)
            v2 = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(v2)
            if hasattr(v2, "COMMON_NAMES"):
                for sci_lower, common in v2.COMMON_NAMES.items():
                    if sci_lower in self._species:
                        cn_lower = common.lower()
                        if cn_lower not in self._common_index:
                            self._common_index[cn_lower] = sci_lower
                            self._common_names_list.append(common)
        except Exception:
            pass  # non-critical

    @staticmethod
    def _extract_scientific_name(text):
        """Extract scientific name from user message."""
        for pat in [
            r"\(([A-Z][a-z]+ [a-z]+)\)",
            r"of ([A-Z][a-z]+ [a-z]+) in",
            r"does ([A-Z][a-z]+ [a-z]+) \(",
            r"about ([A-Z][a-z]+ [a-z]+) as",
            r"([A-Z][a-z]+ [a-z]+) indicate",
        ]:
            m = re.search(pat, text)
            if m:
                return m.group(1)
        return None

    @staticmethod
    def _extract_region(text):
        for r in ["Europe", "UK", "Australia"]:
            if f"[Region: {r}]" in text:
                return r
        return "Europe"

    @staticmethod
    def _extract_common_name(text):
        m = re.search(r"does (.+?) \(", text)
        if m:
            name = m.group(1).strip()
            # Filter out template fragments
            if not name.startswith("it mean") and len(name) > 2:
                return name
        m = re.search(r"about (.+?) as a soil", text)
        if m:
            name = m.group(1).strip()
            if len(name) > 2:
                return name
        return None

    @staticmethod
    def _parse_indicators(text):
        indicators = {}
        KEY_NORMALIZE = {
            "the moisture picture": "Moisture",
            "the ph picture": "Soil pH",
            "salinity is also worth noting": "Salinity",
            "looking at specific nutrients": "Nutrients",
            "there's also a nutrient story here": "Nutrients",
            "these two agree": "Agreement indicator",
        }
        for line in text.split("\n"):
            line = line.strip()
            if ":" in line and not line.startswith("Source:"):
                k, v = line.split(":", 1)
                key = k.strip()
                # Normalize prose keys to standard keys
                key_lower = key.lower()
                if key_lower in KEY_NORMALIZE:
                    key = KEY_NORMALIZE[key_lower]
                # Skip verbose nutrient prose keys
                if key.lower().startswith("specifically,") or key.lower().startswith("when it comes to"):
                    continue
                indicators[key] = v.strip()
        return indicators

    @staticmethod
    def _extract_source(text):
        if "Source:" in text:
            return text.split("Source:")[1].split("\n")[0].strip()
        return ""

    # ── public API ────────────────────────────────────────────

    def search(self, query, top_n=5):
        """
        Search for a species by scientific or common name.

        Returns a list of (scientific_name, common_names, match_type, score)
        sorted by relevance. match_type is "exact" or "fuzzy".
        Score is 1.0 for exact, 0-1 for fuzzy.

        Args:
            query: Search string (e.g. "Yorkshire fog", "Holcus lanatus", "taraxacum")
            top_n: Max results to return.

        Returns:
            List of dicts: {scientific_name, common_names, match_type, score}
        """
        query_lower = query.strip().lower()
        if not query_lower:
            return []

        # Plural/singular normalization: "docks" → "dock", "thistles" → "thistle",
        # "cherries" → "cherry". Enables common-name lookups like "docks" →
        # "Curled dock". (Query variants are also used by partial/fuzzy steps below.)
        stem = None
        if query_lower.endswith("ies") and len(query_lower) > 4:
            stem = query_lower[:-3] + "y"
        elif query_lower.endswith("s") and len(query_lower) > 3 and not query_lower.endswith("ss"):
            stem = query_lower[:-1]
        variants = [query_lower] + ([stem] if stem else [])

        results = []

        # 1. Exact scientific name match
        if query_lower in self._species:
            info = self._species[query_lower]
            results.append({
                "scientific_name": info["scientific_name"],
                "common_names": info["common_names"],
                "match_type": "exact_scientific",
                "score": 1.0,
                "key": query_lower,
            })

        # 2. Exact common name match
        if query_lower in self._common_index:
            key = self._common_index[query_lower]
            if key not in {r["key"] for r in results}:
                info = self._species[key]
                results.append({
                    "scientific_name": info["scientific_name"],
                    "common_names": info["common_names"],
                    "match_type": "exact_common",
                    "score": 1.0,
                    "key": key,
                })

        # 3. Partial scientific name match (name appears in query OR query in name)
        if len(results) < top_n:
            for v in variants:
                for name in self._scientific_names:
                    name_lower = name.lower()
                    if name_lower in v or v in name_lower:
                        key = name_lower
                        if key in {r["key"] for r in results}:
                            continue
                        info = self._species[key]
                        # Score: longer match = higher
                        match_len = len(name_lower)
                        score = min(0.9, 0.6 + (match_len / max(len(v), 1)) * 0.3)
                        results.append({
                            "scientific_name": info["scientific_name"],
                            "common_names": info["common_names"],
                            "match_type": "partial_scientific",
                            "score": round(score, 2),
                            "key": key,
                        })

        # 4. Partial common name match (name appears in query OR query in name)
        if len(results) < top_n:
            for v in variants:
                for cn_lower, key in self._common_index.items():
                    if (cn_lower in v or v in cn_lower) and key not in {r.get("key", "") for r in results}:
                        info = self._species[key]
                        match_len = len(cn_lower)
                        score = min(0.85, 0.55 + (match_len / max(len(v), 1)) * 0.3)
                        results.append({
                            "scientific_name": info["scientific_name"],
                            "common_names": info["common_names"],
                            "match_type": "partial_common",
                            "score": round(score, 2),
                            "key": key,
                        })

        # 5. Fuzzy scientific name match (only for short queries — fuzzy matching
        # on long sentences produces unreliable false positives)
        if len(results) < top_n and len(query_lower) <= 40:
            fuzzy = get_close_matches(
                query_lower, [n.lower() for n in self._scientific_names],
                n=top_n - len(results), cutoff=0.6
            )
            for match in fuzzy:
                if match not in {r.get("key", "") for r in results}:
                    info = self._species[match]
                    # Calculate rough score based on similarity
                    score = 0.7 * (len(set(query_lower) & set(match)) / max(len(query_lower), len(match)))
                    results.append({
                        "scientific_name": info["scientific_name"],
                        "common_names": info["common_names"],
                        "match_type": "fuzzy_scientific",
                        "score": round(score, 2),
                        "key": match,
                    })

        return results[:top_n]

    def get_indicators(self, species_name, region=None):
        """
        Get soil indicators for a species.

        Args:
            species_name: Scientific name (case-insensitive).
            region: Preferred region (e.g. "UK", "Australia", "Europe").
                    If None, returns first available region.

        Returns:
            dict with keys: scientific_name, common_names, region, indicators, source
            OR None if species not found.
        """
        key = species_name.strip().lower()
        if key not in self._species:
            return None

        info = self._species[key]
        regions = info["regions"]

        if not regions:
            return None  # no indicator data for this species

        # Try preferred region first, then UK, then Europe, then first available
        for r in [region, "UK", "Europe"]:
            if r and r in regions:
                reg = regions[r]
                result = {
                    "scientific_name": info["scientific_name"],
                    "common_names": info["common_names"],
                    "region": r,
                    "indicators": reg.get("indicators", {}),
                    "source": reg.get("source", ""),
                }
                if key in self._nutrients:
                    result["nutrients"] = self._nutrients[key]
                return result

        # Fallback to first available region
        first_region = next(iter(regions))
        reg = regions[first_region]
        return {
            "scientific_name": info["scientific_name"],
            "common_names": info["common_names"],
            "region": first_region,
            "indicators": reg.get("indicators", {}),
            "source": reg.get("source", ""),
        }

    def get_common_name(self, species_name):
        """Get common name for a scientific name, or None."""
        key = species_name.strip().lower()
        if key in self._species and self._species[key]["common_names"]:
            return self._species[key]["common_names"][0]
        return None

    @property
    def species_count(self):
        return len(self._species)

    @property
    def regions(self):
        regions = set()
        for info in self._species.values():
            regions.update(info["regions"].keys())
        return sorted(regions)


# ── quick test ────────────────────────────────────────────────

if __name__ == "__main__":
    db = SpeciesDB()
    print(f"Loaded {db.species_count} species across {db.regions}")

    # Test exact scientific
    print("\n── Exact scientific ──")
    for r in db.search("taraxacum officinale"):
        print(f"  {r}")

    # Test common name
    print("\n── Common name ──")
    for r in db.search("Yorkshire fog"):
        print(f"  {r}")

    # Test fuzzy
    print("\n── Fuzzy (typo) ──")
    for r in db.search("taraxacum offcinale"):
        print(f"  {r}")

    # Test indicators
    print("\n── Indicators (UK region) ──")
    result = db.get_indicators("Holcus lanatus", region="UK")
    if result:
        print(f"  Species: {result['scientific_name']}")
        print(f"  Common: {result['common_names']}")
        print(f"  Region: {result['region']}")
        for k, v in result["indicators"].items():
            print(f"    {k}: {v[:100]}")
        print(f"  Source: {result['source']}")

    print("\n── Indicators (Australia region) ──")
    result = db.get_indicators("Holcus lanatus", region="Australia")
    if result:
        for k, v in result["indicators"].items():
            print(f"    {k}: {v[:100]}")
    else:
        print("  Not found in AU — using European data instead")

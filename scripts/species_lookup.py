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
from difflib import get_close_matches, SequenceMatcher


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
        self._canonical = None    # lazily-loaded canonical_map.json (shared with vision)

        self._load()
        self._load_nutrients()
        self._load_merged_database()
        # Extended common names must load AFTER the merged DB adds its species,
        # otherwise map entries for merged-DB-only species are silently skipped.
        self._load_common_name_map()
        # Curated vernacular synonyms load last so they always win.
        self.synonym_count = 0
        self._load_synonyms()
        # Drop artefacts produced by legacy extraction bugs (see _extract_scientific_name)
        self._sanitize()

    # Keys/names that are not species. "Dense infestations" entered the DB when
    # the old extractor mis-read a parenthetical common name in the training
    # template; "… clay" entries are UK soil associations, not plants.
    JUNK_KEY_RE = re.compile(
        r"\b(infestation|infestations|dense|clay|heavy|areas?|pasture|soil|"
        r"conditions?|grassy|widespread|severe)\b", re.I)

    def _sanitize(self):
        """Remove non-species artefacts and de-duplicate the common-name index.

        The training JSONL is the primary source of `self._species`, and it
        contains rows whose "Species:" field is not a plant (UK soil
        associations, mid-word truncations, genus misspellings). Those come from
        published data we must not rewrite, so they are filtered here. See
        scripts/junk_keys.py for the list and the reasoning.
        """
        from junk_keys import JUNK_KEYS

        dropped_keys, dropped_names = [], []

        for key in list(self._species):
            words = key.split()
            junk = (len(words) > 3 or len(words) < 2
                    or bool(self.JUNK_KEY_RE.search(key))
                    or key.strip().lower() in JUNK_KEYS)
            if junk:
                self._species.pop(key, None)
                dropped_keys.append(key)

        valid = set(self._species)
        for cn in list(self._common_index):
            key = self._common_index[cn]
            name = cn.strip()
            bad = (key not in valid
                   or len(name.split()) > 6
                   or bool(self.JUNK_KEY_RE.search(name))
                   or name.endswith("/")
                   or cn.strip().lower() in JUNK_KEYS)
            if bad:
                self._common_index.pop(cn, None)
                dropped_names.append(cn)

        self._scientific_names = [n for n in self._scientific_names
                                  if n.lower() in valid]
        self._common_names_list = [n for n in self._common_names_list
                                   if n.lower() in self._common_index]
        self.sanitize_report = {"dropped_keys": dropped_keys,
                                "dropped_names": len(dropped_names)}
        return self.sanitize_report

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

    # ── vernacular synonyms (fixes "sow thistle", "khaki weed", …) ──────────

    # Tokens too generic to establish a species match on their own. A query
    # matching only on one of these ("khaki weed" vs "onion weed") is a false
    # friend, not a hit.
    GENERIC_TOKENS = {
        "weed", "weeds", "grass", "grasses", "thistle", "thistles", "dock",
        "docks", "sedge", "rush", "rushes", "clover", "plant", "plants",
        "common", "wild", "native", "annual", "perennial", "black", "red",
        "white", "yellow", "blue", "purple", "giant", "creeping", "spiny",
        "prickly", "slender", "small", "large", "water", "marsh", "swamp",
        "couch", "brome", "fescue", "sorrel", "burr", "bur", "cress",
    }

    @classmethod
    def _content_tokens(cls, text):
        """Alphanumeric tokens minus generic filler — the informative part."""
        toks = re.findall(r"[a-z0-9]+", (text or "").lower())
        return {t for t in toks if t not in cls.GENERIC_TOKENS and len(t) > 2}

    @classmethod
    def _token_overlap(cls, a, b):
        ta, tb = cls._content_tokens(a), cls._content_tokens(b)
        if not ta or not tb:
            return 0.0
        return len(ta & tb) / max(len(ta), len(tb))

    def _load_synonyms(self):
        """Load curated vernacular synonyms (data/research/common_name_synonyms.json).

        Shape: {"<common name>": "<species key>", ...}
        Applied AFTER every other source so curated names always win, and a
        synonym never overwrites an existing exact common-name mapping.
        """
        path = self.data_dir.parent / "research" / "common_name_synonyms.json"
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return
        added = 0
        for common, key in (data.get("synonyms") or {}).items():
            key = key.lower()
            cn = common.lower().strip()
            if not cn or key not in self._species:
                continue
            if cn not in self._common_index:
                self._common_index[cn] = key
                if common not in self._species[key]["common_names"]:
                    self._species[key]["common_names"].append(common)
                self._common_names_list.append(common)
                added += 1
        self.synonym_count = added

    @staticmethod
    def _extract_scientific_name(text):
        """Extract the scientific name from a training/user message.

        Order matters. The training template is:
            Species: <Common> (<scientific name>)
        but `<Common>` itself sometimes contains parentheses, e.g.
            Species: Prickly Pear (Cane Cactus / Eve's Pin Cactus) (austrocylindropuntia spp)
        The old "first (Xxx yyy)" pattern therefore captured "Cane Cactus" and
        invented a bogus species ("dense infestations" arose the same way).
        Anchor on unambiguous shapes first and require a clean binomial.
        """
        binomial = r"([A-Z][a-z]+ [a-z][a-z\-]+)"
        for pat in [
            r"Species:\s*.*?\(([a-z][a-z\-]+ [a-z][a-z\-]+)\)\s*$",   # trailing lowercase sci
            rf"Species:\s*{binomial}\s*\(",                            # sci first
            rf"\({binomial}\)",                                        # sole binomial in parens
            r"of ([A-Z][a-z]+ [a-z][a-z\-]+) in",
            r"does ([A-Z][a-z]+ [a-z][a-z\-]+) \(",
            r"about ([A-Z][a-z]+ [a-z][a-z\-]+) as",
            rf"{binomial} indicate",
        ]:
            for line in (text or "").splitlines():
                m = re.search(pat, line.strip())
                if m:
                    name = m.group(1)
                    if re.fullmatch(r"[A-Za-z][a-z\-]+ [a-z][a-z\-]+", name):
                        return name
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
        #    Guard: a match resting only on a generic token ("khaki weed" vs
        #    "onion weed") is a false friend and is rejected.
        if len(results) < top_n:
            for v in variants:
                for cn_lower, key in self._common_index.items():
                    if (cn_lower in v or v in cn_lower) and key not in {r.get("key", "") for r in results}:
                        # reject generic-only overlaps
                        if not self._content_tokens(v) & self._content_tokens(cn_lower):
                            continue
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
        # on long sentences produces unreliable false positives). Scored by
        # token overlap so "sow thistle" cannot beat "sonchus" on edit distance
        # alone.
        if len(results) < top_n and len(query_lower) <= 40:
            fuzzy = get_close_matches(
                query_lower, [n.lower() for n in self._scientific_names],
                n=max(top_n - len(results), 3), cutoff=0.6
            )
            for match in fuzzy:
                if match not in {r.get("key", "") for r in results}:
                    info = self._species[match]
                    seq = SequenceMatcher(None, query_lower, match).ratio()
                    tok = self._token_overlap(query_lower, match)
                    score = round(0.5 * seq + 0.5 * tok, 2)
                    results.append({
                        "scientific_name": info["scientific_name"],
                        "common_names": info["common_names"],
                        "match_type": "fuzzy_scientific",
                        "score": score,
                        "key": match,
                    })

        # 6. Fuzzy common-name match — catches vernacular names the DB never
        #    learned ("sow thistle" → a species already called sow-thistle).
        #    Guarded by content-token overlap so generic filler cannot match.
        if len(results) < top_n and len(query_lower) <= 40:
            q_tokens = self._content_tokens(query_lower)
            if q_tokens:
                best = []
                for cn_lower, key in self._common_index.items():
                    if key in {r.get("key", "") for r in results}:
                        continue
                    cn_tokens = self._content_tokens(cn_lower)
                    if not cn_tokens or not (q_tokens & cn_tokens):
                        continue
                    seq = SequenceMatcher(None, query_lower, cn_lower).ratio()
                    tok = len(q_tokens & cn_tokens) / max(len(q_tokens), len(cn_tokens))
                    if seq >= 0.6 or tok >= 0.5:
                        best.append((0.5 * seq + 0.5 * tok, key, cn_lower))
                for score, key, cn_lower in sorted(best, reverse=True)[:top_n - len(results)]:
                    info = self._species[key]
                    results.append({
                        "scientific_name": info["scientific_name"],
                        "common_names": info["common_names"],
                        "match_type": "fuzzy_common",
                        "score": round(min(score, 0.85), 2),
                        "key": key,
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
            dict with keys: scientific_name, common_names, region, indicators,
            source, region_fallback (bool), requested_region, canonical_key (str),
            merged_from (list[str])
            OR None if the species is unknown or carries no usable indicators.

        Region policy: if the requested region has no indicator data, the first
        populated region is used and `region_fallback` is set True with
        `requested_region` preserved, so callers can disclose that the answer is
        not region-specific rather than passing foreign data off as local.

        Canonical policy: the text DB carries duplicate keys for the same plant
        (`barley grass` / `hordeum leporinum`, `curled dock` / `rumex crispus`, …),
        the same fragmentation the vision path fixed with canonical_map.json. Twelve
        of those pairs hold *different* indicator data, so a farmer asking about
        "curled dock" and one asking about *Rumex crispus* got different soil
        stories for the same weed. Both keys now resolve to one canonical answer
        with their indicators **merged** (union of labels, canonical wins
        collisions), because picking one side would discard real rows — the alias
        is richer for 2 of 20 pairs and the canonical for 6.
        """
        key = species_name.strip().lower()
        # Deterministic order: the canonical entry leads, then the remaining
        # siblings sorted. Without this, `keys` began with whatever the caller
        # typed, so a label defined differently on both sides
        # (cirsium spp "High nitrogen soils" vs cirsium vulgare "High fertility,
        # overgrazing, soil disturbance") resolved differently depending on which
        # name the farmer happened to use — still the bug, just harder to see.
        group = self._canonical_group(key)
        lead = group[0] if group and group[0] in self._species else key
        keys = [lead] + sorted(k for k in group if k != lead and k in self._species)

        infos = [(k, self._species[k]) for k in keys if k in self._species]
        if not infos:
            return None
        key, info = infos[0]
        merged_from = [k for k, _ in infos]

        # Identity follows the QUERIED key, not the canonical lead. Data is merged
        # (below), but a genus bucket must not be relabelled as a species: asking
        # "thistles" has to stay an honest genus-level answer, otherwise the
        # response claims a precision the farmer never supplied. Conversely a
        # specific query keeps its binomial.
        queried = species_name.strip().lower()
        identity = queried if queried in self._species else key
        id_info = self._species[identity]

        def region_order(inf):
            regions = inf["regions"]
            order = [r for r in [region, "Australia", "UK", "Europe"] if r]
            return regions, order

        # Pick the region from the primary entry, but let a sibling supply the
        # indicators when the primary has none for that region.
        def merged_indicators(r):
            out, sources = {}, []
            for k, inf in infos:
                reg = (inf["regions"].get(r) or {})
                inds = {ik: iv for ik, iv in (reg.get("indicators") or {}).items()
                        if iv and str(iv).strip()}
                if inds:
                    sources.append(k)
                    for ik, iv in inds.items():
                        out.setdefault(ik, iv)   # primary (canonical first) wins
            return out, sources

        regions, order = region_order(info)
        for r in order:
            if any(r in inf["regions"] for _, inf in infos):
                inds, sources = merged_indicators(r)
                if inds:
                    return self._result(key, id_info, r, region, inds,
                                        merged_from, sources)

        # any remaining region with actual data
        seen = []
        for _, inf in infos:
            for r in inf["regions"]:
                if r not in seen:
                    seen.append(r)
        for r in seen:
            inds, sources = merged_indicators(r)
            if inds:
                return self._result(key, id_info, r, region, inds, merged_from, sources)

        # species known, but no indicator rows anywhere — honest no-data path
        return None

    def _result(self, key, id_info, r, region, inds, merged_from, sources):
        result = {
            "scientific_name": id_info["scientific_name"],
            "common_names": self._merged_common_names(merged_from),
            "region": r,
            "requested_region": region,
            "region_fallback": bool(region and r != region),
            "indicators": inds,
            "source": (id_info["regions"].get(r) or {}).get("source", ""),
            "canonical_key": key,
            "merged_from": merged_from,
        }
        # nutrients from every sibling, so a merge does not lose claims
        claims = []
        for k in merged_from:
            claims += ((self._nutrients.get(k) or {}).get("claims") or [])
        if claims:
            result["nutrients"] = {"claims": claims}
        return result

    def _merged_common_names(self, keys):
        out, seen = [], set()
        for k in keys:
            for cn in (self._species.get(k, {}).get("common_names") or []):
                if cn.lower() not in seen:
                    seen.add(cn.lower())
                    out.append(cn)
        return out

    def _canonical_group(self, key):
        """All DB keys that denote the same plant as `key` (including itself).

        Uses data/vision/canonical_map.json, the same registry the vision path
        uses, so text and photo answers agree on identity.
        """
        if self._canonical is None:
            self._canonical = {}
            p = self.data_dir.parent.parent / "data" / "vision" / "canonical_map.json"
            if p.exists():
                try:
                    self._canonical = json.loads(p.read_text()).get("canonical", {})
                except (json.JSONDecodeError, OSError):
                    self._canonical = {}
        canon = self._canonical
        if key in canon:
            return [canon[key]] + [k for k, v in canon.items() if v == canon[key]]
        return [key] + [k for k, v in canon.items() if v == key]

    def indicator_coverage(self, region="Australia"):
        """Coverage stats: how many species carry usable indicators per region."""
        total = len(self._species)
        with_region = with_any = 0
        for info in self._species.values():
            regs = info.get("regions") or {}
            if (regs.get(region) or {}).get("indicators"):
                with_region += 1
            if any((r or {}).get("indicators") for r in regs.values()):
                with_any += 1
        return {"species": total, f"with_{region.lower()}": with_region,
                "with_any_region": with_any,
                "no_indicators": total - with_any}

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

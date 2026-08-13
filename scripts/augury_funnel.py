#!/usr/bin/env python3
"""
AUGURY Funnel — the single serving entry point for the text pipeline.

Architecture (Path A, guard rail 6):
    [user text] → formatter model extracts {"species": [...], "confidence": [...]} JSON
                → species_lookup.search() resolves each name (fuzzy, region-aware)
                → database-merged.json answers (deterministic — the model NEVER emits indicators)
                → response composed conversationally (template or formatter model)

The JSON contract is shared with the vision pipeline (MiniCPM-V 4.6 emits the same
schema in Phase 3-5), so photo → species and text → species both feed this funnel.

JSON, never XML tool-calls (guard rail 5 — V3's lesson).

Usage:
    from augury_funnel import AuguryFunnel
    funnel = AuguryFunnel(model_path="models/MiniCPM5-1B-Q4_K_M.gguf")  # model optional
    result = funnel.answer("What do docks and thistles indicate?", region="Australia")
    result = {"response": str, "species": [...], "matches": [...], "refused": bool}
"""

import json
import os
import re
import sys
from pathlib import Path

# Allow running from anywhere
sys.path.insert(0, str(Path(__file__).resolve().parent))

from species_lookup import SpeciesDB


EXTRACT_SYSTEM = (
    "You are AUGURY's species extractor. A farmer asks about weeds or plants in "
    "their fields. Extract EVERY plant species mentioned — common names and "
    "scientific names both count (e.g. 'docks' → Rumex, 'Yorkshire fog' → Holcus "
    "lanatus, 'dandelion' → Taraxacum). Respond with ONLY a JSON object of the "
    "form {\"species\": [\"name\", ...]}. If no plant is mentioned, respond "
    "{\"species\": []}. Do NOT explain, do NOT reason out loud — JSON only."
)

FORMAT_SYSTEM = (
    "You are AUGURY, a soil health assistant specializing in weeds and plants as "
    "soil indicators. You receive structured soil indicator data from a reliable "
    "database and present it in clear, practical language for farmers and land "
    "managers. Never invent or modify indicator data. Never give management, "
    "herbicide, or remediation advice — indicators only. If asked about something "
    "outside plant soil indicators, politely decline."
)


class AuguryFunnel:
    """Text → species JSON → deterministic DB → conversational answer."""

    # UK soil-association entries ("Dandelion clay" = dandelion indicates clay
    # soils) are NOT plant species — skip them when they collide with a plant
    # query unless the user literally asks for that association.
    CLAY_PSEUDO_SPECIES = {"dandelion clay", "plantains clay", "goosegrass clay", "chicory clay"}

    # Function words / farming filler — never valid species probes.
    STOPWORDS = {
        "the", "a", "an", "and", "or", "of", "in", "on", "at", "to", "my", "your",
        "our", "their", "its", "his", "her", "i", "you", "we", "they", "it", "he",
        "she", "this", "that", "these", "those", "there", "here", "is", "are", "was",
        "were", "am", "be", "been", "being", "do", "does", "did", "have", "has",
        "had", "will", "would", "can", "could", "should", "what", "whats", "which",
        "who", "when", "where", "why", "how", "with", "for", "from", "by", "as",
        "so", "just", "about", "seeing", "seen", "got", "growing", "spreading",
        "taking", "over", "everywhere", "paddock", "field", "soil", "pasture",
        "mean", "means", "say", "says", "saying", "telling", "tells", "indicate",
        "indicates", "indicating", "asking", "ask", "wonder", "wondering", "lot", "lots",
    }

    def __init__(self, model_path=None, db=None, n_ctx=2048, n_threads=12):
        self.db = db if db is not None else SpeciesDB()
        self.model = None
        self.model_path = model_path
        if model_path and os.path.exists(model_path):
            from llama_cpp import Llama
            print(f"[funnel] loading formatter model: {model_path}")
            self.model = Llama(model_path=model_path, n_ctx=n_ctx, n_threads=n_threads, verbose=False)
        else:
            print("[funnel] no formatter model — using deterministic template mode")

    # ── species extraction ────────────────────────────────────

    def extract_species(self, text, region=None, max_species=5):
        """
        Extract plant species from free text.

        Deterministic regex extraction (segments + fuzzy DB match). The model
        extractor paths are retained for future work but NOT used by default:
        the trained formatter is persona-locked (refuses the extractor role)
        and the base model's thinking mode swallows the JSON budget.

        Returns a list of dicts: {"name": str, "source": "regex", "score": float}.
        """
        text = (text or "").strip()
        if not text:
            return []
        return self._extract_regex(text, max_species)

    def _extract_with_model(self, text, region):
        region_hint = f"\nThe farmer is in {region}." if region else ""
        try:
            out = self.model.create_chat_completion(
                messages=[
                    {"role": "system", "content": EXTRACT_SYSTEM},
                    {"role": "user", "content": f"{region_hint}\nMessage: {text}"},
                ],
                temperature=0.0,
                max_tokens=768,  # MiniCPM5 thinks before the JSON — budget for it
            )
            raw = out["choices"][0]["message"]["content"]
        except Exception as e:  # noqa: BLE001
            print(f"[funnel] model call failed: {e}")
            return []

        parsed = self._parse_json(self._strip_think(raw))
        if not parsed or not isinstance(parsed.get("species"), list):
            return []

        names = [s.strip() for s in parsed["species"] if isinstance(s, str) and s.strip()]
        return names[:5]

    @staticmethod
    def _strip_think(raw):
        """Strip <think>...</think> reasoning blocks (MiniCPM5/Qwen-style)."""
        if not raw:
            return ""
        return re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

    @staticmethod
    def _parse_json(raw):
        """Best-effort JSON extraction from model output (tolerant of prose/think blocks)."""
        if not raw:
            return None
        # 1. Direct species-array extraction (robust to surrounding prose)
        m = re.search(r'"species"\s*:\s*(\[.*?\])', raw, re.DOTALL)
        if m:
            try:
                arr = json.loads(m.group(1))
                return {"species": arr}
            except json.JSONDecodeError:
                cleaned = re.sub(r",\s*\]", "]", m.group(1)).replace("'", '"')
                try:
                    return {"species": json.loads(cleaned)}
                except json.JSONDecodeError:
                    pass
        # 2. Full-object extraction
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            cleaned = re.sub(r",\s*}", "}", m.group(0)).replace("'", '"')
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                return None

    def _extract_regex(self, text, max_species):
        """Deterministic fallback: segment on conjunctions, then fuzzy search each segment."""
        candidates = []
        seen = set()

        # Whole-message match first (covers "What does Yorkshire fog indicate?")
        whole = self._best_plant_match(text)
        if whole:
            candidates.append(whole)
            seen.add(whole["key"])

        segments = [s.strip() for s in re.split(r"\band\b|[,;]", text) if s.strip()]
        for seg in segments:
            # Strip boilerplate prefix (only at the start) ...
            core = re.sub(
                r"^(what does|what do|what is|what are|what's|tell me about|i have|i'm seeing|i am seeing|seeing|about)\s*",
                "", seg, flags=re.I,
            )
            # ... quantity phrases ("a lot of docks" -> "docks") ...
            core = re.sub(
                r"^(a lot of|lots of|plenty of|heaps of|loads of|a bunch of|masses of|tons of|some|many|seeing lots of|got lots of|saw lots of)\s+",
                "", core, flags=re.I,
            )
            # ... location phrases ("thistles in my paddock" -> "thistles") ...
            core = re.sub(
                r"\s+(in|on|around|about)\s+(my|the|our|their)?\s*(paddock|field|pasture|yard|garden|place|land|property|block|country|ground).*$",
                "", core, flags=re.I,
            )
            # ... and trailing verb phrases ("thistles indicate?" -> "thistles")
            core = re.sub(
                r"\s+(indicates?|indicating|telling|tells?|say[s]?|asking|ask|wonder(ing)?|mean[s]?|means|point[s]? to|pointing to).*$",
                "", core, flags=re.I,
            ).strip()
            # ... and anything after a dash ("thistles — what's going on?")
            core = re.sub(r"\s*[—–]\s*.*$", "", core).strip()
            if len(core) < 2 or core.lower().strip() in self.STOPWORDS:
                continue
            m = self._best_plant_match(core)
            if not m:
                # Progressive prefix fallback: "Serrated tussock is taking over…"
                # → try "Serrated tussock", then "Serrated"
                for n in (2, 1):
                    parts = core.split()
                    if len(parts) <= n:
                        continue
                    probe = re.sub(r"[^a-z0-9 ]", "", " ".join(parts[:n]).lower()).strip()
                    if len(probe) < 3 or probe in self.STOPWORDS:
                        continue
                    m = self._best_plant_match(probe)
                    if m:
                        break
            if m and m["key"] not in seen:
                candidates.append(m)
                seen.add(m["key"])
            if len(candidates) >= max_species:
                break

        return [
            {"name": c["scientific_name"], "source": "regex", "score": c["score"], "key": c["key"]}
            for c in candidates
            if c["score"] >= 0.5
        ]

    def _best_match(self, query):
        if not query.strip():
            return None
        matches = self.db.search(query, top_n=1)
        return matches[0] if matches else None

    # ── resolution ────────────────────────────────────────────

    def resolve(self, extracted, region=None):
        """
        Resolve extracted species names against the deterministic DB.

        Returns list of result dicts (get_indicators output enriched with match info),
        or [] when nothing resolves.
        """
        results = []
        seen = set()
        for item in extracted:
            name = item["name"]
            match = self._best_plant_match(name)
            if not match or match["score"] < 0.5:
                continue
            key = match["key"]
            if key in seen:
                continue
            seen.add(key)
            info = self.db.get_indicators(key, region=region)
            if info is None:
                continue
            info["match"] = {
                "query": name,
                "match_type": match["match_type"],
                "score": match["score"],
            }
            results.append(info)
        return results

    def _best_plant_match(self, query):
        """Top DB match, preferring real species over clay-association pseudo-species."""
        if not query.strip():
            return None
        query_lower = query.strip().lower()
        matches = self.db.search(query, top_n=5)
        if not matches:
            return None
        # If the query itself is a clay association, honor it.
        if query_lower in self.CLAY_PSEUDO_SPECIES:
            return matches[0]
        for m in matches:
            if m["key"] not in self.CLAY_PSEUDO_SPECIES:
                return m
        return None

    # ── response composition ──────────────────────────────────

    def compose(self, results, question, region=None):
        """Compose a response from resolved DB data (template or model)."""
        if not results:
            return (
                "I couldn't find a plant species in your message that I have "
                "indicator data for. Try asking about a specific weed or plant — "
                "e.g. \"What does Yorkshire fog indicate?\" or \"Tell me about "
                "dandelions as a soil indicator.\""
            )
        if self.model is not None:
            return self._compose_with_model(results, question, region)
        return self._compose_template(results)

    @staticmethod
    def _compose_template(results):
        """Deterministic, 100%-accurate template response for one or more species."""
        blocks = []
        for r in results:
            common = r["common_names"][0] if r["common_names"] else None
            sci = r["scientific_name"]
            if common and sci.lower() in common.lower():
                display = common
            elif common:
                display = f"{common} ({sci})"
            else:
                display = sci
            ind = r["indicators"]
            region = r.get("region", "Europe")
            source = r.get("source", "")

            lines = [f"**{display}**"]
            shown = set()
            for key, val in ind.items():
                if key in shown or not val or val.strip().lower() == "not specified":
                    continue
                shown.add(key)
                lines.append(f"\n📋 **{key}:** {val}")
            if "nutrients" in r:
                seen_n = set()
                for c in r["nutrients"].get("claims", []):
                    n = c.get("nutrient")
                    if n and n not in seen_n:
                        seen_n.add(n)
                        lines.append(f"\n🧪 **{n.capitalize()}:** {c.get('relationship', '')}")
            if source:
                lines.append(f"\n---\n*Source: {source} ({region})*")
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)

    def _compose_with_model(self, results, question, region):
        """Conversational composition — model only formats injected DB facts."""
        payload = []
        for r in results:
            common = r["common_names"][0] if r["common_names"] else None
            sci = r["scientific_name"]
            ind_lines = [
                f"- {k}: {v}" for k, v in r["indicators"].items()
                if v and v.strip().lower() not in ("not specified", "none")
            ]
            payload.append(
                "Species: " + (f"{common} ({sci})" if common else sci)
                + f"\nRegion: {r.get('region', region)}\nIndicators:\n" + "\n".join(ind_lines)
                + f"\nSource: {r.get('source', '')}"
            )
        user = (
            "Facts from the AUGURY database (do not add or change any indicator):\n\n"
            + "\n\n".join(payload)
            + f"\n\nFarmer's question: {question}"
        )
        try:
            out = self.model.create_chat_completion(
                messages=[
                    {"role": "system", "content": FORMAT_SYSTEM},
                    {"role": "user", "content": user},
                ],
                temperature=0.3,
                max_tokens=500,
            )
            return self._strip_think(out["choices"][0]["message"]["content"]).strip()
        except Exception as e:  # noqa: BLE001
            print(f"[funnel] formatter model failed: {e} — using template")
            return self._compose_template(results)

    # ── top-level ─────────────────────────────────────────────

    def answer(self, message, region=None):
        """
        Full text pipeline. Returns dict:
            {response, species: [str], matches: [...], refused: bool}
        """
        message = (message or "").strip()
        if not message:
            return {
                "response": "Please ask about a weed or plant — e.g. \"What does Yorkshire fog indicate?\"",
                "species": [], "matches": [], "refused": True,
            }

        extracted = self.extract_species(message, region=region)
        results = self.resolve(extracted, region=region)

        if not results:
            return {
                "response": self.compose([], message, region),
                "species": [], "matches": [], "refused": True,
            }

        response = self.compose(results, message, region)
        return {
            "response": response,
            "species": [r["scientific_name"] for r in results],
            "matches": [r.get("match") for r in results],
            "refused": False,
        }


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="AUGURY text funnel (CLI test)")
    ap.add_argument("--model", default="", help="Path to formatter GGUF (optional)")
    ap.add_argument("--region", default=None)
    ap.add_argument("queries", nargs="+")
    args = ap.parse_args()

    funnel = AuguryFunnel(model_path=args.model or None)
    for q in args.queries:
        print("=" * 70)
        print(f"Q ({args.region}): {q}")
        r = funnel.answer(q, region=args.region)
        print(f"species: {r['species']}")
        print(f"refused: {r['refused']}")
        print(f"A: {r['response']}")

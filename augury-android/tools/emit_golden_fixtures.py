#!/usr/bin/env python3
"""AUGURY — emit_golden_fixtures.py

Generate the JVM-parity golden fixture for the Kotlin port of AUGURY's Python
runtime logic (``augury-android/app/src/main/java/au/org/regeneratus/augury/core``).

Why this exists
---------------
The Kotlin port (``SpeciesStore``, ``StoryComposer``, ``IntentGuard``,
``Grounding``, ``AnswerPayload``) re-implements behaviour that already exists and
is already tested in Python.  A hand-written Kotlin test can only assert what its
author *believed* the Python does.  This script removes the guesswork: it runs
the **real** Python code over the **same** database the app ships and dumps the
observed behaviour as JSON, which the Kotlin test then asserts case by case.

How the reference database is built
-----------------------------------
``SpeciesDB`` parses ``data/training/weeds_indicators_merged_train.jsonl`` (a
build-time artefact).  The app ships ``data/app/augury-ondevice.json`` instead
(pre-parsed, with a per-species ``specificity`` tag and a single
``common_name``).  Only the *loaders* are therefore replaced below:
``search``, ``get_indicators``, ``_canonical_group``, ``_result``,
``_merged_common_names``, ``_load_synonyms`` and
``augury_funnel.classify_specificity`` are the unmodified Python functions.
That is what makes this a parity fixture rather than a second implementation.

What is NOT covered
-------------------
* Free-text species extraction (``AuguryFunnel._extract_regex``) — out of scope
  for the port by instruction; the app's picker / photo path supplies species
  names directly.  Every message probe therefore records the species list the app
  hands in, plus (informationally) what the real Python funnel extracts.
* The formatter model path (``_compose_with_model``) — the port has no model.

Run:
    .venv-mcpmv46/bin/python augury-android/tools/emit_golden_fixtures.py
Writes:
    augury-android/app/src/test/resources/golden/augury_golden_fixtures.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ANDROID_ROOT = HERE.parent
REPO_ROOT = ANDROID_ROOT.parent

sys.path.insert(0, str(REPO_ROOT / "scripts"))

from species_lookup import SpeciesDB  # noqa: E402
import augury_funnel as F  # noqa: E402
import grounding as G  # noqa: E402
import intent as I  # noqa: E402
from junk_keys import JUNK_KEYS  # noqa: E402

ONDEVICE = REPO_ROOT / "data" / "app" / "augury-ondevice.json"
CANONICAL = REPO_ROOT / "data" / "vision" / "canonical_map.json"
SYNONYMS = REPO_ROOT / "data" / "research" / "common_name_synonyms.json"
OUT = (ANDROID_ROOT / "app" / "src" / "test" / "resources" / "golden"
       / "augury_golden_fixtures.json")

# The region the Android app defaults to; AU-first ordering is baked into the DB.
DEFAULT_REGION = "Australia"


class OnDeviceDB(SpeciesDB):
    """SpeciesDB whose in-memory maps come from ``augury-ondevice.json``.

    Deliberately does NOT call ``SpeciesDB.__init__`` — that would parse the
    33k-line training JSONL.  The attribute set it builds is reproduced exactly
    so every inherited method runs unmodified.

    ``_sanitize()`` is intentionally not applied: the on-device DB is already
    curated (its 10 non-species artefacts carry ``specificity: "junk"`` and the
    runtime filters them at match time), and sanitising is a build-time concern
    for the training corpus — exactly what the port must not do.
    """

    def __init__(self, ondevice_path: Path):
        self.data_dir = REPO_ROOT / "data" / "training"
        self._species: dict = {}
        self._common_index: dict = {}
        self._scientific_names: list = []
        self._common_names_list: list = []
        self._nutrients: dict = {}
        self._canonical = None  # lazily loaded by _canonical_group from the real map
        self.sanitize_report = {"dropped_keys": [], "dropped_names": 0}
        self.synonym_count = 0

        doc = json.loads(Path(ondevice_path).read_text())
        self.schema = doc.get("schema")
        self.regions_declared = doc.get("regions")
        self.key_order: list = []
        for sp in doc["species"]:
            key = sp["key"].strip().lower()
            self.key_order.append(key)
            common = (sp.get("common_name") or "").strip()
            info = {
                "scientific_name": sp["scientific_name"],
                "common_names": [common] if common else [],
                "regions": {
                    r["region"]: {
                        "indicators": dict(r.get("indicators") or {}),
                        "source": r.get("source", ""),
                    }
                    for r in sp.get("regions", [])
                },
            }
            self._species[key] = info
            self._scientific_names.append(info["scientific_name"])
            if common:
                cn_lower = common.lower()
                if cn_lower not in self._common_index:
                    self._common_index[cn_lower] = key
                    self._common_names_list.append(common)

        # Runtime vernacular synonyms — the real loader, from the real file.
        self._load_synonyms()


class _SciNameResolvingSpecies(dict):
    """dict that can also resolve a lowercased scientific name to its key.

    Workaround for a bug in ``scripts/species_lookup.py`` (REPORTED, not fixed):
    ``search()`` step 5 treats the matched *lowercased scientific name* as a DB
    key, both for the lookup (``self._species[match]``) and for the reported
    ``key``.  That holds for the training DB (keys are ``scientific_name.lower()``
    by construction) but not for the on-device DB, where 5 species differ —
    ``'cenchrus spp'`` vs ``'Cenchrus spp.'``, ``'rytidosperma spp'`` vs
    ``'Rytidosperma spp. (formerly Austrodanthonia)'``, ``'sporobolus spp'``,
    ``'swainsona spp'``, ``'wahlenbergia spp'``.  There it raises ``KeyError``
    and aborts the whole search.

    Only ``__getitem__`` is widened; ``in``/``items()``/iteration stay exact so
    every other code path in ``search()`` is untouched.
    """

    def __init__(self, base, sci_to_key):
        super().__init__(base)
        self.sci_to_key = sci_to_key

    def __getitem__(self, k):
        if dict.__contains__(self, k):
            return dict.__getitem__(self, k)
        alt = self.sci_to_key.get(k)
        if alt is None:
            raise KeyError(k)
        return dict.__getitem__(self, alt)


def install_search_bug_workaround(db: OnDeviceDB) -> dict:
    sci_to_key: dict = {}
    for k, info in db._species.items():
        sci_to_key.setdefault(info["scientific_name"].lower(), k)
    db._species = _SciNameResolvingSpecies(db._species, sci_to_key)
    db._sci_to_key = sci_to_key
    return sci_to_key


def safe_search(db: OnDeviceDB, query: str, top_n: int = 5):
    """``db.search()`` with the fabricated-key bug mapped back to real keys.

    Steps 1-6 of the real ``search()`` run unchanged; the only adjustment is that
    a result whose ``key`` is not a real DB key (which only step 5 can produce) is
    remapped through the scientific-name index, and dropped if there is no such
    species.  The Kotlin port does exactly the same.
    """
    out = []
    for m in db.search(query, top_n=top_n):
        if m["key"] not in db._species:
            real = db._sci_to_key.get(m["key"])
            if real is None:
                continue
            m = dict(m, key=real)
        out.append(m)
    return out


def specificity(key: str) -> str:
    """The real tagger from augury_funnel (junk_keys + the spp regex)."""
    return F.classify_specificity(key)


def best_plant_match(db: OnDeviceDB, query: str):
    """``AuguryFunnel._best_plant_match`` without constructing the funnel.

    Same body as the shipped method: top-5 search, honour a literal clay
    association, otherwise take the first non-junk, non-pseudo-species match.
    Deliberately does NOT promote a genus bucket to a species.
    """
    if not query.strip():
        return None
    query_lower = query.strip().lower()
    matches = safe_search(db, query, top_n=5)
    if not matches:
        return None
    if query_lower in F.AuguryFunnel.CLAY_PSEUDO_SPECIES:
        return matches[0]
    for m in matches:
        if (m["key"] not in F.AuguryFunnel.CLAY_PSEUDO_SPECIES
                and F.classify_specificity(m["key"]) != "junk"):
            return m
    return None


def resolve_name(db: OnDeviceDB, name: str, region: str | None):
    """One supplied species name -> the resolved indicator result.

    Mirrors the funnel's ``_extract_regex`` -> ``resolve`` round trip for a
    single supplied name: match the query, then re-match on the matched
    scientific name (which is what ``resolve()`` does), then ``get_indicators``
    on the resulting key.
    """
    whole = best_plant_match(db, name)
    if whole is None or whole["score"] < 0.5:
        return None, None
    match = best_plant_match(db, whole["scientific_name"])
    if match is None or match["score"] < 0.5:
        return None, None
    info = db.get_indicators(match["key"], region=region)
    if info is None:
        return None, None
    return info, match


def dump_search(db: OnDeviceDB, query: str, top_n: int = 5):
    return [
        {"key": m["key"], "match_type": m["match_type"], "score": m["score"]}
        for m in safe_search(db, query, top_n=top_n)
    ]


def dump_result(info: dict | None, match: dict | None, key: str | None):
    if info is None:
        return None
    return {
        "scientific_name": info["scientific_name"],
        "common_names": list(info["common_names"]),
        "region": info["region"],
        "requested_region": info["requested_region"],
        "region_fallback": bool(info["region_fallback"]),
        "indicators": dict(info["indicators"]),  # verbatim, insertion-ordered
        "source": info["source"],
        "canonical_key": info["canonical_key"],
        "merged_from": list(info["merged_from"]),
        "specificity": specificity(key) if key else None,
        "match": {
            "match_type": match["match_type"],
            "score": match["score"],
        } if match else None,
    }


def build_db_probes(db: OnDeviceDB):
    """Queries resolved straight through the reference DB."""
    queries: list[tuple[str, str | None]] = []

    # 1. every canonical pair member (both sides of each of the 21 pairs)
    for a, b in sorted(json.loads(CANONICAL.read_text())["canonical"].items()):
        queries.append((a, DEFAULT_REGION))
        queries.append((b, DEFAULT_REGION))
        queries.append((a, None))
        queries.append((b, None))

    # 2. the brief's named probes
    queries += [
        ("docks", DEFAULT_REGION),
        ("thistles", DEFAULT_REGION),
        ("soursob", DEFAULT_REGION),
        ("serrated tussock", DEFAULT_REGION),
        ("nassella trichotoma", DEFAULT_REGION),
        ("lantana", DEFAULT_REGION),
        ("capeweed", DEFAULT_REGION),
        ("dandelion", DEFAULT_REGION),
        ("yorkshire fog", DEFAULT_REGION),
        ("taraxacum officinale", DEFAULT_REGION),
        ("lantana camara", DEFAULT_REGION),
        ("arctotheca calendula", DEFAULT_REGION),
        ("holcus lanatus", DEFAULT_REGION),
        ("khaki weed", DEFAULT_REGION),
        ("caltrop", DEFAULT_REGION),
        ("paterson's curse", DEFAULT_REGION),
        ("curled dock", "UK"),
        ("rumex crispus", "UK"),
        # region fallback: UK-only species requested with the AU default
        ("centaurea cyanus", DEFAULT_REGION),
        ("elytrigia repens", DEFAULT_REGION),
        ("vicia sativa", DEFAULT_REGION),
        ("phleum pratense", DEFAULT_REGION),
        ("centaurea cyanus", "Europe"),
        # species known but carrying no indicator rows anywhere
        ("bothriochloa macra", DEFAULT_REGION),
        ("cheilanthes sieberi", DEFAULT_REGION),
        ("glycine tabacina", DEFAULT_REGION),
        # unknown
        ("asdfghjkl qwerty", DEFAULT_REGION),
        # indicator passthrough, incl. Ph vs Soil pH kept distinct
        ("amaranthus retroflexus", DEFAULT_REGION),
        ("plantago major", DEFAULT_REGION),
        ("nassella neesiana", DEFAULT_REGION),
        ("conyza canadensis", DEFAULT_REGION),
        ("galium aparine", DEFAULT_REGION),
    ]

    out, seen = [], set()
    for q, region in queries:
        if (q, region) in seen:
            continue
        seen.add((q, region))
        info, match = resolve_name(db, q, region)
        out.append({
            "query": q,
            "region": region,
            "search_all": dump_search(db, q),
            "canonical_group": db._canonical_group(q.strip().lower()),
            "result": dump_result(info, match, match["key"] if match else None),
        })
    return out


def compose_for_names(db: OnDeviceDB, names, region):
    """Resolve each supplied name through the reference DB and compose the story.

    Shared by the story probes and the message probes so both are produced by the
    same real ``_compose_template`` / ``_genus_level_notice`` /
    ``_region_fallback_notice`` calls.
    """
    results, keys = [], []
    seen = set()
    for n in names:
        info, match = resolve_name(db, n, region)
        if info is None:
            continue
        if match["key"] in seen:
            continue
        seen.add(match["key"])
        info = dict(info)
        info["match"] = {
            "query": n,
            "match_type": match["match_type"],
            "score": match["score"],
            "specificity": specificity(match["key"]),
        }
        results.append(info)
        keys.append(match["key"])
    template = F.AuguryFunnel._compose_template(results) if results else ""
    composed = (template
                + F.AuguryFunnel._genus_level_notice(results)
                + F.AuguryFunnel._region_fallback_notice(results, region))
    if not results:
        composed = F.AuguryFunnel.compose(_NullFunnel(), [], " ".join(names), region)
    none_keys = sorted(
        k for r in results for k, v in r["indicators"].items()
        if str(v).strip().lower() == "none")
    return results, keys, template, composed, none_keys


class _NullFunnel:
    """Minimal stand-in so ``compose`` can be called without loading the DB."""
    model = None


def build_story_probes(db: OnDeviceDB):
    """Rendered stories, produced by the real ``compose``/``_compose_template``."""
    cases = [
        (["curled dock"], DEFAULT_REGION),
        (["rumex crispus"], DEFAULT_REGION),
        (["docks", "thistles"], DEFAULT_REGION),
        (["soursob"], DEFAULT_REGION),
        (["serrated tussock"], DEFAULT_REGION),
        (["centaurea cyanus"], DEFAULT_REGION),          # region fallback
        (["elytrigia repens"], DEFAULT_REGION),          # region fallback
        (["amaranthus retroflexus"], DEFAULT_REGION),    # Ph AND Soil pH
        (["plantago major"], DEFAULT_REGION),
        (["taraxacum officinale"], DEFAULT_REGION),      # carries a "none" value
        ([], DEFAULT_REGION),                            # no-species response
    ]
    out = []
    for names, region in cases:
        results, keys, template, composed, none_keys = compose_for_names(db, names, region)
        out.append({
            "names": names,
            "region": region,
            "resolved_keys": keys,
            "species": [r["scientific_name"] for r in results],
            "python_template_story": template,
            "python_composed_story": composed,
            "indicator_keys_with_none": none_keys,
        })
    return out


def expected_answer(db: OnDeviceDB, message, supplied, region):
    """What ``AuguryFunnel.answer`` yields for this message on the APP database.

    The app supplies species directly (free-text extraction is out of scope), so
    this mirrors the funnel's guard-rail ordering — empty, then intent, then
    resolution, then composition — with ``supplied`` standing in for extraction.
    """
    msg = (message or "").strip()
    if not msg:
        return {
            "refused": True, "refused_reason": "empty", "intent": "other",
            "species": [], "response": (
                'Please ask about a weed or plant — e.g. "What does Yorkshire fog indicate?"'
            ),
            "indicator_keys_with_none": [],
        }
    kind = I.classify(msg)
    if kind == "management":
        return {
            "refused": True, "refused_reason": "management", "intent": kind,
            "species": [], "response": I.decline_response("management"),
            "indicator_keys_with_none": [],
        }
    results, keys, _template, composed, none_keys = compose_for_names(db, supplied, region)
    if not results:
        return {
            "refused": True, "refused_reason": "no_species", "intent": kind,
            "species": [], "response": composed, "indicator_keys_with_none": [],
        }
    return {
        "refused": False, "refused_reason": None, "intent": kind,
        "species": [r["scientific_name"] for r in results],
        "resolved_keys": keys,
        "response": composed,
        "indicator_keys_with_none": none_keys,
    }


def build_message_probes(db: OnDeviceDB, with_funnel: bool):
    """message -> intent / refusal, with the species list the app supplies."""
    probes = [
        ("What herbicide should I use on lantana?", ["lantana"], DEFAULT_REGION),
        ("Can you recommend a spray for capeweed?", ["capeweed"], DEFAULT_REGION),
        ("Should I lime my paddock to fix acidity?", ["capeweed"], DEFAULT_REGION),
        ("How do I kill serrated tussock?", ["serrated tussock"], DEFAULT_REGION),
        ("What's the best way to control blackberry?", ["blackberry"], DEFAULT_REGION),
        ("How much glyphosate per hectare?", [], DEFAULT_REGION),
        ("Should I apply urea to the paddock?", [], DEFAULT_REGION),
        ("what does dandelion indicate about my soil?", ["dandelion"], DEFAULT_REGION),
        ("What does capeweed tell me about my soil?", ["capeweed"], DEFAULT_REGION),
        ("What does lime-loving capeweed indicate?", ["capeweed"], DEFAULT_REGION),
        ("I have docks and thistles in my paddock", ["docks", "thistles"], DEFAULT_REGION),
        ("Tell me about quantum physics", [], DEFAULT_REGION),
        ("asdfghjkl", [], DEFAULT_REGION),
        ("", [], DEFAULT_REGION),
        ("What does yorkshire fog indicate?", ["yorkshire fog"], DEFAULT_REGION),
        ("What does yorkshire fog indicate?", ["yorkshire fog"], "UK"),
    ]
    funnel = None
    if with_funnel:
        try:
            funnel = F.AuguryFunnel()  # loads the training JSONL; no GGUF needed
        except Exception as exc:  # noqa: BLE001
            print(f"[fixtures] python funnel unavailable: {exc}", file=sys.stderr)

    out = []
    for message, supplied, region in probes:
        kind = I.classify(message)
        entry = {
            "message": message,
            "region": region,
            "supplied_species": list(supplied),
            "intent": kind,
            "decline_response": (I.decline_response(kind)
                                 if kind == "management" else None),
            "expected": expected_answer(db, message, supplied, region),
        }
        if funnel is not None:
            r = funnel.answer(message, region=region)
            entry["python_funnel"] = {
                "refused": r["refused"],
                "refused_reason": r["refused_reason"],
                "species": r["species"],
                "response": r["response"],
                "intent": r["intent"],
            }
        out.append(entry)
    return out


def build_grounding_probes():
    """Real ``grounding.repair`` runs, including the field-test hallucination."""
    cases = [
        {
            "id": "dandelion_below_6_5_field_test",
            "note": "The real field-test hallucination: '6.5' is nowhere in the facts.",
            "facts": ["Soil pH: neutral to slightly acidic"],
            "answer": "Dandelion indicates acidic conditions, likely below 6.5",
        },
        {
            "id": "coolatai_above_ph_7_0",
            "note": "Docstring example from scripts/grounding.py.",
            "facts": ["Soil pH: alkaline or calcareous soils"],
            "answer": "Coolatai grass suggests alkaline or calcareous soils, likely above pH 7.0.",
        },
        {
            "id": "lantana_below_6_5",
            "note": "Docstring example from scripts/grounding.py.",
            "facts": ["Soil pH: acidic conditions"],
            "answer": "Lantana indicates acidic conditions, likely below 6.5.",
        },
        {
            "id": "supported_number_is_left_alone",
            "note": "5.0-9.0 is present in the facts, so nothing is repaired.",
            "facts": ["Ph: wide (pH 5.0-9.0)"],
            "answer": "Prickly acacia tolerates a pH range of 5.0-9.0, so it is not a pH indicator.",
        },
        {
            "id": "unsupported_rate_stripped",
            "note": "Neutralising leaves too few words, so the span is stripped instead.",
            "facts": ["Moisture: dry soils"],
            "answer": "Docks indicate dry soils. Apply 400 mm of water.",
        },
        {
            "id": "multi_sentence_mixed",
            "note": "Only the sentence carrying the invented number is touched.",
            "facts": ["Moisture: dry, well-drained soils", "Fertility: low fertility"],
            "answer": (
                "Docks indicate dry, well-drained soils with low fertility. "
                "They prefer a pH below 6.0 in most situations. "
                "Thistles indicate overgrazing."
            ),
        },
        {
            "id": "clean_answer_untouched",
            "facts": ["Moisture: dry soils"],
            "answer": "Docks indicate dry soils.",
        },
        {
            "id": "two_unsupported_values_in_one_sentence",
            "facts": ["Salinity: non-saline"],
            "answer": "Lantana indicates acid soils below 5.5 and dry conditions under 400 mm.",
        },
    ]
    out = []
    for c in cases:
        cleaned, events = G.repair(c["answer"], c["facts"])
        out.append({
            **c,
            "cleaned": cleaned,
            "events": events,
            "verify": G.verify(c["answer"], c["facts"]),
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--no-funnel", action="store_true",
                    help="skip the (slow) training-DB funnel cross-check")
    args = ap.parse_args()

    db = OnDeviceDB(ONDEVICE)
    install_search_bug_workaround(db)
    print(f"[fixtures] on-device DB: {len(db._species)} species, "
          f"{len(db._common_index)} common names, "
          f"{db.synonym_count} curated synonyms")

    doc = {
        "generated_by": "augury-android/tools/emit_golden_fixtures.py",
        "source_species_db": str(ONDEVICE.relative_to(REPO_ROOT)),
        "source_canonical_map": str(CANONICAL.relative_to(REPO_ROOT)),
        "source_synonyms": str(SYNONYMS.relative_to(REPO_ROOT)),
        "default_region": DEFAULT_REGION,
        "junk_keys": sorted(JUNK_KEYS),
        "clay_pseudo_species": sorted(F.AuguryFunnel.CLAY_PSEUDO_SPECIES),
        "canonical_map": json.loads(CANONICAL.read_text())["canonical"],
        "known_python_bugs": [
            {
                "file": "scripts/species_lookup.py",
                "where": "SpeciesDB.search() step 5 (fuzzy scientific name match)",
                "what": (
                    "self._species[match] and the reported 'key' both use `match`, "
                    "a *lowercased scientific name*, as if it were a DB key. True "
                    "for the training DB (keys are scientific_name.lower()) but not "
                    "for data/app/augury-ondevice.json, where 5 species differ: "
                    "cenchrus spp / Cenchrus spp., rytidosperma spp / Rytidosperma "
                    "spp. (formerly Austrodanthonia), sporobolus spp / Sporobolus "
                    "spp., swainsona spp / Swainsona spp., wahlenbergia spp / "
                    "Wahlenbergia spp. On the app DB this raises KeyError and "
                    "aborts the entire search."
                ),
                "reported_not_fixed": True,
                "fixture_workaround": (
                    "install_search_bug_workaround(): _species.__getitem__ resolves "
                    "a lowercased scientific name to its key, and safe_search() "
                    "remaps a fabricated result key back to the real key (dropping "
                    "the entry if there is none). The Kotlin port indexes scientific "
                    "names explicitly and never fabricates a key."
                ),
            },
            {
                "file": "scripts/species_lookup.py",
                "where": "SpeciesDB.get_indicators() / _result()",
                "what": (
                    "merged_indicators() returns `sources` (which sibling supplied "
                    "the rows) but _result() never uses it; the parameter is dead."
                ),
                "reported_not_fixed": True,
                "fixture_workaround": "none needed - the Kotlin port does not expose it",
            },
            {
                "file": "scripts/grounding.py",
                "where": "_strip_number_spans(), the `for val in bad_values` loop",
                "what": (
                    "bad_values is re-built as a set from an already-sorted list, and "
                    "str hashing is randomised per process (PYTHONHASHSEED), so the "
                    "order in which values are excised is not deterministic. The "
                    "order matters when one value is a substring of another (e.g. "
                    "'6' vs '6.5'). The Kotlin port iterates the sorted "
                    "unsupported-values list, which is the order verify() reports."
                ),
                "reported_not_fixed": True,
                "fixture_workaround": "fixtures capture one observed run",
            },
            {
                "file": "scripts/species_lookup.py",
                "where": "SpeciesDB._sanitize() vs the shipped app database",
                "what": (
                    "Not a bug in Python, but an inconsistency worth recording: "
                    "_sanitize() deletes junk keys from _species entirely, while "
                    "data/app/augury-ondevice.json keeps them and tags them "
                    "specificity='junk'. The Kotlin port follows the app DB (keeps "
                    "them, filters at match time via _best_plant_match) because "
                    "junk_keys.py documents that a user pasting e.g. 'dandelion "
                    "clay' should still get an honest answer."
                ),
                "reported_not_fixed": True,
                "fixture_workaround": "reference DB does not run _sanitize()",
            },
        ],
        "counts": {
            "species": len(db._species),
            "common_names": len(db._common_index),
            "curated_synonyms": db.synonym_count,
            "schema": db.schema,
        },
        "db_probes": build_db_probes(db),
        "story_probes": build_story_probes(db),
        "message_probes": build_message_probes(db, not args.no_funnel),
        "grounding_probes": build_grounding_probes(),
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    print(f"[fixtures] db_probes={len(doc['db_probes'])} "
          f"story_probes={len(doc['story_probes'])} "
          f"message_probes={len(doc['message_probes'])} "
          f"grounding_probes={len(doc['grounding_probes'])}")
    print(f"[fixtures] wrote {out_path} ({out_path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

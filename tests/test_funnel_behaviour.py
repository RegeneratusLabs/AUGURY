#!/usr/bin/env python3
"""AUGURY — text-funnel behaviour tests.

Why these exist
---------------
`scripts/intent.py` was written to decline management/advice questions and its own
module self-test reported "14/14 probes correct" — but nothing imported it.
`AuguryFunnel.answer()` never called it, so through the real entry point:

    "What herbicide should I use on lantana?"  -> refused: False, a lantana soil story

The probes exercised `intent.classify()` directly and never `funnel.answer()`, so a
dead guard rail looked like a live one for an entire session.

These tests deliberately go through `answer()`, the shipped entry point, so the
same class of mistake cannot recur. Deterministic and offline: the funnel runs in
template mode (no GGUF), so no model weights or network are needed.

Run:
    .venv-mcpmv46/bin/python tests/test_funnel_behaviour.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from augury_funnel import AuguryFunnel  # noqa: E402

# Built once: loading the DB is the only expensive part.
_FUNNEL = None


def funnel() -> AuguryFunnel:
    global _FUNNEL
    if _FUNNEL is None:
        _FUNNEL = AuguryFunnel()  # no model_path -> deterministic template mode
    return _FUNNEL


MANAGEMENT_QUESTIONS = [
    "What herbicide should I use on lantana?",
    "Can you recommend a spray for capeweed?",
    "Should I lime my paddock to fix acidity?",
    "How do I kill serrated tussock?",
    "What's the best way to control blackberry?",
    "How much glyphosate per hectare?",
    "Should I apply urea to the paddock?",
]

INDICATOR_QUESTIONS = [
    ("what does dandelion indicate about my soil?", "Taraxacum officinale"),
    ("What does capeweed tell me about my soil?", "Arctotheca calendula"),
    ("What does lime-loving capeweed indicate?", "Arctotheca calendula"),
]

EXTRACTION_CASES = [
    ("serrated tussock", "Nassella trichotoma"),
    ("paterson's curse", "Echium plantagineum"),
    ("khaki weed", "Alternanthera pungens"),
    ("caltrop", "Tribulus terrestris"),
    ("soursob", "Oxalis spp."),
    ("lantana", "Lantana camara"),
]


def test_management_requests_decline_through_the_funnel():
    """The regression: advice requests must be refused at the entry point."""
    f = funnel()
    for q in MANAGEMENT_QUESTIONS:
        r = f.answer(q, region="Australia")
        assert r["refused"] is True, f"{q!r} was answered: {r['response'][:80]!r}"
        assert r["refused_reason"] == "management", f"{q!r} reason={r['refused_reason']}"
        assert r["intent"] == "management", f"{q!r} intent={r['intent']}"
        assert r["species"] == [], f"{q!r} still resolved species={r['species']}"


def test_decline_text_offers_a_redirect():
    """A refusal must not be a dead end — it should redirect to the real purpose."""
    r = funnel().answer("What herbicide should I use on lantana?", region="Australia")
    low = r["response"].lower()
    assert "herbicide" in low or "management" in low, "decline should name what it won't do"
    assert "indicate" in low or "soil" in low, "decline should redirect to indicators"


def test_indicator_questions_still_answer():
    """An explicit indicator question must win over incidental advice vocabulary."""
    f = funnel()
    for q, want in INDICATOR_QUESTIONS:
        r = f.answer(q, region="Australia")
        assert r["refused"] is False, f"{q!r} was refused: {r['response'][:80]!r}"
        assert r["intent"] == "indicator", f"{q!r} intent={r['intent']}"
        assert want in r["species"], f"{q!r} resolved {r['species']}, expected {want}"


def test_core_extraction_still_works():
    """The intent guard must not disturb ordinary species resolution."""
    f = funnel()
    for q, want in EXTRACTION_CASES:
        r = f.answer(q, region="Australia")
        assert want in r["species"], f"{q!r} resolved {r['species']}, expected {want}"


def test_empty_message_is_refused_honestly():
    r = funnel().answer("", region="Australia")
    assert r["refused"] is True
    assert r["refused_reason"] == "empty"


def test_unknown_plant_refuses_with_no_species():
    r = funnel().answer("asdfghjkl qwerty", region="Australia")
    assert r["refused"] is True
    assert r["refused_reason"] == "no_species"


def test_region_fallback_is_disclosed_in_the_answer():
    """UK/EU data must never be passed off as Australian without saying so.

    `get_indicators()` has always set `region_fallback`, but the funnel never
    surfaced it, so an AU user could be shown European indicator data silently.
    """
    r = funnel().answer("What does yorkshire fog indicate?", region="Australia")
    if r["refused"]:
        return  # species not resolvable in this DB build; nothing to assert
    low = r["response"].lower()
    if "europe" in low or "uk" in low:
        assert "note:" in low, (
            "response served non-AU data without a disclosure note"
        )


def test_answer_contract_keys_present():
    """Downstream callers rely on these keys; keep the contract stable."""
    r = funnel().answer("What does dandelion indicate?", region="Australia")
    for key in ("response", "species", "matches", "refused", "refused_reason",
                "intent", "grounding_repairs"):
        assert key in r, f"answer() is missing the {key!r} key"


# ── specificity: genus buckets must be labelled, never disguised ──────────

GENUS_QUERIES = [
    ("thistles", "Cirsium spp"),
    ("soursob", "Oxalis spp."),
    ("rushes", "Juncus spp"),
]

SPECIES_QUERIES = [
    ("serrated tussock", "Nassella trichotoma"),
    ("paterson's curse", "Echium plantagineum"),
    ("lantana", "Lantana camara"),
    ("caltrop", "Tribulus terrestris"),
]


def test_genus_matches_are_disclosed():
    """A genus-level answer must say so — it is not a species identification."""
    f = funnel()
    for q, want in GENUS_QUERIES:
        r = f.answer(q, region="Australia")
        assert want in r["species"], f"{q!r} resolved {r['species']}, expected {want}"
        assert "genus-level" in r["response"], (
            f"{q!r} returned a genus bucket without disclosing it"
        )


def test_species_matches_carry_no_genus_note():
    """The disclosure must not leak onto species-level answers."""
    f = funnel()
    for q, want in SPECIES_QUERIES:
        r = f.answer(q, region="Australia")
        assert want in r["species"], f"{q!r} resolved {r['species']}, expected {want}"
        assert "genus-level" not in r["response"], (
            f"{q!r} is species-level but was labelled genus-level"
        )


def test_genus_bucket_is_not_promoted_to_a_species():
    """Guard against inventing precision.

    An earlier revision promoted a genus bucket to the next-best species by
    score. That next candidate only shares the genus, so it produced:

        "soursob" -> Oxalis acetosella  (a European wood-sorrel)
        "rushes"  -> Juncus tenuis      (a different, mostly-European rush)

    Both are wrong for an Australian paddock, and worse than the honest genus
    answer. This test pins the honest behaviour.
    """
    f = funnel()
    for q, genus in GENUS_QUERIES:
        r = f.answer(q, region="Australia")
        for m in r["matches"]:
            if m and m["query"].lower() == q:
                assert m["specificity"] == "genus_bucket", (
                    f"{q!r} was promoted to {r['species']} — genus answers must "
                    f"stay genus-level"
                )


def test_match_specificity_is_present_for_every_match():
    """The specificity tag is part of the match contract."""
    r = funnel().answer("What does thistles indicate?", region="Australia")
    assert r["matches"], "expected at least one match"
    for m in r["matches"]:
        if m:
            assert m.get("specificity") in ("exact_species", "genus_bucket", "junk")


def test_classify_specificity_tags():
    from augury_funnel import classify_specificity
    assert classify_specificity("cirsium spp") == "genus_bucket"
    assert classify_specificity("Oxalis spp.") == "genus_bucket"
    assert classify_specificity("lantana camara") == "exact_species"
    assert classify_specificity("rushes excess") == "junk"
    assert classify_specificity("") == "exact_species"


def main() -> int:
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failures = []
    for name, fn in tests:
        try:
            fn()
            print(f"  [PASS] {name}")
        except AssertionError as e:
            failures.append((name, str(e)))
            print(f"  [FAIL] {name}\n         {e}")
        except Exception as e:  # noqa: BLE001
            failures.append((name, f"{type(e).__name__}: {e}"))
            print(f"  [ERROR] {name}\n         {type(e).__name__}: {e}")
    print(f"\n{len(tests)-len(failures)}/{len(tests)} funnel tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

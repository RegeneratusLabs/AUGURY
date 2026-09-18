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

#!/usr/bin/env python3
"""AUGURY — tests for the direction verifier's SAFETY properties.

This module is NOT a test that the verifier is accurate — it is not. Measured
against the 40 reviewed-faithful answers in data/thirdparty/results-text.jsonl it
reports conflicts in 25 of them (62.5%), almost all false positives. See the
module docstring of scripts/claim_verify.py for the four diagnosed causes.

These tests exist to guarantee the *negative result stays honest*:

  1. `repair_direction` refuses to run, so it cannot silently delete true claims
     from real answers by drifting into the serving path.
  2. The funnel does not import the module.
  3. Fact parsing (the part that IS reliable) keeps working.
  4. The false-positive figure is pinned, so an accidental "fix" that quietly
     changes behaviour has to update the number deliberately.

Pure and offline. Run:
    .venv-mcpmv46/bin/python tests/test_claim_verify.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from claim_verify import extract_facts, repair_direction, verify_direction  # noqa: E402

RESULTS = ROOT / "data" / "thirdparty" / "results-text.jsonl"
FUNNEL = ROOT / "scripts" / "augury_funnel.py"

# Measured 2026-09-19 against gate-A (reviewed-faithful) answers.
MEASURED_FALSE_POSITIVE_RATE = 0.625


def test_repair_refuses_without_explicit_override():
    """The critical safety property: unsafe repair must not run by default."""
    try:
        repair_direction("Lantana indicates dry soil conditions.",
                         ["Indicators:\n- Moisture: wet"])
    except RuntimeError:
        return
    raise AssertionError("repair_direction ran without allow_unsafe=True")


def test_repair_error_explains_why():
    try:
        repair_direction("x y z w", ["Indicators:\n- Moisture: dry"])
    except RuntimeError as e:
        assert "false positive" in str(e).lower(), "error should state the reason"
        return
    raise AssertionError("expected RuntimeError")


def test_funnel_does_not_import_the_verifier():
    """It must not be reachable from the serving path."""
    src = FUNNEL.read_text()
    assert "claim_verify" not in src, (
        "augury_funnel imports claim_verify; it is diagnostic-only and unsafe"
    )


def test_fact_extraction_reads_structured_payloads():
    """This part IS reliable and is what a corrected verifier would build on."""
    payload = ("Species: Lantana (Lantana camara)\n"
               "Region: Australia\n"
               "Indicators:\n"
               "- Moisture: moist to moderately dry\n"
               "- Soil pH: slightly acidic to neutral\n"
               "\nFarmer's question: what does this mean?")
    facts = dict(extract_facts(payload))
    assert facts.get("moisture") == "moist to moderately dry"
    assert facts.get("soil ph") == "slightly acidic to neutral"
    assert not any("farmer" in k for k in facts), "question leaked into facts"
    assert not any("lantana" in k for k in facts), "species header leaked into facts"


def test_verify_direction_reports_the_obvious_inversion():
    """The failure mode the module targets, on a case with no range overlap.

    'waterlogged' (index 0) is strictly outside a payload of 'dry' (index 10), so
    this one is a genuine catch rather than a lexicon artefact.
    """
    rep = verify_direction("This plant indicates waterlogged ground.",
                           ["Indicators:\n- Moisture: dry"])
    assert rep["conflicts"], "expected a conflict for waterlogged vs dry"
    assert rep["clean"] is False


def test_verify_direction_accepts_a_narrower_claim():
    """A claim inside the payload interval must NOT be flagged."""
    rep = verify_direction("This plant indicates moderately dry ground.",
                           ["Indicators:\n- Moisture: moist to moderately dry"])
    assert rep["clean"] is True, f"narrower claim wrongly flagged: {rep['conflicts']}"


def test_false_positive_rate_is_pinned_and_still_bad():
    """Records the negative result.

    If someone corrects the lexicon, this test SHOULD fail — update the constant
    and the module docstring together, deliberately.
    """
    rows = [json.loads(l) for l in RESULTS.read_text().splitlines() if l.strip()]
    gate_a = [r for r in rows if r.get("gate") == "A" and r.get("answer")]
    assert gate_a, "expected gate-A answers in the third-party results"
    fp = sum(1 for r in gate_a
             if verify_direction(r["answer"], [r.get("user") or ""])["conflicts"])
    rate = fp / len(gate_a)
    assert abs(rate - MEASURED_FALSE_POSITIVE_RATE) < 0.15, (
        f"false-positive rate moved to {rate:.1%} (pinned {MEASURED_FALSE_POSITIVE_RATE:.1%}). "
        f"If the lexicon was intentionally fixed, update the constant and the "
        f"claim_verify module docstring."
    )
    assert rate > 0.25, (
        f"false-positive rate is now {rate:.1%}; if that is a real improvement, "
        f"lower the pinned constant and consider wiring the verifier in"
    )


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
    print(f"\n{len(tests)-len(failures)}/{len(tests)} claim-verifier safety tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

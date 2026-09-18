#!/usr/bin/env python3
"""AUGURY — tests for canonical identity merging and the held-out extractor eval.

Two related defects, both about the text path disagreeing with itself.

1. Duplicate keys for one plant
-------------------------------
The text DB carries both `curled dock` and `rumex crispus` as separate species —
the same label fragmentation the vision path fixed with
`data/vision/canonical_map.json`, which was wired only into the vision scripts.
Twelve of the twenty pairs hold *different* indicator data, so a farmer asking
about "curled dock" and one asking about *Rumex crispus* got different soil
stories for the same weed. Both now resolve to one merged answer.

2. No held-out measurement of fuzzy matching
--------------------------------------------
`common_name_synonyms.json` is a direct lookup table, so querying it proves
nothing about the fuzzy matcher — it would report 100% by construction. The
honest test disables the curated map and asks whether fuzzy matching alone can
recover the right species. That is what `leave_one_out()` measures, and it gives
the number the handover said did not exist.

Pure and offline. Run:
    .venv-mcpmv46/bin/python tests/test_canonical_merge.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from species_lookup import SpeciesDB  # noqa: E402

CANON = json.loads((ROOT / "data" / "vision" / "canonical_map.json").read_text())["canonical"]
SYNONYMS = json.loads(
    (ROOT / "data" / "research" / "common_name_synonyms.json").read_text())["synonyms"]

_DB = None


def db() -> SpeciesDB:
    global _DB
    if _DB is None:
        _DB = SpeciesDB()
    return _DB


class _NoSynonyms(SpeciesDB):
    """A DB with the curated synonym map disabled, to isolate fuzzy matching."""

    def _load_synonyms(self):
        self.synonym_count = 0


_NOSYN = None


def nosyn() -> _NoSynonyms:
    global _NOSYN
    if _NOSYN is None:
        _NOSYN = _NoSynonyms()
    return _NOSYN


def test_fragmented_pairs_exist_in_the_text_db():
    """The premise: both keys of a canonical pair are real DB entries."""
    both = [(a, t) for a, t in CANON.items()
            if a in db()._species and t in db()._species]
    assert both, "expected fragmented key pairs to exist in the text DB"


def test_canonical_pairs_now_return_identical_indicators():
    """The regression: one plant must not give two different answers.

    Compares as a set of pairs, not as dicts: both keys merge the same rows but
    start from their own entry, so insertion ORDER legitimately differs.
    """
    d = db()
    mismatched = []
    for a, t in sorted(CANON.items()):
        ra, rt = d.get_indicators(a), d.get_indicators(t)
        if not ra or not rt:
            continue
        if set(ra["indicators"].items()) != set(rt["indicators"].items()):
            mismatched.append((a, t))
    assert mismatched == [], (
        f"{len(mismatched)} fragmented pairs still disagree: {mismatched[:5]}"
    )


def test_merge_preserves_rows_from_both_sides():
    """Merging must not silently drop indicator rows.

    Picking one side would lose data: the alias key is richer for 2 of 20 pairs
    (potentilla erecta, silene dioica) and the canonical for 6.
    """
    d = db()
    for a, t in sorted(CANON.items()):
        merged = d.get_indicators(a)
        if not merged:
            continue
        labels = set(merged["indicators"])
        for side in (a, t):
            raw = d._species.get(side, {}).get("regions", {})
            for reg in raw.values():
                side_labels = {k for k, v in (reg.get("indicators") or {}).items()
                               if v and str(v).strip()}
                # every label the side had for the CHOSEN region must survive
                if merged["region"] in d._species.get(side, {}).get("regions", {}):
                    chosenside = {k for k, v in (raw[merged["region"]].get("indicators") or {}).items()
                                  if v and str(v).strip()}
                    missing = chosenside - labels
                    assert not missing, f"{side} lost {missing} in the merge for {a}"


def test_merged_result_reports_its_provenance():
    """A merged answer must be auditable: which keys fed it."""
    r = db().get_indicators("curled dock", region="Australia")
    assert r is not None
    assert r["canonical_key"], "missing canonical_key"
    assert len(r["merged_from"]) >= 2, f"expected a merge, got {r['merged_from']}"
    assert "curled dock" in r["merged_from"] and "rumex crispus" in r["merged_from"]


def test_canonical_target_is_first_in_the_group():
    """The canonical key is what the answer should be attributed to."""
    d = db()
    for a, t in sorted(CANON.items()):
        if a not in d._species:
            continue
        group = d._canonical_group(a)
        assert group[0] in (t, a), f"{a!r} resolved to unexpected lead {group[0]!r}"


def test_unfragmented_species_are_unchanged():
    """Species not in the canonical map must behave exactly as before."""
    r = db().get_indicators("nassella trichotoma", region="Australia")
    assert r is not None
    assert r["merged_from"] == ["nassella trichotoma"], r["merged_from"]
    assert r["indicators"], "expected indicators for serrated tussock"


def test_synonym_lookup_is_not_circular():
    """The curated map is a direct lookup, so it cannot be the thing under test.

    With the map disabled, the probe DB must report zero curated synonyms — that
    is what makes `leave_one_out()` a real measurement of the fuzzy matcher rather
    than a tautology over the lookup table.
    """
    d = nosyn()
    assert d.synonym_count == 0, "probe DB should load no curated synonyms"
    # spot-check that the map is what normally makes these resolve
    curated = [k for k in SYNONYMS if k in db()._common_index]
    assert curated, "expected curated synonyms to be registered in the real DB"


def leave_one_out() -> tuple[int, int, list]:
    """Curated synonyms disabled: can fuzzy matching find the right species?"""
    d = nosyn()
    hits, misses = 0, []
    for name, target in sorted(SYNONYMS.items()):
        m = d.search(name, top_n=1)
        got = m[0]["key"] if m else None
        ok = got == target
        if not ok and got:
            merged = d.get_indicators(got) or {}
            ok = target in (merged.get("merged_from") or [])
        if ok:
            hits += 1
        else:
            misses.append((name, target, got))
    return hits, len(SYNONYMS), misses


def test_held_out_evaluation_runs_and_is_reported():
    """Pins the measured baseline for fuzzy common-name matching.

    Measured 2026-09-19: 89/158 = 56.3% with canonical merging enabled (50.0%
    before it). This is the held-out number the handover recorded as missing.

    If this moves materially, update the constant deliberately — and note that a
    *drop* means a resolution regression, while a rise means fuzzy matching or the
    canonical map genuinely improved.
    """
    hits, total, misses = leave_one_out()
    rate = hits / total
    assert total == len(SYNONYMS)
    assert 0.40 <= rate <= 0.70, (
        f"held-out common-name accuracy moved to {rate:.1%} ({hits}/{total}); "
        f"expected around 56%. First misses: {misses[:5]}"
    )
    # the curated map must still be doing real work, i.e. it is not redundant
    assert rate < 1.0, "fuzzy matching now resolves every curated synonym"


def test_held_out_misses_are_recorded_not_hidden():
    """A held-out eval is only useful if its failures are inspectable."""
    _hits, _total, misses = leave_one_out()
    assert misses, "expected some misses; a perfect score suggests map leakage"
    for name, target, got in misses[:20]:
        assert isinstance(name, str) and isinstance(target, str)


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

    hits, total, misses = leave_one_out()
    print(f"\n  held-out (no curated synonyms): {hits}/{total} = {hits/total:.1%}")
    print(f"  {len(tests)-len(failures)}/{len(tests)} canonical-merge tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

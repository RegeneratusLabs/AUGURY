#!/usr/bin/env python3
"""AUGURY — tests for the vision label registry.

The defect these tests pin down
-------------------------------
`PhotoID.canonical()` used to read `canon_map.get(key, alias.get(key, key))`,
letting the legacy v1 alias map override canonical merges. Two alias entries
reversed a merge:

    alias["prosopis spp"] = "prosopis spp."   (canonical says the reverse)
    alias["salix spp"]    = "salix spp."      (canonical says the reverse)

`index-v2/keys.json` stores canonical labels, so ground truth was rewritten one
way while predictions were stored the other way. A *correct* prediction was
scored as a miss, and the shipped path appeared to score ~81.1-81.6% when it
actually scores 82.42% — the same as the harness. The "2.2-point unexplained
discrepancy" recorded in docs/HANDOVER-2026-09-18.md was this bug and nothing else.

Pure: no encoder, no model weights, no network. Stdlib only — this venv has no
pytest and no pip, matching the repo's existing script-based convention.

Run:
    .venv-mcpmv46/bin/python tests/test_label_registry.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "vision"))

from photo_id import registry_errors, resolve_label  # noqa: E402

CANON = json.loads((ROOT / "data" / "vision" / "canonical_map.json").read_text())["canonical"]
ALIAS = json.loads((ROOT / "data" / "vision" / "alias_map.json").read_text())
INDEX_KEYS = json.loads((ROOT / "data" / "vision" / "index-v2" / "keys.json").read_text())
KNOWN = set(INDEX_KEYS)

# The two aliases that must never be applied: their target is not a label this
# index serves (it differs from the canonical key only by a trailing period).
REVERSING_ALIASES = ["prosopis spp", "salix spp"]


def test_index_labels_are_a_fixed_point():
    """Every label the index serves must resolve to itself.

    If this fails, ground truth can be rewritten into a label the index never
    emits, so correct predictions get scored as misses.
    """
    escapes = [k for k in KNOWN if resolve_label(k, KNOWN, CANON, ALIAS) != k]
    assert escapes == [], f"{len(escapes)} index labels escape the index: {escapes[:5]}"


def test_registry_has_no_escapes():
    """No label reachable from the index may fall outside it."""
    assert registry_errors(KNOWN, CANON, ALIAS) == []


def test_legacy_alias_cannot_override_canonical_merge():
    """The regression: a stale alias must not rewrite a canonical label."""
    for key in REVERSING_ALIASES:
        got = resolve_label(key, KNOWN, CANON, ALIAS)
        assert got == key, f"{key!r} resolved to {got!r}, expected {key!r}"


def test_reversing_alias_target_is_outside_the_index():
    """Documents *why* the guard is needed: these targets are not real labels."""
    for key in REVERSING_ALIASES:
        target = ALIAS[key]
        assert target not in KNOWN, (
            f"alias {key!r} -> {target!r} is now inside the index; the guard in "
            f"resolve_label may be obsolete"
        )


def test_no_alias_misresolves_an_index_label():
    """Every alias whose source is an index label must leave that label alone.

    Note for index-v2: *all* alias sources are themselves canonical index labels,
    so the legacy alias map is inert at runtime. It still matters for the v1
    index and for text-path lookups, so the map is kept — but it must never
    rewrite a label the index serves.
    """
    conflicts = {k: (ALIAS[k], resolve_label(k, KNOWN, CANON, ALIAS))
                 for k in ALIAS if k in KNOWN and resolve_label(k, KNOWN, CANON, ALIAS) != k}
    assert conflicts == {}, f"aliases rewriting index labels: {conflicts}"


def test_alias_mechanism_still_works_when_applicable():
    """Alias resolution must still function for a key the index does not serve."""
    known = {"agrostis capillaris", "plantago lanceolata"}
    assert resolve_label("bent grass", known, {}, ALIAS) == "agrostis capillaris"
    assert resolve_label("ribwort plantain", known, {}, ALIAS) == "plantago lanceolata"


def test_alias_outside_index_is_ignored():
    """An alias pointing at a label the index cannot emit is refused."""
    known = {"plantago lanceolata"}
    # target IS in the index -> alias applies
    assert resolve_label("ribwort plantain", known, {}, ALIAS) == "plantago lanceolata"
    # target is NOT in the index -> key returned untouched
    assert resolve_label("onion weed", known, {}, ALIAS) == "onion weed"


def test_canonical_map_beats_alias_map():
    """For a key the index does not serve, canonical wins over the alias map."""
    canon = {"spear thistle": "cirsium vulgare"}
    alias = {"spear thistle": "something else"}
    known = {"cirsium vulgare", "something else"}
    assert resolve_label("spear thistle", known, canon, alias) == "cirsium vulgare"


def test_no_canonical_merge_reverses_an_alias():
    """A canonical pair and an alias pair must not contradict each other.

    Guards the specific data defect that caused the measurement bug.
    """
    contradictions = [(a, b, CANON[a]) for a, b in ALIAS.items()
                      if CANON.get(a) is not None and CANON[a] != b]
    assert contradictions == [], f"alias/canonical contradictions present: {contradictions}"


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
    print(f"\n{len(tests)-len(failures)}/{len(tests)} label-registry tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

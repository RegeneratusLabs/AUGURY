#!/usr/bin/env python3
"""AUGURY — tests for the PDF-extraction artefact repair.

What is being repaired
----------------------
The Maughan & Amos / UK soil-association indicator text was extracted from PDFs and
carries two artefacts:

1. Soft hyphen (U+00AD) marking a line break, with the break space still present:
   ``'compac\\xad tion'`` -> ``'compaction'``.
2. Private Use Area glyphs (U+F052, U+F0B2) where a symbol font failed to map to
   Unicode, always at field boundaries:
   ``'acidic soil \\uf052 high fertility'`` -> ``'acidic soil / high fertility'``.

The dangerous part is the fix, not the bug: "normalise the slashes" is the obvious
move, and it silently destroys every URL in the database
(``https://host/a/b`` -> ``https: / /host / a / b``). Two earlier revisions of
`repair_mojibake.py` did exactly that. These tests pin the URL-safety property.

Pure and offline. Run:
    .venv-mcpmv46/bin/python tests/test_mojibake_repair.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from repair_mojibake import repair_text  # noqa: E402

MERGED_DB = ROOT / "data" / "research" / "database-merged.json"

CASES = [
    # soft hyphen rejoins across the leftover line-break space
    ("soils compac\u00ad tion, erosion", "soils compaction, erosion"),
    ("C wet / water\u00ad logged / poorly drained", "C wet / waterlogged / poorly drained"),
    ("light, clay-lime\u00ad stone soils", "light, clay-limestone soils"),
    ("anaerobio\u00ad sis", "anaerobiosis"),
    ("mois\u00ad ture balance", "moisture balance"),
    ("block\u00ad age of P", "blockage of P"),
    # PUA glyphs become the corpus's own ' / ' field separator
    ("acidic soil \uf052 high fertility / humus rich", "acidic soil / high fertility / humus rich"),
    ("clay / heavy \uf052\uf052 acid or low lime \uf052 high fertility",
     "clay / heavy / acid or low lime / high fertility"),
    ("sandy / stony \uf052 nutrient rich / excess C", "sandy / stony / nutrient rich / excess C"),
    # one-sided slash spacing is normalised
    ("Common/ smooth/ annual sow-thistle", "Common / smooth / annual sow-thistle"),
    ("high fertility/ humus", "high fertility / humus"),
    # already-correct text must be left alone
    ("moderately dry. Avoids waterlogged areas", "moderately dry. Avoids waterlogged areas"),
    ("clay / heavy acid or low lime", "clay / heavy acid or low lime"),
]

URLS = [
    "https://weeds.dpi.nsw.gov.au/Weed/75",
    "https://weeds.dpi.nsw.gov.au/Weed/Alligatorweed",
    "https://weeds.org.au/profiles/alligator-weed/",
    "https://www.herbiguide.com.au/descriptions/hg_khaki_weed.htm",
    "https://www.landscape.sa.gov.au/ki/land-and-farming/pest-management/controlling-weeds/khaki-weed",
    "http://keyserver.lucidcentral.org/weeds/data/media/Html/avena_fatua.htm",
]


def test_known_repairs():
    for src, want in CASES:
        got = repair_text(src)
        assert got == want, f"{src!r} -> {got!r}, expected {want!r}"


def test_repair_is_idempotent():
    for src, _ in CASES:
        once = repair_text(src)
        assert repair_text(once) == once, f"not idempotent for {src!r}"


def test_urls_are_never_rewritten():
    """The regression that two earlier revisions introduced."""
    for u in URLS:
        assert repair_text(u) == u, f"URL was rewritten: {u!r} -> {repair_text(u)!r}"


def test_urls_survive_alongside_artefacts():
    """A URL in a string that also contains artefacts keeps its slashes."""
    src = "see https://weeds.org.au/profiles/x/ for detail \uf052 high fertility"
    got = repair_text(src)
    assert "https://weeds.org.au/profiles/x/" in got, f"URL damaged: {got!r}"
    assert "\uf052" not in got, "PUA glyph survived"


def test_no_artefacts_remain_in_the_database():
    """The shipped DB must be clean of PUA glyphs and soft hyphens."""
    db = json.loads(MERGED_DB.read_text())
    blob = json.dumps(db, ensure_ascii=False)
    assert "\uf052" not in blob, "PUA U+F052 still present"
    assert "\uf0b2" not in blob, "PUA U+F0B2 still present"
    assert "\u00ad" not in blob, "soft hyphen still present"


def test_legitimate_typography_is_preserved():
    """En/em dashes and real symbols are content, not corruption."""
    db = json.loads(MERGED_DB.read_text())
    blob = json.dumps(db, ensure_ascii=False)
    for ch, name in (("\u2013", "en dash"), ("\u2014", "em dash"),
                     ("\u00b2", "superscript two"), ("\u2265", "greater-or-equal")):
        assert ch in blob, f"{name} was destroyed by the repair"


def test_repair_does_not_change_ascii_only_strings():
    for s in ("moderately dry", "neutral to slightly acidic", "pH 5.5-7.0", ""):
        assert repair_text(s) == s, f"ASCII string was modified: {s!r}"


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
    print(f"\n{len(tests)-len(failures)}/{len(tests)} mojibake-repair tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

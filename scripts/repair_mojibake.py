#!/usr/bin/env python3
"""AUGURY — repair_mojibake.py

Fix the 14 database entries whose indicator text carries PDF-extraction garbage.

What the garbage actually is
----------------------------
These strings came from the Maughan & Amos / UK soil-association corpus, extracted
from PDFs. Two distinct artefacts survive:

1. **Soft hyphen (U+00AD) used as a line-break hint.** The extraction preserved the
   hyphenation point, so words are split mid-word:

       'water\\xad logged'   'compac\\xad tion'   'anaerobio\\xad sis'

   A soft hyphen is invisible in rendering and exists only to mark where a word
   *may* break, so the correct repair is to delete it and join the halves.

2. **Private Use Area glyphs (U+F052, U+F0B2).** A symbol font (Webdings/Wingdings
   subset) failed to map to Unicode, so its separator glyphs landed in the PUA.
   Context shows they all sit at field boundaries:

       'acidic soil [U+F052] high fertility'   'sandy / stony [U+F052] nutrient rich'

   The corpus already uses ' / ' as its field separator, so these become ' / '.

Deliberately NOT touched
------------------------
En dash (U+2013, 1825 occurrences) and em dash (U+2014, 200) are correct
typography, not corruption. Superscript two and micro sign likewise. A naive
"non-ASCII" sweep would destroy real content, which is why this script targets
specific codepoints and the specific contexts they appear in.

Idempotent, dry-run by default.

Usage:
    .venv-mcpmv46/bin/python scripts/repair_mojibake.py --dry-run
    .venv-mcpmv46/bin/python scripts/repair_mojibake.py --apply
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

MERGED_DB = ROOT / "data" / "research" / "database-merged.json"
BACKUP = ROOT / "data" / "research" / "database-merged.json.pre-mojibake"

SOFT_HYPHEN = "\u00ad"
PUA_SEPARATORS = "\uf052\uf0b2"

# A soft hyphen inside a word is a hyphenation artefact. Extraction left the
# line-break space behind too ('compac\xad tion'), so consume the hyphen AND any
# following whitespace to rejoin the word.
_SOFT_HYPHEN_RE = re.compile(r"(?<=\w)" + SOFT_HYPHEN + r"\s*(?=\w)")
# Anything left over (e.g. at a space) is just noise -> drop.
_ANY_SOFT_HYPHEN_RE = re.compile(SOFT_HYPHEN + r"\s*")
# One or more PUA separators, with optional surrounding whitespace -> ' / '.
_PUA_RE = re.compile(r"\s*[" + PUA_SEPARATORS + r"]+\s*")
# A slash with whitespace on exactly ONE side ('fertility/ humus', 'Common/ smooth').
# Deliberately narrow: ' / ' is already correct, 'a/b' may be intentional, and a
# blanket slash normaliser would corrupt every URL path (https://host/a/b).
_ONE_SIDED_SLASH_RE = re.compile(r"(?<=\S)\s+/(?=\S)|(?<=\S)/(?=\s)")
# URLs can appear mid-string (a source list plus a trailing note), so protect the
# URL *spans* rather than testing whether the whole string is a URL.
_URL_RE = re.compile(r"https?://\S+")
_SPACE_RE = re.compile(r"\s{2,}")


def _normalise_slashes_outside_urls(s: str) -> str:
    """Apply the one-sided-slash rule only to text that is not part of a URL."""
    out, last = [], 0
    for m in _URL_RE.finditer(s):
        out.append(_ONE_SIDED_SLASH_RE.sub(" / ", s[last:m.start()]))
        out.append(m.group(0))          # URL copied verbatim
        last = m.end()
    out.append(_ONE_SIDED_SLASH_RE.sub(" / ", s[last:]))
    return "".join(out)


def repair_text(s: str) -> str:
    """Repair one indicator string. Pure and idempotent.

    Order matters:
      1. soft hyphens are rejoined first, so words are whole before separators;
      2. PUA glyphs become the corpus's own ' / ' separator;
      3. one-sided slashes are normalised outside URL spans only.

    Any URL in the string — leading or embedded — is preserved byte-for-byte.
    """
    if not s:
        return s
    out = _SOFT_HYPHEN_RE.sub("", s)
    out = _ANY_SOFT_HYPHEN_RE.sub("", out)
    out = _PUA_RE.sub(" / ", out)
    out = _normalise_slashes_outside_urls(out)
    out = _SPACE_RE.sub(" ", out)
    return out.strip()


def _walk(node):
    """Yield (container, key) for every string leaf under `node`."""
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, str):
                yield node, k
            else:
                yield from _walk(v)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            if isinstance(v, str):
                yield node, i
            else:
                yield from _walk(v)


def collect(db: dict) -> dict:
    """Map 'key|region|indicator' -> (before, after) for every repair needed."""
    changes = {}
    for key, entry in db.items():
        for container, idx in _walk(entry):
            before = container[idx]
            after = repair_text(before)
            if after != before:
                changes[f"{key} -> {before[:40]!r}"] = (before, after)
    return changes


def main() -> int:
    ap = argparse.ArgumentParser(description="Repair PDF-extraction artefacts in the species DB")
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    ap.add_argument("--dry-run", action="store_true", help="preview only (the default; explicit)")
    ap.add_argument("--json", action="store_true", help="emit changes as JSON")
    args = ap.parse_args()
    if args.apply and args.dry_run:
        ap.error("--apply and --dry-run are mutually exclusive")

    if not MERGED_DB.exists():
        raise SystemExit(f"missing {MERGED_DB}")
    db = json.loads(MERGED_DB.read_text())
    changes = collect(db)

    if args.json:
        print(json.dumps({k: {"before": b, "after": a} for k, (b, a) in changes.items()}, indent=1))
    else:
        print(f"[mojibake] strings needing repair: {len(changes)}")
        for i, (label, (before, after)) in enumerate(sorted(changes.items())):
            if i >= 10:
                print(f"    ... and {len(changes)-10} more")
                break
            print(f"  - {label}")
            print(f"      before: {before[:96]!r}")
            print(f"      after : {after[:96]!r}")

    if not args.apply:
        print("\n[mojibake] dry run — nothing written. Re-run with --apply.")
        return 0

    if not changes:
        print("\n[mojibake] nothing to do.")
        return 0

    if not BACKUP.exists():
        BACKUP.write_text(json.dumps(db, indent=1))
        print(f"[mojibake] backup written: {BACKUP.name}")

    for entry in db.values():
        for container, idx in _walk(entry):
            container[idx] = repair_text(container[idx])
    MERGED_DB.write_text(json.dumps(db, indent=1))

    # verify: no artefacts remain, and the file still parses
    after = collect(json.loads(MERGED_DB.read_text()))
    print(f"\n[mojibake] applied. re-scan: {len(after)} remaining "
          f"({'CLEAN' if not after else 'STILL DIRTY'})")
    return 0 if not after else 1


if __name__ == "__main__":
    raise SystemExit(main())

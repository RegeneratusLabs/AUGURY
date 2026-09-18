#!/usr/bin/env python3
"""AUGURY — cleanup_workspace.py

Remove the on-disk consequences of non-species keys, so the tree stops lying
about its own contents.

Why this exists
---------------
Auditing the vision gallery for sidecar coverage was slow and initially wrong,
because `data/vision/images/` contains directories that look like species but are
not. `SpeciesDB._load()` builds its species map by parsing the training JSONL and
extracting a scientific name per row, and that corpus contains rows whose
"Species:" field is not a plant, so the extractor faithfully manufactures keys:

    Species: Rushes excess                  -> 'rushes excess'    (UK soil association)
    Species: Fumitory loam                  -> 'fumitory loam'    (UK soil association)
    Species: Mitchell Grass (astrebia spp)  -> 'astrebia spp'     (misspelling)
    Species: Tripleurosper perforatum       -> truncated mid-word

An acquisition run then probes iNaturalist for a plant that does not exist, gets
nothing, and leaves an empty directory behind. A later "which species have no
sidecar?" audit counts those as real species and reports dozens of false
positives — which is exactly the wasted time this script exists to prevent.

Division of labour with junk_keys.py
------------------------------------
Junk *keys* are filtered at parse time by `SpeciesDB._sanitize()`, driven by
`scripts/junk_keys.py`. That is deliberate: the training JSONL is published
(RegeneratusLabs/augury-training-data) and the shipped LoRA was trained on it, so
rewriting the source artefacts would invalidate published hashes and desync the
model from its own training set. This script only removes what those keys left on
disk.

Deliberately NOT removed: genuinely-empty species directories. Those are a real
data gap to be populated by acquisition, not junk. They are counted and reported
so the gap stays visible.

Idempotent and dry-run by default.

Usage:
    .venv-mcpmv46/bin/python scripts/cleanup_workspace.py --dry-run
    .venv-mcpmv46/bin/python scripts/cleanup_workspace.py --apply
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from junk_keys import JUNK_KEYS  # noqa: E402

IMAGES = ROOT / "data" / "vision" / "images"
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")


def _images(d: Path) -> list[str]:
    return [f for f in d.iterdir() if f.is_file() and f.name.lower().endswith(IMAGE_SUFFIXES)]


def collect() -> dict:
    """Classify every species directory. Pure: reads only."""
    junk_dirs, real_empty = [], []
    if IMAGES.exists():
        for d in sorted(IMAGES.iterdir()):
            if not d.is_dir() or _images(d):
                continue
            (junk_dirs if d.name in JUNK_KEYS else real_empty).append(d.name)
    return {"junk_keys": sorted(JUNK_KEYS), "junk_dirs": junk_dirs, "real_empty": real_empty}


def plan(report: dict) -> dict:
    """What would change. Derived from collect(), so dry-run and apply agree."""
    return {
        "dirs_removed": report["junk_dirs"],
        "dirs_skipped": report["real_empty"],
    }


def apply(p: dict) -> None:
    for name in p["dirs_removed"]:
        d = IMAGES / name
        if d.is_dir():
            shutil.rmtree(d)


def main() -> int:
    ap = argparse.ArgumentParser(description="Remove non-species artefacts from the workspace")
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    ap.add_argument("--dry-run", action="store_true", help="preview only (the default; explicit)")
    ap.add_argument("--json", action="store_true", help="emit the plan as JSON")
    args = ap.parse_args()
    if args.apply and args.dry_run:
        ap.error("--apply and --dry-run are mutually exclusive")

    report = collect()
    p = plan(report)

    if args.json:
        print(json.dumps(p, indent=1))
    else:
        print(f"[cleanup] junk keys known        : {len(report['junk_keys'])}")
        print(f"[cleanup] empty junk dirs to del : {len(p['dirs_removed'])}")
        for n in p["dirs_removed"]:
            print(f"      - {n}")
        print(f"[cleanup] genuine empty species  : {len(p['dirs_skipped'])} PRESERVED")
        print( "          (real data gaps, not junk — populate via acquisition)")

    if not args.apply:
        print("\n[cleanup] dry run — nothing written. Re-run with --apply.")
        return 0

    apply(p)
    print("\n[cleanup] applied.")

    remaining = len(plan(collect())["dirs_removed"])
    print(f"[cleanup] re-plan after apply: {remaining} changes remain "
          f"({'IDEMPOTENT' if remaining == 0 else 'NOT IDEMPOTENT'})")
    return 0 if remaining == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

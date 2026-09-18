#!/usr/bin/env python3
"""AUGURY — backfill_sidecars.py

Repair the 21 gallery images that have no `sources.jsonl` entry.

Why they are missing
--------------------
`pull_inaturalist.py` is resumable: it clears and rewrites each species' sidecar
on a run, then re-derives the entry list from the files already on disk. An
interrupted and restarted run therefore leaves images present but unrecorded.
The filename encodes everything needed to identify them:

    <taxon_id>_<photo_id>.jpg      e.g. 557826_682686807.jpg

so the source photo is fully identifiable even though the sidecar lost it.

The rule this script follows: **never invent a licence.**
These images are local-only and gitignored, but the sidecar is the record that
would gate any dataset publication, so a guessed licence is worse than a missing
one. Each repaired entry therefore lands in one of two states:

  * ``license`` recovered from a *corroborating* record. Three of the files have
    an exact photo_id match under a pre-canonicalisation species key
    (`agrostis tenuis` vs `agrostis capillaris`), which is real evidence, not a
    guess, so the licence is copied.
  * ``license: null`` with ``license_status: "requires_verification"`` plus a
    ``verify_url``. Nothing is fabricated; the entry is explicitly marked
    unresolved so it cannot pass a publication check unnoticed.

On resolving the remainder (measured 2026-09-19)
------------------------------------------------
Automated recovery was probed and does **not** work from this host:

  * ``GET /v1/photos/{id}`` — HTTP 404. There is no such endpoint.
  * ``GET https://www.inaturalist.org/photos/{id}`` — HTTP 403 (bot protection),
    so even the human-facing page cannot be confirmed from here.
  * ``GET /v1/observations?taxon_id=…`` works (HTTP 200) but would mean paging
    through e.g. 265,470 observations for *Achillea millefolium* to locate 8
    photo ids.

So this is **not** a one-call-per-photo fix, and the script does not pretend
otherwise. `verify_url` records the canonical photo page as the best available
human check; it is explicitly *not* asserted to be reachable from this host. The
18 entries stay `requires_verification` until a human or an authenticated harvest
confirms them.

``--check-publishable`` fails if any unverified licence remains, so the gap cannot
be silently published.

Idempotent, dry-run by default.

Usage:
    .venv-mcpmv46/bin/python scripts/backfill_sidecars.py --dry-run
    .venv-mcpmv46/bin/python scripts/backfill_sidecars.py --apply
    .venv-mcpmv46/bin/python scripts/backfill_sidecars.py --check-publishable
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMAGES = ROOT / "data" / "vision" / "images"

# <taxon_id>_<photo_id>.jpg — the puller's filename contract.
INAT_NAME_RE = re.compile(r"^(\d+)_(\d+)\.jpg$")
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")
VERIFY_URL = "https://www.inaturalist.org/photos/{photo_id}"


def _images(d: Path) -> list[str]:
    return sorted(f for f in os.listdir(d)
                  if f.lower().endswith(IMAGE_SUFFIXES)
                  and (d / f).is_file())


def _sidecar_entries(sc: Path) -> list[dict]:
    if not sc.exists():
        return []
    out = []
    for ln in sc.read_text().splitlines():
        if ln.strip():
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                continue
    return out


def build_photo_index() -> dict:
    """photo_id -> (license, species, file) for every recorded entry in the gallery."""
    index = {}
    if not IMAGES.exists():
        return index
    for sp in sorted(os.listdir(IMAGES)):
        d = IMAGES / sp
        if not d.is_dir():
            continue
        for e in _sidecar_entries(d / "sources.jsonl"):
            pid = e.get("photo_id")
            if pid and pid not in index:
                index[pid] = (e.get("license"), sp, e.get("file"))
    return index


def collect() -> dict:
    """Find every image with no sidecar entry, and the evidence for each."""
    index = build_photo_index()
    plan = {}
    for sp in sorted(os.listdir(IMAGES)):
        d = IMAGES / sp
        if not d.is_dir():
            continue
        imgs = _images(d)
        if not imgs:
            continue
        have = {e.get("file") for e in _sidecar_entries(d / "sources.jsonl")}
        missing = [f for f in imgs if f not in have]
        if not missing:
            continue
        entries = []
        for f in missing:
            m = INAT_NAME_RE.match(f)
            if not m:
                entries.append({"file": f, "reason": "unrecognised_filename"})
                continue
            taxon_id, photo_id = int(m.group(1)), int(m.group(2))
            rec = index.get(photo_id)
            entry = {
                "file": f, "photo_id": photo_id, "taxon_id": taxon_id,
                "source": "inaturalist",
                "verify_url": VERIFY_URL.format(photo_id=photo_id),
            }
            if rec and rec[0]:
                entry["license"] = rec[0]
                entry["license_status"] = "recovered"
                entry["recovered_from"] = {"species": rec[1], "file": rec[2]}
            else:
                entry["license"] = None
                entry["license_status"] = "requires_verification"
            entries.append(entry)
        plan[sp] = entries
    return plan


def apply(plan: dict) -> None:
    for sp, entries in plan.items():
        sc = IMAGES / sp / "sources.jsonl"
        with open(sc, "a") as fh:
            for e in entries:
                if e.get("reason"):
                    continue          # cannot describe it; leave for a human
                fh.write(json.dumps(e) + "\n")


def check_publishable() -> int:
    """Fail when any sidecar entry has an unresolved licence."""
    unresolved = []
    for sp in sorted(os.listdir(IMAGES)):
        d = IMAGES / sp
        if not d.is_dir():
            continue
        for e in _sidecar_entries(d / "sources.jsonl"):
            if e.get("license") in (None, "", "unverified") or \
               e.get("license_status") == "requires_verification":
                unresolved.append(f"{sp}/{e.get('file')}")
    if unresolved:
        print(f"[sidecars] NOT publishable: {len(unresolved)} entry/entries lack a verified licence")
        for u in unresolved[:15]:
            print(f"    {u}")
        if len(unresolved) > 15:
            print(f"    ... and {len(unresolved)-15} more")
        return 1
    print("[sidecars] all entries carry a licence")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill missing gallery sidecar entries")
    ap.add_argument("--apply", action="store_true", help="write entries (default: dry run)")
    ap.add_argument("--dry-run", action="store_true", help="preview only (the default)")
    ap.add_argument("--check-publishable", action="store_true",
                    help="exit non-zero if any licence is unverified")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    if args.apply and args.dry_run:
        ap.error("--apply and --dry-run are mutually exclusive")

    if args.check_publishable:
        return check_publishable()

    plan = collect()
    n = sum(len(v) for v in plan.values())
    recovered = sum(1 for v in plan.values() for e in v if e.get("license_status") == "recovered")
    unresolved = sum(1 for v in plan.values()
                     for e in v if e.get("license_status") == "requires_verification")
    unrecognised = sum(1 for v in plan.values() for e in v if e.get("reason"))

    if args.json:
        print(json.dumps(plan, indent=1))
    else:
        print(f"[sidecars] species affected        : {len(plan)}")
        print(f"[sidecars] images to backfill      : {n}")
        print(f"           licence RECOVERED       : {recovered}  (corroborated photo_id)")
        print(f"           licence REQUIRES VERIFY : {unresolved}")
        if unrecognised:
            print(f"           unrecognised filename   : {unrecognised}")
        for sp, entries in plan.items():
            rec = sum(1 for e in entries if e.get("license_status") == "recovered")
            ver = sum(1 for e in entries if e.get("license_status") == "requires_verification")
            print(f"    {sp:26s} {len(entries):2d}  (recovered {rec}, verify {ver})")

    if not args.apply:
        print("\n[sidecars] dry run — nothing written. Re-run with --apply.")
        return 0

    apply(plan)
    print("\n[sidecars] applied.")
    left = sum(len(v) for v in collect().values())
    print(f"[sidecars] re-scan: {left} still missing ({'CLEAN' if left == 0 else 'INCOMPLETE'})")
    return 0 if left == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

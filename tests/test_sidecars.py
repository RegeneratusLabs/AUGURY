#!/usr/bin/env python3
"""AUGURY — tests for gallery sidecar integrity and backfill.

Context
-------
`pull_inaturalist.py` clears and rewrites each species' `sources.jsonl` on a run
and re-derives the entry list from files already on disk. An interrupted and
restarted run therefore left 21 images present but unrecorded across 5 species.
The sidecar is the record that would gate any dataset publication, so the
important property is not "the files exist" but "every file has a provenance
entry, and no licence was invented to get there".

The rule under test: a licence is either *recovered from corroborating evidence*
(an exact photo_id match elsewhere in the gallery) or explicitly marked
`requires_verification`. It is never guessed.

Pure and offline. Run:
    .venv-mcpmv46/bin/python tests/test_sidecars.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from backfill_sidecars import (  # noqa: E402
    IMAGES, INAT_NAME_RE, _images, _sidecar_entries, build_photo_index, collect,
)

IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")


def _all_sidecar_entries():
    for sp in sorted(IMAGES.iterdir()):
        if sp.is_dir():
            for e in _sidecar_entries(sp / "sources.jsonl"):
                yield sp.name, e


def test_every_gallery_image_has_a_sidecar_entry():
    """No image may be present without a provenance record."""
    missing = []
    for sp in sorted(IMAGES.iterdir()):
        if not sp.is_dir():
            continue
        imgs = set(_images(sp))
        if not imgs:
            continue
        have = {e.get("file") for e in _sidecar_entries(sp / "sources.jsonl")}
        gap = imgs - have
        if gap:
            missing.append((sp.name, sorted(gap)[:3], len(gap)))
    assert missing == [], f"{len(missing)} species still have unrecorded images: {missing[:5]}"


def test_backfill_is_idempotent():
    """A second pass must find nothing to do."""
    assert collect() == {}, "backfill would re-append entries"


def test_no_licence_was_invented():
    """Every entry either has a licence or is explicitly marked unresolved."""
    bad = []
    for sp, e in _all_sidecar_entries():
        if "file" not in e:
            continue
        lic = e.get("license")
        status = e.get("license_status")
        if lic in (None, "", "unverified"):
            if status != "requires_verification":
                bad.append((sp, e.get("file"), lic, status))
        elif not isinstance(lic, str) or not lic.strip():
            bad.append((sp, e.get("file"), lic, status))
    assert bad == [], f"entries with an ambiguous licence: {bad[:5]}"


def test_recovered_licences_cite_their_evidence():
    """A 'recovered' licence must name where it came from."""
    for sp, e in _all_sidecar_entries():
        if e.get("license_status") == "recovered":
            assert e.get("recovered_from"), (
                f"{sp}/{e.get('file')} claims a recovered licence with no evidence"
            )
            src = e["recovered_from"]
            assert src.get("species") and src.get("file"), (
                f"{sp}/{e.get('file')} has incomplete recovery evidence: {src}"
            )


def test_unverified_entries_are_actionable():
    """An unresolved entry must carry enough to verify it in one call."""
    for sp, e in _all_sidecar_entries():
        if e.get("license_status") == "requires_verification":
            assert e.get("photo_id"), f"{sp}/{e.get('file')} has no photo_id"
            assert e.get("verify_url", "").startswith("https://"), (
                f"{sp}/{e.get('file')} has no verify_url"
            )
            assert str(e["photo_id"]) in e["verify_url"], (
                f"{sp}/{e.get('file')} verify_url does not reference its photo_id"
            )


def test_inaturalist_filenames_are_parseable():
    """The backfill depends on the puller's <taxon>_<photo>.jpg contract."""
    sample = "557826_682686807.jpg"
    m = INAT_NAME_RE.match(sample)
    assert m, f"{sample!r} does not match the filename contract"
    assert m.group(1) == "557826" and m.group(2) == "682686807"
    # a deepweeds name must NOT match (different provenance)
    assert INAT_NAME_RE.match("dw_20170706-110255-0.jpg") is None


def test_photo_index_detects_corroboration():
    """The recovery mechanism itself: same photo_id recorded under another key."""
    index = build_photo_index()
    assert index, "expected a non-empty photo_id index"
    # agrostis capillaris' orphans were corroborated by agrostis tenuis
    assert 706768816 in index, "expected the corroborating photo_id in the index"
    lic, sp, _f = index[706768816]
    assert lic, "corroborating record should carry a licence"


def test_sidecar_entries_are_valid_json_lines():
    for sp in sorted(IMAGES.iterdir()):
        if not sp.is_dir():
            continue
        sc = sp / "sources.jsonl"
        if not sc.exists():
            continue
        for i, ln in enumerate(sc.read_text().splitlines(), 1):
            if not ln.strip():
                continue
            try:
                json.loads(ln)
            except json.JSONDecodeError as e:
                raise AssertionError(f"{sp.name}/sources.jsonl line {i} is invalid JSON: {e}") from e


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
    print(f"\n{len(tests)-len(failures)}/{len(tests)} sidecar tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

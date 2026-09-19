#!/usr/bin/env python3
"""AUGURY — tests for gallery label integrity and taxon matching.

The bug these pin down
----------------------
`pull_inaturalist.match_taxon()` accepted the first taxon candidate sharing "any
two tokens of 4+ characters" with the query. That is resemblance, not identity, and
it silently misfiled photographs:

    prosopis spp        -> taxon 52793 = Holcus lanatus
    sinapis arvensis    -> taxon 55411 = Raphanus raphanistrum

Two different plants ended up holding the *same* photographs. Measured on the
shipped index-v2: 501 of 13,358 vectors were byte-identical, 126 groups spanned
different species, and 294 vectors were affected. `holcus lanatus` and
`prosopis spp` returned similarity 1.0 against each other because they were
literally the same images. Those species were unlearnable, and their benchmark
queries carried wrong ground truth.

The repair moved the mislabeled images to their true species and purged the wrong
taxa-cache entries. These tests keep both the data and the rule honest.

Pure and offline — no API calls, so this runs anywhere.

Run:
    .venv-mcpmv46/bin/python tests/test_gallery_integrity.py
"""
from __future__ import annotations

import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "vision"))
sys.path.insert(0, str(ROOT / "scripts"))

from pull_inaturalist import _epithet, _looks_binomial, _norm  # noqa: E402

IMAGES = ROOT / "data" / "vision" / "images"
PULLER = ROOT / "scripts" / "vision" / "pull_inaturalist.py"
CANONICAL_MAP = ROOT / "data" / "vision" / "canonical_map.json"
TAXA_CACHE = ROOT / "data" / "vision" / "inat_taxa_cache.json"

PREFIX_RE = re.compile(r"^(\d+)_")

# Taxon ids that were proven wrong by the API on 2026-09-19.
WRONG_ASSIGNMENTS = {52793: "Holcus lanatus", 55411: "Raphanus raphanistrum"}


def _file_taxa(d: Path) -> set:
    out = set()
    for f in d.iterdir():
        if f.suffix.lower() != ".jpg":
            continue
        m = PREFIX_RE.match(f.name)
        if m:
            out.add(int(m.group(1)))
    return out


def _gallery_dirs() -> list:
    if not IMAGES.is_dir():
        return []
    return sorted(d for d in IMAGES.iterdir()
                  if d.is_dir() and d.name != "_quarantine")


def test_helper_normalisation():
    assert _norm("  Sinapis   arvensis ") == "sinapis arvensis"
    assert _norm("Banksia spp.") == "banksia spp"
    assert _norm(None) == ""


def test_epithet_extraction():
    assert _epithet("Sinapis arvensis") == "arvensis"
    assert _epithet("Mutarda arvensis") == "arvensis"
    assert _epithet("Banksia") == ""
    assert _epithet("banksia spp") == "spp"


def test_binomial_detection():
    """The helper requires BOTH words capitalised (Title Case).

    That is a deliberate constraint of the existing implementation, and it is
    conservative: a lowercase "Sinapis arvensis" is NOT treated as a binomial, so
    it can only match as a vernacular/exact name. The cost is that some legitimate
    alternate scientific names are missed — which shows up as an *unresolved*
    collision to review, never as a wrong assignment. That is the safe direction.

    Its real job is telling an alternate scientific name apart from a vernacular
    one, so capitalised vernaculars are blocked by modifier.
    """
    assert _looks_binomial("Sinapis Arvensis")
    assert _looks_binomial("Holcus Lanatus")
    assert not _looks_binomial("Sinapis arvensis")   # not Title Case
    assert not _looks_binomial("Charlock")
    assert not _looks_binomial("Wild Radish")        # vernacular modifier
    assert not _looks_binomial("Black Nightshade")   # vernacular modifier
    assert not _looks_binomial("Charlock (Sinapis arvensis)")


def test_loose_token_rule_is_gone():
    """The precise defect must not come back.

    The old rule was a token-overlap heuristic. If it reappears, the
    contamination returns with it, so assert on the source itself.
    """
    src = PULLER.read_text()
    assert "len(toks_q & toks_t) >= 2" not in src, (
        "the loose token-overlap acceptance rule is back — it is what misfiled "
        "prosopis spp as Holcus lanatus"
    )
    assert "matched_term" in src, "expected the narrowed epithet+matched-term rule"


def test_no_cross_species_images_remain():
    """Two species must not hold the same photographs.

    Synonym pairs (already collapsed by canonical_map.json) legitimately share a
    taxon id, so only *different canonical plants* count as contamination.
    """
    canon = json.loads(CANONICAL_MAP.read_text()).get("canonical", {}) if CANONICAL_MAP.exists() else {}
    by_taxon = collections.defaultdict(set)
    for d in _gallery_dirs():
        for t in _file_taxa(d):
            by_taxon[t].add(d.name)
    bad = {}
    for t, species in by_taxon.items():
        groups = {canon.get(s, s) for s in species}
        if len(groups) > 1:
            bad[t] = sorted(species)
    assert bad == {}, f"cross-species taxon collisions remain: {bad}"


def test_contaminated_species_are_emptied_or_reassigned():
    """prosopis spp and sinapis arvensis must not still hold the wrong images."""
    for name in ("prosopis spp", "prosopis spp."):
        d = IMAGES / name
        if not d.is_dir():
            continue
        assert 52793 not in _file_taxa(d), (
            f"{name} still holds Holcus lanatus (taxon 52793) photographs"
        )
    d = IMAGES / "sinapis arvensis"
    if d.is_dir():
        assert 55411 not in _file_taxa(d), (
            "sinapis arvensis still holds Raphanus raphanistrum (55411) photographs"
        )


def test_taxa_cache_does_not_repeat_wrong_assignments():
    """A wrong cached id would silently re-contaminate on the next pull."""
    if not TAXA_CACHE.exists():
        return
    cache = json.loads(TAXA_CACHE.read_text())
    offenders = {}
    for key, val in cache.items():
        tid = val.get("taxon_id") if isinstance(val, dict) else val
        if tid in WRONG_ASSIGNMENTS and key not in WRONG_ASSIGNMENTS[tid].lower():
            offenders[key] = tid
    assert offenders == {}, (
        f"taxa cache still maps species to a proven-wrong taxon: {offenders}"
    )


def test_every_image_still_has_a_sidecar_entry():
    """The repair moved files, so their provenance must have moved too."""
    from backfill_sidecars import _images, _sidecar_entries
    missing = []
    for d in _gallery_dirs():
        imgs = set(_images(d))
        if not imgs:
            continue
        have = {e.get("file") for e in _sidecar_entries(d / "sources.jsonl")}
        gap = imgs - have
        if gap:
            missing.append((d.name, len(gap)))
    assert missing == [], f"images without provenance after the move: {missing[:5]}"


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
    print(f"\n{len(tests)-len(failures)}/{len(tests)} gallery-integrity tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

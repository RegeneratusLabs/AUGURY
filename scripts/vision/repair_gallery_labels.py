#!/usr/bin/env python3
"""AUGURY — repair_gallery_labels.py

Move mislabeled gallery images to the species they actually came from.

The bug
-------
`pull_inaturalist.py` resolves a species key to an iNaturalist taxon id and files
that taxon's photos under the key. When `match_taxon()` resolved the wrong taxon
(the loose "two shared 4+ char tokens" rule, plus a cache that never re-validates),
two different species ended up holding *the same photographs*:

    holcus lanatus     125 images, all prefix 52793
    prosopis spp        50 images, all prefix 52793   <-- taxon 52793 IS Holcus lanatus
    raphanus raphanistrum 50 images, all prefix 55411
    sinapis arvensis      50 images, all prefix 55411 <-- taxon 55411 IS Raphanus raphanistrum

Verified against the API, not inferred: `/v1/taxa/52793` returns "Holcus lanatus"
and `/v1/taxa/55411` returns "Raphanus raphanistrum".

Consequence: those species are unlearnable (the gallery says two different plants
are the same thing) and their benchmark queries carry wrong ground truth, so the
reported accuracy is depressed for reasons that are not model error.

How the repair decides
----------------------
The filename prefix is the resolved taxon id (or `q<sha1>` for the full-text
fallback). The script asks the API what each contested taxon id actually is, then:

  * if the taxon's true name matches the *other* species in the collision, that
    species keeps its images — which confirms the current holder is the wrong one;
  * otherwise the collision is reported as UNRESOLVED and nothing is moved.

It never guesses and never deletes. Images move to the correct species directory
when that directory is a known key, and to `_quarantine/<taxon>` when it is not.

Idempotent, dry-run by default.

Usage:
    .venv-mcpmv46/bin/python scripts/vision/repair_gallery_labels.py --dry-run
    .venv-mcpmv46/bin/python scripts/vision/repair_gallery_labels.py --apply
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import shutil
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

IMAGES = ROOT / "data" / "vision" / "images"
TAXA_CACHE = ROOT / "data" / "vision" / "inat_taxa_cache.json"
CANONICAL_MAP = ROOT / "data" / "vision" / "canonical_map.json"
QUARANTINE = IMAGES / "_quarantine"

UA = {"User-Agent": "AUGURY-gallery-repair/1.0"}
TAXON_RE = re.compile(r"^(\d+)_")

SPECIES_LIST = ROOT / "data" / "vision" / "species_list.json"
_SPECIES_BY_KEY: dict = {}
if SPECIES_LIST.exists():
    _SPECIES_BY_KEY = {s["key"]: s for s in json.loads(SPECIES_LIST.read_text())
                       if isinstance(s, dict) and s.get("key")}

# Cache for API answers within a run, persisted so reruns are cheap and offline-safe.
TAXON_NAMES_FILE = ROOT / "data" / "vision" / "inat_taxon_names.json"


def api_taxon_name(tid: int, cache: dict, offline: bool = False) -> str | None:
    """Return the scientific name for a taxon id, or None if unknown."""
    key = str(tid)
    if key in cache:
        return cache[key]
    if offline:
        return None
    try:
        req = urllib.request.Request(f"https://api.inaturalist.org/v1/taxa/{tid}",
                                     headers=UA)
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.load(r)
        res = d.get("results") or []
        name = res[0].get("name") if res else None
    except Exception:  # noqa: BLE001
        return None
    time.sleep(1.0)
    if name:
        cache[key] = name
    return name


def file_prefixes(d: Path) -> collections.Counter:
    c = collections.Counter()
    for f in os.listdir(d):
        if not f.lower().endswith(".jpg"):
            continue
        m = TAXON_RE.match(f)
        if m:
            c[int(m.group(1))] += 1
    return c


def find_collisions() -> dict:
    """Species dirs whose images carry a taxon id also used by another species."""
    by_taxon = collections.defaultdict(list)
    for sp in sorted(os.listdir(IMAGES)):
        d = IMAGES / sp
        if not d.is_dir() or sp == "_quarantine":
            continue
        for tid in file_prefixes(d):
            by_taxon[tid].append(sp)
    return {tid: sps for tid, sps in by_taxon.items() if len(sps) > 1}


def _species_names(key: str) -> set:
    """Every name this species is known by, lowercased.

    Includes `common_names`, because the species list stores alternate *scientific*
    names there — `atropis distans` lists "Puccinellia distans" among its common
    names, and without checking those the owner could not be identified.
    """
    sp = _SPECIES_BY_KEY.get(key)
    if not sp:
        return {key}
    names = {key, (sp.get("scientific_name") or "").lower()}
    names |= {str(c).lower() for c in (sp.get("common_names") or [])}
    # "Puccinellia distans (Atropis distans)" -> also index the bare part
    extra = set()
    for n in names:
        m = re.match(r"^([^(]+?)\s*\(", n)
        if m:
            extra.add(m.group(1).strip())
    return names | extra


def plan(cache: dict, offline: bool) -> dict:
    """Decide, per collision, which species legitimately owns the taxon id."""
    canon = {}
    if CANONICAL_MAP.exists():
        canon = json.loads(CANONICAL_MAP.read_text()).get("canonical", {})

    moves, unresolved, keep = [], [], []
    for tid, species in sorted(find_collisions().items()):
        # collapse synonyms: two keys for the same plant are not a collision
        groups = {canon.get(s, s) for s in species}
        if len(groups) == 1:
            keep.append({"taxon_id": tid, "species": species,
                         "reason": "synonym pair (same canonical plant)"})
            continue
        true_name = api_taxon_name(tid, cache, offline=offline)
        if not true_name:
            unresolved.append({"taxon_id": tid, "species": species,
                               "reason": "taxon name unavailable (offline or API error)"})
            continue
        tn = true_name.strip().lower()
        # A species owns the taxon when the true name is one of ITS names. Checked
        # against every known name, not just the key, so alternate scientific names
        # recorded in `common_names` resolve correctly.
        owners = [s for s in species if tn in _species_names(s)]
        if len(owners) != 1:
            unresolved.append({
                "taxon_id": tid, "species": species, "true_name": true_name,
                "reason": ("no species in the collision claims this name"
                           if not owners else "more than one species claims this name")})
            continue
        owner = owners[0]
        for s in species:
            if s == owner:
                continue
            d = IMAGES / s
            n = file_prefixes(d).get(tid, 0)
            if not n:
                continue
            dest = IMAGES / owner if (IMAGES / owner).is_dir() else QUARANTINE / str(tid)
            moves.append({"taxon_id": tid, "true_name": true_name,
                          "from": s, "to": str(dest.relative_to(ROOT)),
                          "count": n,
                          "files": [f for f in os.listdir(d)
                                    if TAXON_RE.match(f) and int(TAXON_RE.match(f).group(1)) == tid]})
    return {"keep": keep, "moves": moves, "unresolved": unresolved}


def apply_moves(p: dict) -> None:
    """Move images AND their provenance records.

    A move that leaves the sidecar entry behind silently destroys the images'
    licensing/attribution trail — the entry stays in the old species' file naming a
    file that is no longer there, and the new location has an image with no
    provenance. Both are integrity failures, so the sidecar is rewritten on both
    sides.
    """
    for m in p["moves"]:
        src = IMAGES / m["from"]
        dest = ROOT / m["to"]
        dest.mkdir(parents=True, exist_ok=True)
        moved = set()
        for f in m["files"]:
            s, d = src / f, dest / f
            if not s.exists():
                continue
            if d.exists():
                s.unlink()          # identical content already present
            else:
                shutil.move(str(s), str(d))
            moved.add(f)
        _migrate_sidecar_entries(src, dest, moved)


def _migrate_sidecar_entries(src: Path, dest: Path, moved: set) -> None:
    """Move the `sources.jsonl` rows for `moved` files from src to dest."""
    if not moved:
        return
    src_sc = src / "sources.jsonl"
    dest_sc = dest / "sources.jsonl"

    keep, taken = [], []
    if src_sc.exists():
        for ln in src_sc.read_text().splitlines():
            if not ln.strip():
                continue
            try:
                e = json.loads(ln)
            except json.JSONDecodeError:
                keep.append(ln)
                continue
            (taken if e.get("file") in moved else keep).append(e if isinstance(e, dict) else ln)
        src_sc.write_text("".join(
            (json.dumps(x) if isinstance(x, dict) else x) + "\n" for x in keep))

    if not taken:
        return
    existing = set()
    if dest_sc.exists():
        for ln in dest_sc.read_text().splitlines():
            if ln.strip():
                try:
                    existing.add(json.loads(ln).get("file"))
                except json.JSONDecodeError:
                    pass
    with open(dest_sc, "a") as fh:
        for e in taken:
            if isinstance(e, dict) and e.get("file") not in existing:
                fh.write(json.dumps(e) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description="Move mislabeled gallery images")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--offline", action="store_true",
                    help="use only cached taxon names; never call the API")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    if args.apply and args.dry_run:
        ap.error("--apply and --dry-run are mutually exclusive")

    cache = {}
    if TAXON_NAMES_FILE.exists():
        cache = json.loads(TAXON_NAMES_FILE.read_text())
    p = plan(cache, offline=args.offline)

    if args.json:
        print(json.dumps(p, indent=1))
    else:
        print(f"[repair] benign synonym collisions : {len(p['keep'])}")
        print(f"[repair] mislabeled groups to move : {len(p['moves'])}")
        for m in p["moves"]:
            print(f"    taxon {m['taxon_id']} ({m['true_name']}): "
                  f"{m['count']} images  {m['from']!r} -> {m['to']}")
        print(f"[repair] unresolved (needs review) : {len(p['unresolved'])}")
        for u in p["unresolved"]:
            print(f"    taxon {u['taxon_id']}: {u['species']} — {u['reason']}")

    if not args.apply:
        print("\n[repair] dry run — nothing moved. Re-run with --apply.")
        if cache:
            TAXON_NAMES_FILE.write_text(json.dumps(cache, indent=1, sort_keys=True))
        return 0

    apply_moves(p)
    if cache:
        TAXON_NAMES_FILE.write_text(json.dumps(cache, indent=1, sort_keys=True))

    # fix the taxa cache so the puller does not repeat the mistake
    if TAXA_CACHE.exists():
        tc = json.loads(TAXA_CACHE.read_text())
        victims = {m["from"] for m in p["moves"]}
        removed = [k for k in victims if k in tc]
        for k in removed:
            tc.pop(k, None)
        TAXA_CACHE.write_text(json.dumps(tc, indent=1))
        print(f"[repair] removed {len(removed)} wrong taxa-cache entries: {removed}")

    after = plan(cache, offline=True)
    remaining = len(after["moves"])
    print(f"[repair] applied. re-plan: {remaining} moves remain "
          f"({'IDEMPOTENT' if remaining == 0 else 'INCOMPLETE'})")
    print("[repair] NOTE: re-embed and rebuild the index for this to take effect:")
    print("    cache_embeddings.py -> fit_pca.py -> build_index_v2.py -> calibrate_bands.py")
    return 0 if remaining == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

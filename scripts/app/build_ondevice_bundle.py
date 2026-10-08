#!/usr/bin/env python3
"""AUGURY — build_ondevice_bundle.py

BUILD-TIME tool. Produces the two artifacts the Android app downloads from the
Hugging Face Hub at runtime. Nothing here is bundled into the APK.

    <out>/augury-ondevice.json   species facts, app-optimised (species.db@1)
    <out>/manifest.json          the app's update lever (manifest_schema 1)

Inputs (read, never modified):

    data/research/database-merged.json   source of truth for indicator facts
    data/vision/species_list.json        the vision universe (audit / cross-check)
    data/vision/index-v3/meta.json       index vectors / dim / species / backend
    data/vision/index-v3/band_config.json  (preferred) or band_calibration.json

Design rules that matter (see the W2 brief):

  * Indicator keys and values pass through VERBATIM. No normalisation, no
    merging, no renaming, no lowercasing, no de-duplication — not even the
    ``Ph`` / ``Soil pH`` pair. The app renders whatever keys exist; cleaning them
    here would defeat the whole point of the free-form-key design.
  * Every ``bytes`` / ``sha256`` is computed from the actual local file. If an
    artifact is not on disk yet (another agent may still be producing it) the
    field is emitted as ``null`` and listed in a loud UNRESOLVED warning. A
    manifest with invented hashes is worse than an incomplete one.
  * HF ``revision`` values come from the Hub API. A failed lookup yields
    ``null`` plus a warning, never a guess.

Usage:

    .venv-mcpmv46/bin/python scripts/app/build_ondevice_bundle.py
    .venv-mcpmv46/bin/python scripts/app/build_ondevice_bundle.py --out data/app
    .venv-mcpmv46/bin/python scripts/app/build_ondevice_bundle.py --verify
    .venv-mcpmv46/bin/python scripts/app/build_ondevice_bundle.py --verify --allow-unresolved

``--verify`` is the regression gate: it re-reads ``manifest.json``, re-hashes
every referenced local file and fails (non-zero) on any drift, on a missing
local file, or on an unresolved ``null`` bytes/sha256 field. ``--allow-unresolved``
downgrades *only* the null-field class to a warning (drift still fails) — that is
for the in-progress window before every producer has landed its artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# --------------------------------------------------------------------------- #
# Paths and protocol constants
# --------------------------------------------------------------------------- #

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

DEFAULT_DB = REPO_ROOT / "data" / "research" / "database-merged.json"
DEFAULT_SPECIES_LIST = REPO_ROOT / "data" / "vision" / "species_list.json"
DEFAULT_INDEX_DIR = REPO_ROOT / "data" / "vision" / "index-v3"
DEFAULT_OUT = REPO_ROOT / "data" / "app"

# Band calibration: `band_config.json` is the newer name (a parallel agent is
# adding it); `band_calibration.json` is what exists today. Prefer the former.
BAND_FILENAMES = ("band_config.json", "band_calibration.json")

# Product requirement: Australia is the v1 audience, so it leads every list.
PREFERRED_REGION_ORDER = ("Australia", "UK", "Europe")

# Repos / paths referenced by the manifest. These are publication coordinates,
# not measurements, so they are constants here.
FORMATTER_REPO = "RegeneratusLabs/augury-1b"
FORMATTER_PATH = "MiniCPM5-1B-AUGURY-Q4_K_M.gguf"
FORMATTER_PROTOCOL = "formatter.chatml-grounded@1"

FACTS_REPO = "RegeneratusLabs/augury-app"
FACTS_PATH = "augury-ondevice.json"
FACTS_PROTOCOL = "species.db@1"
FACTS_SCHEMA = 1

VISION_PROTOCOL = "vision.clip-token-l2-pca-knn-ip@1"
VISION_INDEX_REPO = "RegeneratusLabs/augury-vision-index"
VISION_INDEX_PATH = "vision-index-v3.tar.gz"
VISION_INDEX_SCHEMA = 1

ENCODER_REPO = "RegeneratusLabs/augury-app"
# fp32, NOT int8. Dynamic int8 quantisation was measured and REJECTED on
# 2026-09-19: on the same 40 queries, ONNX fp32 scored 0.7500/0.8500 (identical to
# PyTorch, delta +0.00p) while ONNX int8 collapsed to 0.0500/0.1250 (delta
# -70.00p). The fp32 control matching PyTorch exactly proves the pipeline was
# correct, so the collapse is a real quantisation effect — ViT attention needs
# more dynamic range than int8 weights provide. Full record:
# data/vision/bench/encoder_gate_dinov2-base-fp32.json
ENCODER_PATH = "dinov2-base-fp32.onnx"
ENCODER_QUANT = "fp32"

# Local candidate locations, most specific first, searched relative to the repo
# root. A CLI override always wins.
FORMATTER_CANDIDATES = (
    "models/MiniCPM5-1B-AUGURY-Q4_K_M.gguf",
    FORMATTER_PATH,
)
INDEX_CANDIDATES = (
    f"data/vision/{VISION_INDEX_PATH}",
    "data/vision/index-v3.tar.gz",
    VISION_INDEX_PATH,
)
ENCODER_CANDIDATES = (
    f"models/onnx/{ENCODER_PATH}",
    f"models/{ENCODER_PATH}",
    f"data/vision/{ENCODER_PATH}",
    ENCODER_PATH,
)
# Bounded roots for the last-resort basename search (keeps verify working when a
# producer lands the artifact somewhere reasonable but unexpected).
SEARCH_ROOTS = ("", "models", "models/onnx", "data", "data/vision", "data/app", "data/vision/index-v3")

# Vision preprocessing is part of the published protocol (the encoder's training
# transform), so it is a constant, not a measured value.
PREPROCESS = {
    "resize_shortest_edge": 256,
    "crop": 224,
    "resample": "bicubic",
    "mean": [0.485, 0.456, 0.406],
    "std": [0.229, 0.224, 0.225],
    "output": "cls_token",
}

# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #


def warn(msg: str) -> None:
    print(f"[warn] {msg}", file=sys.stderr)


def die(msg: str, code: int = 2) -> "NoReturn":  # noqa: F821 - annotation only
    print(f"[error] {msg}", file=sys.stderr)
    raise SystemExit(code)


def iso8601_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def canonical_json(obj) -> str:
    """Canonical form used for the manifest `generation` digest."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def manifest_generation(manifest: dict) -> str:
    body = {k: v for k, v in manifest.items() if k != "generation"}
    return sha256_bytes(canonical_json(body).encode("utf-8"))


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def resolve_local_file(basename: str, candidates, override, out_dir: Path, extra_roots=()):
    """First existing candidate wins; otherwise a bounded basename search.

    Returns (path, searched) where path is None when nothing was found.
    """
    searched = []
    ordered = []
    if override:
        ordered.append(Path(override))
    for cand in candidates:
        p = Path(cand)
        ordered.append(p if p.is_absolute() else REPO_ROOT / p)
    if out_dir is not None:
        ordered.append(Path(out_dir) / basename)

    for p in ordered:
        searched.append(str(p))
        if p.is_file():
            return p.resolve(), searched

    roots = list(SEARCH_ROOTS) + [str(r) for r in extra_roots]
    for root in roots:
        base = Path(root) if Path(root).is_absolute() else REPO_ROOT / root
        p = base / basename
        searched.append(str(p))
        if p.is_file():
            return p.resolve(), searched
    return None, searched


def measure(path: Path):
    """(bytes, sha256) for a real file — the only way these numbers are produced."""
    return path.stat().st_size, sha256_file(path)


# --------------------------------------------------------------------------- #
# Specificity (single source of truth lives in augury_funnel / junk_keys)
# --------------------------------------------------------------------------- #

_GENUS_BUCKET_RE = re.compile(r"\bspp\.?$", re.I)


def _fallback_classify_specificity(key: str) -> str:
    try:
        from junk_keys import JUNK_KEYS  # type: ignore
    except ImportError:  # pragma: no cover - defensive
        JUNK_KEYS = frozenset()
    k = (key or "").strip()
    if k.lower() in JUNK_KEYS:
        return "junk"
    if _GENUS_BUCKET_RE.search(k):
        return "genus_bucket"
    return "exact_species"


def _load_classify_specificity():
    try:
        from augury_funnel import classify_specificity  # type: ignore

        return classify_specificity, "augury_funnel.classify_specificity"
    except Exception as exc:  # pragma: no cover - defensive
        warn(
            "could not import classify_specificity from scripts/augury_funnel.py "
            f"({type(exc).__name__}: {exc}); using the local replication of the rule"
        )
        return _fallback_classify_specificity, "local replication"


# --------------------------------------------------------------------------- #
# Species facts
# --------------------------------------------------------------------------- #


def ordered_regions(region_names) -> list:
    """Preferred order first (AU leads), then anything else, alphabetically."""
    names = list(dict.fromkeys(region_names))
    preferred = [r for r in PREFERRED_REGION_ORDER if r in names]
    extra = sorted(r for r in names if r not in PREFERRED_REGION_ORDER)
    return preferred + extra


def display_scientific_name(name):
    """Capitalise the genus for display, without touching the source DB.

    29 species in `database-merged.json` carry an all-lowercase scientific name
    (`banksia spp`, `allocasuarina verticillata`, `atriplex nummularia`). They are
    correct as *keys*, but they read as broken to a non-technical user in a
    picker, so the display copy is fixed here rather than by editing the DB.

    Deliberately a DISPLAY-ONLY fix: the source database stays byte-identical
    because it is hashed into published artifacts and feeds the training corpus.
    Same reasoning as `scripts/junk_keys.py` (filter at parse time, never rewrite
    a published artifact).
    """
    if not isinstance(name, str) or not name.strip():
        return name
    tokens = name.split()
    if not tokens:
        return name
    head = tokens[0]
    # Only a lowercase-initial ASCII letter needs fixing; leave "spp" plural
    # markers and any non-ASCII name untouched.
    if head[:1].islower():
        tokens[0] = head[0].upper() + head[1:]
    return " ".join(tokens)


def pick_common_name(rec: dict):
    """Choose the vernacular name to ship, or `None` if the record has none.

    `common_names[0]` is NOT the vernacular name. For 1,961 of the 2,256 records
    the first entry simply repeats the binomial (`['Geranium phaeum']`), while a
    later entry carries the name a farmer actually types. Taking `[0]` silently
    dropped the vernacular name for **14 Australian species**, including several
    of the most-searched weeds in the country:

        nassella trichotoma  -> 'serrated tussock', 'Yass River tussock'
        lolium rigidum       -> 'annual ryegrass', 'rigid ryegrass'
        alternanthera philoxeroides -> 'alligator weed'
        bromus diandrus      -> 'great brome', 'ripgut brome'
        salvinia molesta     -> 'salvinia', 'giant salvinia'
        juncus bufonius      -> 'Toad rush'
        rumex obtusifolius   -> 'Broad-leaved dock'

    A picker-first product cannot afford that: searching "serrated tussock"
    returned nothing while the row sat in the database. Preference order is

      1. the first differing name that carries no parenthetical
         (`'alligator weed'`, `'serrated tussock'`),
      2. otherwise the first differing name, with a trailing
         `(<scientific name>)` removed when that is exactly what the
         parenthetical contains (`'Broad-leaved dock (Rumex obtusifolius)'`
         -> `'Broad-leaved dock'`),
      3. otherwise the first non-empty name, parenthetical and all,
      4. otherwise `None`.

    Everything else is left byte-for-byte as the source has it: stripping
    arbitrary parentheticals would be a data edit, and this script makes none.
    """
    names = [n.strip() for n in (rec.get("common_names") or []) if isinstance(n, str) and n.strip()]
    if not names:
        return None

    sci = (rec.get("scientific_name") or "").strip()
    sci_cf = sci.casefold()
    differing = [n for n in names if n.casefold() != sci_cf]
    if not differing:
        return names[0]

    plain = [n for n in differing if "(" not in n]
    if plain:
        return plain[0]

    candidate = differing[0]
    suffix = f"({sci_cf})"
    if sci and candidate.casefold().endswith(suffix):
        stripped = candidate[: -len(suffix)].strip()
        if stripped:
            return stripped
    return candidate


def has_vernacular_name(rec: dict) -> bool:
    """True when the record carries a name that is not just its own binomial.

    This is the metric the docs should quote. Counting a non-empty
    `common_names` field overstates coverage roughly tenfold: 2,188 of 2,256
    records have one, but only 227 carry a genuine vernacular name.
    """
    return pick_common_name(rec) is not None and any(
        isinstance(n, str)
        and n.strip()
        and n.strip().casefold() != (rec.get("scientific_name") or "").strip().casefold()
        for n in (rec.get("common_names") or [])
    )


def build_species_entries(db: dict, classify) -> tuple:
    entries = []
    for key, rec in db.items():
        rec = rec if isinstance(rec, dict) else {}
        regions_map = rec.get("regions") or {}

        out_regions = []
        has_indicators = False
        for region in ordered_regions(regions_map.keys()):
            region_val = regions_map.get(region) or {}
            indicators = region_val.get("indicators") or {}
            if indicators:
                has_indicators = True
            # VERBATIM passthrough: keys, values and insertion order untouched.
            out_regions.append({"region": region, "indicators": dict(indicators)})

        common_name = pick_common_name(rec)

        entries.append(
            {
                "key": key,
                "common_name": common_name,
                "scientific_name": display_scientific_name(rec.get("scientific_name")),
                "specificity": classify(key),
                "has_indicators": has_indicators,
                "regions": out_regions,
            }
        )

    def sort_key(entry):
        au_first = 0 if any(r["region"] == "Australia" for r in entry["regions"]) else 1
        name = entry["common_name"] or entry["key"]
        return (au_first, name.casefold(), entry["key"])

    entries.sort(key=sort_key)
    regions = ordered_regions(
        r for rec in db.values() if isinstance(rec, dict) for r in (rec.get("regions") or {})
    )
    return entries, regions


def indicator_key_histogram(entries: list) -> dict:
    hist: dict = {}
    for entry in entries:
        for region in entry["regions"]:
            for k in region["indicators"]:
                hist[k] = hist.get(k, 0) + 1
    return dict(sorted(hist.items(), key=lambda kv: (-kv[1], kv[0])))


def audit_against_species_list(db: dict, entries: list, species_list, out=print) -> dict:
    """Cross-check the DB (output universe) against the vision species list."""
    sl_keys = {e.get("key") for e in species_list if isinstance(e, dict)}
    db_keys = set(db)
    sl_au = {
        e.get("key")
        for e in species_list
        if isinstance(e, dict)
        and any(
            (r.get("region") if isinstance(r, dict) else r) == "Australia"
            for r in (e.get("regions") or [])
        )
    }
    # "w/ common name" below means a GENUINE vernacular name, not merely a
    # non-empty `common_names` field: those are not the same thing, and conflating
    # them is how "185 of 188 AU species have real common names" got into the docs
    # when the true figure was 161 of 221. See `pick_common_name()`.
    sl_by_key = {e.get("key"): e for e in species_list if isinstance(e, dict)}
    sl_au_cn = {k for k in sl_au if has_vernacular_name(sl_by_key.get(k) or {})}
    out_au = {e["key"] for e in entries if any(r["region"] == "Australia" for r in e["regions"])}
    out_au_cn = {
        e["key"]
        for e in entries
        if e["key"] in out_au and e["common_name"]
    }
    db_by_key = {k: v for k, v in db.items() if isinstance(v, dict)}
    out_au_vernacular = {k for k in out_au if has_vernacular_name(db_by_key.get(k) or {})}
    report = {
        "db_keys": len(db_keys),
        "species_list_keys": len(sl_keys),
        "db_only_keys": sorted(db_keys - sl_keys),
        "species_list_only_keys": sorted(sl_keys - db_keys),
        "species_list_au": len(sl_au),
        "species_list_au_with_common_name": len(sl_au_cn),
        "output_au": len(out_au),
        "output_au_with_common_name": len(out_au_cn),
        "output_au_with_vernacular_name": len(out_au_vernacular),
        "output_au_missing_vernacular_name": sorted(out_au - out_au_vernacular),
        "au_in_db_not_in_species_list": sorted(out_au - sl_au),
        "au_stale_in_species_list": sorted(
            k for k in (out_au - sl_au) if k in sl_keys
        ),
    }
    report["au_absent_from_species_list"] = sorted(
        k for k in report["au_in_db_not_in_species_list"] if k not in sl_keys
    )
    out("")
    out("  cross-check vs data/vision/species_list.json (vision universe — audit only)")
    out(
        f"    species_list keys .............. {report['species_list_keys']}"
        f"   (AU {report['species_list_au']}, AU w/ common name {report['species_list_au_with_common_name']})"
    )
    out(
        f"    DB keys (output universe) ...... {report['db_keys']}"
        f"   (AU {report['output_au']}, AU w/ a name {report['output_au_with_common_name']}, "
        f"AU w/ a genuine vernacular name {report['output_au_with_vernacular_name']})"
    )
    if report["output_au_missing_vernacular_name"]:
        out(
            f"    AU with no vernacular name ..... "
            f"{len(report['output_au_missing_vernacular_name'])} (the picker can still "
            f"reach these by scientific name)"
        )
    out(f"    species_list-only keys ......... {len(report['species_list_only_keys'])}")
    out(f"    DB-only keys ................... {len(report['db_only_keys'])}")
    out(
        f"    AU delta ....................... +{len(report['au_in_db_not_in_species_list'])}"
        f" = {len(report['au_absent_from_species_list'])} keys absent from species_list"
        f" + {len(report['au_stale_in_species_list'])} keys the species_list carries without an AU region"
    )
    if report["au_absent_from_species_list"]:
        out(f"      absent from species_list ({len(report['au_absent_from_species_list'])}): "
            + ", ".join(report["au_absent_from_species_list"]))
    if report["au_stale_in_species_list"]:
        out(f"      stale in species_list ({len(report['au_stale_in_species_list'])}): "
            + ", ".join(report["au_stale_in_species_list"]))
    return report


# --------------------------------------------------------------------------- #
# Hugging Face revisions
# --------------------------------------------------------------------------- #


def hf_revisions(repos, overrides: dict, offline: bool, out=print) -> tuple:
    """Resolve repo head revisions. Returns ({repo: sha|None}, {repo: reason})."""
    resolved = {}
    reasons = {}
    cache: dict = {}
    api = None
    if not offline:
        try:
            from huggingface_hub import HfApi

            api = HfApi()
        except Exception as exc:
            warn(f"huggingface_hub unavailable ({type(exc).__name__}: {exc}); all revisions null")
            api = None

    for repo in repos:
        if repo in overrides:
            resolved[repo] = overrides[repo]
            reasons[repo] = "CLI override"
            continue
        if repo in cache:
            resolved[repo], reasons[repo] = cache[repo]
            continue
        if offline or api is None:
            resolved[repo] = None
            reasons[repo] = "offline mode — lookup skipped"
            cache[repo] = (None, reasons[repo])
            continue
        sha, reason = None, None
        for kind in ("model", "dataset"):
            try:
                info = (
                    api.model_info(repo, files_metadata=True)
                    if kind == "model"
                    else api.dataset_info(repo, files_metadata=True)
                )
                sha = info.sha
                reason = f"HF {kind} repo head"
                break
            except Exception as exc:
                reason = f"{type(exc).__name__}: {str(exc).splitlines()[0][:140]}"
        resolved[repo] = sha
        reasons[repo] = reason
        cache[repo] = (sha, reason)
    for repo, sha in resolved.items():
        if sha is None:
            warn(f"revision unresolved for {repo} — {reasons[repo]}; emitting null")
        else:
            out(f"    revision {repo} = {sha}   ({reasons[repo]})")
    return resolved, reasons


# --------------------------------------------------------------------------- #
# Build
# --------------------------------------------------------------------------- #


def build_manifest(args, out_dir: Path, facts_path: Path) -> tuple:
    index_dir = Path(args.index_dir)
    if not index_dir.is_absolute():
        index_dir = REPO_ROOT / index_dir
    meta_path = index_dir / "meta.json"
    if not meta_path.is_file():
        die(f"vision index meta not found: {meta_path}")
    meta = load_json(meta_path)

    band_path = None
    for name in BAND_FILENAMES:
        if (index_dir / name).is_file():
            band_path = index_dir / name
            break
    if band_path is None:
        die(f"no band calibration found in {index_dir} (looked for {', '.join(BAND_FILENAMES)})")
    bands_raw = load_json(band_path)

    unresolved = []

    def problem(field: str, why: str) -> None:
        unresolved.append((field, why))

    # ---- local artifacts: measured, never invented -------------------------- #
    # A template-only publication (--no-formatter) omits the formatter entirely:
    # the story is rendered by the deterministic template, so there is no 688 MB
    # GGUF to download. Absence is a decision, not an unresolved field, so it
    # must not be reported as "incomplete".
    include_formatter = not getattr(args, "no_formatter", False)
    print("  measuring local artifacts (sha256 over real bytes)")
    if include_formatter:
        formatter_local, formatter_searched = resolve_local_file(
            Path(FORMATTER_PATH).name, FORMATTER_CANDIDATES, args.formatter_gguf, out_dir
        )
    else:
        formatter_local, formatter_searched = None, []
        print("    formatter: omitted (--no-formatter: template-only publication)")
    index_tar_local, index_tar_searched = resolve_local_file(
        VISION_INDEX_PATH, INDEX_CANDIDATES, args.index_tar, out_dir
    )
    encoder_local, encoder_searched = resolve_local_file(
        ENCODER_PATH, ENCODER_CANDIDATES, args.encoder_onnx, out_dir
    )

    def measure_or_null(local, field_prefix, searched):
        if local is None:
            problem(f"{field_prefix}.bytes", "local file not found")
            problem(f"{field_prefix}.sha256", "local file not found")
            return None, None
        nbytes, digest = measure(local)
        print(f"    {field_prefix}: {local}  {nbytes} bytes  sha256={digest}")
        return nbytes, digest

    fmt_bytes, fmt_sha = (
        measure_or_null(formatter_local, "formatter", formatter_searched)
        if include_formatter else (None, None)
    )
    idx_bytes, idx_sha = measure_or_null(index_tar_local, "vision.index", index_tar_searched)
    enc_bytes, enc_sha = measure_or_null(encoder_local, "vision.encoders[0]", encoder_searched)

    # The published formatter is the same file we just hashed: cross-check it
    # against the Hub's LFS metadata when we can, so a stale local copy is caught.
    if include_formatter and formatter_local is not None and not args.offline:
        try:
            from huggingface_hub import HfApi

            info = HfApi().model_info(FORMATTER_REPO, files_metadata=True)
            for sib in info.siblings or []:
                if sib.rfilename == FORMATTER_PATH and sib.lfs is not None:
                    if sib.lfs.sha256 == fmt_sha:
                        print(f"    [ok] local GGUF matches the Hub LFS sha256 for {FORMATTER_REPO}/{FORMATTER_PATH}")
                    else:
                        warn(
                            "local GGUF differs from the Hub LFS object for "
                            f"{FORMATTER_REPO}/{FORMATTER_PATH}: local={fmt_sha} hub={sib.lfs.sha256}"
                        )
                    if sib.size is not None and sib.size != fmt_bytes:
                        warn(f"local GGUF size {fmt_bytes} != Hub size {sib.size}")
                    break
            else:
                warn(f"{FORMATTER_PATH} not found in {FORMATTER_REPO} (or has no LFS metadata)")
        except Exception as exc:
            warn(f"Hub cross-check of {FORMATTER_REPO}/{FORMATTER_PATH} failed: {type(exc).__name__}: {exc}")

    facts_bytes = facts_path.stat().st_size
    facts_sha = sha256_file(facts_path)
    print(f"    facts: {facts_path}  {facts_bytes} bytes  sha256={facts_sha}")

    # ---- revisions ---------------------------------------------------------- #
    print("  resolving HF revisions")
    repos = ([FORMATTER_REPO] if include_formatter else []) + [
        FACTS_REPO, VISION_INDEX_REPO, ENCODER_REPO
    ]
    revisions, _reasons = hf_revisions(repos, args.revision, args.offline)
    for repo, field in (
        (FACTS_REPO, "facts.revision"),
        (VISION_INDEX_REPO, "vision.index.revision"),
        (ENCODER_REPO, "vision.encoders[0].revision"),
    ):
        if revisions.get(repo) is None:
            problem(field, f"HF lookup failed for {repo}")

    def gen12(digest, field):
        if digest is None:
            problem(f"{field}.generation", "derived from a null sha256")
            return None
        return digest[:12]

    formatter_entry = None
    if include_formatter:
        formatter_entry = {
            "protocol": FORMATTER_PROTOCOL,
            # The GGUF is published to a *model* repo; HF resolves model repos
            # with NO path prefix, while datasets use /datasets. The app builds
            # its download URL from this field, so omitting it makes the very
            # first (688 MB) download 401.
            "repo_type": "model",
            "repo": FORMATTER_REPO,
            "path": FORMATTER_PATH,
            "revision": revisions.get(FORMATTER_REPO),
            "bytes": fmt_bytes,
            "sha256": fmt_sha,
            "generation": gen12(fmt_sha, "formatter"),
        }

    manifest = {
        "manifest_schema": 1,
        "generated": args.generated,
        "generation": None,  # filled in below
        # Absent for a template-only publication (--no-formatter). The app treats
        # a missing formatter as a complete product and renders the deterministic
        # template; it is not an "app update required" condition.
        **({"formatter": formatter_entry} if formatter_entry is not None else {}),
        "facts": {
            "protocol": FACTS_PROTOCOL,
            "schema": FACTS_SCHEMA,
            "repo_type": "dataset",
            "repo": FACTS_REPO,
            "path": FACTS_PATH,
            "revision": revisions.get(FACTS_REPO),
            "bytes": facts_bytes,
            "sha256": facts_sha,
            "generation": gen12(facts_sha, "facts"),
        },
        "vision": {
            "index": {
                "protocol": VISION_PROTOCOL,
                "schema": VISION_INDEX_SCHEMA,
                "repo_type": "dataset",
                "repo": VISION_INDEX_REPO,
                "path": VISION_INDEX_PATH,
                "revision": revisions.get(VISION_INDEX_REPO),
                "bytes": idx_bytes,
                "sha256": idx_sha,
                "backend": meta.get("backend"),
                "vectors": meta.get("vectors"),
                "dim": meta.get("dim"),
                "species": meta.get("species"),
                "generation": gen12(idx_sha, "vision.index"),
            },
            "encoders": [
                {
                    "backend": meta.get("backend"),
                    "protocol": VISION_PROTOCOL,
                    "repo_type": "dataset",
                    "repo": ENCODER_REPO,
                    "path": ENCODER_PATH,
                    "revision": revisions.get(ENCODER_REPO),
                    "bytes": enc_bytes,
                    "sha256": enc_sha,
                    "quant": ENCODER_QUANT,
                    "generation": gen12(enc_sha, "vision.encoders[0]"),
                }
            ],
            "bands": {
                # JSON round-trip noise only: the file stores 0.6800000000000004 /
                # 0.4300000000000001; the published protocol values are 0.68 / 0.43.
                "auto_conf": round(float(bands_raw["auto_conf"]), 6),
                "confirm_conf": round(float(bands_raw["confirm_conf"]), 6),
                "source": f"{index_dir.name} {band_path.name}",
            },
            "preprocess": dict(PREPROCESS),
        },
    }
    for field in ("backend", "vectors", "dim", "species"):
        if manifest["vision"]["index"][field] is None:
            problem(f"vision.index.{field}", f"missing in {meta_path}")
    if not all(isinstance(v, int) for v in (meta.get("vectors"), meta.get("dim"), meta.get("species"))):
        warn(f"non-integer index meta values in {meta_path}: { {k: meta.get(k) for k in ('vectors','dim','species')} }")
    manifest["generation"] = manifest_generation(manifest)
    return manifest, unresolved


def cmd_build(args) -> int:
    db_path = Path(args.db)
    if not db_path.is_absolute():
        db_path = REPO_ROOT / db_path
    sl_path = Path(args.species_list)
    if not sl_path.is_absolute():
        sl_path = REPO_ROOT / sl_path
    for p in (db_path, sl_path):
        if not p.is_file():
            die(f"input not found: {p}")

    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = Path.cwd() / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[build] {db_path}")
    db = load_json(db_path)
    if not isinstance(db, dict):
        die(f"expected a JSON object of species keyed by name, got {type(db).__name__}")

    print(f"[build] {sl_path}")
    species_list = load_json(sl_path)
    if not isinstance(species_list, list):
        die(f"expected a JSON array, got {type(species_list).__name__}")

    classify, classify_src = _load_classify_specificity()
    print(f"[build] specificity rule: {classify_src}")

    entries, regions = build_species_entries(db, classify)

    facts = {
        "schema": 1,
        "generated": args.generated,
        "regions": regions,
        "species": entries,
    }
    expected = [r for r in PREFERRED_REGION_ORDER if r in regions]
    if len(regions) != len(expected):
        warn(
            "region set differs from the published schema example "
            f"(['Australia', 'UK', 'Europe']): got {regions}"
        )

    facts_bytes = json.dumps(facts, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    facts_path = out_dir / FACTS_PATH
    facts_path.write_bytes(facts_bytes)

    hist = indicator_key_histogram(entries)
    with_indicators = sum(1 for e in entries if e["has_indicators"])
    au = sum(1 for e in entries if any(r["region"] == "Australia" for r in e["regions"]))
    specs: dict = {}
    for e in entries:
        specs[e["specificity"]] = specs.get(e["specificity"], 0) + 1

    print("")
    print("  augury-ondevice.json")
    print(f"    path .......................... {facts_path}")
    print(f"    bytes ......................... {len(facts_bytes)}")
    print(f"    sha256 ........................ {sha256_bytes(facts_bytes)}")
    print(f"    species ....................... {len(entries)}")
    print(f"    has_indicators true ........... {with_indicators}")
    print(f"    has_indicators false .......... {len(entries) - with_indicators}")
    print(f"    Australia-region species ...... {au}")
    print(f"    specificity ................... {specs}")
    print(f"    distinct indicator keys ....... {len(hist)}")
    for k, n in hist.items():
        print(f"        {k!r}: {n}")
    print(f"    acacia nilotica common_name ... {next((e['common_name'] for e in entries if e['key'] == 'acacia nilotica'), None)!r}")

    audit_against_species_list(db, entries, species_list)

    manifest, unresolved = build_manifest(args, out_dir, facts_path)
    manifest_bytes = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    (out_dir / "manifest.json").write_bytes(manifest_bytes)

    print("")
    print("  manifest.json")
    print(f"    path .......................... {out_dir / 'manifest.json'}")
    print(f"    bytes ......................... {len(manifest_bytes)}")
    print(f"    generation .................... {manifest['generation']}")
    print(f"    bands ......................... auto={manifest['vision']['bands']['auto_conf']} "
          f"confirm={manifest['vision']['bands']['confirm_conf']} "
          f"source={manifest['vision']['bands']['source']!r}")
    print(f"    index ......................... vectors={manifest['vision']['index']['vectors']} "
          f"dim={manifest['vision']['index']['dim']} species={manifest['vision']['index']['species']} "
          f"backend={manifest['vision']['index']['backend']}")

    if unresolved:
        print("")
        print("  " + "!" * 74)
        print("  !!! UNRESOLVED MANIFEST FIELDS — emitted as null, NOT fabricated")
        for field, why in unresolved:
            print(f"  !   {field:34s} {why}")
        print("  !   Re-run once the producing agents land their artifacts, or pass")
        print("  !   --index-tar PATH / --encoder-onnx PATH / --revision REPO=SHA.")
        print("  !   --verify treats these nulls as failures (see --allow-unresolved).")
        print("  " + "!" * 74)

    print("")
    print(f"[build] wrote {facts_path} and {out_dir / 'manifest.json'}")
    if args.strict and unresolved:
        print(f"[build] --strict: {len(unresolved)} unresolved field(s)", file=sys.stderr)
        return 1
    return 0


# --------------------------------------------------------------------------- #
# Verify
# --------------------------------------------------------------------------- #


def _verify_entry(name, entry, out_dir, args, failures, notes):
    """Check one manifest artifact record. Returns list of unresolved field names."""
    unresolved = []
    recorded_bytes = entry.get("bytes")
    recorded_sha = entry.get("sha256")
    path = entry.get("path")
    if entry.get("revision") is None:
        unresolved.append(f"{name}.revision")
    if recorded_bytes is None:
        unresolved.append(f"{name}.bytes")
    if recorded_sha is None:
        unresolved.append(f"{name}.sha256")

    if name == "facts":
        local = out_dir / FACTS_PATH
        if not local.is_file():
            local = None
    else:
        override = {
            "formatter": args.formatter_gguf,
            "vision.index": args.index_tar,
            "vision.encoders[0]": args.encoder_onnx,
        }.get(name)
        candidates = {
            "formatter": FORMATTER_CANDIDATES,
            "vision.index": INDEX_CANDIDATES,
            "vision.encoders[0]": ENCODER_CANDIDATES,
        }[name]
        local, _ = resolve_local_file(path, candidates, override, out_dir)

    if local is None:
        if recorded_sha is None:
            notes.append(f"{name}: local file not found and manifest field is null")
        else:
            failures.append(f"{name}: local file not found (manifest says {path!r}, sha256 {recorded_sha[:12]}…)")
        return unresolved

    nbytes, digest = measure(local)
    if recorded_sha is None:
        notes.append(
            f"{name}: manifest field is null but a local file now exists at {local} "
            f"({nbytes} bytes, sha256 {digest[:12]}…) — regenerate the manifest"
        )
    else:
        if digest != recorded_sha:
            failures.append(f"{name}: sha256 drift — manifest {recorded_sha} vs local {digest} ({local})")
        if recorded_bytes is not None and nbytes != recorded_bytes:
            failures.append(f"{name}: bytes drift — manifest {recorded_bytes} vs local {nbytes} ({local})")
        if digest == recorded_sha and nbytes == recorded_bytes:
            print(f"  [ok]   {name:20s} {nbytes:>10} bytes  sha256={digest[:12]}…  {local}")
    return unresolved


def cmd_verify(args) -> int:
    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = Path.cwd() / out_dir
    manifest_path = out_dir / "manifest.json"
    if not manifest_path.is_file():
        die(f"manifest not found: {manifest_path}")

    manifest = load_json(manifest_path)
    print(f"[verify] {manifest_path}")
    failures: list = []
    notes: list = []

    if manifest.get("manifest_schema") != 1:
        failures.append(f"manifest_schema is {manifest.get('manifest_schema')!r}, expected 1")

    recomputed = manifest_generation(manifest)
    if recomputed != manifest.get("generation"):
        failures.append(
            f"generation digest mismatch — manifest {manifest.get('generation')!r} vs recomputed {recomputed} "
            "(the manifest was edited after generation)"
        )
    else:
        print(f"  [ok]   generation          {recomputed}")

    unresolved: list = []
    vision = manifest.get("vision") or {}
    checks: list = []
    if manifest.get("formatter"):
        checks.append(("formatter", manifest["formatter"]))
    else:
        # A template-only publication legitimately omits the formatter — the story
        # is rendered by the deterministic template. Absence is a product
        # decision, not an unresolved field, so it must not fail verification.
        print("  [ok]   formatter           absent (template-only publication)")
    checks.append(("facts", manifest.get("facts") or {}))
    checks.append(("vision.index", vision.get("index") or {}))
    for i, enc in enumerate(vision.get("encoders") or []):
        checks.append((f"vision.encoders[{i}]", enc or {}))

    for name, entry in checks:
        unresolved += _verify_entry(name, entry, out_dir, args, failures, notes)

    print("")
    for note in notes:
        warn(note)
    if unresolved:
        label = "UNRESOLVED (null) FIELDS"
        print("")
        print(f"  {label}:")
        for field in unresolved:
            print(f"    - {field}")
        if args.allow_unresolved:
            warn(f"--allow-unresolved: {len(unresolved)} null field(s) accepted as incomplete (NOT verified)")
        else:
            failures.append(
                f"{len(unresolved)} unresolved null field(s): {', '.join(unresolved)} "
                "(pass --allow-unresolved to accept an incomplete manifest)"
            )

    print("")
    if failures:
        print(f"[verify] FAILED — {len(failures)} problem(s):")
        for f in failures:
            print(f"  - {f}")
        return 1
    checked = sum(1 for _, e in checks if e.get("sha256"))
    print(f"[verify] PASSED — {checked} artifact hash(es) match, generation digest intact")
    if unresolved:
        print(f"[verify] (incomplete: {len(unresolved)} unresolved field(s) accepted via --allow-unresolved)")
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Build the AUGURY on-device bundle (species facts + update manifest) for HF."
    )
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="output directory (default: data/app)")
    ap.add_argument("--db", default=str(DEFAULT_DB), help="species DB (source of truth for indicators)")
    ap.add_argument("--species-list", default=str(DEFAULT_SPECIES_LIST), help="vision species_list.json")
    ap.add_argument("--index-dir", default=str(DEFAULT_INDEX_DIR), help="vision index-v3 directory")
    ap.add_argument("--formatter-gguf", default=None, help="override local GGUF path")
    ap.add_argument(
        "--no-formatter",
        action="store_true",
        help="omit the formatter GGUF entirely — a template-only publication "
             "(the story is rendered deterministically; no 688 MB download)",
    )
    ap.add_argument("--index-tar", default=None, help="override local vision index tarball path")
    ap.add_argument("--encoder-onnx", default=None, help="override local encoder ONNX path")
    ap.add_argument(
        "--revision",
        action="append",
        default=[],
        metavar="REPO=SHA",
        help="pin an HF revision instead of querying the Hub (repeatable)",
    )
    ap.add_argument("--generated", default=None, help="override the ISO8601 generated timestamp")
    ap.add_argument("--offline", action="store_true", help="skip all Hub lookups (revisions become null)")
    ap.add_argument("--strict", action="store_true", help="exit non-zero if any manifest field is unresolved")
    ap.add_argument("--verify", action="store_true", help="verify an existing manifest instead of building")
    ap.add_argument(
        "--allow-unresolved",
        action="store_true",
        help="--verify only: accept null (unresolved) fields as incomplete instead of failing",
    )
    args = ap.parse_args(argv)

    overrides = {}
    for item in args.revision:
        if "=" not in item:
            die(f"--revision expects REPO=SHA, got {item!r}")
        repo, sha = item.split("=", 1)
        overrides[repo.strip()] = sha.strip()
    args.revision = overrides

    if args.generated is None:
        args.generated = iso8601_now()

    if args.verify:
        return cmd_verify(args)
    return cmd_build(args)


if __name__ == "__main__":
    raise SystemExit(main())

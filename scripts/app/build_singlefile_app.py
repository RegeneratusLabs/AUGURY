#!/usr/bin/env python3
"""AUGURY — build_singlefile_app.py

BUILD-TIME tool. Produces `augury.html`: one self-contained page that names a
weed and reads the soil from it. No model, no network, no install.

    scripts/app/singlefile/app_template.html   the shell (CSS + markup)
    scripts/app/singlefile/app.js              the logic (search + render)
    data/research/database-merged.json         the facts (source of truth)
    data/research/common_name_synonyms.json    curated vernacular names
    data/vision/canonical_map.json             duplicate keys -> one plant

The template and the script stay separate files because they are cheap to read
and edit; the *artefact* is the single HTML file they produce, with the whole
database and both assets inlined. It opens from `file://` with no server.

What this builder adds that the on-device bundle does not carry:

  * **Per-data-point provenance.** `database-merged.json` records source names,
    URLs and which indicator each was read for (33 species today); nutrient
    claims each carry their own source and confidence; and many Australian
    evidence strings name their source in the text. All of it is extracted here
    and attached to the reading, so the app can say where a row came from.
  * **A declared lineage per region.** For the majority of rows the database
    does *not* record a per-row source. Rather than imply one, the builder
    labels those rows "pipeline default" and states the region's documented
    lineage (Ellenberg for Europe; Maughan & Amos + CAWR for the UK; the
    Australian research/mining layer for AU).
  * **The database identity.** sha256, byte count and species counts are
    measured from the file being embedded, never written by hand.

Usage:
    python3 scripts/app/build_singlefile_app.py
    python3 scripts/app/build_singlefile_app.py --out augury.html
    python3 scripts/app/build_singlefile_app.py --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from junk_keys import JUNK_KEYS  # type: ignore  # noqa: E402

DEFAULT_DB = ROOT / "data" / "research" / "database-merged.json"
DEFAULT_SYNONYMS = ROOT / "data" / "research" / "common_name_synonyms.json"
DEFAULT_CANONICAL = ROOT / "data" / "vision" / "canonical_map.json"
DEFAULT_TEMPLATE = ROOT / "scripts" / "app" / "singlefile" / "app_template.html"
DEFAULT_JS = ROOT / "scripts" / "app" / "singlefile" / "app.js"
DEFAULT_OUT = ROOT / "augury.html"

# --------------------------------------------------------------------------- #
# Source registry
# --------------------------------------------------------------------------- #

# Canonical names + the spellings that occur in the evidence text. Canonical
# names for the Australian layer are taken verbatim from the database's own
# `provenance.sources` names where those exist, so a chip that links a URL and a
# chip detected in body text read as the same organisation.
#
# A curated URL is written here ONLY when it is the organisation's own stable
# landing page. Everything else resolves through `provenance.sources`, which
# carries the exact document URL the researcher used. A source with no known URL
# renders as a plain (unlinked) chip rather than a guessed link.
CURATED_SOURCES: list[tuple[str, list[str], str | None]] = [
    ("NSW WeedWise (NSW DPIRD)", ["NSW DPIRD", "NSW WeedWise", "NSW DPI Primefact", "NSW DPI"],
     "https://weeds.dpi.nsw.gov.au/"),
    ("Weeds Australia (CISS)", ["Weeds Australia"], "https://weeds.org.au/"),
    ("HerbiGuide (AU)", ["HerbiGuide"], "https://www.herbiguide.com.au/"),
    ("AWRI (Australian Wine Research Institute)", ["AWRI"],
     "https://www.awri.com.au/industry_support/viticulture/weed-management/"),
    ("GRDC", ["GRDC"], "https://grdc.com.au/"),
    ("PIRSA", ["PIRSA"], "https://www.pir.sa.gov.au/"),
    ("Agriculture Victoria", ["Agriculture Victoria"], None),
    ("Queensland DAF", ["Queensland DAF", "QLD DAF", "Queensland Department of Agriculture"], None),
    ("Landscape South Australia", ["Landscape South Australia", "Landscape Board"], None),
    ("WeedScan (CISS)", ["WeedScan"], None),
    ("Flora SA", ["Flora SA"], None),
    ("WA DWER", ["WA DWER", "Department of Water and Environmental Regulation"], None),
    ("Victorian Weed Risk Assessment (VRO archive)", ["Victorian Weed Risk Assessment", "VRO archive"], None),
    ("Parsons & Cuthbertson (1992)", ["Parsons & Cuthbertson"], None),
    ("Ellenberg Indicator Values (1991)", ["Ellenberg"], None),
    ("Maughan & Amos (2022, 2024)", ["Maughan", "Amos"], None),
    ("CAWR Bioindicators Field Guide", ["CAWR"], None),
    ("Walters, Weeds: Control Without Poisons (1999)", ["Walters"], None),
    ("Pfeiffer, Weeds and What They Tell", ["Pfeiffer"], None),
]

# Documented region lineage. The database does not record a per-row source for
# most rows; this is what the pipeline itself says produced them, and the app
# labels it as a pipeline default rather than passing it off as a citation.
LINEAGE: dict[str, dict] = {
    "Europe": {
        "label": "Ellenberg Indicator Values (1991)",
        "url": None,
        "note": (
            "European rows were converted from the Ellenberg vascular-plant indicator "
            "values in data/sources/Ellenberg_VascularPlants.csv "
            "(scripts/build_ellenberg_dataset.py). Later research and mining passes "
            "added or replaced rows for individual species."
        ),
    },
    "UK": {
        "label": "Maughan & Amos (2022, 2024) · CAWR Bioindicators Field Guide",
        "url": None,
        "note": (
            "UK rows come from the Maughan & Amos bioindicator guides and the CAWR "
            "field guide (scripts/build_maughan_amos_dataset.py)."
        ),
    },
    "Australia": {
        "label": "AUGURY Australian research & mining layer",
        "url": None,
        "note": (
            "Australian rows were compiled from government and extension material — "
            "NSW WeedWise (NSW DPIRD), Weeds Australia (CISS), HerbiGuide, GRDC, PIRSA, "
            "Agriculture Victoria, Landscapes SA, AWRI and others "
            "(scripts/merge_research_indicators.py, scripts/merge_enriched_species.py). "
            "Where a species carries recorded sources, they are listed separately above."
        ),
    },
}


def build_registry(db: dict) -> dict:
    """canonical name -> {u: url}; plus alias -> canonical."""
    registry: dict[str, dict] = {}
    alias: dict[str, str] = {}

    # 1. Recorded provenance: exact document name and URL.
    for rec in db.values():
        if not isinstance(rec, dict):
            continue
        for s in ((rec.get("provenance") or {}).get("sources") or []):
            name = (s.get("name") or "").strip()
            if not name:
                continue
            url = (s.get("url") or "").strip() or None
            cur = registry.setdefault(name, {"u": None})
            if url and not cur["u"]:
                cur["u"] = url

    # 2. Nutrient claim sources: names without URLs.
    for rec in db.values():
        if not isinstance(rec, dict):
            continue
        for c in ((rec.get("nutrients") or {}).get("claims") or []):
            name = (c.get("source") or "").strip()
            if name:
                registry.setdefault(name, {"u": None})

    # 3. Curated organisations and their aliases.
    for canonical, aliases, url in CURATED_SOURCES:
        cur = registry.setdefault(canonical, {"u": None})
        if url and not cur["u"]:
            cur["u"] = url
        for a in aliases:
            alias[a.lower()] = canonical
        alias[canonical.lower()] = canonical

    return {"sources": registry, "alias": alias}


# --------------------------------------------------------------------------- #
# Inline source detection
# --------------------------------------------------------------------------- #

# Only aliases long enough to be unambiguous are matched, and only on a word
# boundary — "Amos" inside "famous" must not register as Maughan & Amos.
MIN_ALIAS = 4


def detect_sources(text: str, alias: dict) -> list[str]:
    """Canonical source names named inside one evidence string, in order."""
    if not text:
        return []
    low = text.lower()
    spans: list[tuple[int, int, str]] = []
    for a, canonical in alias.items():
        if len(a) < MIN_ALIAS:
            continue
        for m in re.finditer(r"(?<![a-z0-9])" + re.escape(a) + r"(?![a-z0-9])", low):
            spans.append((m.start(), m.end(), canonical))
    # Longest alias wins where two overlap ("NSW WeedWise" over "NSW DPI").
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    taken: list[tuple[int, int]] = []
    out: list[str] = []
    for start, end, canonical in spans:
        if any(not (end <= a or start >= b) for a, b in taken):
            continue
        taken.append((start, end))
        if canonical not in out:
            out.append(canonical)
    return out


# --------------------------------------------------------------------------- #
# Record shaping
# --------------------------------------------------------------------------- #


def pick_common_name(rec: dict) -> str | None:
    """The vernacular name a person would actually type, or None.

    Ported from scripts/app/build_ondevice_bundle.py, whose comment explains why
    `common_names[0]` is wrong: for most records it simply repeats the binomial,
    and taking it silently drops the vernacular name.
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


def display_scientific_name(name) -> str:
    """Capitalise a lowercase genus for display; the DB key itself is untouched."""
    if not isinstance(name, str) or not name.strip():
        return name or ""
    tokens = name.split()
    if tokens and tokens[0][:1].islower():
        tokens[0] = tokens[0][0].upper() + tokens[0][1:]
    return " ".join(tokens)


def classify_specificity(key: str) -> str:
    k = (key or "").strip()
    if k.lower() in JUNK_KEYS:
        return "junk"
    if re.search(r"\bspp\.?$", k, re.I):
        return "genus_bucket"
    return "exact_species"


def build_record(key: str, rec: dict, alias: dict) -> dict:
    regions = rec.get("regions") or {}
    out_regions = []
    for region, rv in regions.items():
        inds = (rv or {}).get("indicators") or {}
        if not isinstance(inds, dict) or not inds:
            continue
        # Detect per data point, not per region: a source named in the moisture
        # sentence is evidence for moisture, and attaching it to every row of the
        # region would overstate what was read where.
        src: dict[str, list[str]] = {}
        for ik, iv in inds.items():
            names = detect_sources(str(iv), alias)
            if names:
                src[ik] = names
        out_regions.append({"n": region, "i": dict(inds), "src": src,
                            "l": (rv or {}).get("source") or None})

    # Australia leads, then UK, then Europe, then anything else — the app's
    # audience order, matching the shipped manifest.
    order = ["Australia", "UK", "Europe"]
    out_regions.sort(key=lambda r: (order.index(r["n"]) if r["n"] in order else 9, r["n"]))

    entry: dict = {
        "k": key,
        "s": display_scientific_name(rec.get("scientific_name")),
        "y": classify_specificity(key),
        "r": out_regions,
    }
    common = pick_common_name(rec)
    names = [n.strip() for n in (rec.get("common_names") or []) if isinstance(n, str) and n.strip()]
    if common and common not in names:
        names.insert(0, common)
    if names:
        entry["n"] = names[:6]
    if common:
        entry["c"] = common

    prov = rec.get("provenance") or {}
    srcs = [
        {"n": s.get("name"), "u": s.get("url") or None, "f": s.get("used_for") or []}
        for s in (prov.get("sources") or [])
        if s.get("name")
    ]
    if srcs or prov:
        entry["p"] = {
            "a": prov.get("added_by"),
            "d": prov.get("added_at"),
            "f": prov.get("research_file"),
            "s": srcs,
        }

    claims = []
    for c in ((rec.get("nutrients") or {}).get("claims") or []):
        claim = {"n": c.get("nutrient"), "r": c.get("relationship")}
        if c.get("confidence"):
            claim["c"] = c["confidence"]
        if c.get("source"):
            claim["s"] = c["source"]
        if c.get("detail"):
            claim["d"] = c["detail"]
        claims.append(claim)
    if claims:
        entry["cl"] = claims

    return entry


def sort_key(entry: dict):
    au_first = 0 if any(r["n"] == "Australia" for r in entry["r"]) else 1
    name = entry.get("c") or entry["s"] or entry["k"]
    return (au_first, name.casefold(), entry["k"])


# --------------------------------------------------------------------------- #
# Assemble
# --------------------------------------------------------------------------- #


def build_payload(db: dict, synonyms: dict, canonical: dict, db_path: Path, build_date: str | None = None) -> dict:
    reg = build_registry(db)
    alias = reg["alias"]
    sources = reg["sources"]

    species = []
    with_data = 0
    for key, rec in db.items():
        if not isinstance(rec, dict):
            continue
        entry = build_record(key, rec, alias)
        if entry["r"]:
            # "with indicator data" means a species a user can actually read, so
            # non-species keys (scripts/junk_keys.py) are not counted.
            if entry["y"] != "junk":
                with_data += 1
        species.append(entry)
    species.sort(key=sort_key)

    raw = db_path.read_bytes()
    meta = {
        "db_path": str(db_path.relative_to(ROOT)) if db_path.is_relative_to(ROOT) else str(db_path),
        "db_bytes": len(raw),
        "db_sha256": hashlib.sha256(raw).hexdigest(),
        "species_count": len(species),
        "with_data": with_data,
        "regions": sorted({r["n"] for e in species for r in e["r"]}),
        "build_date": build_date or date.today().isoformat(),
        "source_count": len(sources),
    }

    return {
        "meta": meta,
        "lineage": LINEAGE,
        "sources": sources,
        "synonyms": synonyms,
        "canonical": canonical,
        "junk": sorted(JUNK_KEYS),
        "species": species,
    }


def render(payload: dict, template: str, js: str) -> str:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    # A JSON string can legally contain "</script>", which would end the block.
    data = data.replace("</", "<\\/")
    if "__AUGURY_DATA__" not in template or "__AUGURY_APP__" not in template:
        raise SystemExit("[error] template is missing __AUGURY_DATA__ / __AUGURY_APP__")
    return template.replace("__AUGURY_DATA__", data).replace("__AUGURY_APP__", js)


EXTERNAL_RE = re.compile(
    r"""<(?:script|link|img|iframe|source|video|audio|embed)\b[^>]*?"""
    r"""(?:src|href)\s*=\s*["'](?:https?:)?//""",
    re.I,
)


def check(html: str) -> list[str]:
    """Structural checks that the artefact really is a self-contained page."""
    problems = []
    if "__AUGURY_DATA__" in html or "__AUGURY_APP__" in html:
        problems.append("template placeholders were not substituted")
    if EXTERNAL_RE.search(html):
        problems.append("the page references an external asset (script/link/img/iframe)")
    for banned in ("fetch(", "XMLHttpRequest", "navigator.sendBeacon", "WebSocket("):
        if banned in html:
            problems.append(f"the page contains a network call: {banned}")
    m = re.search(r'<script id="augury-db" type="application/json">(.*?)</script>', html, re.S)
    if not m:
        problems.append("embedded database block not found")
        return problems
    try:
        payload = json.loads(m.group(1).replace("<\\/", "</"))
    except json.JSONDecodeError as exc:
        problems.append(f"embedded database is not valid JSON: {exc}")
        return problems
    if not payload.get("species"):
        problems.append("embedded database has no species")
    if payload.get("meta", {}).get("species_count") != len(payload["species"]):
        problems.append("meta.species_count disagrees with the species array")
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build the AUGURY single-file HTML app.")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--synonyms", default=str(DEFAULT_SYNONYMS))
    ap.add_argument("--canonical", default=str(DEFAULT_CANONICAL))
    ap.add_argument("--template", default=str(DEFAULT_TEMPLATE))
    ap.add_argument("--js", default=str(DEFAULT_JS))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--date", default=None, help="override the build date (YYYY-MM-DD) recorded in the page")
    ap.add_argument("--check", action="store_true", help="build in memory, verify, write nothing")
    args = ap.parse_args(argv)

    db_path = Path(args.db)
    for p in (db_path, Path(args.synonyms), Path(args.canonical), Path(args.template), Path(args.js)):
        if not p.is_file():
            print(f"[error] input not found: {p}", file=sys.stderr)
            return 2

    db = json.loads(db_path.read_text(encoding="utf-8"))
    synonyms_doc = json.loads(Path(args.synonyms).read_text(encoding="utf-8"))
    synonyms = synonyms_doc.get("synonyms") or {}
    canonical_doc = json.loads(Path(args.canonical).read_text(encoding="utf-8"))
    canonical = canonical_doc.get("canonical") or {}

    payload = build_payload(db, synonyms, canonical, db_path, build_date=args.date)
    html = render(payload, Path(args.template).read_text(encoding="utf-8"),
                  Path(args.js).read_text(encoding="utf-8"))

    problems = check(html)
    meta = payload["meta"]
    print("AUGURY single-file app")
    print(f"  database ............... {meta['db_path']}")
    print(f"  species ................ {meta['species_count']}")
    print(f"  with indicator rows .... {meta['with_data']}")
    print(f"  regions ................ {', '.join(meta['regions'])}")
    print(f"  known sources .......... {meta['source_count']}")
    print(f"  vernacular synonyms .... {len(synonyms)}")
    print(f"  html bytes ............. {len(html.encode('utf-8')):,}")
    print(f"  database sha256 ........ {meta['db_sha256']}")
    for p in problems:
        print(f"  [FAIL] {p}", file=sys.stderr)
    if problems:
        return 1
    print("  [ok] self-contained: no external assets, no network calls")

    if args.check:
        print("[check] no file written")
        return 0

    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    out.write_text(html, encoding="utf-8")
    print(f"[build] wrote {out}  ({out.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

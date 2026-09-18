#!/usr/bin/env python3
"""AUGURY third-party test — fetch_test_photos.py

Builds the held-out field-test corpus: fresh photos pulled from the internet
(GBIF occurrence media -> Wikimedia Commons -> iNaturalist) for 20 of
Australia's most common weeds, plus 10 non-weed controls.

Guarantees the test is genuinely third-party and genuinely held out:
  * every downloaded image is SHA-256 checked against the local vision gallery,
    so no test image is already an index member;
  * per-image license + attribution + source URL are recorded;
  * selection is seeded (`--seed`) and resumable (`--resume`).

Outputs (default data/thirdparty/):
  corpus.json / corpus.csv   manifest (species, source, license, hashes)
  photos/<key>/<n>.jpg       downloaded images
  fetch_log.jsonl            every attempt, including rejected candidates

Usage:
  .venv-mcpmv46/bin/python scripts/thirdparty_test/fetch_test_photos.py \
      [--out data/thirdparty] [--seed 20260818] [--resume] [--only key1,key2]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import random
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

UA = "AUGURY-thirdparty-fieldtest/0.1 (local research evaluation)"
TIMEOUT = 45

# ── corpus: 20 common Australian weeds (all present in DB + local index) ──────
WEEDS = [
    ("lantana camara",            "Lantana",             "Lantana camara",            "woody"),
    ("parthenium hysterophorus",  "Parthenium weed",     "Parthenium hysterophorus",  "broadleaf"),
    ("parkinsonia aculeata",      "Parkinsonia",         "Parkinsonia aculeata",      "woody"),
    ("acacia nilotica",           "Prickly acacia",      "Acacia nilotica",           "woody"),
    ("cryptostegia grandiflora",  "Rubber vine",         "Cryptostegia grandiflora",  "woody climber"),
    ("xanthium occidentale",      "Noogoora burr",       "Xanthium occidentale",      "broadleaf"),
    ("conyza bonariensis",        "Fleabane",            "Conyza bonariensis",        "broadleaf"),
    ("arctotheca calendula",      "Capeweed",            "Arctotheca calendula",      "broadleaf"),
    ("raphanus raphanistrum",     "Wild radish",         "Raphanus raphanistrum",     "broadleaf"),
    ("emex australis",            "Doublegee",           "Emex australis",            "broadleaf"),
    ("carthamus lanatus",         "Saffron thistle",     "Carthamus lanatus",         "thistle"),
    ("onopordum acanthium",       "Scotch thistle",      "Onopordum acanthium",       "thistle"),
    ("cirsium vulgare",           "Spear thistle",       "Cirsium vulgare",           "thistle"),
    ("hypericum perforatum",      "St John's wort",      "Hypericum perforatum",      "broadleaf"),
    ("hyparrhenia hirta",         "Coolatai grass",      "Hyparrhenia hirta",         "grass"),
    ("andropogon gayanus",        "Gamba grass",         "Andropogon gayanus",        "grass"),
    ("nassella neesiana",         "Chilean needle grass", "Nassella neesiana",        "grass"),
    ("echinochloa crus-galli",    "Barnyard grass",      "Echinochloa crus-galli",    "grass"),
    ("eichhornia crassipes",      "Water hyacinth",      "Eichhornia crassipes",      "aquatic"),
    ("asphodelus fistulosus",     "Onion weed",          "Asphodelus fistulosus",     "geophyte"),
]

# Non-weed controls. kind=gbif -> real third-party photo; kind=synthetic -> rendered locally.
CONTROLS = [
    ("control-banana",        "Banana (crop control)",        "Musa acuminata",          "gbif"),
    ("control-mango",         "Mango (crop control)",         "Mangifera indica",        "gbif"),
    ("control-tomato",        "Tomato (crop control)",        "Solanum lycopersicum",    "gbif"),
    ("control-rose",          "Rose (garden control)",        "Rosa chinensis",          "gbif"),
    ("control-eucalypt",      "Eucalypt leaf (native control)", "Eucalyptus camaldulensis", "gbif"),
    ("control-agapanthus",    "Agapanthus (garden control)",  "Agapanthus praecox",      "gbif"),
    ("control-cup",           "Coffee cup (non-plant)",       "",                        "synthetic"),
    ("control-car",           "Car (non-plant)",              "",                        "synthetic"),
    ("control-fence",         "Fence (non-plant)",            "",                        "synthetic"),
    ("control-soil",          "Bare soil (non-plant)",        "",                        "synthetic"),
]

SYNTHETIC_SPECS = {
    "control-cup":   ("cup",    (222, 222, 226)),
    "control-car":   ("car",    (60, 90, 140)),
    "control-fence": ("fence",  (140, 120, 90)),
    "control-soil":  ("soil",   (92, 70, 52)),
}


# ── http helpers ─────────────────────────────────────────────────────────────
def http_get(url: str, retries: int = 4, binary: bool = False):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                data = r.read()
            return data if binary else json.loads(data.decode("utf-8", "replace"))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (attempt + 1) + random.random())
    raise RuntimeError(f"GET failed after {retries}: {url} ({last})")


def gbif_json(path: str, params: dict):
    return http_get("https://api.gbif.org/v1" + path + "?" + urllib.parse.urlencode(params))


# ── gallery hashing (held-out guarantee) ─────────────────────────────────────
def gallery_hashes(images_dir: Path, index_files: Path) -> tuple[set, set]:
    """Return (sha256 set, basename set) for the images that are IN the index."""
    indexed = set(json.loads(index_files.read_text()))
    shas, names = set(), set(indexed)
    n = 0
    if images_dir.is_dir():
        for sp_dir in images_dir.iterdir():
            if not sp_dir.is_dir():
                continue
            for p in sp_dir.glob("*.jpg"):
                if p.name not in indexed:
                    continue
                try:
                    shas.add(hashlib.sha256(p.read_bytes()).hexdigest())
                    n += 1
                except OSError:
                    pass
    print(f"[gallery] indexed basenames={len(names)}  hashed={n}  sha-set={len(shas)}")
    return shas, names


# ── candidate pools ──────────────────────────────────────────────────────────
def gbif_candidates(sci: str, limit: int = 12) -> list[dict]:
    m = gbif_json("/species/match", {"name": sci, "rank": "SPECIES"})
    uk = (m or {}).get("usageKey")
    if not uk:
        return []
    occ = gbif_json("/occurrence/search", {
        "taxonKey": uk, "country": "AU", "mediaType": "StillImage",
        "limit": min(limit, 20),
    })
    out = []
    for r in occ.get("results", []):
        for media in r.get("media", []) or []:
            ident = media.get("identifier") or ""
            if not ident.startswith("http"):
                continue
            out.append({
                "url": ident,
                "license": (media.get("license") or "unknown").replace(
                    "http://creativecommons.org/licenses/", "").replace(
                    "https://creativecommons.org/licenses/", ""),
                "source": "gbif",
                "attribution": media.get("rightsHolder") or media.get("creator") or r.get("recordedBy") or "",
                "province": r.get("stateProvince") or "",
                "record_url": f"https://www.gbif.org/occurrence/{r.get('key')}",
            })
    return out


def wikimedia_candidates(sci: str, limit: int = 8) -> list[dict]:
    api = ("https://commons.wikimedia.org/w/api.php?action=query&format=json"
           "&generator=search&gsrnamespace=6&gsrlimit=" + str(limit) +
           "&gsrsearch=" + urllib.parse.quote(sci) +
           "&prop=imageinfo&iiprop=url|extmetadata|size&iiurlwidth=1024")
    j = http_get(api)
    pages = ((j or {}).get("query") or {}).get("pages") or {}
    out = []
    for p in pages.values():
        ii = (p.get("imageinfo") or [{}])[0]
        url = ii.get("thumburl") or ii.get("url")
        if not url or not url.lower().split("?")[0].endswith((".jpg", ".jpeg", ".png")):
            continue
        em = ii.get("extmetadata") or {}
        out.append({
            "url": url,
            "license": (em.get("LicenseShortName") or {}).get("value", "unknown"),
            "source": "wikimedia",
            "attribution": (em.get("Artist") or {}).get("value", "")[:200],
            "province": "",
            "record_url": ii.get("descriptionurl") or "",
        })
    return out


def inat_candidates(sci: str, limit: int = 8) -> list[dict]:
    j = http_get("https://api.inaturalist.org/v1/observations?" + urllib.parse.urlencode({
        "taxon_name": sci, "place_id": 6744, "quality_grade": "research",
        "photos": "true", "per_page": min(limit, 20), "order_by": "random",
    }))
    out = []
    for r in j.get("results", []):
        for ph in r.get("photos", []) or []:
            url = ph.get("url") or ""
            if not url:
                continue
            url = url.replace("/square.", "/original.").replace("/small.", "/original.").replace("/medium.", "/original.")
            out.append({
                "url": url,
                "license": (ph.get("license_code") or "unknown"),
                "source": "inaturalist",
                "attribution": (r.get("user") or {}).get("login", ""),
                "province": (r.get("place_guess") or ""),
                "record_url": f"https://www.inaturalist.org/observations/{r.get('id')}",
            })
    return out


# ── image validation ─────────────────────────────────────────────────────────
def validate_image(raw: bytes, min_px: int = 200):
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(raw))
        im.verify()
        im = Image.open(io.BytesIO(raw))
        w, h = im.size
        if min(w, h) < min_px:
            return False, f"too_small({w}x{h})"
        return True, f"{w}x{h}"
    except Exception as e:  # noqa: BLE001
        return False, f"invalid({e.__class__.__name__})"


def render_synthetic(key: str, path: Path) -> dict:
    """Render a locally generated non-plant control image (clearly synthetic)."""
    from PIL import Image, ImageDraw
    kind, colour = SYNTHETIC_SPECS[key]
    w = h = 640
    im = Image.new("RGB", (w, h), colour)
    d = ImageDraw.Draw(im)
    if kind == "cup":
        d.ellipse((170, 190, 470, 470), fill=(250, 250, 252), outline=(150, 150, 155), width=6)
        d.arc((320, 180, 560, 460), 270, 90, fill=(150, 150, 155), width=12)
        d.ellipse((200, 200, 440, 420), fill=(90, 55, 35))
    elif kind == "car":
        d.rectangle((90, 300, 550, 430), fill=(190, 40, 40))
        d.rectangle((170, 220, 470, 305), fill=(210, 210, 220))
        d.ellipse((140, 400, 240, 490), fill=(30, 30, 30))
        d.ellipse((400, 400, 500, 490), fill=(30, 30, 30))
    elif kind == "fence":
        for x in range(80, 620, 180):
            d.rectangle((x, 150, x + 40, 560), fill=(170, 150, 120))
        d.rectangle((60, 220, 600, 260), fill=(150, 130, 100))
        d.rectangle((60, 360, 600, 400), fill=(150, 130, 100))
    elif kind == "soil":
        for i in range(4000):
            x = random.randint(0, w - 1)
            y = random.randint(0, h - 1)
            v = random.randint(-25, 25)
            d.point((x, y), fill=(max(0, min(255, colour[0] + v)),
                                  max(0, min(255, colour[1] + v)),
                                  max(0, min(255, colour[2] + v))))
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, "JPEG", quality=90)
    return {"source": "synthetic", "license": "n/a (rendered locally)",
            "attribution": "AUGURY test harness", "province": "",
            "record_url": "", "url": "", "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "dims": f"{w}x{h}"}


# ── main ─────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "data" / "thirdparty"))
    ap.add_argument("--images-dir", default=str(ROOT / "data" / "vision" / "images"))
    ap.add_argument("--index-files", default=str(ROOT / "data" / "vision" / "index" / "files.json"))
    ap.add_argument("--seed", type=int, default=20260818)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--only", default="", help="comma-separated keys to (re)fetch")
    ap.add_argument("--max-candidates", type=int, default=16)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    out = Path(args.out).resolve()
    photos = out / "photos"
    out.mkdir(parents=True, exist_ok=True)

    sha_set, name_set = gallery_hashes(Path(args.images_dir), Path(args.index_files))
    log_path = out / "fetch_log.jsonl"
    log = open(log_path, "a", buffering=1)

    only = {s.strip() for s in args.only.split(",") if s.strip()}
    rows = []

    def handle(key: str, common: str, sci: str, form: str, kind: str, is_control: bool):
        dest_dir = photos / key
        dest = dest_dir / "1.jpg"
        if args.resume and dest.exists() and (dest_dir / "meta.json").exists():
            meta = json.loads((dest_dir / "meta.json").read_text())
            print(f"[skip] {key}: already fetched ({meta.get('source')})")
            return {"key": key, "common_name": common, "scientific_name": sci, "form": form,
                    "is_control": is_control, "photo": str(dest.relative_to(ROOT)), **meta}
        dest_dir.mkdir(parents=True, exist_ok=True)

        if kind == "synthetic":
            meta = render_synthetic(key, dest)
            (dest_dir / "meta.json").write_text(json.dumps(meta, indent=1))
            print(f"[synth] {key}: rendered {meta['dims']}")
            return {"key": key, "common_name": common, "scientific_name": sci, "form": form,
                    "is_control": is_control, "photo": str(dest.relative_to(ROOT)), **meta}

        pools = [("gbif", lambda: gbif_candidates(sci, args.max_candidates)),
                 ("wikimedia", lambda: wikimedia_candidates(sci, 10)),
                 ("inaturalist", lambda: inat_candidates(sci, 10))]
        cands = []
        for label, fn in pools:
            try:
                got = fn()
                print(f"[pool] {key}: {label} -> {len(got)} candidates")
                cands += got
            except Exception as e:  # noqa: BLE001
                log.write(json.dumps({"key": key, "pool": label, "error": str(e)}) + "\n")
                print(f"[pool] {key}: {label} FAILED ({e})")
        rng.shuffle(cands)

        for c in cands:
            url = c["url"]
            base = Path(urllib.parse.urlparse(url).path).name
            if base in name_set:
                log.write(json.dumps({"key": key, "url": url, "reject": "in_index_basename"}) + "\n")
                continue
            try:
                raw = http_get(url, retries=3, binary=True)
            except Exception as e:  # noqa: BLE001
                log.write(json.dumps({"key": key, "url": url, "reject": f"download:{e}"}) + "\n")
                continue
            sha = hashlib.sha256(raw).hexdigest()
            if sha in sha_set:
                log.write(json.dumps({"key": key, "url": url, "reject": "in_index_sha"}) + "\n")
                continue
            ok, detail = validate_image(raw)
            if not ok:
                log.write(json.dumps({"key": key, "url": url, "reject": detail}) + "\n")
                continue
            dest.write_bytes(raw)
            meta = {"source": c["source"], "license": c["license"],
                    "attribution": c["attribution"], "province": c["province"],
                    "record_url": c["record_url"], "url": url,
                    "bytes": len(raw), "sha256": sha, "dims": detail}
            (dest_dir / "meta.json").write_text(json.dumps(meta, indent=1))
            log.write(json.dumps({"key": key, "url": url, "accept": detail}) + "\n")
            print(f"[ok]   {key}: {c['source']} {detail} {meta['license']} {c['province'][:30]}")
            time.sleep(0.4)
            return {"key": key, "common_name": common, "scientific_name": sci, "form": form,
                    "is_control": is_control, "photo": str(dest.relative_to(ROOT)), **meta}

        print(f"[FAIL] {key}: no usable held-out photo from any pool")
        return None

    for key, common, sci, form in WEEDS:
        if only and key not in only:
            continue
        r = handle(key, common, sci, form, "gbif", False)
        if r:
            rows.append(r)

    for key, common, sci, kind in CONTROLS:
        if only and key not in only:
            continue
        r = handle(key, common, sci, "control", kind, True)
        if r:
            rows.append(r)

    log.close()

    # enrich with DB indicator shape so the report can separate model vs data limits
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        from species_lookup import SpeciesDB
        db = SpeciesDB()
        for r in rows:
            if r["is_control"]:
                r["db_shape"] = "n/a"
                continue
            info = db.get_indicators(r["key"], region="Australia")
            keys = list((info or {}).get("indicators", {}))
            r["db_shape"] = ("general-only" if keys == ["General indicators"]
                             else f"{len(keys)} structured keys")
    except Exception as e:  # noqa: BLE001
        print(f"[warn] DB shape enrichment failed: {e}")

    (out / "corpus.json").write_text(json.dumps(rows, indent=1))
    with open(out / "corpus.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["key", "common_name", "scientific_name", "form",
                                           "is_control", "db_shape", "source", "license",
                                           "attribution", "province", "photo", "sha256", "dims"],
                           extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    n_weed = sum(1 for r in rows if not r["is_control"])
    n_ctrl = sum(1 for r in rows if r["is_control"])
    print(f"\ncorpus: {n_weed} weeds + {n_ctrl} controls -> {out/'corpus.json'}")
    if n_weed < len(WEEDS) or n_ctrl < len(CONTROLS):
        print("WARNING: corpus incomplete — see fetch_log.jsonl")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

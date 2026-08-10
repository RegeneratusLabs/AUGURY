#!/usr/bin/env python3
"""AUGURY vision — pull_inaturalist.py

Primary image acquisition source (iNaturalist covers nearly all 2,230 DB species).

Design (guard rails: resumable, throttled, polite, license-aware):
  * Taxa matching  : GET /v1/taxa?q=<name>&rank=species  — exact-name match first,
                     common-name fallback; results cached in a taxa cache file.
  * Observations   : GET /v1/observations?taxon_id=X&quality_grade=research&captive=false
                     paginated (per_page=200). Only research-grade, non-captive.
  * License policy : record per-photo license_code in the sidecar; prefer non-NC
                     (CC0/CC-BY/CC-BY-SA) photos first, include NC only to reach target.
  * Throttle       : API ~1 req/sec (iNat recommended). Image downloads from the
                     static.inaturalist.org CDN with small concurrency (4) + jitter,
                     exponential backoff on 429/403.
  * Resumable      : state file (JSON) per species — rerun safe, skips completed work.
  * Integrity      : every downloaded image is opened with PIL; failures are dropped
                     and retried from the pool.

Outputs:
  data/vision/images/<key>/<taxon_id>_<photo_id>.jpg     (key = species_list key)
  data/vision/inat_state.json                            (resume state)
  data/vision/acquisition_progress.log                   (append-only progress)

Usage:
  .venv-mcpmv46/bin/python scripts/vision/pull_inaturalist.py \
      [--species-list data/vision/species_list.json] \
      [--out data/vision/images] [--target 50] [--min 10] \
      [--limit-species 10] [--au-first] [--reset]
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import io
import json
import random
import sys
import time
from pathlib import Path

import requests

API = "https://api.inaturalist.org/v1"
IMG = "https://static.inaturalist.org/photos"
HDRS = {"User-Agent": "AUGURY-vision-dataset-builder/0.1 (research; contact: augury@localhost)"}
NC_OK = {"cc0", "cc-by", "cc-by-sa"}          # non-NC, safe for open release
NC_ALL = NC_OK | {"cc-by-nc", "cc-by-nc-sa", "cc-by-nc-nd"}  # all CC we accept


def api_get(path, params, session, retries=5):
    url = f"{API}{path}"
    for attempt in range(retries):
        try:
            r = session.get(url, params=params, headers=HDRS, timeout=30)
            if r.status_code in (429, 500, 502, 503):
                wait = 2 ** attempt + random.random()
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            time.sleep(2 ** attempt + random.random())
    return None


def match_taxon(species, session, cache):
    """Return (taxon_id, matched_name) or (None, reason)."""
    names = [species["scientific_name"]] + species["common_names"]
    seen = set()
    for name in names:
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        data = api_get("/taxa", {"q": name, "rank": "species", "per_page": 5}, session)
        time.sleep(1.0)  # throttle API
        if not data or not data.get("results"):
            continue
        for t in data["results"]:
            tname = (t.get("name") or "").lower()
            mt = (t.get("matched_term") or "").lower()
            if tname == species["scientific_name"].lower():
                return t["id"], t.get("name")
            if mt and mt == name.lower():
                return t["id"], t.get("name")
            if species["scientific_name"].lower() in (tname, (t.get("preferred_common_name") or "").lower()):
                return t["id"], t.get("name")
            # token overlap >= 2 (handles genus renames e.g. Acacia -> Vachellia)
            toks_q = {w for w in name.lower().replace(".", " ").split() if len(w) > 3}
            toks_t = {w for w in tname.replace(".", " ").split() if len(w) > 3}
            if len(toks_q & toks_t) >= 2:
                return t["id"], t.get("name")
    return None, "no-taxon-match"


def collect_photos_from_obs(data, target, cands, seen):
    for obs in data or []:
        for ph in (obs.get("photos") or []):
            pid = ph.get("id")
            if not pid or pid in seen:
                continue
            seen.add(pid)
            url = (ph.get("url") or "").replace("square", "medium")
            lic = (ph.get("license_code") or "").lower()
            if url and lic in NC_ALL:
                cands.append((pid, url, lic))
    return cands, seen


def collect_photos(taxon_id, session, target):
    """Return list of (photo_id, url, license_code), non-NC first, up to target."""
    cands, seen = [], set()
    page = 1
    while len(cands) < target * 3 and page <= 12:
        data = api_get("/observations", {
            "taxon_id": taxon_id, "quality_grade": "research", "captive": "false",
            "per_page": 200, "page": page,
            "fields": "photos,observed_on",
        }, session)
        time.sleep(1.0)
        if not data or not data.get("results"):
            break
        collect_photos_from_obs(data["results"], target, cands, seen)
        if len(data["results"]) < 200:
            break
        page += 1
    # non-NC first, then NC
    cands.sort(key=lambda c: 0 if c[2] in NC_OK else 1)
    return cands[:target]


def collect_photos_q(query, session, target):
    """Fallback: full-text observation search (handles synonyms w/o taxon match)."""
    cands, seen = [], set()
    page = 1
    while len(cands) < target * 3 and page <= 6:
        data = api_get("/observations", {
            "q": query, "quality_grade": "research", "captive": "false",
            "per_page": 200, "page": page,
            "fields": "photos,observed_on",
        }, session)
        time.sleep(1.0)
        if not data or not data.get("results"):
            break
        collect_photos_from_obs(data["results"], target, cands, seen)
        if len(data["results"]) < 200:
            break
        page += 1
    cands.sort(key=lambda c: 0 if c[2] in NC_OK else 1)
    return cands[:target]


def download_one(args):
    photo_id, url, lic, out_path = args
    for attempt in range(4):
        try:
            r = requests.get(url, headers=HDRS, timeout=30)
            if r.status_code == 429:
                time.sleep(5 + 5 * attempt + random.random() * 3)
                continue
            if r.status_code == 403:
                return out_path, "403", lic
            r.raise_for_status()
            from PIL import Image
            im = Image.open(io.BytesIO(r.content))
            im.verify()
            out_path.write_bytes(r.content)
            return out_path, "ok", lic
        except Exception:
            time.sleep(1 + attempt + random.random())
    return out_path, "failed", lic


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--species-list", default="data/vision/species_list.json")
    ap.add_argument("--out", default="data/vision/images")
    ap.add_argument("--target", type=int, default=50)
    ap.add_argument("--min", dest="min_imgs", type=int, default=10)
    ap.add_argument("--limit-species", type=int, default=0, help="0 = all species")
    ap.add_argument("--au-first", action="store_true")
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()

    species = json.loads(Path(args.species_list).read_text())
    if args.au_first:
        species.sort(key=lambda s: (not s["is_au"], s["key"]))
    if args.limit_species:
        species = species[: args.limit_species]

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    state_path = out_dir.parent / "inat_state.json"
    state = {} if args.reset else (json.loads(state_path.read_text()) if state_path.exists() else {})
    log_path = out_dir.parent / "acquisition_progress.log"
    cache_path = out_dir.parent / "inat_taxa_cache.json"
    taxa_cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}

    session = requests.Session()
    logf = open(log_path, "a", buffering=1)
    summary = {"ok": 0, "no_images": 0, "no_taxon": 0, "failed": 0}

    for s in species:
        key = s["key"]
        st = state.get(key, {})
        if st.get("status") == "done":
            summary["ok"] += 1
            continue
        sp_dir = out_dir / key
        sp_dir.mkdir(parents=True, exist_ok=True)

        taxon_id = st.get("taxon_id") or taxa_cache.get(key)
        query = st.get("query")
        if not taxon_id and not query:
            taxon_id, matched = match_taxon(s, session, taxa_cache)
            if taxon_id:
                taxa_cache[key] = taxon_id
            else:
                query = s["scientific_name"]  # fallback: observations full-text search

        if taxon_id:
            photos = collect_photos(taxon_id, session, args.target)
        else:
            photos = collect_photos_q(query, session, args.target)
            if not photos:
                state[key] = {"status": "no_images", "query": query}
                json.dump(state, open(state_path, "w"))
                summary["no_images"] += 1
                logf.write(f"[{key}] no research-grade photos (q='{query}')\n")
                continue

        id_prefix = str(taxon_id) if taxon_id else "q" + hashlib.sha1(query.encode()).hexdigest()[:8]

        done = set(st.get("done", []))
        todo = [p for p in photos if p[0] not in done]
        if len(done) >= args.target:
            state[key] = {"status": "done", "taxon_id": taxon_id, "query": query, "done": sorted(done)}
            json.dump(state, open(state_path, "w"))
            summary["ok"] += 1
            continue

        sidecar = sp_dir / "sources.jsonl"
        sidecar_ids = set()
        if sidecar.exists():
            for ln in sidecar.read_text().splitlines():
                try:
                    sidecar_ids.add(json.loads(ln)["photo_id"])
                except Exception:
                    pass

        jobs = []
        backfill = []
        for pid, url, lic in todo:
            out_path = sp_dir / f"{id_prefix}_{pid}.jpg"
            if out_path.exists():
                done.add(pid)
                if pid not in sidecar_ids:
                    backfill.append((pid, url, lic, out_path))
                continue
            jobs.append((pid, url, lic, out_path))

        with open(sidecar, "a", buffering=1) as sc:
            for pid, url, lic, out_path in backfill:
                sc.write(json.dumps({"photo_id": pid, "file": out_path.name,
                                     "license": lic, "source": "inaturalist"}) + "\n")
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
                for out_path, res, lic in ex.map(download_one, jobs):
                    if res == "ok":
                        pid = int(out_path.stem.split("_")[-1])
                        done.add(pid)
                        sc.write(json.dumps({"photo_id": pid, "file": out_path.name,
                                             "license": lic, "source": "inaturalist"}) + "\n")
                    elif res == "403":
                        break

        if len(done) >= args.min_imgs:
            state[key] = {"status": "done", "taxon_id": taxon_id, "query": query, "done": sorted(done)}
            summary["ok"] += 1
        else:
            state[key] = {"status": "partial", "taxon_id": taxon_id, "query": query, "done": sorted(done)}
            summary["failed"] += 1
        json.dump(state, open(state_path, "w"))
        json.dump(taxa_cache, open(cache_path, "w"))
        logf.write(f"[{key}] taxon={taxon_id} imgs={len(done)}/{args.target} "
                   f"(min {args.min_imgs}) -> {state[key]['status']}\n")

    print("summary:", summary)
    print("state written:", state_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())

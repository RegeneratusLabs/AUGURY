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
import re
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


def _norm(s: str) -> str:
    return " ".join((s or "").strip().lower().replace(".", " ").split())


def _epithet(name: str) -> str:
    """The specific epithet of a binomial ('sinapis arvensis' -> 'arvensis').

    Genus names get swapped by reorganisation (*Sinapis arvensis* is now
    *Mutarda arvensis*, *Prosopis* is now *Neltuma* in some taxonomies), so the
    epithet is the stablest part of the name.
    """
    parts = _norm(name).split()
    return parts[1] if len(parts) == 2 else ""


# A capitalized two-word vernacular ("Wild radish", "Black nightshade") would pass
# the shape test for a binomial, so the leading modifier is blocked explicitly.
_VERNACULAR_MODIFIERS = {
    "wild", "common", "black", "white", "red", "yellow", "blue", "purple", "pink",
    "green", "great", "lesser", "small", "large", "creeping", "curled", "spiny",
    "slender", "narrow", "broad", "hairy", "smooth", "annual", "perennial", "sea",
    "field", "hedge", "water", "marsh", "sand", "silver", "golden", "scented",
    "italian", "african", "australian", "european", "japanese", "chinese", "indian",
}


def _looks_binomial(name: str) -> bool:
    """True for a two-word Latin name like 'Sinapis arvensis'.

    Used to decide whether a string in a species' `common_names` is really an
    alternate *scientific* name. The species list stores these interchangeably —
    `sinapis arvensis` lists "Sinapis arvensis" among its common names — and
    treating that as a vernacular name is what let a different species match.
    """
    parts = (name or "").split()
    if len(parts) != 2:
        return False
    if parts[0].lower() in _VERNACULAR_MODIFIERS:
        return False
    return all(p[:1].isupper() and p[1:].islower() for p in parts)


def match_taxon(species, session, cache):
    """Resolve a species/genus key to a taxon id.

    Returns (taxon_id, matched_name, rank, method) — or (None, reason, None, None).

    Correctness rules (these replace a rule that silently misfiled photographs)
    -------------------------------------------------------------------------
    The previous version accepted the first candidate with "any two shared tokens
    of 4+ characters". That is far too weak: it let ``prosopis spp`` resolve to
    **Holcus lanatus** (taxon 52793) and ``sinapis arvensis`` to
    **Raphanus raphanistrum** (55411), so two different plants ended up holding the
    same photographs. Those species were unlearnable, and their benchmark queries
    carried wrong ground truth.

    The rule is now **identity, not resemblance**: the candidate taxon must BE the
    species asked for.

    * a taxon name equal to the scientific name is accepted;
    * an entry in ``common_names`` that is actually a binomial counts as an
      alternate scientific name (the species list mixes the two);
    * a vernacular common name is accepted only when the taxon's name equals that
      name *and* the taxon is species rank — i.e. iNaturalist reports the taxon
      itself under that name.

    Deliberately NOT accepted: iNaturalist's ``matched_term``. It reports the
    *query* it fuzzy-matched, so for ``q=Sinapis arvensis`` it happily returns
    **Raphanus raphanistrum** with ``matched_term='Sinapis arvensis'`` — a synonym
    relation, not an identity. Trusting it reintroduced the very bug being fixed.

    Genus keys (``banksia spp``) are looked up at rank ``genus``; they have no
    species-rank taxon, which is why the old rule sent them somewhere unrelated.
    """
    sci = _norm(species.get("scientific_name"))
    bare = sci.split()[0] if sci else ""
    is_genus = sci.endswith(" spp") or sci.endswith(" spp.")
    want_rank = "genus" if is_genus else "species"

    # Query strings to try. The previous version sent the raw key, so "banksia spp"
    # was searched verbatim at rank=genus and returned zero results — which is how
    # genus buckets previously fell through to an unrelated species.
    if is_genus:
        queries = [bare]
        # "Banksia (Proteaceae)" -> "Banksia"
        queries += [re.sub(r"\s*\(.*?\)\s*", "", c).strip()
                    for c in (species.get("common_names") or []) if c]
    else:
        queries = [species.get("scientific_name")] + list(species.get("common_names") or [])

    seen = set()
    for name in queries:
        n = _norm(name)
        if not n or n in seen:
            continue
        seen.add(n)
        data = api_get("/taxa", {"q": name, "rank": want_rank, "per_page": 5}, session)
        time.sleep(1.0)  # throttle API
        if not data or not data.get("results"):
            continue
        for t in data["results"]:
            if t.get("rank") != want_rank:
                continue
            tname = _norm(t.get("name"))
            if not tname:
                continue
            if is_genus:
                if tname == n or (bare and tname == bare):
                    return t["id"], t.get("name"), t.get("rank"), "genus-exact"
                # Genus reorganisation: iNaturalist resolves the queried genus name
                # to a different accepted genus (*Austrodanthonia* -> *Rytidosperma*,
                # *Callistemon* -> *Melaleuca*) and echoes the query in
                # `matched_term`. That echo is the evidence the match is the same
                # clade under a new name, rather than an unrelated genus.
                #
                # Safe here specifically because the query is a bare genus token with
                # no epithet, so a synonym relation is the only way it resolves. The
                # species path cannot use this rule — see below.
                if _norm(t.get("matched_term")) == n:
                    return t["id"], t.get("name"), t.get("rank"), "genus-synonym"
                continue
            # identity: the taxon must be this species
            if tname == sci:
                return t["id"], t.get("name"), t.get("rank"), "scientific-exact"
            # an alternate scientific name recorded among the common names
            if _looks_binomial(name) and tname == n:
                return t["id"], t.get("name"), t.get("rank"), "alt-scientific"
            # a vernacular name, but only if the taxon is reported under it
            if tname == n:
                return t["id"], t.get("name"), t.get("rank"), "common-exact"
            # Genus reorganisation: the specific epithet survives even when the
            # genus is renamed (*Sinapis arvensis* -> *Mutarda arvensis*,
            # *Callistemon* -> *Melaleuca*). Require the epithet to match AND
            # iNaturalist to have matched our full query string.
            #
            # The epithet check is what keeps this safe. Without it, asking for
            # "Sinapis arvensis" would accept *Raphanus raphanistrum* (a synonym
            # relation, and the exact mislabel this work repairs); with it, the
            # only candidate sharing the epithet `arvensis` is the true species.
            # iNat sometimes pads the matched term ("Sinapis arvensis arvensis"),
            # so this is a prefix test rather than equality.
            ep_q, ep_t = _epithet(sci), _epithet(tname)
            mt = _norm(t.get("matched_term"))
            if ep_q and ep_q == ep_t and mt.startswith(sci):
                return t["id"], t.get("name"), t.get("rank"), "epithet+matched-term"
    return None, "no-taxon-match", None, None


def validate_query_photos(photos, taxon_id, session, sample: int = 3) -> bool:
    """Confirm full-text observation hits really belong to the intended clade.

    `collect_photos_q` searches observations by free text, which can return a
    different genus entirely. Sample the first few observations and require each
    one's taxon to be the resolved taxon or a descendant of it.
    """
    if not photos or not taxon_id:
        return False
    ids = [p[0] for p in photos[:sample]]
    data = api_get("/observations", {"id": ",".join(str(i) for i in ids),
                                     "per_page": sample, "fields": "id,taxon"}, session)
    time.sleep(1.0)
    if not data or not data.get("results"):
        return False
    for obs in data["results"]:
        tax = obs.get("taxon") or {}
        anc = {a.get("id") for a in (tax.get("ancestors") or [])}
        if tax.get("id") != taxon_id and taxon_id not in anc:
            return False
    return True


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
    ap.add_argument("--only", default="",
                    help="comma-separated keys to re-pull; clears their cached "
                         "state/taxon so the match is genuinely redone")
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

    if args.only:
        wanted = {k.strip().lower() for k in args.only.split(",") if k.strip()}
        known = {s["key"].lower() for s in species}
        missing = wanted - known
        if missing:
            print(f"[pull] WARNING: not in species list: {sorted(missing)}")
        species = [s for s in species if s["key"].lower() in wanted]
        # A targeted re-pull must genuinely re-resolve: the cached state and taxon
        # for these keys are exactly what was wrong, so clear them first.
        for s in species:
            state.pop(s["key"], None)
            taxa_cache.pop(s["key"], None)

    session = requests.Session()
    logf = open(log_path, "a", buffering=1)
    summary = {"ok": 0, "no_images": 0, "no_taxon": 0, "failed": 0}

    for s in species:
        key = s["key"]
        st = state.get(key, {})
        if st.get("status") == "done":
            # `done` means "reached the target of the run that set it", not "has
            # every image we will ever want". Skipping unconditionally is why
            # raising --target silently did nothing: 169 of 188 AU species stayed
            # at ~50 images while a 300-target run reported success.
            #
            # Measure progress by the recorded iNaturalist photo ids, NOT by files
            # on disk: `lantana camara` holds 1,114 files but only 50 from iNat
            # (the rest are DeepWeeds), so a file count would wrongly look complete.
            have = len(st.get("done") or [])
            if have >= args.target:
                summary["ok"] += 1
                continue
            logf.write(f"[{key}] reopening: {have} iNat images < target {args.target}\n")
        sp_dir = out_dir / key
        sp_dir.mkdir(parents=True, exist_ok=True)

        # The cache may hold either a bare id (legacy) or a record with the
        # resolved name/rank/method. Recording the name is what makes a wrong
        # assignment visible later instead of silent.
        cached = taxa_cache.get(key)
        if isinstance(cached, dict):
            taxon_id = cached.get("taxon_id") or st.get("taxon_id")
        else:
            taxon_id = st.get("taxon_id") or cached
        query = st.get("query")
        if not taxon_id and not query:
            taxon_id, matched, rank, method = match_taxon(s, session, taxa_cache)
            if taxon_id:
                taxa_cache[key] = {"taxon_id": taxon_id, "name": matched,
                                   "rank": rank, "method": method}
                logf.write(f"[{key}] taxon={taxon_id} ({matched}, {rank}) via {method}\n")
            else:
                query = s["scientific_name"]  # fallback: observations full-text search

        if taxon_id:
            photos = collect_photos(taxon_id, session, args.target)
        else:
            photos = collect_photos_q(query, session, args.target)
            if photos and not validate_query_photos(photos, taxon_id, session):
                # free-text search returned a different clade — refuse rather than
                # file another species' photographs under this key
                state[key] = {"status": "no_images", "query": query,
                              "reason": "full-text results failed clade validation"}
                json.dump(state, open(state_path, "w"))
                summary["no_images"] += 1
                logf.write(f"[{key}] REJECTED: full-text q='{query}' returned another clade\n")
                continue
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

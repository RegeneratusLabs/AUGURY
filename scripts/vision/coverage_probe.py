#!/usr/bin/env python3
"""AUGURY vision — coverage_probe.py

Produces data/vision/coverage_report.md: per-source coverage of the 2,230-species
list, projected image counts, and (after the acquisition pass) species with no
coverage anywhere. Preliminary by design — regenerate after pull_inaturalist /
pull_deepweeds / pull_gbif have run.

Usage:
  .venv-mcpmv46/bin/python scripts/vision/coverage_probe.py [--gbif-probe 15]
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import requests

GBIF = "https://api.gbif.org/v1"
HDRS = {"User-Agent": "AUGURY-vision-coverage-probe/0.1"}

DEEPWEEDS_CLASSES = {
    "Lantana": "lantana camara", "Prickly acacia": "acacia nilotica",
    "Parthenium": "parthenium hysterophorus", "Rubber vine": "cryptostegia grandiflora",
    "Parkinsonia": "parkinsonia aculeata",
}


def gbif_probe(name, retries=3):
    for a in range(retries):
        try:
            r = requests.get(f"{GBIF}/species/match", params={"name": name, "rank": "SPECIES"},
                             headers=HDRS, timeout=25)
            if r.status_code in (429, 500, 502, 503):
                time.sleep(2 ** a); continue
            r.raise_for_status()
            uk = r.json().get("usageKey")
            if not uk:
                return None
            m = requests.get(f"{GBIF}/species/{uk}/media", headers=HDRS, timeout=25)
            if m.status_code == 200:
                return len(m.json().get("results", []))
            return 0
        except requests.RequestException:
            time.sleep(2 ** a)
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gbif-probe", type=int, default=15)
    ap.add_argument("--out", default="data/vision/coverage_report.md")
    args = ap.parse_args()

    species = json.loads(Path("data/vision/species_list.json").read_text())
    state = json.loads(Path("data/vision/inat_state.json").read_text()) if Path("data/vision/inat_state.json").exists() else {}
    s2pn = json.loads(Path("data/vision/species2plantnet.json").read_text()) if Path("data/vision/species2plantnet.json").exists() else {}

    n_au = sum(1 for s in species if s["is_au"])
    n_pn = len(s2pn)
    n_pn_au = sum(1 for k in s2pn if next((s["is_au"] for s in species if s["key"] == k), False))

    iat_status = {}
    for s in species:
        st = state.get(s["key"], {})
        iat_status[st.get("status", "not_run")] = iat_status.get(st.get("status", "not_run"), 0) + 1
    iat_covered = iat_status.get("done", 0) + iat_status.get("partial", 0)

    # GBIF probe on species with no iNat coverage yet
    gbif_hits = 0
    gbif_media_sum = 0
    probed = 0
    for s in species:
        if state.get(s["key"], {}).get("status") in ("done", "partial"):
            continue
        n = gbif_probe(s["scientific_name"])
        time.sleep(0.4)
        probed += 1
        if n:
            gbif_hits += 1
            gbif_media_sum += n
        if probed >= args.gbif_probe:
            break

    img_total = sum(len(list((Path("data/vision/images") / s["key"]).glob("*.jpg")))
                    for s in species if (Path("data/vision/images") / s["key"]).is_dir())
    unknown_total = sum(len(list(d.glob("*.jpg"))) for d in Path("data/vision/images_unknown").glob("*")) if Path("data/vision/images_unknown").exists() else 0

    lines = [
        "# AUGURY Vision — coverage report",
        "",
        f"_Generated {__import__('datetime').date.today()} — preliminary; regenerate after the acquisition pass._",
        "",
        f"- Species list (canonical): **{len(species)}** (AU-tagged: **{n_au}**)",
        f"- Images on disk: **{img_total}** (train dirs) + **{unknown_total}** (unknown/refusal dirs)",
        "",
        "## Per-source coverage",
        "",
        "| Source | Coverage | Notes |",
        "|---|---|---|",
        f"| Pl@ntNet-300K | {n_pn} species ({n_pn_au} AU) | French-flora benchmark; name-mapped via species2plantnet.json; images NOT pulled (see handover) |",
        f"| DeepWeeds | {len(DEEPWEEDS_CLASSES)} classes in DB + 3 unknown + Negative | CC BY 4.0, northern-AU weeds |",
        f"| iNaturalist | {iat_covered} species covered so far ({iat_status.get('not_run', 0)} not run) | research-grade, throttled pull |",
        f"| GBIF media (probe n={probed}) | {gbif_hits} with media (avg {gbif_media_sum / max(gbif_hits, 1):.0f} imgs) | gap-filler for iNat misses |",
        "",
        "## iNaturalist status histogram (current)",
        "",
        "| status | species |",
        "|---|---|",
    ]
    for k, v in sorted(iat_status.items()):
        lines.append(f"| {k} | {v} |")
    lines += ["", "## Target policy",
              "",
              "- Per-species target: 30–50 images (floor 10 → status done/partial)",
              "- AU + cosmopolitan weeds prioritized first (--au-first)",
              "- Species below floor or with zero images anywhere are documented here and excluded from the vision label set",
              "- Unknown/refusal layer: DeepWeeds negative class + Chinee apple / Snake weed / Siam weed"]
    Path(args.out).write_text("\n".join(lines))
    print(f"wrote {args.out}")
    print(f"species={len(species)} AU={n_au} plantnet={n_pn} iNat covered={iat_covered} "
          f"gbif probe hits={gbif_hits}/{probed} images_on_disk={img_total}")
    return 0


if __name__ == "__main__":
    main()

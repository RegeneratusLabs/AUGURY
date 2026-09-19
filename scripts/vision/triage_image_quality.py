#!/usr/bin/env python3
"""AUGURY — triage_image_quality.py

Turn the raw quality scan into a shortlist that is worth a model's attention.

Why strata
----------
`scan_image_quality.py` measures 111,302 images. The raw blur metric is NOT
comparable across the gallery, because the sources differ in resolution:

    DeepWeeds   256x256   (65,536 px)
    iNaturalist ~500x375, 500x500, 640x480 …

A small image has fewer high-frequency pixels, so its Laplacian variance is lower
regardless of how sharp it is. Ranking the whole gallery on raw blur would simply
re-discover the DeepWeeds subset. Within-resolution-stratum percentile ranks remove
that confound.

What it emits
-------------
A ranked, reason-tagged shortlist. Each image can carry several reasons:
  * `tiny`        — very low pixel count, little detail for retrieval
  * `soft`        — bottom of the blur distribution *within its resolution band*
  * `compressed`  — very low bytes-per-pixel (heavy JPEG artefacts)
  * `flat`        — very low luminance std (blank / near-uniform frame)
  * `extreme`     — extreme aspect ratio (screenshot, panorama, strip)
  * `unreadable`  — decode failure

Also cross-references the AU benchmark: a bad *query* image is far more damaging
than a bad gallery image, because it makes the species unscoreable. That list is
reported separately and first.

Usage:
    .venv-mcpmv46/bin/python scripts/vision/triage_image_quality.py
    .venv-mcpmv46/bin/python scripts/vision/triage_image_quality.py --top 300
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCAN = ROOT / "data" / "vision" / "bench" / "image_quality.jsonl"
SPLIT = ROOT / "data" / "vision" / "au_split.json"
OUT = ROOT / "data" / "vision" / "bench" / "image_quality_shortlist.json"

# Thresholds are deliberately conservative: the aim is a shortlist a human or a
# model can actually review, not a verdict. They are percentiles within stratum,
# plus two absolute guards that need no distribution.
PCT_SOFT = 0.02          # bottom 2% of blur within the resolution band
PCT_COMPRESSED = 0.02    # bottom 2% of bytes-per-pixel within band
PCT_FLAT = 0.01          # bottom 1% of luminance std within band
ABS_TINY_PX = 20_000     # below this there is very little to look at
ABS_EXTREME_ASPECT = 3.0


def main() -> int:
    ap = argparse.ArgumentParser(description="Shortlist low-quality gallery images")
    ap.add_argument("--scan", default=str(SCAN))
    ap.add_argument("--top", type=int, default=0, help="limit reported rows (0=all)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    recs = [json.loads(l) for l in Path(args.scan).read_text().splitlines() if l.strip()]
    print(f"[triage] scanned records: {len(recs)}")

    # Resolution strata: rank within comparable image sizes.
    def stratum(r):
        px = r.get("pixels") or 0
        if px <= 70_000:
            return "small"          # ~256x256, the DeepWeeds band
        if px <= 200_000:
            return "medium"         # ~500x500
        return "large"

    buckets = collections.defaultdict(list)
    for r in recs:
        if r.get("ok"):
            buckets[stratum(r)].append(r)
    for name, rs in sorted(buckets.items()):
        print(f"[triage]   {name:7s} {len(rs):7d} images")

    # Percentile ranks within stratum.
    def rank_within(rs, key):
        s = sorted(rs, key=lambda r: r.get(key) or 0)
        n = max(1, len(s) - 1)
        for i, r in enumerate(s):
            r[f"_{key}_rank"] = i / n

    for name, rs in buckets.items():
        for key in ("blur_var", "bpp", "lum_std"):
            rank_within(rs, key)

    # Benchmark queries, so a bad query can be called out separately.
    query_paths = set()
    if SPLIT.exists():
        doc = json.loads(SPLIT.read_text())
        for v in doc["species"].values():
            query_paths.update(v["queries"])

    shortlist = []
    for r in recs:
        reasons = []
        if not r.get("ok"):
            reasons.append("unreadable")
        else:
            if (r.get("pixels") or 0) < ABS_TINY_PX:
                reasons.append("tiny")
            if r.get("_blur_var_rank", 1) <= PCT_SOFT:
                reasons.append("soft")
            if r.get("_bpp_rank", 1) <= PCT_COMPRESSED:
                reasons.append("compressed")
            if r.get("_lum_std_rank", 1) <= PCT_FLAT:
                reasons.append("flat")
            if (r.get("aspect") or 1) >= ABS_EXTREME_ASPECT:
                reasons.append("extreme")
        if reasons:
            shortlist.append({
                "path": r["path"], "reasons": reasons,
                "pixels": r.get("pixels"), "blur_var": r.get("blur_var"),
                "bpp": r.get("bpp"), "lum_std": r.get("lum_std"),
                "is_benchmark_query": r["path"] in query_paths,
                "score": len(reasons) + (2 if r["path"] in query_paths else 0),
            })

    shortlist.sort(key=lambda x: (-x["score"], x["path"]))
    tallies = collections.Counter(x for s in shortlist for x in s["reasons"])
    flagged_queries = [s for s in shortlist if s["is_benchmark_query"]]

    if args.json:
        print(json.dumps({"shortlist": shortlist[:args.top or None]}, indent=1))
    else:
        print(f"\n[triage] shortlisted: {len(shortlist)} of {len(recs)} "
              f"({len(shortlist)/max(1,len(recs)):.2%})")
        print("[triage] by reason:")
        for k, n in tallies.most_common():
            print(f"    {k:12s} {n}")
        print(f"\n[triage] BENCHMARK QUERIES flagged: {len(flagged_queries)} "
              f"(these directly cost accuracy)")
        for s in flagged_queries[:15]:
            print(f"    {s['path']}  {s['reasons']}")
        print("\n[triage] top shortlist rows:")
        for s in shortlist[:15]:
            print(f"    {s['path']:52s} {','.join(s['reasons'])}")

    OUT.write_text(json.dumps({
        "flagged": len(shortlist), "total": len(recs),
        "by_reason": dict(tallies),
        "benchmark_queries_flagged": [s["path"] for s in flagged_queries],
        "shortlist": shortlist,
    }, indent=1))
    print(f"\n[triage] wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""AUGURY — turn an on-device accuracy CSV into a success-rate report.

`OnDeviceAccuracyTest` writes one row per query; this turns those rows into the
numbers a decision needs. Top-1 is the headline ("Best match"), top-3 is what the
confirm card actually offers, and the AUTO band matters most of all: a confident
wrong identification is the product's dangerous failure, so its *precision* is
reported separately from its coverage.

An `error` on a row is counted as a miss, not excluded — a photo the pipeline
could not process is a photo the user did not get an answer for.

Usage:
    adb pull /data/data/au.org.regeneratus.augury/files/accuracy-results.csv
    python3 tools/summarise_accuracy.py accuracy-results.csv [--by-species]
"""
from __future__ import annotations

import argparse
import collections
import csv
import sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", help="accuracy-results.csv pulled from the device")
    ap.add_argument("--by-species", action="store_true", help="list the worst species")
    ap.add_argument("--misses", type=int, default=0, help="print the first N top-1 misses")
    args = ap.parse_args()

    with open(args.csv) as fh:
        first = fh.readline()
        fh.seek(0)
        if first.startswith("i,"):
            rows = list(csv.DictReader(fh))
        else:
            # Tolerate a headerless file: the writer used to truncate its own
            # header, and a complete run must not be thrown away over that.
            fields = "i file expected top1 top2 top3 s1 s2 s3 band1 hit1 hit3 error ms".split()
            rows = [dict(zip(fields, r)) for r in csv.reader(fh) if r]
    if not rows:
        sys.exit("[accuracy] the CSV is empty")

    n = len(rows)
    errors = [r for r in rows if r["error"].strip()]
    answered = n - len(errors)
    hit1 = sum(1 for r in rows if r["hit1"] == "1")
    hit3 = sum(1 for r in rows if r["hit3"] == "1")
    auto = [r for r in rows if r["band1"] == "AUTO"]
    auto_hit = sum(1 for r in auto if r["hit1"] == "1")
    ms = [int(r["ms"]) for r in rows if r["ms"].isdigit()]

    def pct(a: int, b: int) -> float:
        return 100.0 * a / b if b else 0.0

    print(f"queries      : {n}")
    print(f"answered     : {answered}  ({len(errors)} error rows)")
    print(f"top-1        : {hit1}/{n} = {pct(hit1, n):.2f}%")
    print(f"top-3        : {hit3}/{n} = {pct(hit3, n):.2f}%")
    print(f"AUTO band    : {len(auto)}/{n} = {pct(len(auto), n):.2f}% coverage, "
          f"{auto_hit}/{len(auto)} = {pct(auto_hit, len(auto)):.2f}% precision")
    if ms:
        ms_sorted = sorted(ms)
        print(f"per image    : mean {sum(ms) / len(ms):.0f} ms · "
              f"median {ms_sorted[len(ms_sorted) // 2]} ms · max {max(ms)} ms")

    # Top-1 as a share of the top-3 offers: how often the right plant was on the
    # confirm card at all, and how often it was already the headline.
    missed_top3 = n - hit3
    print(f"not offered  : {missed_top3}/{n} = {pct(missed_top3, n):.2f}% "
          f"(right species absent from all three)")

    if args.by_species:
        per = collections.defaultdict(lambda: [0, 0, 0])
        for r in rows:
            e = per[r["expected"]]
            e[0] += 1
            e[1] += r["hit1"] == "1"
            e[2] += r["hit3"] == "1"
        worst = sorted(per.items(), key=lambda kv: (kv[1][1] / kv[1][0], -kv[1][0]))
        print("\nworst species by top-1 (n>=3):")
        for name, (c, h1, h3) in worst:
            if c >= 3 and h1 < c:
                print(f"  {h1}/{c} top1  {h3}/{c} top3  {name}")

    if args.misses:
        print(f"\nfirst {args.misses} top-1 misses:")
        shown = 0
        for r in rows:
            if r["hit1"] != "1" and shown < args.misses:
                tag = "top3" if r["hit3"] == "1" else "MISS"
                print(f"  [{tag}] {r['file']}: expected={r['expected']} "
                      f"got={r['top1']} ({r['s1']}) {r['error']}")
                shown += 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

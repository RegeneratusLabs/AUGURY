#!/usr/bin/env python3
"""Find overlapping text nodes in a uiautomator dump.

Why this exists: `AuguryCard` was a `Box`, so every child of a card was laid out
at the same position — a section label was drawn underneath the content that
followed it. The card sized itself to its tallest child, so the label contributed
zero height and was invisible (uiautomator sometimes drops it from the tree
entirely). On a real phone that reads as text clashing with text.

Two rules keep this honest:

* Only nodes that carry text/content-desc are compared. Container nodes overlap
  by design.
* A pair is skipped ONLY when one node is a genuine XML ancestor of the other.
  Geometric containment is NOT enough — a short label sitting inside the bounds
  of a tall paragraph is exactly the bug being hunted, so it must be reported.

Usage:
    adb shell uiautomator dump /sdcard/d.xml && adb pull /sdcard/d.xml /tmp/d.xml
    python3 tools/check_screen_overlaps.py /tmp/d.xml \
        --package au.org.regeneratus.augury --tag "Story"

`--package` matters: without it the launcher's own nodes are reported, and its
workspace node carries a content-desc whose bounds contain every icon.
"""
from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET

BOUNDS_RE = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


def rect(node) -> tuple[int, int, int, int] | None:
    m = BOUNDS_RE.match(node.get("bounds") or "")
    if not m:
        return None
    x1, y1, x2, y2 = (int(g) for g in m.groups())
    return (x1, y1, x2, y2)


def label(node) -> str:
    text = (node.get("text") or "").strip()
    desc = (node.get("content-desc") or "").strip()
    return text or desc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dump")
    ap.add_argument("--min-overlap-px", type=int, default=4,
                    help="ignore overlaps smaller than this on either axis")
    ap.add_argument("--tag", default="", help="label printed with the report")
    ap.add_argument("--package", default="",
                    help="only consider nodes owned by this package (ignores the launcher/system UI)")
    args = ap.parse_args()

    root = ET.parse(args.dump).getroot()

    parent: dict[int, int] = {}
    for p in root.iter("node"):
        for c in p:
            if c.tag == "node":
                parent[id(c)] = id(p)

    def is_ancestor(a, b) -> bool:
        cur = parent.get(id(b))
        while cur is not None:
            if cur == id(a):
                return True
            cur = parent.get(cur)
        return False

    nodes = []
    for node in root.iter("node"):
        r = rect(node)
        text = label(node)
        if r is None or not text:
            continue
        if args.package and node.get("package") != args.package:
            continue
        nodes.append((node, r, text))

    clashes = []
    for i, (na, ra, ta) in enumerate(nodes):
        for nb, rb, tb in nodes[i + 1:]:
            if is_ancestor(na, nb) or is_ancestor(nb, na):
                continue
            w = min(ra[2], rb[2]) - max(ra[0], rb[0])
            h = min(ra[3], rb[3]) - max(ra[1], rb[1])
            if w >= args.min_overlap_px and h >= args.min_overlap_px:
                clashes.append((ta, ra, tb, rb, w, h))

    where = f" [{args.tag}]" if args.tag else ""
    if not clashes:
        print(f"OK{where}: {len(nodes)} text nodes, no overlapping pairs")
        return 0

    print(f"CLASH{where}: {len(clashes)} overlapping pair(s) among {len(nodes)} text nodes")
    for ta, ra, tb, rb, w, h in clashes:
        print(f"  {ta[:46]!r} {ra}")
        print(f"    over {tb[:46]!r} {rb}  ({w}x{h}px)")
    return 1


if __name__ == "__main__":
    sys.exit(main())

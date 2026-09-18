#!/usr/bin/env python3
"""AUGURY — tests that tracked artifacts stay portable and honest.

Why this exists
---------------
Auditing this workspace cost real time because files disagreed with reality:
empty directories that looked like data, scripts pointing at paths from a previous
layout, and a project summary describing an architecture that no longer existed.
Those are *misleading*, not merely untidy — a fresh clone wastes the same time
rediscovering each one.

Two properties are pinned here:

1. **Portability.** Tracked files must not embed the author's home directory.
   `au_split.json` carried `"images_dir": "/home/jthomson/AUGURY/..."` while every
   per-image entry beside it was already repo-relative, so the absolute path added
   no information and broke the artifact on any other machine.

2. **Honesty of documentation.** Any doc that describes a superseded layout or
   architecture must say so, so a reader does not act on it.

The third-party field-test report and its RUNBOOK are deliberately exempt from (1):
they record the machine the independent test actually ran on, which is provenance,
not leakage.

Pure and offline. Run:
    .venv-mcpmv46/bin/python tests/test_workspace_hygiene.py
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Files that legitimately record the test host as provenance.
PROVENANCE_EXEMPT = ("data/thirdparty/report-augury-thirdparty-test.md",
                     "data/thirdparty/RUNBOOK.md")

HOME_PATH_RE = re.compile(r"/home/[A-Za-z0-9_.-]+/")


def _tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True)
    return [l for l in out.stdout.splitlines() if l.strip()]


def test_no_tracked_file_embeds_a_home_directory():
    """Tracked artifacts must be portable across machines."""
    offenders = []
    for rel in _tracked_files():
        if rel in PROVENANCE_EXEMPT:
            continue
        p = ROOT / rel
        if not p.is_file() or p.stat().st_size > 2_000_000:
            continue
        try:
            text = p.read_text(errors="ignore")
        except OSError:
            continue
        if HOME_PATH_RE.search(text):
            offenders.append(rel)
    assert offenders == [], (
        f"{len(offenders)} tracked file(s) embed a home directory: {offenders[:8]}"
    )


def test_au_split_is_portable_and_unchanged_in_substance():
    """The benchmark split must be repo-relative and still complete."""
    doc = json.loads((ROOT / "data" / "vision" / "au_split.json").read_text())
    assert not doc["images_dir"].startswith("/"), (
        f"images_dir must be repo-relative, got {doc['images_dir']!r}"
    )
    assert doc["images_dir"] == "data/vision/images", doc["images_dir"]
    assert doc["counts"]["species"] == 186, doc["counts"]["species"]
    assert doc["counts"]["queries"] == 916, doc["counts"]["queries"]
    assert doc["counts"]["gallery"] == 13358, doc["counts"]["gallery"]


def test_merge_report_target_is_relative():
    doc = json.loads((ROOT / "data" / "research" / "enriched-merge-report.json").read_text())
    assert not doc["target"].startswith("/"), doc["target"]
    assert doc["target"] == "data/research/database-merged.json", doc["target"]


GALLERY = ROOT / "data" / "vision" / "images"


def test_no_dead_empty_directories_outside_the_gallery():
    """An empty dir that looks like a data source is a trap, not tidiness.

    "Empty" means no files *anywhere beneath* it — a parent such as `data/sources`
    that holds files in subdirectories is not a dead directory.

    The gallery is excluded on purpose: its empty species directories are a *real,
    tracked* data gap (`pull_inaturalist` found no research-grade photos), not
    junk. `scripts/cleanup_workspace.py` deliberately preserves them. They are
    pinned by the next test instead, so they stay visible rather than being
    silently cleaned away.
    """
    if GALLERY.exists():
        gallery_prefix = str(GALLERY.relative_to(ROOT)) + "/"
    else:
        gallery_prefix = "data/vision/images/"

    dead = []
    for p in (ROOT / "data").rglob("*"):
        if not p.is_dir():
            continue
        rel = str(p.relative_to(ROOT)) + "/"
        if rel.startswith(gallery_prefix):
            continue
        if not any(f.is_file() for f in p.rglob("*")):
            dead.append(rel)
    # A directory is only dead if none of its children are listed either.
    minimal = [d for d in dead if not any(o != d and o.startswith(d) and o not in dead
                                          for o in dead)]
    assert minimal == [], f"dead empty directories under data/: {minimal}"


def test_gallery_empty_species_dirs_are_the_known_data_gap():
    """Pin the real gap: species known to the DB with no gallery images."""
    if not GALLERY.is_dir():
        return  # gallery is local-only and gitignored
    empty = sorted(p.name for p in GALLERY.iterdir()
                   if p.is_dir() and not any(p.iterdir()))
    # 49 after the 8 junk-key dirs were removed (was 57).
    assert len(empty) <= 49, (
        f"empty species dirs grew to {len(empty)} (expected <=49); "
        f"either new junk keys appeared or acquisition regressed. First: {empty[:5]}"
    )


def test_superseded_scripts_say_so():
    """A dead script must announce itself rather than fail cryptically."""
    for rel in ("scripts/merge_research.py", "scripts/merge_research_data.py"):
        text = (ROOT / rel).read_text()
        assert "SUPERSEDED" in text, f"{rel} does not mark itself superseded"
        assert "merge_research_indicators.py" in text, (
            f"{rel} should point at the replacement"
        )


def test_superseded_scripts_point_at_existing_paths():
    """Their path constants must resolve, so provenance runs are not misleading."""
    for rel in ("scripts/merge_research.py", "scripts/merge_research_data.py"):
        text = (ROOT / rel).read_text()
        assert "/home/" not in text, f"{rel} still hardcodes a home directory"
        assert "parent.parent" in text, f"{rel} should derive its root from __file__"


def test_project_summary_is_marked_historical():
    """docs/PROJECT.md describes the pass-1/V3 era; it must say so."""
    text = (ROOT / "docs" / "PROJECT.md").read_text()
    assert "HISTORICAL" in text.upper(), "PROJECT.md is not marked historical"
    assert "superseded" in text.lower(), "PROJECT.md should name its successor docs"


def test_no_duplicate_title_lines_in_docs():
    """A repeated paragraph is a symptom of hand-editing drift."""
    offenders = []
    for p in (ROOT / "docs").glob("*.md"):
        lines = [l.strip() for l in p.read_text().splitlines() if len(l.strip()) > 80]
        seen = set()
        for l in lines:
            if l in seen:
                offenders.append(f"{p.name}: {l[:60]}...")
                break
            seen.add(l)
    assert offenders == [], f"docs contain verbatim duplicated long lines: {offenders}"


def main() -> int:
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failures = []
    for name, fn in tests:
        try:
            fn()
            print(f"  [PASS] {name}")
        except AssertionError as e:
            failures.append((name, str(e)))
            print(f"  [FAIL] {name}\n         {e}")
        except Exception as e:  # noqa: BLE001
            failures.append((name, f"{type(e).__name__}: {e}"))
            print(f"  [ERROR] {name}\n         {type(e).__name__}: {e}")
    print(f"\n{len(tests)-len(failures)}/{len(tests)} workspace-hygiene tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

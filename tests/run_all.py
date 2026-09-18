#!/usr/bin/env python3
"""AUGURY — run the whole test suite.

Every test file here is stdlib-only, offline, and deterministic: this venv has no
pytest and no pip, matching the repo's existing script-based convention. Model- and
GPU-dependent checks (the GGUF formatter, encoder embedding) are deliberately NOT
part of this suite — see data/thirdparty/RUNBOOK.md for those gates, which must run
as separate processes because this host cannot hold the encoder and the GGUF
resident at once (~5 GB free RAM).

Run:
    .venv-mcpmv46/bin/python tests/run_all.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent


def main() -> int:
    files = sorted(p for p in TESTS.glob("test_*.py"))
    if not files:
        print("[tests] no test files found")
        return 1

    failed = []
    for f in files:
        print(f"\n{'='*70}\n{f.name}\n{'='*70}")
        r = subprocess.run([sys.executable, str(f)], cwd=str(ROOT))
        if r.returncode != 0:
            failed.append(f.name)

    print(f"\n{'='*70}")
    if failed:
        print(f"[tests] FAILED: {', '.join(failed)}")
        return 1
    print(f"[tests] all {len(files)} test file(s) passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

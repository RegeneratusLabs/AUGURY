#!/usr/bin/env python3
"""AUGURY — tests for the single-file HTML app (`augury.html`).

The app is a build artefact, so these checks are about the artefact rather than
about a running browser:

  1. **Self-contained.** No external script/link/img/iframe, and no network API
     in the page. If this fails, the promise "one file, offline" is broken.
  2. **Reproducible.** Rebuilding from the same sources with the artefact's own
     recorded build date must reproduce it byte for byte. If this fails, either
     the committed page is stale or the builder is non-deterministic.
  3. **Grounded.** Every species key in the source database is present in the
     page, and every region row carries indicator values. The app must not be
     able to show a reading the database does not contain.
  4. **Referenced.** The database's own provenance survives into the page: the
     species that carry recorded sources still carry them, with URLs, and the
     region lineage is declared.

The JavaScript core (search, region policy, rendering) is covered by
`scripts/app/singlefile/test_app.js`, which this test runs under node when node
is available — the app's own half is not re-implemented here.

Run:
    .venv-mcpmv46/bin/python tests/test_singlefile_app.py
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "augury.html"
BUILDER = ROOT / "scripts" / "app" / "build_singlefile_app.py"
JS_TEST = ROOT / "scripts" / "app" / "singlefile" / "test_app.js"

failures: list[str] = []
checks = 0


def ok(name: str, cond: bool, detail: str = "") -> None:
    global checks
    checks += 1
    if cond:
        print(f"  \u2713 {name}")
    else:
        failures.append(name)
        print(f"  \u2717 {name}" + (f"  \u2014 {detail}" if detail else ""))


def load_builder():
    spec = importlib.util.spec_from_file_location("build_singlefile_app", BUILDER)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def embedded_payload(html: str) -> dict:
    m = re.search(r'<script id="augury-db" type="application/json">(.*?)</script>', html, re.S)
    assert m, "embedded database block not found"
    return json.loads(m.group(1).replace("<\\/", "</"))


def main() -> int:
    builder = load_builder()

    print("artefact")
    if not APP.is_file():
        print(f"  [FAIL] {APP} does not exist — run scripts/app/build_singlefile_app.py")
        return 1
    html = APP.read_text(encoding="utf-8")
    ok("augury.html exists and is a single file", True)
    ok("it is a complete HTML document", html.lstrip().startswith("<!doctype html") and "</html>" in html)
    ok("it has no external asset references", not builder.EXTERNAL_RE.search(html))
    for banned in ("fetch(", "XMLHttpRequest", "sendBeacon", "WebSocket("):
        ok(f"it makes no network call via {banned}", banned not in html)
    ok("it does not load a model or WASM runtime",
       not re.search(r"\.(wasm|onnx|gguf|bin)\b", html, re.I))

    payload = embedded_payload(html)
    meta = payload["meta"]
    ok("the embedded database parses as JSON", bool(payload.get("species")))
    ok("every species record is well formed",
       all(isinstance(s.get("k"), str) and isinstance(s.get("s"), str) for s in payload["species"]))

    print("\ngrounded in the database")
    db = json.loads((ROOT / "data" / "research" / "database-merged.json").read_text(encoding="utf-8"))
    page_keys = {s["k"] for s in payload["species"]}
    ok("every source-database key is embedded", set(db) == page_keys,
       f"missing {len(set(db) - page_keys)}, extra {len(page_keys - set(db))}")
    ok("meta.species_count matches the array", meta["species_count"] == len(payload["species"]))

    empty_rows = 0
    for s in payload["species"]:
        for r in s.get("r") or []:
            if not r.get("i"):
                empty_rows += 1
    ok("no region row is embedded empty", empty_rows == 0, f"{empty_rows} empty rows")

    # The app must not invent a reading: sample real rows back against the DB.
    mismatches = 0
    sampled = 0
    for key in ("taraxacum officinale", "lycium ferocissimum", "cirsium vulgare"):
        rec = db.get(key)
        if not rec:
            continue
        entry = next((s for s in payload["species"] if s["k"] == key), None)
        assert entry is not None
        for region, rv in (rec.get("regions") or {}).items():
            inds = (rv or {}).get("indicators") or {}
            if not inds:
                continue
            row = next((r for r in entry["r"] if r["n"] == region), None)
            sampled += 1
            if row is None or row["i"] != inds:
                mismatches += 1
    ok("sampled indicator rows are byte-identical to the database",
       sampled > 0 and mismatches == 0, f"{mismatches}/{sampled} differ")

    print("\nreferences survive")
    src_species = [k for k, v in db.items() if (v.get("provenance") or {}).get("sources")]
    ok("the database has species with recorded provenance to carry", len(src_species) > 0)
    carried = [s for s in payload["species"] if (s.get("p") or {}).get("s")]
    ok("all of them carry it into the page", len(carried) >= len(src_species),
       f"{len(carried)} < {len(src_species)}")
    with_urls = [s for s in carried if any(x.get("u") for x in s["p"]["s"])]
    ok("recorded sources keep their URLs", len(with_urls) > 0)
    ok("a global source registry is embedded", len(payload.get("sources") or {}) > 0)
    ok("region lineage is declared for every region in the data",
       all(r in payload.get("lineage", {}) for r in meta["regions"]),
       f"{meta['regions']} vs {sorted(payload.get('lineage', {}))}")
    detected = sum(len(r.get("src") or {}) for s in payload["species"] for r in (s.get("r") or []))
    ok("inline-named sources were detected in evidence text", detected > 0, f"{detected} data points")
    ok("every detected source names a data point that exists in its region row",
       all(k in r["i"] for s in payload["species"] for r in (s.get("r") or [])
           for k in (r.get("src") or {})))

    print("\nuser-facing copy")
    # The page explains what it does; it does not argue with a straw man. These
    # phrases were removed deliberately (no-AI / no-model / offline sloganeering),
    # and the technical identity is one level down, under "Technical details".
    for phrase in ("No AI", "no guessing", "no model", "no network", "Offline single file",
                   "Database rows merged", "not generated"):
        ok(f"the page never says “{phrase}”", phrase.lower() not in html.lower())
    ok("the database identity is still disclosed", meta["db_sha256"] in html)
    ok("it is disclosed under a collapsible Technical details panel", "Technical details" in html)
    ok("the app offers a reading-level copy control", 'data-act="copy"' in html)
    ok("the app offers a how-it-works panel", 'id="how"' in html and 'id="howBtn"' in html)

    print("\nreproducible build")
    rebuilt = builder.render(
        builder.build_payload(db,
                              json.loads((ROOT / "data" / "research" / "common_name_synonyms.json").read_text())["synonyms"],
                              json.loads((ROOT / "data" / "vision" / "canonical_map.json").read_text())["canonical"],
                              ROOT / "data" / "research" / "database-merged.json",
                              build_date=meta["build_date"]),
        (ROOT / "scripts" / "app" / "singlefile" / "app_template.html").read_text(encoding="utf-8"),
        (ROOT / "scripts" / "app" / "singlefile" / "app.js").read_text(encoding="utf-8"),
    )
    ok("rebuilding reproduces the committed file byte for byte", rebuilt == html,
       f"{len(rebuilt)} vs {len(html)} bytes — re-run scripts/app/build_singlefile_app.py")

    print("\nembedded database identity")
    import hashlib
    digest = hashlib.sha256((ROOT / "data" / "research" / "database-merged.json").read_bytes()).hexdigest()
    ok("the page records the real sha256 of its source database", meta["db_sha256"] == digest)

    print("\njavascript core")
    node = shutil.which("node")
    if node is None:
        print("  \u2022 skipped — node not on PATH (run scripts/app/singlefile/test_app.js manually)")
    else:
        r = subprocess.run([node, str(JS_TEST), str(APP)], cwd=str(ROOT),
                           capture_output=True, text=True)
        tail = (r.stdout or "").strip().splitlines()[-1:] or [""]
        ok("the JS core checks pass under node", r.returncode == 0,
           tail[0] if r.returncode else "")
        if r.returncode != 0:
            print(r.stdout)
            print(r.stderr)

    print(f"\n{len(failures)} failed, {checks - len(failures)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

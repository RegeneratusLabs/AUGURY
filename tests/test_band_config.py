#!/usr/bin/env python3
"""AUGURY — tests for the confidence-band runtime config.

The defect these tests pin down
-------------------------------
`calibrate_bands.py` wrote its output to `band_calibration.json`, but
`photo_id.PhotoID` reads `<index-dir>/band_config.json`. For `index-v3` only the
first was ever produced, so PhotoID silently fell back to the legacy constants:

    PhotoID('data/vision/index-v3').band_config
      -> {'auto_conf': 0.8, 'confirm_conf': 0.6, 'calibrated': False}

That is the *same* failure mode the v2 README warns about. On the whitened score
scale, precision peaks near 0.68 and **falls above 0.75**, so 0.80 selects the
worst decile — and in a UI it would push almost every photo out of the top band
and nag the user to confirm even when the model is 95% sure.

The invariant, stated once
--------------------------
If a calibration run happened for an index (there is a `band_calibration.json`),
then the runtime config must exist too, must be well-formed, and **must agree with
the audit trail**. Those two files describing different thresholds is the bug.

Pure: no encoder, no model weights, no network, no faiss. Stdlib only — this venv
has no pytest and no pip, matching the repo's script-based convention.

Run:
    .venv-mcpmv46/bin/python tests/test_band_config.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VISION = ROOT / "data" / "vision"

# The legacy constants, restated here so this file fails loudly if anyone drags
# them back into a whitened index. See photo_id.AUTO_CONF.
LEGACY_AUTO = 0.80
LEGACY_CONFIRM = 0.60

# Thresholds measured for each shipped index. These are regression pins: if a
# rebuild legitimately changes them, update this table *and* say why in the
# commit message. Never widen it just to make a test pass.
#
# index-v3 updated 2026-09-19: the gallery was re-pulled so that the ten AU
# species whose images were 100% unvalidated full-text hits now resolve through
# validated taxon ids. That lifted top-1 from 81.8% to 85.9% and moved the
# calibrated bands from 0.68/0.43 to 0.64/0.30 (auto: 95.4% precision at 63.7%
# coverage). Update the pin, never the artifact, when the index legitimately
# changes.
EXPECTED = {
    "index-v2": {"auto_conf": 0.65, "confirm_conf": 0.44},
    "index-v3": {"auto_conf": 0.64, "confirm_conf": 0.30},
}


def _index_dirs() -> list[Path]:
    return sorted(p for p in VISION.glob("index*") if p.is_dir())


def _audit_dirs() -> list[Path]:
    """Directories holding a calibration audit trail."""
    dirs = [p for p in VISION.glob("index*") if p.is_dir()
            and (p / "band_calibration.json").exists()]
    if (VISION / "band_calibration.json").exists():
        dirs.append(VISION)
    return sorted(set(dirs))


def test_calibrated_indexes_have_a_runtime_config():
    """Every index that was calibrated must also ship the config PhotoID reads.

    This is the exact omission that left index-v3 running on the legacy 0.80.
    """
    missing = []
    for d in _audit_dirs():
        # A calibration written next to the repo root belongs to whichever index
        # its own JSON names; those are covered by test below.
        if d == VISION:
            continue
        if not (d / "band_config.json").exists():
            missing.append(d.name)
    assert missing == [], (
        f"{len(missing)} calibrated index(es) have no band_config.json, so PhotoID "
        f"silently uses the legacy {LEGACY_AUTO}/{LEGACY_CONFIRM} constants: {missing}"
    )


def test_runtime_config_is_well_formed():
    """Required keys present, thresholds ordered, values in range."""
    problems = []
    for d in _index_dirs():
        cfg_path = d / "band_config.json"
        if not cfg_path.exists():
            continue
        cfg = json.loads(cfg_path.read_text())
        for key in ("auto_conf", "confirm_conf", "calibrated"):
            if key not in cfg:
                problems.append(f"{d.name}: missing {key!r}")
        if "auto_conf" in cfg and "confirm_conf" in cfg:
            auto, confirm = cfg["auto_conf"], cfg["confirm_conf"]
            if not 0.0 < confirm < auto < 1.0:
                problems.append(
                    f"{d.name}: thresholds out of order ({confirm} !< {auto})")
    assert problems == [], f"malformed band_config.json: {problems}"


def test_runtime_config_agrees_with_audit_trail():
    """The two files must not describe different thresholds.

    This is the drift guard. `calibrate_bands.py` now writes both from one
    computation, so a mismatch means someone hand-edited one of them.
    """
    mismatches = []
    for d in _audit_dirs():
        cfg_path = d / "band_config.json"
        audit_path = d / "band_calibration.json"
        if not (cfg_path.exists() and audit_path.exists()):
            continue
        cfg = json.loads(cfg_path.read_text())
        audit = json.loads(audit_path.read_text())
        for key in ("auto_conf", "confirm_conf"):
            if key not in cfg or key not in audit:
                continue
            if abs(float(cfg[key]) - float(audit[key])) > 1e-9:
                mismatches.append(
                    f"{d.name}: {key} config={cfg[key]} audit={audit[key]}")
    assert mismatches == [], f"band config has drifted from its audit trail: {mismatches}"


def test_never_legacy_constants_on_a_whitened_index():
    """0.80 / 0.60 must not appear as a live threshold on a whitened index.

    They were chosen for raw-cosine v1 scores. On the whitened scale they select
    the worst decile, and the v2 README documents this explicitly.
    """
    offenders = []
    for d in _index_dirs():
        cfg_path = d / "band_config.json"
        if not cfg_path.exists():
            continue
        cfg = json.loads(cfg_path.read_text())
        if cfg.get("calibrated") is not True:
            offenders.append(f"{d.name}: calibrated is not True ({cfg.get('calibrated')!r})")
            continue
        auto = float(cfg.get("auto_conf", 0))
        confirm = float(cfg.get("confirm_conf", 0))
        if abs(auto - LEGACY_AUTO) < 1e-9 or abs(confirm - LEGACY_CONFIRM) < 1e-9:
            offenders.append(f"{d.name}: legacy constants still live ({auto}/{confirm})")
    assert offenders == [], "; ".join(offenders)


def test_expected_thresholds_are_pinned():
    """Pin the measured thresholds for the shipped indexes."""
    problems = []
    for name, want in EXPECTED.items():
        cfg_path = VISION / name / "band_config.json"
        if not cfg_path.exists():
            problems.append(f"{name}: no band_config.json")
            continue
        cfg = json.loads(cfg_path.read_text())
        for key, val in want.items():
            got = cfg.get(key)
            if got is None or abs(float(got) - val) > 1e-6:
                problems.append(f"{name}: {key} expected {val}, got {got}")
        if cfg.get("calibrated") is not True:
            problems.append(f"{name}: calibrated is not True")
    assert problems == [], "; ".join(problems)


def test_photo_id_actually_loads_the_calibrated_config():
    """The end-to-end assertion: PhotoID must not fall back to its defaults.

    Imports photo_id without instantiating PhotoID (which would load the encoder
    and faiss). DEFAULT_BAND_CONFIG is what a missing file degrades to, so we
    assert the shipped file beats it.
    """
    sys.path.insert(0, str(ROOT / "scripts" / "vision"))
    try:
        import photo_id  # noqa: PLC0415
    except ImportError as e:  # faiss/torch absent — skip rather than false-fail
        print(f"         (skipped: photo_id unavailable: {e})")
        return

    problems = []
    for name in EXPECTED:
        cfg_path = VISION / name / "band_config.json"
        if not cfg_path.exists():
            problems.append(f"{name}: no band_config.json")
            continue
        cfg = dict(photo_id.DEFAULT_BAND_CONFIG)
        cfg.update(json.loads(cfg_path.read_text()))
        if cfg.get("calibrated") is not True:
            problems.append(f"{name}: PhotoID would report calibrated={cfg.get('calibrated')!r}")
        if abs(float(cfg["auto_conf"]) - LEGACY_AUTO) < 1e-9:
            problems.append(f"{name}: PhotoID would use the legacy {LEGACY_AUTO}")
    assert problems == [], "; ".join(problems)


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
    print(f"\n{len(tests)-len(failures)}/{len(tests)} band-config tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

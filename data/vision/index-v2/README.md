# AUGURY — vision retrieval index v2 (canonical keys + PCA whitening)

Runtime artifact for the photo path. Replaces the v1 index, which scored
**71.8%** top-1 on the AU benchmark.

## What is in here

| File | Contents |
|---|---|
| `index.faiss` | FAISS `IndexFlatIP`, 13,358 vectors × 384-d |
| `keys.json` | canonical species key per vector (duplicate keys merged) |
| `files.json` | source image basename per vector |
| `embeddings.npy` | the same vectors, for rebuilding or re-scoring |
| `pca_whiten.npz` | whitening transform (`W`, `mu`) — **required at query time** |
| `band_config.json` | calibrated confidence thresholds |
| `meta.json` | build provenance |

## Measured performance

Benchmark: `data/vision/au_split.json` — 916 queries, 186 AU species, fixed seed,
every query excluded from its own gallery.

| Configuration | top-1 | top-3 |
|---|---|---|
| v1 (raw DINOv2-base, raw keys) | 71.8% | 86.5% |
| + canonical key merge | 80.8% | 88.5% |
| **v2 shipped `PhotoID`** | **82.4%** | **91.3%** |
| v2 harness measurement | 82.4% | 89.2% |

**The shipped path and the harness agree exactly on top-1: 82.4%.** The
2.2-point discrepancy recorded in `docs/HANDOVER-2026-09-18.md` was fully
explained on 2026-09-19 and was a **label-registry bug, not a retrieval
difference**.

### What the discrepancy actually was

`PhotoID.canonical()` read `canon_map.get(key, alias.get(key, key))`, letting the
legacy v1 `alias_map.json` override canonical merges. Two of its entries reversed
a merge, changing the key by a trailing period:

```
alias["prosopis spp"] = "prosopis spp."   (canonical_map says the reverse)
alias["salix spp"]    = "salix spp."      (canonical_map says the reverse)
```

`keys.json` here stores **canonical** labels, so ground truth was rewritten one
way while predictions were stored the other way. A correct prediction was scored
as a miss. Measured on all 916 queries against these exact artifacts:

| ground-truth definition | top-1 |
|---|---|
| canonical map only (what `bench.py` and `calibrate_bands.py` used) | 0.8242 |
| `PhotoID.canonical()` (canon + alias fallback) | 0.8155 |
| alias-first | 0.8155 |

So calibration used one definition and the "shipped case-by-case" measurement
used another; the two numbers never measured the same function. `resolve_label()`
now treats a label the index serves as its own fixed point, and
`PhotoID.__init__` **raises** if any label resolves outside the index. Regression
tests: `tests/test_label_registry.py` (9 checks, stdlib only).

### Why the top-3 columns differ

Top-3 is higher on the shipped path (91.3% vs 89.2%) because `PhotoID.identify()`
collapses duplicate species within top-k while `bench.py` does not — 809 of 916
queries have a repeated label in their raw top-3. The flat harness figure is the
more conservative one; the shipped figure is what a user actually sees.

## Confidence bands (calibrated)

| Band | Threshold | Share | Measured precision |
|---|---|---|---|
| auto | ≥ 0.65 | 60.9% | 88.7% |
| confirm | 0.44 – 0.65 | 33.1% | 72.3% |
| unknown | < 0.44 | 6.0% | — |

**Precision on this score scale peaks near 0.65 and falls above 0.75**, so the old
0.80 auto-accept threshold selected the worst decile. Do not reintroduce it.

No threshold reaches 95% precision — the encoder ceiling measured 92.3%. An
auto-accept band therefore cannot be honest at this accuracy level; treat the
`auto` band as "higher confidence", not "safe to accept unverified".

## Query contract

```python
from vision.photo_id import PhotoID
pid = PhotoID(index_dir="data/vision/index-v2")   # picks up pca_whiten.npz + band_config.json
pid.identify("weed.jpg", k=3)     # [{key, canonical, score}, ...]
pid.verdict(results)              # auto | confirm | unknown, calibrated
```

`PhotoID` applies the whitening transform automatically when the index ships one.

## Rebuilding

```bash
.venv-mcpmv46/bin/python scripts/vision/cache_embeddings.py --backend dinov2-base \
    --split data/vision/au_split.json
.venv-mcpmv46/bin/python scripts/vision/fit_pca.py
.venv-mcpmv46/bin/python scripts/vision/build_index_v2.py
.venv-mcpmv46/bin/python scripts/vision/calibrate_bands.py
```

## Known limits

- **AU-scoped**: 174 canonical AU species. Extending to the full 2,174-species
  gallery is untested.
- **Not the 90% target.** Reaching it needs GPU-backed encoder fine-tuning or a
  denser per-species gallery; SigLIP2 fusion and DINOv2-large were both measured and
  are infeasible on CPU (~0.17 img/s).
- Gallery images are licensed per-image (`data/vision/images/<key>/sources.jsonl`);
  the aggregate is non-commercial. Only the compact index is a runtime artifact.

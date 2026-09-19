# Photo-ID measurement log

Every figure here is measured, and every before/after uses a fixed query set with a
leakage check. Rebuilding the split reshuffles which images are held out, so scores
from two different splits are NOT comparable — a naive comparison on this project
reported 97.88% when the honest number was +1.1 points.

## 2026-09-19 — index-v3 on validated galleries (current)

Gallery 16,580 images / 184 species, 920 held-out queries. **Leakage check: 0 of the
920 query files appear in the gallery.**

| metric | value |
|---|---|
| top-1 | **85.9%** |
| top-3 | 89.7% |
| auto band (t=0.64) | 95.4% precision, 63.7% coverage |
| confirm band (t=0.30) | 69.6% precision, 36.1% coverage |

## Trajectory

| build | gallery | top-1 | note |
|---|---|---|---|
| v1 raw keys | 13,358 | 71.8% | label fragmentation |
| v2 + canonical keys + PCA | 13,358 | 82.4% | labels were also cross-contaminated |
| v3 cleaned | 13,448 | 81.8% | contamination repaired; 4 species unlearnable -> working |
| **v3 validated** | **16,580** | **85.9%** | 10 unvalidated fallback galleries re-pulled |

## What moved the number

Not image count. Ten AU species had galleries built from an **unvalidated
free-text search** (files with a `q` prefix), i.e. whatever iNaturalist returned:

    callistemon spp 11/11, austrostipa spp 47/47, hakea spp 45/45,
    banksia spp 50/50, dianella spp 48/48, lepidosperma spp 50/50,
    gahnia spp 50/50, cirsium spp 50/50, opuntia spp 50/50,
    austrodanthonia spp 11/11

`lepidosperma spp` (a sedge) contained a pink poppy. These were also the worst
performers: callistemon 0%, austrostipa 20%, hakea 20%, banksia 40%.

After re-pulling them with a validated genus matcher (8 exact, 2 via genus synonym:
*Austrodanthonia* -> *Rytidosperma*, *Callistemon* -> *Melaleuca*), an independent
visual sample of 125 images found **124 plausible (99.2%)**.

## Image quality audit (all 111,302 images)

Cheap metrics over the whole gallery, then a visual review of the flagged subset
(a full visual pass would be ~111k model calls):

* 111,302 measured, **0 unreadable**.
* 4,619 shortlisted (4.15%) — ranked within resolution strata, because raw blur
  ranking just re-discovers the 256x256 DeepWeeds subset.
* 384 of those fall inside the AU benchmark; 20 parallel subagents reviewed them.
* Confirmed real defects: microscope views of dissected spikelets, herbarium twigs
  on cloth, near-black underexposed frames, scenery with no identifiable plant.
* 6 images flagged as **mislabelled** (e.g. a pink poppy in a sedge folder) — all of
  them inside the unvalidated `q`-prefix galleries.

## Remaining gap to 90%

4.1 points. Density modelling says reaching 90% by gallery size alone is tight:
taking every species currently below 90% to exactly 90% yields ~89.3%. The validated
acquisition path now exists, so densification can proceed (target 300/species,
~46k images, measured download throughput ~24-70 images/min single-stream).

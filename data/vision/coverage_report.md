# AUGURY Vision — coverage report

_Generated 2026-08-08 — preliminary; regenerate after the acquisition pass._

- Species list (canonical): **2230** (AU-tagged: **188**)
- Images on disk: **111320** (train dirs) + **12321** (unknown/refusal dirs)

## Per-source coverage

| Source | Coverage | Notes |
|---|---|---|
| Pl@ntNet-300K | 155 species (16 AU) | French-flora benchmark; name-mapped via species2plantnet.json; images NOT pulled (see handover) |
| DeepWeeds | 5 classes in DB + 3 unknown + Negative | CC BY 4.0, northern-AU weeds |
| iNaturalist | 2185 species covered so far (0 not run) | research-grade, throttled pull |
| GBIF media (probe n=10) | 1 with media (avg 1 imgs) | gap-filler for iNat misses |

## iNaturalist status histogram (current)

| status | species |
|---|---|
| done | 2153 |
| no_images | 45 |
| partial | 32 |

## Target policy

- Per-species target: 30–50 images (floor 10 → status done/partial)
- AU + cosmopolitan weeds prioritized first (--au-first)
- Species below floor or with zero images anywhere are documented here and excluded from the vision label set
- Unknown/refusal layer: DeepWeeds negative class + Chinee apple / Snake weed / Siam weed
# AUGURY

**Name the weed, read the soil.** AUGURY maps a weed species to the soil
conditions it indicates — moisture, pH, fertility, structure, salinity, nutrient
status — from a researched species database. Indicators only. No management
advice.

**The app is one HTML file.** `augury.html` — ~1 MB, opens from `file://`, works
with no server, no install, no network, and no model. You type a weed's name
(common or scientific) and get the reading the database holds for it, with the
source of every data point shown next to it.

```
open augury.html          # that is the whole install
```

> "The plant is the mirror of the soil." — Gérard Ducerf

---

## What the pivot changed

The project previously shipped a photo-identification pipeline (DINOv2 + kNN over
a 15 GB image gallery, a 346 MB encoder download) and a fine-tuned MiniCPM5-1B
formatter. Both are now **out of the product**, deliberately:

| Then | Now |
|---|---|
| Photograph a weed → embedding → kNN → top-3 shortlist → tap to confirm | **Type the name.** Common or scientific, fuzzy-matched, no camera, no 372 MB encoder |
| A 688 MB language model wrote the answer in prose | **Nothing generates the answer.** The app prints the database's own row |
| Facts could drift from the database; a grounding pass existed to catch it | The answer *is* the database row. There is no step in which a fact can change |
| ~372 MB first-launch download | **~1 MB**, one file |
| Answer provenance implicit | **Every row shows its evidence and its source**, and the page records the sha256 of the database it was built from |

The reason is in `docs/RELEASE-DECISION-2026-10-08.md`: the photo path reached
173 of 2,256 species (7.7%), needed 368 MB to do it, carried an unresolved
CC-BY-NC licensing question, and ended — structurally — at a species the user
taps anyway. The name path reaches all 2,223 species with indicator data, in one
file, with no model in the loop.

The old components still exist in the tree for provenance (see
[Legacy](#legacy-kept-for-provenance)); they are not part of the app.

---

## What an answer looks like

For **Dandelion** (*Taraxacum officinale*), region Australia:

```
Moisture    fresh to moist
Ph          wide range, weakly acid to neutral
Fertility   high fertility, N-rich
Structure   compacted; taproot breaks compaction
Salinity    None
```

Each row has an **Evidence** control that opens the verbatim string the database
stores, and the sources it was read from. Below the reading:

- **Nutrient claims** — one row per recorded claim, each with its own source and
  a confidence badge (251 claims across 78 species).
- **Where this came from** — the sources recorded against *this species*, with
  URLs and the exact indicator each was used for ("Read for: Soil type,
  Moisture, Disturbance"), plus any source named inside the evidence text, plus
  the region's declared pipeline lineage.
- **How to read this** — the database path, its sha256, and the matched key, so
  any answer can be traced back to the bytes it came from.

### How provenance is graded — and not overstated

The database does not record a per-row source for every row, so the app never
pretends it does. Three levels are distinguished in the UI:

| Level | Meaning |
|---|---|
| **Recorded** | The species carries `provenance.sources` in the database: a named document, usually a URL, and the indicators it was read for. 33 species today, all Australian. |
| **Named in the evidence** | The evidence string itself names its source (NSW DPIRD, HerbiGuide, Weeds Australia, AWRI, GRDC, PIRSA…). Detected by word-boundary match, shown as a chip. |
| **Pipeline default** | The dataset-level lineage for that region, labelled as such: Ellenberg Indicator Values (1991) for Europe, Maughan & Amos (2022, 2024) + CAWR for the UK, the Australian research/mining layer for AU. Recorded at the dataset level, *not* per species — and the app says so. |

---

## Build it

```bash
python3 scripts/app/build_singlefile_app.py            # writes augury.html
python3 scripts/app/build_singlefile_app.py --check    # verify without writing
```

Inputs: `data/research/database-merged.json` (the facts),
`common_name_synonyms.json` (curated vernacular names), `data/vision/canonical_map.json`
(duplicate keys → one plant), plus the template and script in
`scripts/app/singlefile/`. The builder measures the database's sha256 and byte
count from the file it embeds; nothing is typed in by hand.

## Test it

```bash
python3 tests/test_singlefile_app.py        # artefact: self-contained, reproducible, grounded
node scripts/app/singlefile/test_app.js     # the app's own search + lookup core
python3 tests/run_all.py                    # the whole repo suite
```

The JS core is DOM-free on purpose, so the same code that ships in the page runs
under node. The Python test rebuilds the page from source and asserts it is
byte-identical to the committed file, so a stale artefact fails the suite.

## What is in the database

| | |
|---|---|
| Species | 2,256 keys; **2,223 with indicator data** |
| Regions | Australia (221), UK (82), Europe (2,102) |
| Indicator keys | `Moisture`, `Soil pH`, `Ph`, `Fertility`, `Structure`, `Salinity`, `Organic matter`, `Soil type`, `Disturbance`, `General indicators`, `Other indicators`, `Species` |
| Nutrient claims | 251, each with its own source and confidence |
| Vernacular names | 227 in the database + 158 curated synonyms |

Free-form indicator keys: the app renders whatever keys exist, so a new dimension
needs no code change. Values are never normalised, merged or rewritten.

**Coverage, stated honestly.** Only 227 of 2,256 records carry a genuine
vernacular name (the rest repeat the binomial), so a name search is backed by the
scientific name and by 158 curated synonyms; a typo gets a deterministic
"did you mean" rather than a guess. 17 records have no indicator data at all, and
the app says so instead of inventing a reading. Genus-level matches (e.g.
"thistles" → *Cirsium* spp.) are disclosed as genus-level. Region fallback is
disclosed too: ask for Australian data on a European species and the app tells
you it is showing European data and why.

---

## Legacy (kept for provenance)

These are **not** part of the app and are not required to build or run it:

- `augury-android/` — the Compose app, including the photo path and the
  artifact-download pipeline. Its `SpeciesStore.kt` is the reference
  implementation the app's JS search is ported from.
- `scripts/augury_funnel.py`, `scripts/species_lookup.py`, `scripts/plant_id.py`,
  `scripts/vision/` — the text funnel, the DB lookup, the photo-ID pipeline.
- `scripts/train_*.py`, `data/training/`, `data/vision/` — the formatter training
  corpus and the 15 GB image gallery (gallery is local-only and gitignored).
- `docs/` — the research record: `RELEASE-DECISION-2026-10-08.md`,
  `technical-stack.md`, `model-understanding-and-blindspots.md`, the handovers.

## Docs

- [Single-file app — design & data contract](docs/SINGLEFILE-APP.md)
- [Release decision: ship the database, park the model](docs/RELEASE-DECISION-2026-10-08.md)
- [Technical stack](docs/technical-stack.md) · [Data roadmap](docs/data-roadmap.md) ·
  [Model understanding & blind spots](docs/model-understanding-and-blindspots.md)

## License

Apache-2.0 (code) · CC-BY-4.0 (database) · individual sources cited per answer.
The vision gallery is non-commercial aggregate with per-image license sidecars
(iNat cc-by-nc photos) and is not redistributed by the app.

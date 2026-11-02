# AUGURY

**Name the weed, read the soil.** AUGURY maps a weed species to the soil
conditions it indicates — moisture, pH, fertility, structure, salinity, nutrient
status — from a researched species database. Indicators only. No management
advice.

**The app is one HTML file.** `augury.html` — ~1 MB, opens from `file://`, works
with no server, no install, no network, and no model. You type a weed's name
(common or scientific) and get the reading the database holds for it, with the
source of every data point shown next to it. The interface says that in plain
language: it shows you the reading and its sources rather than announcing what it
is not.

```
open augury.html          # that is the whole install
```

> "The plant is the mirror of the soil." — Gérard Ducerf

---

## What ships, and what is still in progress

The working example is the single file. Two model tracks live in this tree, and
neither one is what you run:

| Track | State | Why it is not the thing you use yet |
|---|---|---|
| **Name lookup — one HTML file** (`augury.html`) | **Shipped. This is the project.** | — |
| **Photo identification** — DINOv2 embeddings + kNN over a curated gallery | **In progress, gated on accuracy** | 85.87% top-1 on the AU holdout it was calibrated on, but **60% top-1 on 20 fresh third-party photos** it had never seen. Reaches **173 of 2,256 species (7.7%)** and no European or UK species at all, for **~372 MB** installed |
| **Fine-tuned generator** — MiniCPM5-1B formatter | **In progress, gated on accuracy and grounding** | every answer it wrote had to be checked back against the database by a separate grounding pass. A generator that must be audited to be trusted is a slower route to the same row |

Both tracks stay in the tree and continue. What changed is what ships: the app
does not wait for either of them.

| Then | Now |
|---|---|
| Photograph a weed → embedding → kNN → top-3 shortlist → tap to confirm | **Type the name.** Common or scientific, fuzzy-matched, no camera, no 372 MB encoder |
| A 688 MB language model wrote the answer in prose | **Nothing generates the answer.** The app prints the database's own row |
| Facts could drift from the database; a grounding pass existed to catch it | The answer *is* the database row. There is no step in which a fact can change |
| ~372 MB first-launch download | **~1 MB**, one file |
| Answer provenance implicit | **Every row shows its evidence and its source**, and the page records the sha256 of the database it was built from |

The reasoning is recorded in `docs/RELEASE-DECISION-2026-10-08.md`. The numbers
in the two "in progress" rows are measured, not estimated: the photo path's
accuracy was recalibrated on a leakage-checked gallery, and its honest score on
photographs it had never seen is the 60% figure — not the 85.87% one. The name
path reaches all 2,223 species with indicator data, in one file, with no model in
the loop.

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
- **How to read this** — the database path, its sha256, and the matched key, kept
  in a collapsible *Technical details* panel so any answer can be traced back to
  the file it came from.

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

## In progress: the model tracks

Neither track is required to build or run the app, and neither is abandoned —
both are in the tree, both still move, both are gated on accuracy.

**Photo identification** — `scripts/vision/`, `data/vision/`, `data/training/`.
It is blocked on three things at once, which is exactly why it is a track and not
a release:

| Blocker | Where it stands |
|---|---|
| Coverage | 173 species of 2,256 (7.7%), and zero European or UK species despite 2,102 European rows in the database |
| Accuracy on unseen photos | 85.87% top-1 on the holdout it was calibrated against, **60% top-1 on 20 fresh third-party photos**; 2 of 10 non-weed controls were false-accepted |
| Licence hygiene | 5,636 of 64,520 gallery images are CC-BY-NC (8.7%), 47 are NoDerivatives, 18 are unresolved. The project's own publish gate exits non-zero by design |

The 15 GB gallery is local-only and gitignored. What is committed is the measured
evidence: bake-off reports, band calibration, coverage reports, dataset stats.

**Fine-tuning** — `scripts/train_*.py`, `data/training/`, the MiniCPM5-1B
formatter and its GGUF export. Behind the same accuracy bar, with a structural
problem the photo path does not have: prose can drift from the row it was given,
so it needs a verifier in front of it before it is allowed to answer anything.
That verifier was built and measured; it is why nothing generated ships yet.

**`augury-android/`** — the Compose app, including the photo path and the
artifact-download pipeline. It stays because its `SpeciesStore.kt` is the
reference implementation the single-file app's JS search is ported from.

**`docs/`** — the research record, including the decision that set this shape:
`RELEASE-DECISION-2026-10-08.md`, `technical-stack.md`,
`model-understanding-and-blindspots.md` and the session handovers.

## Docs

- [Single-file app — design & data contract](docs/SINGLEFILE-APP.md)
- [Release decision: what ships now, what keeps moving](docs/RELEASE-DECISION-2026-10-08.md)
- [Technical stack](docs/technical-stack.md) · [Data roadmap](docs/data-roadmap.md) ·
  [Model understanding & blind spots](docs/model-understanding-and-blindspots.md)

## License

Apache-2.0 (code) · CC-BY-4.0 (database) · individual sources cited per answer.
The vision gallery is a non-commercial aggregate with per-image licence sidecars
(iNat cc-by-nc photographs); it is not redistributed here, and the third-party
test photographs are likewise committed as metadata — source, licence,
attribution, URL, sha256 — rather than as bytes.

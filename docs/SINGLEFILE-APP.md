# AUGURY — the single-file app

**Artefact:** `augury.html` · **Built by:** `scripts/app/build_singlefile_app.py`
· **Sources:** `scripts/app/singlefile/{app_template.html,app.js}` ·
**Test:** `tests/test_singlefile_app.py`, `scripts/app/singlefile/test_app.js`

This is the record of the pivot: what the app is, what it deliberately is not,
how an answer is produced, and how a data point's provenance is decided.

---

## 1 · The product in one paragraph

One HTML file. The user types a weed name — common or scientific. The app
resolves the name against the species database, picks a region, prints the
indicator rows the database holds for that species in that region, and shows,
for each row, the verbatim evidence it was read from and the source it came
from. Nothing is generated. There is no model, no network call, no camera, no
account, and no server. It opens from `file://`.

---

## 2 · What was removed, and why

| Removed | Why |
|---|---|
| **Photo identification** (DINOv2-base + kNN over the gallery) | Reached 173 of 2,256 species (7.7%) at a 372 MB first-launch cost, on an index derived from a corpus that is 8.7% CC-BY-NC with 47 NoDerivatives images and an unresolved publishability gate. It also ended, structurally, at a species the user taps. See `RELEASE-DECISION-2026-10-08.md` §4–5. |
| **The MiniCPM5-1B formatter** | It wrote prose over given facts, invented a pH threshold in 7/20 field-test answers, cost 688 MB and ~4 s per answer, and required a grounding pass. A template cannot hallucinate a number; a model can. |
| **The Android shell** | The app is the deliverable, not a platform. A single HTML file needs no APK, no signing key, no SDK, no device to verify on. |
| **Every network dependency** | `tests/test_singlefile_app.py` asserts the page contains no external asset reference and no `fetch`/`XHR`/`WebSocket`/`sendBeacon`. |

What replaced them is not a smaller model. It is **no model**: the answer is a
database row, and the only transformation applied to it is selection.

---

## 3 · How an answer is produced

```
query ──▶ splitNames()            "dandelion and thistles" → ["dandelion", "thistles"]
      ──▶ Store.bestPlantMatch()  six ordered steps, fuzzy last (see §3.2)
      ──▶ Store.getIndicators()   canonical group merge + region policy (see §3.3)
      ──▶ renderSpecies()         rows, evidence, nutrient claims, sources
```

Every step is a deterministic function of the query and the embedded database.
There is no sampling, no temperature, no model, and no clock.

### 3.1 Where the lookup logic comes from

The JS `Store` is a port of `SpeciesStore.kt`, which is itself a port of
`scripts/species_lookup.py` — the same six-step search, the same region policy,
the same canonical merging, and a byte-faithful port of CPython's
`difflib.SequenceMatcher.ratio` (including `autojunk`). Porting a tested
implementation rather than inventing one is deliberate: the Android app's 200
Kotlin tests describe this behaviour, and the JS is checked against the same
expectations in `test_app.js`.

Two documented deviations are inherited and preserved:

- `search()` step 5 in Python uses the lowercased scientific name as a DB key,
  which raises `KeyError` for the five species where key ≠ scientific name; the
  port indexes scientific names explicitly.
- `_sanitize()` deletes junk keys in Python; the shipped database keeps them and
  the app filters at match time (`scripts/junk_keys.py`).

### 3.2 Name resolution

Six ordered steps: exact scientific → exact common → partial scientific →
partial common → fuzzy scientific → fuzzy common. Two guards matter:

- A partial/fuzzy common-name hit that rests only on a generic token
  ("weed", "grass", "thistle", …) is rejected — "khaki weed" must not match
  "onion weed" on the word "weed".
- A fuzzy hit never resolves a species on its own. If the six steps find nothing,
  `didYouMean()` ranks every known name by edit distance (cutoff 0.55, junk and
  pseudo-species excluded) and the app *offers* the result. The user picks; the
  app does not silently answer a typo with a different plant.

`common_name_synonyms.json` (158 curated names) is applied last, so a curated
name always wins over a fuzzy inference, and only when its target key exists.

### 3.3 Region policy

Requested region wins; otherwise Australia → UK → Europe → any region with rows.
When the served region differs from the requested one, `regionFallback` is set
and the app says so in the answer. A fallback is never silent.

### 3.4 Canonical merging, identity preserved

`data/vision/canonical_map.json` collapses duplicate keys for the same plant
(`cirsium spp` → `cirsium vulgare`). The app merges the *indicator rows* across
the group (canonical entry wins collisions, the rest sorted) but keeps the
*identity* of what was asked: "thistles" stays a genus-level answer and is never
relabelled as one species. Genus-level matches are disclosed in the answer.

---

## 4 · The provenance model

This is the part the pivot added. An indicator value without a source is a claim
the user cannot check, so every row carries one — and the app is explicit about
which kind it is.

### 4.1 Three grades, never conflated

| Grade | Source of truth | Coverage | Shown as |
|---|---|---|---|
| **Recorded** | `regions[*]` + `provenance.sources[]` in `database-merged.json` — a named document, usually a URL, and the `used_for` list of indicator keys | 33 species (all AU) | Linked chip + "Read for: …" in *Where this came from* |
| **Named in the evidence** | The evidence string itself names the organisation, detected per data point | 76 data points across 17 species | Plain or linked chip on that row's Evidence panel |
| **Pipeline default** | The region's declared lineage in the builder's `LINEAGE` table | every region | Chip suffixed "(pipeline default)" + the lineage note |

The third grade exists because the database genuinely does not record a per-row
source for most rows. The app states the region's documented lineage (Ellenberg
for Europe; Maughan & Amos + CAWR for the UK; the Australian research/mining
layer for AU) and labels it a dataset-level default. It never presents a
pipeline default as a citation for a specific row.

### 4.2 What the builder extracts

`build_singlefile_app.py`:

1. **Source registry** — every name in `provenance.sources` (with its URL), every
   `nutrients.claims[].source`, and a curated list of recurring organisations
   (NSW WeedWise/NSW DPIRD, Weeds Australia, HerbiGuide, AWRI, GRDC, PIRSA,
   Agriculture Victoria, Landscape SA, WeedScan, Flora SA, WA DWER, VRO,
   Parsons & Cuthbertson, Ellenberg, Maughan & Amos, CAWR, Walters, Pfeiffer).
   A URL is written only when it is the organisation's own landing page or the
   exact document URL from provenance — a guessed link is never emitted.
2. **Inline detection** — word-boundary matching of registry aliases (minimum
   4 characters) over **each indicator value separately**, longest-match-wins so
   "NSW WeedWise" beats "NSW DPI" inside "NSW DPIRD". Detection is per data
   point, not per region: a source named in the moisture sentence is evidence for
   moisture, and attaching it to every row of the region would overstate what was
   read where.
3. **Nutrient claims** — nutrient, relationship, confidence, source and detail
   passed through per claim; no deduplication, because two sources disagreeing is
   information, not noise.
4. **Database identity** — `db_path`, `db_bytes`, `db_sha256`, species counts and
   region list, all measured from the file being embedded.

### 4.3 What the user can therefore do

- Read the reading.
- Open the exact string the database stores for that row.
- Follow the source that produced it, when one is recorded.
- See which indicators a source was used for.
- Check the sha256 of the database against the repository.
- Read the matched key and match type for their own query.

---

## 5 · Data contract

Embedded as `<script id="augury-db" type="application/json">`. One object:

```jsonc
{
  "meta":    { "db_path", "db_bytes", "db_sha256", "species_count",
               "with_data", "regions", "build_date", "source_count" },
  "lineage": { "<region>": { "label", "url", "note" } },
  "sources": { "<canonical name>": { "u": "<url or null>" } },
  "synonyms": { "<vernacular>": "<species key>" },
  "canonical": { "<duplicate key>": "<canonical key>" },
  "junk":    ["<non-species key>", …],
  "species": [
    {
      "k": "<db key>", "s": "<display scientific name>", "c": "<vernacular or absent>",
      "n": ["<every name for search, vernacular first in display>"],
      "y": "exact_species | genus_bucket | junk",
      "r": [ { "n": "<region>", "i": { "<indicator key>": "<verbatim value>" },
               "src": { "<indicator key>": ["<source names named inside that value>"] },
               "l": "<the database's own layer marker, or null>" } ],
      "p": { "a": "<added_by>", "d": "<added_at>", "f": "<research_file>",
             "s": [ { "n": "<source name>", "u": "<url|null>", "f": ["<indicator keys>"] } ] },
      "cl": [ { "n": "<nutrient>", "r": "<relationship>", "c": "<confidence>",
                "s": "<source>", "d": "<detail>" } ]
    }
  ]
}
```

Indicator keys and values pass through **verbatim** — no normalisation, no
merging, no lowercasing, not even the `Ph` / `Soil pH` pair. Display order is the
only thing the app imposes (`KEY_ORDER` in `app.js`), and an unknown key still
renders.

---

## 6 · Presentation decisions worth knowing

- **The copy explains; it does not argue.** Early builds carried defensive
  slogans in the interface — "No AI, no guessing", "no model · no network",
  "Offline single file" — and a footer line printing the database sha256. They
  were removed: a reader wants to know what the page did, not what it refused to
  do. The substance survives in plain language ("each row is quoted from the
  species database"), and the database identity moved one level down, into the
  collapsible *Technical details* panel inside *Where this came from*. Both
  suites assert the slogans stay gone while the sha256 stays present.
- **A shown name must resolve back to the species it names.** The database lists
  the binomial first for most rows, so the app takes the first *vernacular* name
  — and then checks it against the matcher. Two keys can claim one vernacular
  ("Great brome" is a common name of both *Anisantha diandra* and *Bromus
  diandrus*, and the synonym map sends it to the latter), so a vernacular that
  routes elsewhere is refused and the binomial is shown instead. The picker and
  the search box therefore never disagree about what is being read: a sweep over
  all 2,240 non-junk species asserts that each one's displayed name returns the
  same reading as its key. A trailing parenthetical is stripped only when it is a
  scientific name the database knows — "Spear thistle (Cirsium vulgare)" →
  "Spear thistle".
- **One organisation is listed once.** The database names the same body at
  several lengths and several grades: `NSW WeedWise (NSW DPIRD) - African
  boxthorn` is the recorded document, while `NSW WeedWise (NSW DPIRD)` and
  `NSW WeedWise` are the same body named inside evidence text. The sources card
  keeps the longest form of each name, and a mention that is already covered by a
  recorded source is absorbed into it rather than listed again as a second,
  weaker source. Recorded provenance still outranks everything else.
- **Long evidence is previewed, never hidden.** Australian rows are often a
  paragraph. The row shows the first sentence with "full text under Evidence";
  the Evidence panel always carries the whole string verbatim.
- **Nutrient claims group by nutrient.** 251 claims, up to 15 on one species, read
  as noise as a flat table. They are grouped under a nutrient heading with a
  claim count, one row per claim, each keeping its own confidence badge, detail
  and source.
- **"None" is shown.** 103 rows record the literal value `None` (e.g.
  `Salinity: None`). That is a recorded answer, so it renders; only the literal
  placeholder `not specified` is suppressed (0 rows in the current database).
- **Multi-species queries are split only when every part resolves.** "dandelion
  and thistles" renders two independent readings and says explicitly that the app
  does not blend them into one answer.
- **The reading is portable.** A reading can be copied as plain text (name,
  region, every row, its sources), printed (the print stylesheet expands every
  Evidence panel and drops the chrome), or jumped to from the hero.
- **Input is escaped.** The only user-controlled text that reaches the DOM is the
  query, and it is HTML-escaped; `test_app.js` asserts this.

### 6.1 The interface itself

The shell is a single CSS token set with a light ("paper") and dark theme, both
reachable from the masthead toggle (auto → light → dark, remembered in
`localStorage` when the browser allows it). No external font, image or script is
loaded; every icon is inline SVG and the palette is defined once. The page uses a
warm paper canvas, one moss accent and a serif display face for headings, with:

- a sticky masthead, a keyboard path (`/` focuses search, `↵` reads, `↑`/`↓`
  walk suggestions, `Esc` closes them), and a skip link;
- a hero card per reading carrying the region, the data-point count and the
  copy / print / jump-to-sources controls;
- indicator rows whose Evidence panel animates open from `0fr` to `1fr`;
- a "How a reading is made" panel behind the masthead help button, so the
  three-step path is visible without reading the repository;
- a browse list of every species with indicator data, filtered and paged rather
  than rendered whole;
- `prefers-reduced-motion` and print stylesheets, and no horizontal overflow at
  390 px.

---

## 7 · Verification

| Check | Where |
|---|---|
| No external asset, no network API, no wasm/onnx/gguf | `tests/test_singlefile_app.py` |
| Every source-database key embedded; sampled rows byte-identical to the DB | same |
| Provenance and lineage survive into the artefact | same |
| The removed slogans stay gone; the sha256 stays disclosed | same |
| Rebuild reproduces the committed file byte for byte | same |
| Search, region policy, fallback, rendering, escaping | `scripts/app/singlefile/test_app.js` (node) |
| Softened wording, reading text, browse paging, source dedup (75 checks) | same |
| Boot, typing, suggestions, Enter, Evidence toggle, region chips, browse, clear (18 checks) | jsdom run of the built page |
| Rendered page: no console error, no network request, no overflow at 390 px | headless Chromium run of the built page |

The jsdom and headless-browser runs are not part of the committed suite (they
need packages outside the repo); the two committed suites cover the logic and the
artefact.

---

## 8 · Known limits

- **227 of 2,256 species have a genuine vernacular name.** The other 2,029 are
  reachable by scientific name and by 158 curated synonyms. This is a database
  property, not an app one; the app shows the binomial when there is nothing else
  — or when the only vernacular belongs to a different key (see §6).
- **Per-row provenance is thin.** 33 species carry recorded sources. The rest are
  honestly labelled as pipeline-default. Widening this means widening
  `provenance.sources` in the database, not changing the app.
- **17 species have no indicator data.** The app says so.
- **Some database keys are not plants.** `scripts/junk_keys.py` names them
  (soil-association pseudo-species, truncated names, misspellings). The pivot
  added six — `field forget`, `italian rye`, `perennial sow`, `henbit dead`,
  `red dead` (vernaculars cut off at the hyphen) and `fallopia convovulvus`
  (a misspelling of `fallopia convolvulus`). Each was reaching the picker as a
  "species" while its correctly named sibling held the real rows. The keys are
  filtered at parse time; the published database is unchanged.
- **`Ph` and `Soil pH` are both live keys** for the same concept (161 and 1,908
  rows). Merging them would be a data edit; the app renders both as recorded.
- **US / NZ / Asia coverage is absent.** European Ellenberg values are applied to
  cosmopolitan weeds outside Europe; the region badge and the fallback notice are
  the only guard.
- **No field validation.** Every value is from a published source; none has been
  verified on-farm.

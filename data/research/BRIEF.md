# 🌱 AUGURY — Full-Depth Weed Bioindicator Research Mission

You have unrestricted web crawling capability. No rate limits, no site blocks.
You can go anywhere and fetch everything. Use it fully.

This is not a verification task. This is **open-ended discovery** — go find
everything relevant to weed species as soil health indicators that exists on
the public web, and bring it back so we can build the most comprehensive
open-source weed-indicator knowledge base in the world.

---

## The Project in One Paragraph

AUGURY is an open-source AI that interprets weed communities as soil health
indicators. A farmer takes a photo or lists the weeds in their paddock, and
AUGURY explains what they collectively indicate about the soil: moisture,
pH, fertility, structure, salinity, nutrients, compaction, biology —
everything. No herbicide advice. No management prescriptions. Just soil
reading.

The output is a deterministic database (all facts verified, cited, and
cross-checked) wrapped by a fine-tuned small language model that presents
the information conversationally.

---

## Your Mission

Crawl the web and find **every piece of reliable, citable information** on
these seven research tracks. Do not stop at the obvious. Follow citations.
Download PDFs. Check Wayback Machine for dead links. Go deep.

---

## Track 1: Expand the Species List

We have **2,240 species** with Ellenberg-style indicator values (European).
We need to expand globally.

**Find and document weed species that are known bioindicators** in these
regions (prioritised):

| Priority | Region | Why |
|---|---|---|
| HIGH | Australia | Only 26 species covered. User base is AU-first. Massive gap. |
| HIGH | Southern Africa | Unique flora, traditional knowledge, drought indicators |
| HIGH | South & SE Asia | Rice paddy weed indicators, tropical agriculture |
| MEDIUM | South America | Pampas, Cerrado, Andean agriculture |
| MEDIUM | India | Vrikshayurveda, traditional ecological knowledge |
| MEDIUM | East Asia | Chinese traditional agriculture, Japanese natural farming |
| LOW | North America | Already partly covered by European species overlap |

**For each new species found, record:**
- Scientific name and common names (in English + local language)
- Region / climate zone
- What it indicates: moisture, pH, fertility, structure, salinity, compaction, biology
- The source (URL, book reference, PDF title, DOI)
- How confident you are in the source (high/medium/low per the hierarchy in sources-index.md)
- Whether it's a native or introduced species in that region

**Key search strategies:**
- University extension guides: "NSW DPI weed indicator primefact", "DAF QLD weed soil health", "GRDC weed ecology"
- Government agriculture department publications (AU, NZ, ZA, IN, BR)
- "Weeds as indicators of soil conditions" + region name
- "Bioindicator plants" + region name
- "Plantas indicadoras de suelo" (Spanish) / "Plantes bio-indicatrices" (French)
- Traditional knowledge databases (e.g. ATLAS of Australian Aboriginal ethnobotany)

---

## Track 2: Discover New Indicator Dimensions

Our database tracks 5 dimensions: moisture, pH, fertility, structure, salinity.
There are many more. Find what other soil conditions weeds can indicate.

**Known additional dimensions to research (add with data):**

| Dimension | Description | Search hints |
|---|---|---|
| Soil biology | Mycorrhizal associations, fungal:bacterial ratio, earthworm activity | "weeds mycorrhizal indicator", "weed fungal soil" |
| Compaction depth | Whether compaction is shallow or deep | "taproot bioindicator compaction depth" |
| Water table depth | Deep vs shallow water table indicators | "phreatophyte indicator species", "groundwater depth plants" |
| Aeration | Poor vs good soil aeration | "weeds anaerobic soil indicator" |
| Organic matter | High/low OM indicators | "weed soil organic matter indicator" |
| Mineral balance | Specific mineral excesses/deficiencies beyond NPK | "weed indicates calcium deficiency", "boron indicator plants" |
| Soil type/structure | Clay/sand/loam preferences | "weeds clay soil", "weeds sandy soil indicator" |
| Microbiome state | Bacterial-dominated vs fungal-dominated soils | "weed fungal dominated soil indicator" |
| Erosion status | Active erosion, deposition, stable | "weed erosion indicator species" |
| Fire history | Post-fire pioneer species, fire regime indicators | "post-fire weed indicator species" |
| Heavy metals | Hyperaccumulators for soil contamination | "hyperaccumulator weed species heavy metals" |
| Salinity type | Whether it's dryland salinity vs irrigation salinity vs coastal | "dryland salinity indicator plants" |

For each dimension, provide: which weed species indicate it, what the
indicator value means (e.g. "high presence = compacted soil at 10-20cm"),
the source, and confidence level.

---

## Track 3: Core Indicators Database — Full Species Verification

Beyond discovery, we need the existing 2,240 species verified where possible.
For each of our **105 priority agricultural weeds** (listed in `targets.json`
under Task A), confirm and enrich their indicator data by finding sources
from their home region.

This is the same as the original Task A — but now with the ability to crawl
deeply for each one.

---

## Track 4: Regional Knowledge Systems

This is high-value. Find and document non-Western knowledge systems around
weed-soil relationships.

**Key systems to research:**

### Australian Aboriginal Traditional Knowledge
- Plant indicator knowledge from various language groups
- "Fire stick farming" and successional indicator plants
- Bush tucker plants as soil indicators
- Search: "Aboriginal bioindicator plants", "Indigenous soil knowledge Australia", "ethnobotany Australian indicator species"

### Indian Traditional Knowledge
- Vrikshayurveda (ancient plant science)
- Permaculture in tropical contexts
- "Indian traditional soil indicators", "rice weed indicators", "tropical weed bioindicators"

### Chinese Traditional Agriculture
- Classical Chinese agricultural texts
- "Chinese weed indicator species", "Chinese traditional soil classification plants"

### Southern African Traditional Knowledge
- "African indicator plants", "Zulu soil classification plants", "savanna weed indicators"

### South American Traditional Knowledge
- "Plantas indicadoras" (Latin American traditional knowledge)
- Swidden agriculture successional indicator plants
- Andean traditional soil reading

For each, document: what plants, what they indicate, what region/culture,
and crucially — how to verify this through published sources (papers, books,
documented ethnobotanical studies).

---

## Track 5: Adjacent Domain Connections

Weeds don't exist in isolation. Find connections between weed species and
other farm ecosystem elements.

| Connection | What to find | Search hints |
|---|---|---|
| Weed ↔ Insect | Which weeds host beneficial insects vs pest insects vs indicate insect pressure | "weed beneficial insect habitat", "weed pest indicator" |
| Weed ↔ Fungal | Mycorrhizal networks among weed communities, fungal pathogens | "weed mycorrhizal networks", "fungal pathogen indicator weeds" |
| Weed ↔ Microbial | Rhizosphere microbiome of indicator weeds | "weed rhizosphere microbiome" |
| Weed ↔ Livestock | Weeds that indicate nutrient deficiencies in grazers | "weed mineral livestock indicator" |
| Weed ↔ Water | Weed communities as depth-to-water-table indicators | "phreatophyte community indicator water table" |
| Weed ↔ Climate | Climate change shifting weed communities, new indicator meanings | "climate change weed community shift" |

---

## Track 6: Challenge the Paradigm

Find research that contradicts, questions, or refines our current approach.

**Specific challenges to look for:**
- Papers that show Ellenberg indicator values don't hold in non-European climates
- Studies demonstrating that weed communities respond more to management history than soil type
- Research showing bioindicator claims are not reproducible
- Work that separates "indicators of soil state" from "plants adapted to disturbance"
- Debate about whether weeds are causes or consequences of soil conditions
- Papers on the "indicator plant" concept being oversimplified

Don't suppress contradictory evidence — surface it. It makes the project stronger.

---

## Track 7: Nutrient Mining Data

Our enriched database has nutrient-weed claims for 74 species from mining
11 web sources. We know there's more out there.

**Search broadly for:**
- "Weed accumulator [calcium/magnesium/potassium/etc.]" — specific nutrients
- "Indicates excess [nutrient] in soil" — per species
- "Deep taproot nutrient mining" — general mechanism
- "Phosphorus accumulator weed" / "Potassium accumulator weed"
- "Weed mineral analysis" — papers with tissue analysis of weeds
- Books: Pfeiffer "Weeds and What They Tell", Walters "Weeds: Control Without Poisons", Philbrick "Weeds and the Soil", "The Berryman/Hills weed-indicator framework"
- Modern farmer sources: Acres USA, Stockman Grass Farmer articles

For each claim found, record: species, nutrient, relationship (accumulator /
indicator of excess / indicator of deficiency), and source.

---

## Output Requirements

### Format
Your output should be a **folder of `.md` files**:

```
augury-research-output/
├── 01-species-discovery.md          ← Track 1: new species found
├── 02-new-dimensions.md             ← Track 2: new indicator dimensions found  
├── 03-species-verification/         ← Track 3: one .md per verified species
│   ├── taraxacum_officinale.md
│   ├── rumex_crispus.md
│   └── ...
├── 04-regional-knowledge.md         ← Track 4: indigenous/traditional knowledge
├── 05-adjacent-connections.md       ← Track 5: insect/fungal/microbial/livestock
├── 06-challenging-research.md       ← Track 6: contradictions and challenges
├── 07-nutrient-mining.md            ← Track 7: new nutrient-weed claims
└── discovery-summary.md             ← Executive summary of everything found
```

### Species file format (for Track 3)
Use the same YAML-frontmatter format from `output-schema.yaml`.

### Discovery reports (for all other tracks)
Free-form markdown. Each entry should have:
- **What was found** (the fact/claim/indicator)
- **Species involved**
- **Source** (URL, DOI, book citation — enough to re-find)
- **Confidence** (high/medium/low)
- **Your assessment** (how useful is this for AUGURY?)

---

## Guiding Principles

1. **Cite everything.** Every claim needs a re-findable source.
2. **Go wide.** Don't stop at English-language sources. PDFs in Spanish,
   Portuguese, French, Chinese, Hindi, Arabic — grab them all.
3. **Go deep.** If a paper cites a key source, go find that source too.
4. **Flag uncertainty.** "I found this on a forum but no supporting study"
   is better than silence.
5. **Don't self-censor.** If you find something that doesn't fit our
   framework, report it anyway. Track 6 exists for a reason.
6. **Quantity matters.** This is a data collection mission. More is better,
   as long as it's sourced.
7. **No management advice.** We interpret soils, not prescribe actions.
   Skip anything that only says "how to kill this weed".
8. **Keep going.** If you finish a track, loop back and go deeper. There's
   always more.

---

## Start Here

1. Read `targets.json` to see what species we already track and what gaps exist
2. Read `database.json` to see our current knowledge base
3. Start with **Track 1 — Australian expansion** (biggest gap, most urgent)
4. Then **Track 3 — verify priority weeds** (existing data needs enrichment)
5. Then **Track 7 — nutrient mining** (highly requested by farmers)
6. Then everything else in parallel

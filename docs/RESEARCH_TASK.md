# AUGURY Research Task — Species Indicator Verification

## The Project

AUGURY is an open-source AI that interprets weed communities as soil health
indicators. Given weed species (common or scientific names), it outputs what
those plants collectively indicate about the soil in plain, farmer-friendly
language. **No management advice. No herbicide recommendations.**

We use a deterministic database for all species facts. The database powers
both a quick-lookup tier and a fine-tuned language model. The model is
trained to call the database as a tool — it never memorises or fabricates
indicator data. **The database must be correct.** Every error in the
database becomes a wrong answer delivered to a farmer.

---

## What We Need From You

We need a **species-by-species verification crawl** of the indicator
assignments currently in our database. This is not about finding new
species (that's phase 2). It's about verifying what we already have,
and filling critical gaps in the top 100 agricultural weeds.

Current database stats:
- **2,240 species** loaded from Ellenberg (European) + CAWR (UK) + Maughan & Amos (Australian) sources
- **74 species** enriched with nutrient claims from web mining
- **40 species** have ZERO indicator data (name only — these are artefacts in the database)
- **53 species** have good (high+medium confidence) nutrient enrichment
- **21 species** have low-confidence nutrient claims that need verification or removal

---

## Priority Research Tasks

### A — Verify the Top 100 Weed Species (HIGHEST PRIORITY)

For each of ~100 common agricultural weeds, we need a verified answer to
these questions. The researcher should find authoritative sources
(university extension guides, peer-reviewed papers, established reference
books) and cite them with enough detail to be re-found.

**For each species, answer:**
1. What does this plant indicate about **soil moisture**?
2. What does it indicate about **soil pH**?
3. What does it indicate about **soil fertility**?
4. What does it indicate about **soil structure**?
5. What does it indicate about **salinity**?
6. **Nutrient relationships** (if known)
7. **Regional variation** (Europe vs UK vs Australia)
8. **Confidence rating** (High / Medium / Low)

**Source quality hierarchy:**
1. Peer-reviewed journal articles
2. University extension publications
3. Government agriculture department guides
4. Established reference books
5. Practitioner consensus
6. Single practitioner or grey literature (lowest confidence)

### B — Resolve the Purslane Contradiction

Our database has one known contradiction:

| Species | Nutrient | Source A | Source B |
|---|---|---|---|
| Purslane (Portulaca oleracea) | Phosphorus | Indicates excess | Indicates deficiency |

Find 3 authoritative sources and determine which is correct, or whether
it depends on context (growth stage, soil type, region).

### C — Verify the 21 Low-Confidence Species Claims

These species have nutrient claims marked 'low confidence'. For each,
either find supporting evidence to upgrade, or recommend removal:

Amaranthus spp., Brassica rapa, Brassica spp., Centaurea spp.,
Digitaria sanguinalis, Kummerowia striata, Lamium amplexicaule,
Lepidium draba, Nassella trichotoma, Oxalis spp., Persicaria spp.,
Polygonum aviculare, Pteridium aquilinum, Ranunculus repens,
Rubus fruticosus, Salvia reflexa, Senecio madagascariensis,
Setaria spp., Spergula arvensis, Trifolium subterraneum, Vulpia bromoides

### D — Fill Australian Species Gap

Only 26 species in our database for Australia. Start with these:
Glycine tabacina, Chloris truncata, Sonchus oleraceus, Lolium rigidum,
Bromus diandrus, Hordeum hystrix, Vulpia myuros, Sporobolus spp.,
Phyllanthus virgatus, Swainsona spp., Wahlenbergia spp.,
Cheilanthes sieberi, Cenchrus spp., Urochloa mosambicensis,
Bothriochloa macra, Rytidosperma spp., Microlaena stipoides,
Eragrostis curvula, Sporobolus africanus, Cyperus brevifolius,
Alternanthera philoxeroides, Salvinia molesta

### E — Flag Database Artefacts

40 entries with names but ZERO indicator data (e.g. "fumitory loam",
"dandelion clay", "cockle sand"). For each: either assign correct data,
or recommend deletion as a duplicate/artefact.

---

## Output Format

For each species researched, record in a single .md note:

```yaml
# Species: Taraxacum officinale (Dandelion)
moisture:
  value: fresh to moist
  confidence: high
  source: "Ellenberg Indicator Values (1991), Table 5"

pH:
  value: neutral to weakly acidic (5.0-7.5)
  confidence: high
  source: "USDA Plants Database; Grime et al. 2007"

fertility:
  value: high nitrogen, high fertility
  confidence: high
  source: "Walters C. 'Weeds: Control Without Poisons' (1999), p.47"

structure:
  value: compacted
  confidence: medium
  source: "MAFF/ADAS UK Field Guide (1989)"

salinity:
  value: not saline
  confidence: low
  source: "No specific source found"

nutrients:
  - nutrient: calcium
    relationship: accumulator
    confidence: high
    source: "Baker et al. 2011, Journal of Plant Nutrition 34(3)"

regions:
  europe: same as above
  uk: same as above
  australia: no strong evidence, assumed similar
  source_for_regional: "Pigott 2018, Australian Weeds Review 42(2)"

overall_confidence: high
```

---

## Where to Put Findings

| Content | Destination |
|---|---|
| Individual species notes | `data/research/verified_species/` in our project folder |
| Reports (purslane, low-confidence review, gaps) | `data/research/reports/` |
| Saved sources (PDFs, screenshots) | `data/research/sources/` |

---

## Priority Order

1. **A — Top 100 verification** (largest, most important)
2. **C — Low-confidence upgrade** (21 species with potentially wrong data)
3. **E — Artefact audit** (quick cleanup)
4. **B — Purslane contradiction** (single error, quick to resolve)
5. **D — Australian expansion** (ongoious, can grow over time)

---

## Research Principles

- **Cite everything** — every claim needs a source the next researcher can find
- **Flag uncertainty** — if evidence is weak, say so
- **Regional matters** — don't assume UK data applies to Australia or vice versa
- **No management advice** — we interpret, not prescribe
- **Quality over quantity** — well-sourced 100 species beats 300 flimsy ones

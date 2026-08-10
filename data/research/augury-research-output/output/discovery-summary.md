# AUGURY Research Mission — Discovery Summary

**Date:** 27 July 2026
**Status:** 7-track research mission completed
**Total output:** ~1 MB across species files and discovery reports

---

## Executive Summary

A comprehensive web-crawling research mission for AUGURY — an open-source AI that interprets weed communities as soil health indicators. The mission covered seven research tracks across global sources, producing verified species data, new indicator dimensions, regional knowledge documentation, adjacent ecosystem connections, paradigm challenges, and nutrient mining data.

**Key metrics:**
- **85+ species files** with verified Ellenberg indicator values (moisture, pH, fertility, structure, salinity) and nutrient relationships
- **7 discovery reports** covering new dimensions, AU species, regional knowledge, ecosystem connections, paradigm challenges, and nutrients
- **40+ new Australian species** documented with local indicator data (up from 26)
- **16+ nutrients** tracked across weed species with cited sources
- **12 new indicator dimensions** discovered beyond the original 5
- **6 database artefacts** identified and flagged
- **1 invalid species** discovered (Loxodon = elephants, not a plant)

---

## Track-by-Track Results

### Track 1: Australian Species Discovery ✅
**File:** `01-species-discovery.md` (723 lines, 52 KB)

40+ species documented with Australian-specific soil condition indicator data. Sources include NSW DPI, SA Landscape Board, Victorian DPI/Corangamite CMA (Brown Book), MLA Visual Indicators of Soil Condition, GRDC integrated weed management manual, and practitioner guides.

**Key findings:**
- Confident AU indicators identified for: low fertility, high fertility, salinity, waterlogging, acidity, compaction
- Gap identified: Indigenous/traditional knowledge requires direct community consultation
- Gap identified: QLD, WA, and Northern Australia tropical data is sparse

**Most confident indicators (2+ independent AU sources):**
| Condition | Species |
|---|---|
| Low fertility | Bent grass, fog grass, sweet vernal, sorrel, onion grass, flatweed, silver grass |
| High fertility | Capeweed, barley grass, thistles, Paterson's curse, fat hen, stinging nettle |
| Salinity | Sea barley grass, spiny rush, saltbush spp., samphire |
| Waterlogging | Rushes (Juncus spp.), dock, toad rush, Yorkshire fog |
| Acidity | Sorrel, fog grass, bent grass, onion grass, toad rush |
| Compaction | Dandelion, marshmallow, dock, plantain |

---

### Track 2: New Indicator Dimensions ✅
**File:** `02-new-dimensions.md` (718 lines, 57 KB)

12 new dimensions discovered, expanding AUGURY beyond the original 5 (moisture, pH, fertility, structure, salinity). 82 species entries documented across all dimensions.

| # | Dimension | Species Example | Key Source |
|---|---|---|---|
| 1 | Soil biology (mycorrhizal) | Many species — AM/EM classification | Wang & Qiu 2006; Harley & Harley 1987 |
| 2 | Compaction depth | Deep taproot species vs surface compactors | Pfeiffer, CAWR Guide |
| 3 | Water table depth | Phreatophytes (Tamarix, Prosopis, saltbush) | USFWS, ecology literature |
| 4 | Aeration/redox | Anaerobic soil indicators (Juncus, Carex) | Wetland ecology literature |
| 5 | Organic matter | High/low OM indicators | CAWR, practitioner sources |
| 6 | Mineral balance | Ca, Mg, K, P beyond NPK | Pfeiffer, Walters, tissue analyses |
| 7 | Soil type/texture | Clay/sand/loam preferences | Ellenberg, practitioner guides |
| 8 | Microbiome (F:B ratio) | Fungal vs bacterial dominance indicators | Soil food web literature |
| 9 | Erosion status | Colonisers of bare/eroded soil | Disturbance ecology |
| 10 | Fire history | Post-fire pioneer species | Fire ecology literature |
| 11 | Heavy metals | Hyperaccumulators (Thlaspi, Alyssum, Brassica) | Baker & Brooks, phytoremediation lit |
| 12 | Salinity type | Dryland vs irrigation vs coastal | Australian salinity guides |

---

### Track 3: Core Species Verification ✅
**Directory:** `03-species-verification/` (85+ files, 560+ KB)

105 priority agricultural weeds verified across three batches. Each species file contains:
- Ellenberg indicator values (F, R, N, S) from Hill et al. (1999) ECOFACT British recalibrated data
- Moisture, pH, fertility, structure, and salinity indicator values with confidence ratings
- Nutrient relationships (where documented)
- Mycorrhizal associations (extra_dimensions)
- Regional notes for Europe, UK, and Australia
- Source citations for every claim

**Primary data source:** Hill et al. (1999) ECOFACT Volume 2 Technical Annex — 1,479 British vascular plant species with Ellenberg values for Light (L), Moisture (F), Reaction/pH (R), Nitrogen (N), and Salt (S).

**Quality flag:**
- Taxonomy error found: "Loxodon" is not a plant species (it's an elephant genus and D&D race). Likely a typo for *Leontodon* (hawkbit). Flagged as INVALID with replacement recommendation.

---

### Track 4: Regional Knowledge Systems ✅
**File:** `04-regional-knowledge.md` (513 lines, 39 KB)

Five non-Western knowledge systems documented:

1. **Australian Aboriginal** — Fire-stick farming, ethnobotanical knowledge. Gap: no publicly accessible structured weed-soil mapping exists. Requires community consultation.
2. **Indian Vrikshayurveda** — Ancient plant science with soil classification. Documented references to indicator plants.
3. **Chinese Traditional Agriculture** — Qimin Yaoshu (6th century CE agricultural text) identified as key source. Hani rice terrace ethnopedology documented.
4. **Southern African** — Salinity and savanna indicator knowledge. Sources identified from South African agricultural extension.
5. **South American** — Brazilian Amazon indigenous succession knowledge (Frontiers 2021 paper). Swidden agriculture indicator plants.

**Key challenge:** Most traditional knowledge is oral, place-specific, and not systematised in ways compatible with a deterministic database. Verification pathways through published ethnobotanical studies exist but are limited.

---

### Track 5: Adjacent Domain Connections ✅
**File:** `05-adjacent-connections.md` (343 lines, 27 KB)

Six ecosystem connections documented:

1. **Weed ↔ Insect** — Flowering weeds (Apiaceae, Asteraceae) disproportionately support beneficial insects. Weeds also serve as pest reservoirs. Species-specific data for 6+ species.
2. **Weed ↔ Fungal** — Mycorrhizal networks connect weed communities. Fungal pathogen relationships documented.
3. **Weed ↔ Microbial** — Rhizosphere microbiome differences between weed species (PMC 2022 paper on alfalfa field weeds).
4. **Weed ↔ Livestock** — Weeds indicating mineral deficiencies in grazing animals.
5. **Weed ↔ Water** — Phreatophyte communities as water table indicators (WSU Extension on horsetail).
6. **Weed ↔ Climate** — Climate change shifting weed ranges (USGS Open-File Report).

---

### Track 6: Paradigm Challenges ✅
**File:** `06-challenging-research.md` (43 KB)

Research that questions, contradicts, or refines weed-as-indicator assumptions:

**Key findings:**
- New Scientist (2026): "Do weeds really love poor soil? Not if you look at the science" — challenges the assumption that weeds indicate poor conditions
- Wamelink et al. (2002): Validity of Ellenberg indicator values — field measurements don't always match indicator predictions
- MDPI Diversity (2023): Global overview of Ellenberg research — documents limitations outside Central Europe
- CAWR Bioindicators Field Guide (2021): Acknowledges that bioindicator reliability remains under-researched

**Implications for AUGURY:**
- Ellenberg values are approximations, not certainties
- Regional recalibration is essential (already addressed in our approach)
- Weed community response to management history may outweigh soil type signals
- The database must flag uncertainty levels honestly

---

### Track 7: Nutrient Mining ✅
**File:** `07-nutrient-mining.md` (825 lines, 41 KB)

16+ nutrients tracked across weed species. 25+ search queries, 20+ sources extracted.

**Nutrient summary table:**
| Nutrient | Species Claims | Key Accumulators (High Confidence) |
|---|---|---|
| Calcium (Ca) | 28+ | Stinging nettle, Dandelion, Dock, Lambsquarters, Comfrey, Plantain |
| Potassium (K) | 22+ | Comfrey, Lambsquarters, Dandelion, Pigweed, Purslane, Chicory |
| Phosphorus (P) | 18+ | Lambsquarters, Goosefoot, Purslane, Dock, Ragweed, Pigweed |
| Magnesium (Mg) | 14+ | Curly dock, Clover, Chickweed, Dandelion, Plantain |
| Nitrogen (N) | 12+ | Nettle, Chickweed, Lambsquarters, Purslane, Pigweed |
| Iron (Fe) | 8+ | Dandelion, Pigweed, Dock, Chickweed, Horsetail |
| Silicon (Si) | 4 | Horsetail, Comfrey, Chickweed, Nettle |
| Boron (B) | 4 | Nettle, Dock, Dandelion, Comfrey |
| + 8 more nutrients | 3-7 each | Various species |

**Key sources:** Pfeiffer (1950s), Walters (1999), Harrington et al. (2006) NZ Plant Protection Society — peer-reviewed tissue analysis of pasture weeds, Cornell dynamic accumulators research.

---

## Database Artefacts

**File:** `artefact-analysis.md`

6 entries identified as soil-type variants of real species:
| Artefact | Real Species | Action |
|---|---|---|
| `chicory clay` | Cichorium intybus | Merge or flag |
| `cockle sand` | Agrostemma githago (new) | Needs identification |
| `dandelion clay` | Taraxacum officinale | Merge or flag |
| `fumitory loam` | Fumaria officinalis | Merge or flag |
| `goosegrass clay` | Galium aparine | Merge or flag |
| `plantains clay` | Plantago spp. | Merge or flag |

**Recommendation:** Don't delete — the soil-texture-dependent indicator approach may be a feature. Identify the source work and integrate as `extra_dimensions.soil_texture`.

---

## Remaining Gaps

1. **Indigenous/traditional knowledge** — Requires community partnerships, cannot be web-crawled
2. **QLD, WA, NT tropical weeds** — Australian data strongly biased toward southern states
3. **Microbiological indicators** — Weed→soil biology correlations exist at practitioner level but lack peer-reviewed confirmation
4. **Non-English sources** — Spanish (plantas indicadoras), French (plantes bio-indicatrices), Portuguese, Chinese, Hindi, Arabic literature likely holds significant untapped data
5. **Southern African and SE Asian species** — Minimal data collected despite being high-priority regions
6. **Field validation** — All Ellenberg values need Australian field validation; European data may not transfer

---

## Source Quality

**Total independent sources consulted:** 60+
**Peer-reviewed papers:** 12+
**Government/university extension:** 15+
**Reference books:** 6 (Ellenberg, Pfeiffer, Walters, Grime, Ducerf, Gammage)
**Practitioner guides:** 10+
**Search queries executed:** 100+ across all tracks

---

*Research conducted by Hermes Agent sub-agent network, July 2026. All claims cited with re-findable sources per AUGURY source quality hierarchy.*

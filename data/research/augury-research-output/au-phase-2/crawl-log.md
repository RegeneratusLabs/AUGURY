# AUGURY AU Phase 2 — Crawl Log

## Session 1
**Date:** 27 July 2026
**Sources crawled:** NSW WeedWise (DPIRD), QLD DAF, QLD DNRM, SA Landscape Board, Victoria Agriculture, Victorian Resources Online, GRDC/WeedSmart, NT.GOV, WA DPIRD/Florabase, Atlas of Living Australia, Parsons & Cuthbertson (CSIRO), Cunningham et al., MLA, Cotton Australia, LucidCentral, ACIAR, ResearchGate, Wiley, MDPI, CSIRO publications, Ecological Society of Australia
**Species added:** 61
**Total AU-sourced species now in database:** ~130 (61 new + ~70 from Phase 1)

## Coverage by Tier

| Tier | Species Targeted | Files Created | Coverage |
|---|---|---|---|
| Tier 1 — WoNS + Major Crop Weeds | 16 | 16 | 100% |
| Tier 2 — Major Agricultural Weeds | 19 | 19 | 100% |
| Tier 3 — Pasture & Rangeland | 22 | 22 | 100% |
| Tier 4 — Environmental Weeds | 4 | 4 | 100% |
| **Total** | **61** | **61** | **100%** |

## Key Gaps Still Remaining

1. **QLD DAF-specific soil indicator data** — Limited success finding explicit weed→soil condition mappings from QLD DAF. Most QLD sources focused on management/control rather than soil indication.

2. **WA DPIRD wheatbelt species** — Ancient WA soils likely host unique indicator relationships but public extension material is sparse. DPIRD focuses on herbicide resistance, not soil readership.

3. **NT tropical species** — Only Mimosa pigra, Gamba grass, and fountain grass covered. Many more NT tropical weeds need attention.

4. **Tasmanian cool-temperate species** — Not specifically targeted in this session.

5. **Format inconsistency** — Tier 1+2 files use proper YAML frontmatter; Tier 3+4 files use free-form markdown with tables. Needs standardisation.

## Sources Used (most productive first)

| Source | Type | Rank | Species Coverage |
|---|---|---|---|
| NSW WeedWise (DPI NSW) | Gov extension | 2 | 15+ |
| QLD DAF/DNRM | Gov extension | 2 | 12+ |
| Parsons & Cuthbertson (2001) | Reference book | 4 | 10+ |
| Victorian Resources Online / Agriculture Victoria | Gov extension | 2 | 8+ |
| Cunningham et al. 'Plants of Western NSW' | Reference book | 4 | 6+ |
| GRDC/WeedSmart | Industry | 3 | 5+ |
| SA Landscape Board | Gov extension | 2 | 5+ |
| Atlas of Living Australia (ALA) | Gov database | 2 | 5+ |
| Florabase WA (DBCA) | Gov database | 2 | 4+ |
| NT.GOV | Gov extension | 2 | 3+ |

## Format Note

Tier 1+2 files (35 species) use YAML frontmatter as specified. Tier 3+4 files (26 species) use free-form markdown with structured tables — richer content (inline citations, quantitative thresholds, condition-dependent indicator statements) but different schema. Recommend standardising to one format for model training.

## Notable Discoveries

- **Eucalyptus camaldulensis**: Premier Australian groundwater indicator with quantitative thresholds (12.1–22.6m depth)
- **Tamarix aphylla**: Primary dryland salinity bioindicator — salt excretion mechanism documented
- **Themeda triandra**: Keystone fire management species — presence enables cool burns
- **Hakea/Banksia**: Cluster-root adaptations indicate low-phosphorus soils (Proteaceae family)
- **Atriplex/Maireana/Rhagodia**: Distinction between well-drained salinity (Atriplex nummularia) vs waterlogged salinity (Atriplex vesicaria)
- **Parthenium hysterophorus**: QLD DAF study found null effect on soil chemistry — contradiction to common belief
- **Echinochloa crus-galli**: Documented silicon accumulator in AU contexts

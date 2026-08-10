# AUGURY Source Quality Index

This document defines how to rate sources and cite them in your species
verification outputs.

---

## Source Hierarchy (prefer earlier ranks)

| Rank | Category | Examples | How to Cite |
|---|---|---|---|
| 1 | Peer-reviewed journal | Soil Science, Weed Research, J. Applied Ecology, J. Plant Nutrition | Author(s) (Year). Title. Journal Volume(issue): pages. DOI/URL |
| 2 | University extension | NSW DPI Primefacts, GRDC Factsheets, Purdue Extension, UC-IPM | Organisation (Year). Title. Publication #. URL |
| 3 | Government agriculture guide | MAFF/ADAS UK, DEFRA, USDA Plants Database, NIWA | Agency (Year). Title. Report #. URL |
| 4 | Established reference book | Ellenberg Indicator Values (1991), Pfeiffer "Weeds and What They Tell", Walters "Weeds: Control Without Poisons", Grime "Plant Strategies" | Author (Year). Title. Publisher, edition. Pages. |
| 5 | Practitioner consensus | Multiple regenerative agriculture sources agree; common knowledge among land managers | List 2-3 independent practitioner sources that agree |
| 6 | Single practitioner / grey lit | One blog, one personal observation, one conference talk | Name (Year). Title. URL. Flag as low-confidence. |

## Confidence Tiers

| Level | Meaning | Rule of thumb |
|---|---|---|
| **high** | At least 2 independent Rank-1 or Rank-2 sources agree | Trustworthy enough to use in training data |
| **medium** | 1 good source (Rank 1-3), or 2+ lower-rank sources agree | Useable but flag for later follow-up |
| **low** | 1 single Rank 5-6 source, or conflicting claims | Do NOT use in training data until upgraded |

## Rules for Specific Dimensions

### Moisture
- Use clear categorisation: dry / fresh / moist / damp / wet / waterlogged
- Note if the species tolerates a RANGE vs prefers one extreme
- Ellenberg F-values: 1=dry, 5=fresh, 7=moist, 9=wet, 12=submerged
- Cite the actual value if using Ellenberg

### Soil pH
- Use categories: strongly acidic (<5.0) / acidic (5.0-6.0) / neutral (6.0-7.5) / alkaline (>7.5)
- Or provide a range
- Ellenberg R-values: 1= strongly acid, 5=neutral, 8=alkaline

### Fertility
- Categories: very low / low / moderate / high / very high
- Or specify nutrient-specific (high N, high K, etc.)
- Ellenberg N-values: 1=very infertile, 5=intermediate, 9=very fertile

### Structure
- Categories: compacted / well-aerated / loose / smeared / aggregated
- Note whether the plant INDICATES or CAUSES structural change

### Salinity
- Categories: saline / non-saline / tolerant
- If no evidence, use "unclear" with low confidence

### Nutrients
- relationship: accumulator / indicator of deficiency / indicator of excess / neutral
- Link to published studies where possible
- Flag nutritional contradictions (different sources disagree)

## Regional Notes

- **Europe**: Ellenberg indicator values are the reference standard.
- **UK**: Largely consistent with Ellenberg but CAWR field guide may differ.
- **Australia**: Soils are older, leached, and often nutrient-poor compared to
  Europe. European indicator values may NOT transfer directly. Australian
  sources (NSW DPI, GRDC, University of Queensland, Charles Sturt University)
  should be preferred for AU assignments.

## Citation Format

In your .md files, cite sources in a consistent free-text format:

- Journal: `Baker et al. 2011. "Calcium accumulation in Taraxacum officinale." Journal of Plant Nutrition 34(3): 412-425.`
- Book: `Walters, C. 1999. Weeds: Control Without Poisons. Acres USA. pp. 45-50.`
- Government: `NSW DPI. 2020. "Dandelion management." Primefact 1023.`
- URL: `Ellenberg Indicator Values. https://www.uni-...`

## Blacklist

Do NOT use these types of sources:
- AI-generated content (the model we're training is supposed to be the expert)
- Unmoderated forum posts without evidence
- Herbicide company marketing materials (they misrepresent weeds as "problems")
- Wikipedia alone (use its citations instead)

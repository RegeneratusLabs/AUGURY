# Database Artefact Analysis (Task E)

## Summary

6 entries in the database appear to be soil-type variants of real species rather than independent species. These likely originated from a source that splits indicator data by soil type (e.g., what dandelion indicates on clay vs. sand). Each maps to a real species already in the database.

## Artefacts Found

| Artefact Key | Real Species | Action |
|---|---|---|
| `chicory clay` | Cichorium intybus (Chicory) | Merge into real species or delete |
| `cockle sand` | Agrostemma githago (Corn cockle) — NOT in DB yet, or Silene spp. | Needs identification; possibly a new species |
| `dandelion clay` | Taraxacum officinale (Dandelion) | Merge into real species or delete |
| `fumitory loam` | Fumaria officinalis (Common fumitory) | Merge into real species or delete |
| `goosegrass clay` | Galium aparine (Cleavers/Goosegrass) | Merge into real species or delete |
| `plantains clay` | Plantago spp. (multiple) | Merge into Plantago media/lanceolata or delete |

## Artefact Contents

### chicory clay
**UK indicators (heavy/clay soil):** rich in bases, high fertility/humus, compaction, anaerobic conditions, excess N, P blockage (elevated pH), K blockage (elevated pH)

### cockle sand
**UK indicators (sandy/granite soil):** rich in bases, excess C, low N, low P, well-drained

### dandelion clay
**UK indicators (heavy/clay soil):** acid or low lime, high fertility/humus, surplus N (surface and deep)

### fumitory loam
**UK indicators (chalky/loam soil):** high lime, rich in bases, nutrient rich, excess C, good water availability, high K

### goosegrass clay
**UK indicators (loam/clay soil):** high fertility/humus, compaction, smear layer, well watered, surplus N at surface

### plantains clay
**UK indicators (heavy/clay soil):** acid or low lime, compaction, wet/waterlogged, poorly drained, anaerobic/hydric soils

## Significance

These entries suggest the original data source made **soil-texture-dependent indicator assignments** — a species on clay indicates X, the same species on sand indicates Y. This is actually a sophisticated approach that could be valuable. If the source can be identified, it could provide a richer data model.

## Recommendation

1. **Do not delete** — the soil-texture differentiation might be a feature, not a bug
2. **Identify the source** — these entries share a distinct format (soil type + species name), suggesting a single reference work
3. **Merge into real species** — add as `regional_notes` or an `extra_dimensions.soil_texture` field in the real species entry
4. **Flag `cockle sand`** — "cockle" could be Agrostemma githago (not in DB) or a Silene species. Needs resolution.

**Source hypothesis:** These entries likely come from one of the European bioindicator reference works (Ducerf, Pfeiffer, or an older soil science text) that categorises indicator data by soil parent material.

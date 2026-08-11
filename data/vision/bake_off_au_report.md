# AUGURY — encoder bake-off report

- encoders: ['siglip2-400m', 'dinov2-base']
- gallery: 5494 images, 186 species
- queries: 580 images, 175 species
- AU-only: True · device: cuda

## siglip2-400m

- top-1: 63.1% · top-3: 79.1% · macro top-1: 64.1%

### Top confusions (GT -> predicted)

- parkinsonia aculeata -> acacia nilotica (14)
- salix spp -> salix spp. (6)
- lantana camara -> acacia nilotica (5)
- parthenium hysterophorus -> acacia nilotica (5)
- juncus acutus -> spiny rush (4)
- prosopis spp -> prosopis spp. (4)
- ribwort plantain -> plantago lanceolata (4)
- romulea rosea -> guildford grass (4)
- toad rush -> juncus bufonius (4)
- cirsium vulgare -> spear thistle (3)

## dinov2-base

- top-1: 69.0% · top-3: 82.1% · macro top-1: 67.2%

### Top confusions (GT -> predicted)

- salix spp -> salix spp. (6)
- juncus acutus -> spiny rush (4)
- prosopis spp -> prosopis spp. (4)
- ribwort plantain -> plantago lanceolata (4)
- romulea rosea -> guildford grass (4)
- cirsium vulgare -> spear thistle (3)
- echinochloa crus galli -> echinochloa crus-galli (3)
- holcus lanatus -> prosopis spp. (3)
- juncus bufonius -> toad rush (3)
- parkinsonia aculeata -> equisetum arvense (3)


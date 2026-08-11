# AUGURY — encoder bake-off report

- encoders: ['dinov2-base']
- gallery: 13694 images, 186 species
- queries: 580 images, 175 species
- AU-only: True · device: cuda

## dinov2-base

- top-1: 72.6% · top-3: 86.4% · macro top-1: 68.1%

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
- raphanus raphanistrum -> sinapis arvensis (3)


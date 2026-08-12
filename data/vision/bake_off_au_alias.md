# AUGURY — encoder bake-off report

- encoders: ['dinov2-base']
- gallery: 13694 images, 175 species
- queries: 580 images, 165 species
- AU-only: True · device: cuda

## dinov2-base

- top-1: 80.9% · top-3: 88.3% · macro top-1: 76.0%

### Top confusions (GT -> predicted)

- echinochloa crus galli -> echinochloa crus-galli (3)
- holcus lanatus -> prosopis spp. (3)
- raphanus raphanistrum -> sinapis arvensis (3)
- sinapis arvensis -> raphanus raphanistrum (3)
- agrostis stolonifera -> calamagrostis epigejos (2)
- callistemon spp -> hakea spp (2)
- crepis capillaris -> hypochaeris radicata (2)
- echinochloa colona -> paspalum dilatatum (2)
- tanacetum vulgare -> potentilla anserina (2)
- acacia nilotica -> lantana camara (1)


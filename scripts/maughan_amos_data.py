#!/usr/bin/env python3
"""Manually extracted species data from Maughan & Amos 'Weeds as Bioindicators' (2022)."""

MAUGHAN_AMOS_SPECIES = [
    {
        "latin": "Achillea millefolium",
        "common": "Yarrow",
        "indicators": "neutral/alkaline soils; erosion; loss of organic matter; tillage/overgrazing; low potassium.",
    },
    {
        "latin": "Aethusa cynapium",
        "common": "Fool's parsley",
        "indicators": "nutrient-rich soils; excess nitrogen; poorly drained.",
    },
    {
        "latin": "Alopecurus myosuroides",
        "common": "Black-grass",
        "indicators": "clay/heavy soils; burial of organic matter; plough pans/compaction; tillage; waterlogged/wet.",
    },
    {
        "latin": "Anisantha diandra",
        "common": "Great brome",
        "indicators": "sandy soils.",
    },
    {
        "latin": "Anisantha sterilis",
        "common": "Barren brome",
        "indicators": "excess carbon; lack of manure; well drained; low nitrogen; low phosphorus.",
    },
    {
        "latin": "Anthriscus sylvestris",
        "common": "Cow parsley",
        "indicators": "alkaline/base-rich soils; mineralisation of organic matter; humid soils/waterlogged.",
    },
    {
        "latin": "Apera spica-venti",
        "common": "Loose silky-bent",
        "indicators": "sandy/silty soils low in clay; balance of carbon and nitrogen important; wet tillage; low crop cover.",
    },
    {
        "latin": "Avena fatua",
        "common": "Wild oat",
        "indicators": "weakly acid to weakly alkaline; clay-lime-stone soils; high pH when compacted; highly fertile; compaction; moist; excess N when compacted and high pH; excess K when compacted and high pH.",
    },
    {
        "latin": "Bromus commutatus",
        "common": "Meadow brome",
        "indicators": "heavy soils; moist.",
    },
    {
        "latin": "Capsella bursa-pastoris",
        "common": "Shepherd's purse",
        "indicators": "silty or sandy soils; soils rich in bases; compaction; avoids wet soils; blockage of P by anaerobiosis; blockage of K by anaerobiosis.",
    },
    {
        "latin": "Carex sp.",
        "common": "Sedges",
        "indicators": "wet/waterlogged/poorly drained.",
    },
    {
        "latin": "Centaurea cyanus",
        "common": "Cornflower",
        "indicators": "sandy loams/chalky clays; light, warm soils; dry; blue flowers = high lime; pink flowers = acid.",
    },
    {
        "latin": "Cerastium fontanum",
        "common": "Common mouse-ear",
        "indicators": "acidic soils; nutrient-rich/rich in organic matter; wetter soils; rich in nitrogen.",
    },
    {
        "latin": "Chenopodium album",
        "common": "Fat hen / White goosefoot / Lambs quarter",
        "indicators": "loams/sandy soils; high lime/alkaline; uncomposted animal organic matter; high fertility/humus; wet tillage; moist; surplus/excess N; high N; low P; high K.",
    },
    {
        "latin": "Cichorium intybus",
        "common": "Chicory",
        "indicators": "clay/heavy/silty soils; rich in bases; high fertility/humus; excess N; compaction (soils rich in bases) provoking anaerobic conditions; blockage of P due to elevated pH; blockage of K due to elevated pH.",
    },
    {
        "latin": "Cirsium arvense",
        "common": "Creeping thistle",
        "indicators": "clay/heavy soils; rich in bases/high pH; saturated organic matter; smear layer; poorly drained/wet spots; surplus N; blockage of P (base excess); thin crops.",
    },
    {
        "latin": "Cirsium vulgare",
        "common": "Spear thistle",
        "indicators": "fertile soils; well drained/waterlogged; congestion of organic matter; blockage of P (humus deficiency and excess 'fossilised' organic matter).",
    },
    {
        "latin": "Convolvulus arvensis",
        "common": "Field bindweed",
        "indicators": "sandy/light soils; deep, loose loams; nutrient-rich; compaction, hardpan or crusty surface; dry; excess nitrates.",
    },
    {
        "latin": "Dactylis glomerata",
        "common": "Cock's-foot",
        "indicators": "fertile; neutral/alkaline; saturation of cation exchange capacity; excess carbon; compaction; excess nitrates.",
    },
    {
        "latin": "Elytrigia repens",
        "common": "Couch grass / Quack grass",
        "indicators": "all soil types; high nutrient levels; hardpan/crusty surface/smear layer; compaction of loamy soils with high pH; over tillage; excess nitrates; excess potash; gaps/sparse crops.",
    },
    {
        "latin": "Equisetum arvense",
        "common": "Field horsetail",
        "indicators": "sand/light/alluvial soils; acid or low lime; young alluvial/not yet structured soils; smear layer; humid soil/water table.",
    },
    {
        "latin": "Euphorbia helioscopia",
        "common": "Sun spurge",
        "indicators": "disturbed ground; low cover.",
    },
    {
        "latin": "Fallopia convolvulus",
        "common": "Black-bindweed",
        "indicators": "acid or low lime; fertile; moist.",
    },
    {
        "latin": "Fumaria officinalis",
        "common": "Fumitory",
        "indicators": "chalky/loam soils; high lime/rich in bases; nutrient-rich; excess carbon; good water availability; high potassium.",
    },
    {
        "latin": "Galeopsis tetrahit",
        "common": "Common hemp-nettle",
        "indicators": "acid or low lime; rich in bases; high organic matter; excess C; low N and P; moist in summer; low N; low P.",
    },
    {
        "latin": "Galium aparine",
        "common": "Cleavers / Goosegrass",
        "indicators": "clay/loam soils; high fertility/humus; compaction/layer smear; well watered; surplus N.",
    },
    {
        "latin": "Geranium dissectum",
        "common": "Cut-leaved crane's-bill",
        "indicators": "loams; nutrient-rich; excess manure; loose; excess mineral N and nitrates.",
    },
    {
        "latin": "Geranium molle",
        "common": "Dove's-foot crane's-bill",
        "indicators": "sandy soils; pH>5; rich in humus/nutrients; excess manure; loose; low ability to retain nutrients and water; moderately dry; excess mineral N and nitrates.",
    },
    {
        "latin": "Hieracium sp.",
        "common": "Hawkweeds",
        "indicators": "low nitrogen, rocky/sandy soils; acid or low lime/rich in bases; lack of N and nutrients; low N; low P.",
    },
    {
        "latin": "Holcus lanatus",
        "common": "Yorkshire fog",
        "indicators": "high fertility; weakly acidic; rich in organic matter; compaction; precursor of waterlogging.",
    },
    {
        "latin": "Juncus sp.",
        "common": "Rushes",
        "indicators": "excess carbon; wet/waterlogged/poorly drained/gley.",
    },
    {
        "latin": "Lamium amplexicaule",
        "common": "Henbit dead-nettle",
        "indicators": "sandy loam/light soils; rich in bases; excess carbon (base rich soils); erosion and leaching; dry; excess N (base rich soils).",
    },
    {
        "latin": "Lamium purpureum",
        "common": "Red dead-nettle",
        "indicators": "sandy loam; fertile, rich in nutrients; moderate organic matter.",
    },
    {
        "latin": "Legousia hybrida",
        "common": "Venus's-looking-glass",
        "indicators": "chalky soils; rich in bases; deficiency of humus and clay; low nitrogen.",
    },
    {
        "latin": "Lolium multiflorum",
        "common": "Italian rye-grass",
        "indicators": "moderately fertile; high N / rich in N; compacted; well-drained; excess nitrates.",
    },
    {
        "latin": "Lolium perenne",
        "common": "Perennial rye-grass",
        "indicators": "pH 5-8.",
    },
    {
        "latin": "Lotus corniculatus",
        "common": "Bird's-foot trefoil",
        "indicators": "low fertility.",
    },
    {
        "latin": "Matricaria discoidea",
        "common": "Pineapple weed",
        "indicators": "sandy/loam soils; nutrient-rich; compaction, hardpan or crusty surface; damp soils.",
    },
    {
        "latin": "Medicago lupulina",
        "common": "Black medic",
        "indicators": "dry soil; low nitrogen.",
    },
    {
        "latin": "Myosotis arvensis",
        "common": "Field forget-me-not",
        "indicators": "rich in bases; excess carbon; sometimes excess manure.",
    },
    {
        "latin": "Papaver rhoeas",
        "common": "Common poppy",
        "indicators": "good moisture; sudden increases in pH; contrasting moisture conditions (dry summer, wet winter); low cover.",
    },
    {
        "latin": "Persicaria maculosa",
        "common": "Redshank / Lady's thumb",
        "indicators": "acid or low lime; pH 5-7; acidic soil; sand/light soil; high fertility/humus; well aerated/excess C/gley formation; wet/waterlogged/poorly drained; cultivated or trampled when wet/anaerobic.",
    },
    {
        "latin": "Phleum pratense",
        "common": "Timothy",
        "indicators": "heavy soils; balance of carbon, organic matter and bases; damp/moist; balance of nitrogen and nutrients.",
    },
    {
        "latin": "Plantago lanceolata",
        "common": "Ribwort plantain",
        "indicators": "balance of organic matter; fertility/aerobic microbial activity; moisture balance.",
    },
    {
        "latin": "Plantago media",
        "common": "Hoary plantain",
        "indicators": "richness in bases; pH >= 7.5; blockage of P due to elevated pH; blockage of K due to elevated pH.",
    },
    {
        "latin": "Plantago sp.",
        "common": "Plantains",
        "indicators": "clay/heavy soils; acid or low lime; compaction; wet/waterlogged/poorly drained and anaerobic/hydric soils.",
    },
    {
        "latin": "Poa annua",
        "common": "Annual meadowgrass",
        "indicators": "fertile soils; compaction; erosion and leaching of soils with low retention capacity; humid soil.",
    },
    {
        "latin": "Poa trivialis",
        "common": "Rough stalked meadowgrass",
        "indicators": "pH>5; excess of phosphorus and mineral nitrogen; excess carbon; moisture retentive/waterlogged; excess phosphorus.",
    },
    {
        "latin": "Polygonum aviculare",
        "common": "Common knotgrass / Prostrate knotweed",
        "indicators": "acid or low lime; low fertility; compaction/erosion; well-drained (summer); waterlogged; excess nitrates/nitrites; low cover (bare soil).",
    },
    {
        "latin": "Ranunculus repens",
        "common": "Creeping buttercup",
        "indicators": "clay/heavy soils; lime deficiency; cultivated soil/wet tillage; compaction of the soil when wet; waterlogged/poorly drained; surplus N at the surface.",
    },
    {
        "latin": "Raphanus raphanistrum",
        "common": "Runch / Wild radish",
        "indicators": "acid or low lime; sandy/loam soils; lime deficiency/excess lime; low fertility/high nutrient levels; compaction of soils rich in bases provoking anaerobic conditions; extreme contrasts in moisture (dry then wet); surplus N at surface; blockage of P due to anaerobic conditions; blockage of K due to anaerobic conditions.",
    },
]

# Species from pages 10-15 of the 2024 update (species not in 2022 guide)
MAUGHAN_AMOS_2024_EXTRA = [
    {
        "latin": "Rumex obtusifolius",
        "common": "Broad-leaved dock",
        "indicators": "high fertility; compaction; waterlogged/poorly drained; excess potassium; high nitrogen.",
    },
    {
        "latin": "Rumex crispus",
        "common": "Curled dock",
        "indicators": "clay soils; poorly drained; compaction; high potassium; anaerobic conditions.",
    },
    {
        "latin": "Senecio vulgaris",
        "common": "Groundsel",
        "indicators": "cultivated/disturbed soils; high fertility; well-drained; nitrogen-rich.",
    },
    {
        "latin": "Sinapis arvensis",
        "common": "Charlock",
        "indicators": "alkaline/calcareous soils; high fertility; clay/loam; well-drained; rich in bases.",
    },
    {
        "latin": "Sonchus arvensis",
        "common": "Perennial sow-thistle",
        "indicators": "clay soils; compaction; waterlogging; high fertility.",
    },
    {
        "latin": "Sonchus asper",
        "common": "Prickly sow-thistle",
        "indicators": "fertile soils; clay/loam; nitrogen-rich; disturbed ground.",
    },
    {
        "latin": "Stellaria media",
        "common": "Common chickweed",
        "indicators": "fertile, well-aerated soils; nitrogen-rich; moist; high organic matter.",
    },
    {
        "latin": "Taraxacum officinale",
        "common": "Dandelion",
        "indicators": "clay soils; compaction; low calcium; high potassium; anaerobic soils; calcium deficiency.",
    },
    {
        "latin": "Trifolium repens",
        "common": "White clover",
        "indicators": "low nitrogen; moist; compacted; low fertility.",
    },
    {
        "latin": "Tussilago farfara",
        "common": "Coltsfoot",
        "indicators": "clay soils; poorly drained; alkaline; waterlogged; compacted.",
    },
    {
        "latin": "Urtica dioica",
        "common": "Common nettle",
        "indicators": "high nitrogen; high fertility; rich in phosphates; moist; high organic matter; rich in bases.",
    },
    {
        "latin": "Veronica persica",
        "common": "Common field speedwell",
        "indicators": "fertile soils; nitrogen-rich; moist; disturbed soils.",
    },
    {
        "latin": "Vicia sativa",
        "common": "Common vetch",
        "indicators": "low nitrogen; well-drained; sandy/loam soils; low fertility.",
    },
]

---
species: "Echinochloa colona"
common_names: ["Awnless barnyard grass", "Junglerice"]
regions: ["Australia"]
tracks: ["AU Phase 2"]

moisture:
  value: "Moist soils — requires >20 mm rainfall for germination; peak emergence Nov-Dec after summer rain"
  confidence: high
  source: "Chauhan 2023 GRDC Update; Mahajan et al. 2023 Agronomy MDPI; AgriFutures Australia 2022"
  notes: "Multiple cohorts Oct-Feb. Germination triggered by >20 mm rainfall events. Peak in December. Heavy clay soils retain moisture and favour germination."

pH:
  value: "Wide range — pH 4-10; germination unaffected by pH in this range"
  confidence: high
  source: "Mutti et al. 2019 Crop & Pasture Science (CSIRO)"
  notes: "Exceptionally wide pH tolerance. Not a pH indicator species."

fertility:
  value: "High nitrogen uptake — can remove up to 80% of soil mineral nitrogen"
  confidence: high
  source: "AgriFutures Australia 2022; Opena 2021 Charles Sturt University PhD"
  notes: "Major nitrogen competitor in rice and summer crops. Estimated to remove up to 80% of soil mineral N. High fertility indicator for summer cropping."

structure:
  value: "Heavy-textured soils preferred — higher clay content favours germination; light-stimulated, surface-germinating"
  confidence: high
  source: "Mahajan et al. 2023 Agronomy; Mutti et al. 2019 Crop & Pasture Science"
  notes: "Dominated in heavy-textured soils with high clay. Surface germination (light-dependent). No-till favours persistence. Burial below 8 cm prevents emergence."

salinity:
  value: "Moderately salt-tolerant — GR biotype more tolerant (209 mM NaCl for 50% inhibition)"
  confidence: high
  source: "Mutti et al. 2019 Crop & Pasture Science (CSIRO)"
  notes: "Glyphosate-resistant biotype had higher salt tolerance than susceptible (209 vs 174 mM NaCl). May indicate saline areas."

nutrients:
  - nutrient: "Nitrogen"
    relationship: "depletive"
    confidence: high
    source: "AgriFutures Australia 2022; Opena 2021 CSU PhD"
    notes: "Major N depleter — removes up to 80% of soil mineral nitrogen in rice systems."

extra_dimensions:
  mycorrhizal:
    value: "AM — likely (Poaceae)"
    confidence: low
    source: "General Poaceae trait"
    notes: ""
  insect_connection:
    value: "Not specifically noted in AU sources"
    confidence: low
    source: "No specific AU source"
    notes: ""

regional_notes:
  australia:
    value: "Top 3 most problematic summer crop weeds in Australia. Costs grain industry $14.6M annually. Present in all states. Glyphosate-resistant populations confirmed in northern grain region (36% of surveyed populations resistant). Major weed of sorghum, cotton, mungbean, maize, and rice. Up to 40,000 seeds/plant. Seeds persist >2 years in light-textured soil. Winter pasture legume rotations suppress seedbank in rice systems."
    source: "Chauhan 2023 GRDC Update; Mahajan et al. 2023; Mutti et al. 2019; AgriFutures 2022; Pratley et al. 2008 Aust J Ag Research"

overall_confidence: high
source_count: 7

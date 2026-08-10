#!/usr/bin/env python3
"""
Merge Firecrawl Round 1 research into the AUGURY database.
Adds new indicator dimensions and nutrient claims from deep research.
"""
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from species_lookup import SpeciesDB

P = Path(__file__).resolve().parent.parent

# ── New indicator data from Firecrawl research ──────────
# Format: {species_key: {"indicators": {dim: value}, "nutrients": [{nutrient, relationship, source}]}}

NEW_DATA = {
    "rumex crispus": {
        "indicators": {
            "Moisture": "high moisture preference; tolerates waterlogged soils; indicates poorly drained conditions",
            "Soil pH": "pH 5.2-7.0; less frequently on peat soils or very acidic conditions <5.2",
            "Fertility": "low to moderate nutrient requirement; responds to N and P",
            "Structure": "strong indicator of soil compaction; tolerates waterlogged and poorly drained soils",
            "Salinity": "moderate salinity tolerance; has salt glands on leaves that release salt"
        },
        "nutrients": [
            {"nutrient": "calcium", "relationship": "indicates low calcium", "source": "Cornell University Weed Science", "confidence": "medium"},
            {"nutrient": "magnesium", "relationship": "indicates extremely high", "source": "MSU Extension", "confidence": "medium"},
            {"nutrient": "phosphorus", "relationship": "indicates extremely high", "source": "MSU Extension", "confidence": "medium"},
            {"nutrient": "potassium", "relationship": "indicates extremely high", "source": "MSU Extension", "confidence": "medium"},
            {"nutrient": "zinc", "relationship": "accumulator", "source": "Cornell University Weed Science", "confidence": "medium"}
        ]
    },
    "rumex obtusifolius": {
        "indicators": {
            "Moisture": "prefers moist, well-aerated, deep soils; indicates moist conditions in permanent grasslands",
            "Soil pH": "tolerates broad pH range; documented up to pH 8.20-8.25; grows less on very acidic <5.2",
            "Fertility": "strong indicator of fertile, nutrient-rich soils; high N, P, K response",
            "Structure": "prefers well-aerated soils; heavy/clay soils; indicates compacted soil in some contexts",
            "Salinity": "tolerates moderately saline soils; ECe 2.78-2.80 mS/cm (~1.4 dS/m)"
        },
        "nutrients": [
            {"nutrient": "nitrogen", "relationship": "responds strongly to N, P, K", "source": "Cornell University Weed Science", "confidence": "medium"}
        ]
    },
    "cirsium vulgare": {
        "indicators": {
            "Moisture": "intermediate moisture; tolerates dry and wet soils; germinates with adequate soil moisture",
            "Soil pH": "tolerates wide pH range; rare below pH 4.8; neutral preferred",
            "Fertility": "grows best on nitrogen-rich soils; proliferates with N fertilization",
            "Structure": "strong indicator of soil compaction; favored by soil disturbance; overgrazed rangelands",
            "Salinity": "not considered halophytic or salt-tolerant; primarily non-saline environments"
        },
        "nutrients": [
            {"nutrient": "nitrogen", "relationship": "strong nitrogen dependence; proliferates with N fertilization", "source": "USDA FEIS", "confidence": "high"}
        ]
    },
    "galium aparine": {
        "indicators": {
            "Moisture": "moist soil preference; indicator of moist conditions; found in riparian areas, floodplains",
            "Soil pH": "pH 5.5-8.0; indicative of pH 5.8-7.0; absent at pH 4.1",
            "Fertility": "prefers nutrient-rich sites; indicator of fertile soil; above-average N and P",
            "Structure": "occurs on most soils; indicator of loam; found on rich loam, heavy organic soils",
            "Salinity": "limited salinity tolerance; primarily non-saline environments"
        },
        "nutrients": [
            {"nutrient": "nitrogen", "relationship": "high nitrogen indicator; frequency increases with soil N content", "source": "USDA Forest Service FEIS", "confidence": "high"},
            {"nutrient": "cadmium", "relationship": "accumulator; 139.63 mg/kg at soil Cd 75 mg/kg", "source": "Fresenius Environmental Bulletin 2015", "confidence": "medium"}
        ]
    },
    "chenopodium album": {
        "indicators": {
            "Moisture": "moist soils preferred; tolerates dry and moist; drought tolerant once established",
            "Soil pH": "pH 4-10 very broad; thrives across broad pH range; germination unaffected by pH",
            "Fertility": "highly fertile soil indicator; heavy feeder; highly responsive to N",
            "Structure": "tolerant of soil compaction; establishes in compacted disturbed areas",
            "Salinity": "facultative halophyte; 37% germination at 200 mM NaCl; GR50 at 139.9 mM NaCl"
        },
        "nutrients": [
            {"nutrient": "nitrogen", "relationship": "strong nitrogen indicator; responds up to 480 lb N/acre", "source": "Cornell University CALS", "confidence": "high"},
            {"nutrient": "phosphorus", "relationship": "moderate response to P up to 52 kg/ha", "source": "Cornell University CALS", "confidence": "medium"},
            {"nutrient": "potassium", "relationship": "strong response; highly competitive when K is high", "source": "Cornell University CALS", "confidence": "medium"}
        ]
    },
    "amaranthus retroflexus": {
        "indicators": {
            "Moisture": "moderate to well-drained; drought tolerant; disturbed, dry-to-moist soils",
            "Soil pH": "pH 5.5-7.5; less common below pH 5.0; occasionally to pH 8.0",
            "Fertility": "moderately fertile soils; tolerates low-to-moderate fertility; pioneer species",
            "Structure": "highly tolerant of soil compaction; indicator of compacted, crusted, disturbed soils",
            "Salinity": "moderate salt tolerance; ECe 4-8 dS/m threshold"
        },
        "nutrients": [
            {"nutrient": "nitrogen", "relationship": "strong nitrogen accumulator and indicator", "source": "MSU Extension", "confidence": "high"},
            {"nutrient": "potassium", "relationship": "very high in K", "source": "MSU Extension", "confidence": "medium"},
            {"nutrient": "manganese", "relationship": "very high in Mn", "source": "MSU Extension", "confidence": "medium"},
            {"nutrient": "phosphorus", "relationship": "low in P", "source": "MSU Extension", "confidence": "medium"},
            {"nutrient": "calcium", "relationship": "low in Ca", "source": "MSU Extension", "confidence": "medium"}
        ]
    },
    "portulaca oleracea": {
        "indicators": {
            "Moisture": "moist, well-drained; drought tolerant; optimal growth with consistent moisture",
            "Soil pH": "pH 5.6-7.8; germination unaffected pH 5-9; tolerates acid, alkaline, neutral",
            "Fertility": "most problematic on highly fertile soils; indicates fertile, cultivated areas",
            "Structure": "tolerates compacted, disturbed, and sandy soils; common on disturbed areas",
            "Salinity": "highly salt-tolerant halophyte; threshold ECe 6.3 dS/m; 50% reduction at ECe 11.5 dS/m"
        },
        "nutrients": [
            {"nutrient": "phosphorus", "relationship": "indicates abundance of P", "source": "Cornell CALS; USDA-ARS Salinity Lab", "confidence": "high"},
            {"nutrient": "calcium", "relationship": "accumulator; tissue 98.5-324 mmol/kg dry wt", "source": "USDA-ARS", "confidence": "medium"},
            {"nutrient": "magnesium", "relationship": "accumulator", "source": "USDA-ARS", "confidence": "medium"},
            {"nutrient": "potassium", "relationship": "accumulator; 890-2410 mmol/kg", "source": "USDA-ARS", "confidence": "high"},
            {"nutrient": "iron", "relationship": "accumulator", "source": "USDA-ARS", "confidence": "medium"},
            {"nutrient": "zinc", "relationship": "accumulator", "source": "USDA-ARS", "confidence": "medium"}
        ]
    },
    "plantago major": {
        "indicators": {
            "Moisture": "tolerates long periods of waterlogging; indicates poorly drained soils",
            "Soil pH": "pH 6.5-7.8; tolerates very high pH >8.0; indicates high pH",
            "Fertility": "tolerates low N and P; indicates low fertility",
            "Structure": "highly tolerant of soil compaction; strong indicator of compacted soil",
            "Salinity": "salt tolerant; occurs on seashores and roadsides with de-icing salts"
        },
        "nutrients": [
            {"nutrient": "nitrogen", "relationship": "tolerates low N; germination stimulated by nitrate", "source": "Cornell University CALS", "confidence": "medium"},
            {"nutrient": "phosphorus", "relationship": "tolerates low P", "source": "Cornell University CALS", "confidence": "medium"}
        ]
    },
    "conyza canadensis": {
        "indicators": {
            "Moisture": "drought-tolerant; prefers drier soils; indicates seasonal moisture stress",
            "Soil pH": "pH 5.0-8.0; very wide tolerance; slightly acidic to neutral preferred",
            "Fertility": "indicates poor to moderately fertile soils; pioneer on infertile, degraded sites",
            "Structure": "highly tolerant of soil compaction; indicator of severely compacted, eroded soils",
            "Salinity": "moderate to low salt tolerance; optimal ECe <2-4 dS/m; sensitive >3 dS/m"
        },
        "nutrients": [
            {"nutrient": "nitrogen", "relationship": "indicates poor N and P status; pioneer on N-deficient soils", "source": "UMass Extension", "confidence": "high"},
            {"nutrient": "phosphorus", "relationship": "indicates poor P status", "source": "UMass Extension", "confidence": "medium"},
            {"nutrient": "potassium", "relationship": "associated with K-deficient soils", "source": "UMass Extension", "confidence": "medium"}
        ]
    },
    "urtica dioica": {
        "nutrients": [
            {"nutrient": "calcium", "relationship": "dynamic accumulator; 17,440 ppm with BAF 8.1", "source": "SARE/Rutto 2013", "confidence": "high"},
            {"nutrient": "iron", "relationship": "accumulator; 52.11 mg/100g", "source": "Rutto 2013", "confidence": "high"},
            {"nutrient": "potassium", "relationship": "accumulator; 2.8% dry basis", "source": "Adhikari 2015", "confidence": "high"},
            {"nutrient": "magnesium", "relationship": "accumulator", "source": "ScienceDirect 2022", "confidence": "medium"},
            {"nutrient": "phosphorus", "relationship": "accumulator", "source": "ScienceDirect 2022", "confidence": "medium"},
            {"nutrient": "zinc", "relationship": "accumulator", "source": "ScienceDirect 2022", "confidence": "medium"}
        ]
    },
    "capsella bursa-pastoris": {
        "nutrients": [
            {"nutrient": "calcium", "relationship": "accumulator; >1.7% Ca dry weight", "source": "Mountain Herb", "confidence": "medium"},
            {"nutrient": "potassium", "relationship": "accumulator; 1.3% K dry weight", "source": "Mountain Herb", "confidence": "medium"},
            {"nutrient": "phosphorus", "relationship": "accumulator; 729 mg/100g", "source": "Mountain Herb", "confidence": "medium"},
            {"nutrient": "iron", "relationship": "accumulator; 40.7 mg/100g", "source": "Mountain Herb", "confidence": "medium"},
            {"nutrient": "nitrogen", "relationship": "prefers N-rich soils", "source": "Magic Garden Seeds", "confidence": "low"}
        ]
    },
    "cirsium arvense": {
        "nutrients": [
            {"nutrient": "calcium", "relationship": "accumulator; NE ratio 2.59-11.29 vs maize", "source": "Liska et al. 2007", "confidence": "high"},
            {"nutrient": "nitrogen", "relationship": "accumulator; NE ratio 1.09-1.65", "source": "Liska et al. 2007", "confidence": "high"},
            {"nutrient": "phosphorus", "relationship": "accumulator; NE ratio 1.12-1.16", "source": "Liska et al. 2007", "confidence": "high"},
            {"nutrient": "potassium", "relationship": "accumulator; NE ratio 0.87-2.51", "source": "Liska et al. 2007", "confidence": "high"},
            {"nutrient": "magnesium", "relationship": "accumulator; NE ratio 0.82-1.74", "source": "Liska et al. 2007", "confidence": "high"},
            {"nutrient": "potassium", "relationship": "indicates low K soils", "source": "Harrington et al. 2014 NZPP", "confidence": "medium"},
            {"nutrient": "magnesium", "relationship": "indicates low Mg soils", "source": "Harrington et al. 2014 NZPP", "confidence": "medium"},
            {"nutrient": "iron", "relationship": "indicates excess Fe", "source": "Fairfax Gardening", "confidence": "low"},
            {"nutrient": "manganese", "relationship": "indicates deficient Mn", "source": "Fairfax Gardening", "confidence": "low"}
        ]
    },
    "stellaria media": {
        "nutrients": [
            {"nutrient": "nitrogen", "relationship": "indicates high N, fertile soil", "source": "Almanac; Oladeji et al. 2020", "confidence": "high"}
        ]
    },
    "sinapis arvensis": {
        "nutrients": [
            {"nutrient": "potassium", "relationship": "indicates excess K", "source": "Fairfax Gardening", "confidence": "low"},
            {"nutrient": "phosphorus", "relationship": "indicates low P", "source": "Fairfax Gardening", "confidence": "low"}
        ]
    },
    "equisetum arvense": {
        "nutrients": [
            {"nutrient": "calcium", "relationship": "indicates Ca deficiency", "source": "Fairfax Gardening", "confidence": "low"},
            {"nutrient": "silica", "relationship": "accumulator", "source": "BC Farms and Food", "confidence": "medium"}
        ]
    },
    "elymus repens": {
        "nutrients": [
            {"nutrient": "iron", "relationship": "indicates improper Fe-Mn ratio", "source": "Fairfax Gardening", "confidence": "low"},
            {"nutrient": "manganese", "relationship": "indicates improper Fe-Mn ratio", "source": "Fairfax Gardening", "confidence": "low"}
        ]
    },
    "cichorium intybus": {
        "nutrients": [
            {"nutrient": "potassium", "relationship": "accumulator; 699 mg/100g", "source": "Agricultural Science UA", "confidence": "medium"},
            {"nutrient": "calcium", "relationship": "accumulator", "source": "Permies.com", "confidence": "low"},
            {"nutrient": "phosphorus", "relationship": "accumulator", "source": "Permaculture Scotland", "confidence": "low"},
            {"nutrient": "nitrogen", "relationship": "indicates rich, N-heavy soil", "source": "Almanac", "confidence": "medium"}
        ]
    },
    "trifolium pratense": {
        "nutrients": [
            {"nutrient": "iron", "relationship": "dynamic accumulator; 57.3 ppm Fe with BAF", "source": "SARE/Tyler & Zarro", "confidence": "high"},
            {"nutrient": "nitrogen", "relationship": "vigorous growth indicates N-deficient soil", "source": "McGill EAP", "confidence": "medium"}
        ]
    },
    "symphytum officinale": {
        "nutrients": [
            {"nutrient": "potassium", "relationship": "accumulator; 12,600 ppm K with BAF 5.5", "source": "SARE/Tyler & Zarro 2020", "confidence": "high"},
            {"nutrient": "calcium", "relationship": "accumulator; 6,583 ppm Ca", "source": "SARE/Tyler & Zarro 2020", "confidence": "high"},
            {"nutrient": "nitrogen", "relationship": "accumulator; 10,000 ppm N with BAF 3.0", "source": "SARE/Tyler & Zarro 2020", "confidence": "high"}
        ]
    },
}


def main():
    db = SpeciesDB()
    updated = 0
    new_nutrients = 0
    
    for key, new_data in NEW_DATA.items():
        if key not in db._species:
            print(f"  WARNING: species '{key}' not in database, skipping")
            continue
        
        info = db._species[key]
        
        # Add new indicators
        indicators = new_data.get("indicators", {})
        if indicators:
            for region in info.get("regions", {}):
                if "indicators" not in info["regions"][region]:
                    info["regions"][region]["indicators"] = {}
                info["regions"][region]["indicators"].update(indicators)
            updated += 1
        
        # Add new nutrients
        nutrients = new_data.get("nutrients", [])
        if nutrients:
            if key in db._nutrients:
                db._nutrients[key]["claims"].extend(nutrients)
            else:
                db._nutrients[key] = {"claims": nutrients}
            new_nutrients += len(nutrients)
    
    # Write updated merged database
    merged_path = Path(__file__).resolve().parent.parent / "data" / "research" / "database-merged.json"
    import json
    with open(merged_path) as f:
        merged_db = json.load(f)
    
    # Also update database-merged.json for the species we modified
    for key, new_data in NEW_DATA.items():
        if key not in merged_db:
            continue
        indicators = new_data.get("indicators", {})
        nutrients = new_data.get("nutrients", [])
        
        if indicators:
            for region in merged_db[key].get("regions", {}):
                merged_db[key]["regions"][region].setdefault("indicators", {}).update(indicators)
        
        if nutrients:
            merged_db[key].setdefault("nutrients", {}).setdefault("claims", []).extend(nutrients)
    
    with open(merged_path, "w") as f:
        json.dump(merged_db, f, indent=2, ensure_ascii=False)
    
    print(f"=== Merge Complete ===")
    print(f"Species with new indicators: {updated}")
    print(f"New nutrient claims added: {new_nutrients}")
    print(f"Merged DB updated: {len(merged_db)} species")
    
    # Show what changed
    print(f"\n=== Updated Coverage ===")
    au_count = sum(1 for v in db._species.values() if 'Australia' in v.get('regions', {}))
    print(f"Total species: {len(db._species)}")
    print(f"AU species: {au_count}")
    print(f"Species with nutrients: {len(db._nutrients)}")


if __name__ == "__main__":
    main()

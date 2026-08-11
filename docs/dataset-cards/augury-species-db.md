# AUGURY Species Database

Deterministic species → soil-indicator database. The source of truth for AUGURY:
models never emit facts from memory — they receive these records from the lookup
engine (`species_lookup.py`) and present them conversationally.

## Files

- `database-merged.json` — 2,230 species, regions (Europe / Australia / UK),
  per-region indicator dicts (Moisture, Soil pH, Fertility, Salinity, Structure, ...),
  nutrients claims where researched
- `species_list.json` — 2,230-species vision list: image keys, common names,
  `is_au` flag, same indicator data (used by the vision dataset builders)
- `unified_species_database.json` — legacy consolidated view (superseded by
  database-merged.json)

## Provenance (see also `LICENSE` in the repo root)

| Source | Region | Notes |
|---|---|---|
| Ellenberg Indicator Values (1991) | Europe | 2,793 species, cited values |
| Maughan & Amos bioindicators guides (2022, 2024) | UK | manual extraction |
| CAWR Bioindicators Field Guide (2021) | UK | manual transcription |
| AU government extension publications (SA, VIC, NSW DPI, QLD DAF) | Australia | 188 AU species |
| Web-sourced indicator claims (`data/mining/`) | mixed | unverified, flagged |

## License

CC-BY-4.0. Indicator claims are literature-based and **not verified on-farm**.
AUGURY provides indicators only — never management or remediation advice.

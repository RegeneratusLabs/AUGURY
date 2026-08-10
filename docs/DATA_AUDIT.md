# AUGURY — Data Audit Report

**Date:** 28 July 2026
**Scope:** Forensic audit of all training data, database, scripts, and edge cases
**Auditor:** Reasonix (systematic analysis with bash + Python tools)

---

## Critical Findings (Fix Before Training)

### C1. Feedback Loop Broken — User Question Not Stored
- **File:** `feedback.jsonl`
- **Issue:** Stores only `{timestamp, rating, response, region}`. The user's
  QUESTION is not recorded — making it impossible to diagnose bad ratings.
- **Fix:** Update `augury_server.py` / `augury_server_v2.py` to include
  `question` field in feedback records.
- **Severity:** Critical — prevents model improvement from real-world use.

### C2. Empty String / Space Search Returns Spurious Results
- **File:** `scripts/species_lookup.py` — `search()` method
- **Issue:** Queries `""` and `" "` each return 3 results (first 3 species
  alphabetically). Should return empty list.
- **Impact:** In production, a user submitting a blank query would get
  misleading results instead of an error prompt.
- **Fix:** Add input validation: if query is empty/whitespace after stripping,
  return `[]`.
- **Severity:** Critical — production bug.

### C3. "Pigweed" Common Name Not Found
- **File:** `scripts/species_lookup.py` — common name index
- **Issue:** `search("Pigweed")` returns 0 results despite "pigweed" being
  a common name for *Amaranthus* species and "Redroot pigweed" being the
  standard common name for *Amaranthus retroflexus*.
- **Root cause:** The common name index appears to only index exact-matching
  entries. "Pigweed" likely exists in the database under a plural or
  alternative form.
- **Fix:** Verify common name index covers all known variants. Add fuzzy
  matching fallback for common names.
- **Severity:** Critical — common agricultural weed name returns nothing.

---

## High Findings (Fix Before Training if Possible)

### H1. 95.5% European Data Dominance
- **Region split:** EU=27,159 (95.5%), UK=1,048 (3.7%), AU=136 (0.5%)
- **Impact:** Model trained on this split would be a European Ellenberg
  specialist, failing on Australian queries.
- **Mitigation:** Already addressed via research phases (104 AU species
  identified, awaiting merge). Training data must be regenerated with
  balanced AU representation before training.
- **Severity:** High — architecture is designed for this fix.

### H2. 7,967 Duplicate Question Occurrences (28% Redundancy)
- **Training data:** 28,449 total rows, 20,482 unique questions, 7,967
  duplicates (same species + same template appearing twice).
- **Impact:** 28% of training budget wasted on redundant examples. Effects
  are minor (slight over-weighting of those species) but wasteful.
- **Root cause:** Template-based generation producing the same species twice,
  or species appearing in multiple source datasets without dedup.
- **Fix:** Add question-text dedup to `merge_datasets.py`'s `merge_and_split`
  function (currently dedups only by species key).
- **Severity:** High — wastes compute and may skew species representation.

### H3. Only 110 Species Have Real Common Names
- **Breakdown:** 110 with genuine common names, 1,955 with scientific name
  used as common name (e.g. "Geranium phaeum" listed as both), 175 with no
  common name at all.
- **Impact:** The model learns to output scientific names for most species,
  which is unhelpful for farmers who use common names.
- **Fix:** Not a quick fix — requires sourcing common names for ~2,000
  species. Prioritise the 646 agricultural/cosmopolitan species from the
  pruned DB.
- **Severity:** High — affects user experience but known and documented.

### H4. V3 Training Data Is European-Only
- **1,542 rows** across 4 layers — all query European species. No Australian
  variants exist.
- **Impact:** The tool-calling model would learn to call `lookup_species()`
  with `region: "Europe"` only, never "Australia" or "UK".
- **Fix:** Regenerate V3 data after merging AU research. Each species needs
  tool-use examples with all applicable regions.
- **Severity:** High — must be fixed before V3 training.

---

## Medium Findings (Fix When Convenient)

### M1. Hardcoded Paths in Training Scripts
| File | Line | Issue |
|---|---|---|
| `scripts/convert_to_gguf.py` | 22 | `LORA_DIR = "Weeds V1"` (CLI override exists but default is wrong) |
| `scripts/train_augury_v2.py` | 188 | `output_dir = "augury_v2_lora"` (hardcoded) |

- **Fix:** Parameterise. Convert to CLI arguments or config file.
- **Severity:** Medium — causes confusion but not data corruption.

### M2. No AU Region Data in V3 Examples
- All 1,542 V3 training examples use European species. The tool-calling
  format supports `region` argument but has no AU examples for the model
  to learn from.
- **Fix:** Generate AU-specific tool-use examples for the 104 new AU species.
- **Severity:** Medium — the model architecture supports it, data just
  needs generating.

### M3. Duplicate Question Detection Not in Pipeline
- `merge_datasets.py` dedups by species key, not by question text. Two
  entries for the same species with the same template text both survive.
- **Fix:** Add question-text hashing to the dedup logic.
- **Severity:** Medium — improves training efficiency.

---

## Low Findings (Informational / Deferred)

### L1. Ellenberg Source Has No Version Metadata
- **File:** `data/sources/Ellenberg_VascularPlants.csv`
- **2,793 species**, fields: Name, L, T, K, F, R, N, S, LF, LF_B
- No date, version, or provenance metadata in file. Original source is
  Ellenberg (1991).
- **Impact:** Cannot verify if this is the original or updated version.
- **Action:** Add metadata header row. Note source year and calibration region.

### L2. V3 Dataset Is Small (1,542 Rows) for 4B Model
- 4B models typically need 5K-50K fine-tune examples. 1,542 is at the
  low end.
- **Mitigation:** LoRA is efficient for small datasets. Can also augment
  with V2 formatting data.
- **Severity:** Low — workable but worth expanding.

### L3. Validation Split Is Healthy
- V2: 28,449 train / 3,131 val = 9.9% held out ✅
- V3: ~10% held out across all 4 layers ✅

### L4. No Region Tag Mismatches Found
- Sampled 10,000 training rows: 0 cases where a species is tagged with a
  region it doesn't exist in. ✅

### L5. No Ducerf Data Leaks into Training
- Ducerf references exist only in `merge_datasets.py` as a filter rule.
  No Ducerf data survives into training. ✅

### L6. All Training Species Exist in Database
- Sampled: 0 species in training data that aren't in database.json. ✅

### L7. Refusal Examples Correctly Structured
- No herbicide advice leaked into refusal responses. System prompt
  boundary respected. ✅

### L8. V3 Tool-Calling Format Correct
- `function_call` JSON correctly formatted. Multi-turn tool sequences
  work. Direct answer and refusal layers properly structured. ✅

---

## Summary Table

| ID | Finding | Severity | Status |
|---|---|---|---|
| C1 | Feedback loop missing question field | Critical | 🔴 Unfixed |
| C2 | Empty query returns spurious results | Critical | 🔴 Unfixed |
| C3 | "Pigweed" common name not found | Critical | 🔴 Unfixed |
| H1 | 95.5% EU data dominance | High | ✅ Addressed (AU research done, awaiting merge) |
| H2 | 28% duplicate training questions | High | 🔴 Unfixed |
| H3 | Only 110 species have real common names | High | 🔴 Known, requires sourcing |
| H4 | V3 training data is European-only | High | 🔴 Needs regeneration |
| M1 | Hardcoded paths in training scripts | Medium | 🔴 Unfixed |
| M2 | No AU region data in V3 examples | Medium | 🔴 Needs generation |
| M3 | No question-text dedup | Medium | 🔴 Unfixed |
| L1-L8 | Various informational items | Low | ✅ Acceptable |

---

## Action Items Before Training

1. **Fix C1** — Update server to record user question with feedback
2. **Fix C2** — Add input validation to species_lookup.py search()
3. **Fix C3** — Debug common name index for "Pigweed" and other farm-relevant names
4. **Resolve H2** — Add question-text dedup to merge_datasets.py
5. **Resolve H4** — Regenerate V3 training data with AU species after merge
6. **Address M1** — Parameterise hardcoded paths post-training

**Items that DON'T block training:**
- H3 (common names) — Nice but not a blocker. Model can say scientific names.
- M2/M3 — Can be fixed incrementally.
- L1-L8 — Already acceptable.

---

## Fixes Applied (28 July 2026)

### Resolved — Critical
| ID | Finding | Fix |
|---|---|---|
| C1 | Feedback loop missing question | Both v1 and v2 servers now capture last user question from DOM |
| C2 | Empty query returns spurious results | Early return `[]` added to search() before partial matching |
| C3 | "Pigweed" common name not found | Added 7 Amaranthus spp. with 'pigweed'/'redroot pigweed' to COMMON_NAMES |

### Resolved — Informational
| ID | Finding | Status |
|---|---|---|
| H2 (partial) | Purslane contradiction | Already resolved in DB — aggregate says high phosphorus, low-conf deficiency flagged |
| M1 (partial) | Hardcoded LORA_DIR | Default changed from Weeds V1 to augury_v2_lora. CLI override still available. |

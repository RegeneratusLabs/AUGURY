# AUGURY Training Data (text)

ShareGPT-format training data for the AUGURY text formatter (MiniCPM5-1B).
Each example: structured species/region/indicator data in the user turn →
conversational farmer-facing soil story in the assistant turn. The model learns
to *present given facts*, never to generate them.

## Files

- `weeds_indicators_merged_train.jsonl` — 13,627 rows (regenerated 2026-08-11
  from database-merged.json; AU-balanced: 186/188 AU species covered)
- `weeds_indicators_merged_val.jsonl` — 1,514 rows
- `standalone_train.jsonl` / `standalone_val.jsonl` — 612/69 clean Q&A rows
  (Path B reference; AU-heavy)
- `v3_function_calling/` — historical tool-calling format (1,522 rows;
  superseded by the retrieval+formatter architecture, kept for reference)

## Row anatomy

```
user:      Species: Hesperis matronalis
           Region: Europe

           Indicators:
           - Moisture: strictly damp to wet. Strong indicator of poor drainage
           - Soil pH: neutral. pH 6.0–7.5. ...

assistant: Let's look at what Hesperis matronalis is saying about your soil. ...
```

## Region balance (2026-08-11 regeneration)

Europe 13,446 · Australia 1,228 · UK 484 · refusal/no-region 84.
EU dominates by species count (2,263 Ellenberg species) — by design, every AU
species is fully represented with region-tagged examples.

## License

CC-BY-4.0 (see LICENSE-DATA in the repo root for per-source provenance).

# Photo-ID measurement log

## 2026-09-19 — gallery contamination repair

`index-v2` (contaminated) vs `index-v3` (cleaned), **same held-out queries**, so the
label repair is the only variable. 93 original query images whose files are NOT in
the rebuilt gallery:

| index | top-1 | top-3 |
|---|---|---|
| index-v2 (contaminated) | 78/93 = 83.87% | 92.47% |
| index-v3 (cleaned) | **79/93 = 84.95%** | 92.47% |

**Headline accuracy barely moved (+1.1 pt, n=93 — not significant).** The value of
the repair is elsewhere:

* The four contaminated species went from unlearnable to working:
  `holcus lanatus` 0/5 → 4/5, `raphanus raphanistrum` 0/5 → 4/5,
  `sinapis arvensis` 0/5 → 5/5, `prosopis spp` 6/10 → 4/5.
* **The 95% precision band became reachable.** `calibrate_bands.py` on the cleaned
  index finds `t=0.68` at **95.1% precision** (51.6% coverage). The handover's
  "no threshold reaches 95%" was a symptom of the contamination.
* Per-species numbers are now trustworthy; before, several were meaningless.

### A leakage trap worth remembering

A naive before/after on the *regenerated* split reported **97.88%**, which is
wrong. Rebuilding the split reshuffles which images are held out, and 803 of the
original query files became gallery members — the queries were matching
themselves. Any comparison across two different splits must exclude query files
that appear in the gallery being scored. That check is why this table says +1.1 pt
and not +14.7 pt.

### Current state (cleaned split, 910 queries / 184 species)

* top-1 **81.8%**, top-3 **89.7%**
* auto band ≥0.68: 95.1% precision, 51.6% coverage
* confirm band ≥0.43: 85.0% precision, 94.1% coverage

The 90% target is therefore ~8 points away, and the remaining gap is *not* data
corruption — it is thin galleries plus genuinely hard look-alike genera
(`banksia`/`hakea`/`callistemon`/`lepidosperma`, `austrostipa`/`austrodanthonia`).

# AUGURY — The 15GB Gallery vs. a Phone User (discussion + options)

**Status:** 2026-08-18 · Open product decision. This doc lays out why the raw
gallery is not shipped to phones, what actually goes on-device, and the options
for right-sizing the download. A decision is needed before the photo path ships.

---

## 1 · The key architectural fact

**A phone never downloads the 15GB raw gallery.** The gallery on HF
(`RegeneratusLabs/augury-vision-gallery`, 111,320 images) is the *source of
truth* — the thing you download once to build/extend the retrieval index. The
on-device artifact is the **FAISS index + embeddings**:

| Artifact | Size (approx) | What it is |
|---|---|---|
| Raw gallery (HF) | **15GB** | 111,320 JPEGs + license sidecars — rebuild/extend source |
| Full FAISS index (all 2,231 spp) | ~300-450MB | DINOv2-base embeddings (768-dim) + index + keys |
| AU-scoped index (188 spp, v1 scope) | ~40-90MB | same, only the AU subset |
| Quantised index (IVF/PQ/int8) | ~100-150MB full | smaller, small accuracy hit |

So "15GB for a phone" is a **misconception to kill in public messaging**: the
phone gets a compact index. The 15GB is a server/rebuild artifact.

## 2 · The real problem: the index is still the full 15GB-equivalent in vector space

Even though the *download* is small, the *memory + CPU* cost of kNN over the
full gallery is real on a phone:

- Full gallery = 111,320 vectors × 768 floats ≈ 342MB fp32 in RAM just for the
  matrix; a flat index search is O(N) per query (~111k cosine ops — fine on
  modern phone CPUs, a few ms, but RAM is the constraint).
- The full index is not even built yet (local checkpoint: 100/2,231 species).

## 3 · Options (recommendation first)

### Option A (recommended) — Ship the AU-scoped index by default
- **What:** build the index over the 188 AU species (the v1 product scope), ~40-90MB.
- **Why it wins:** matches the product's AU-first promise, tiny download, full
  confidence-band behaviour, and the EU/UK species stay on HF for future regions.
- **Cost:** an EU farmer's species won't resolve (honest "not in my library").
- **Effort:** embed ~20-30k AU images → index. One CPU overnight job (the
  `embed_gallery.py --au-only` path already exists).

### Option B — Quantise the full index (IVF/PQ or int8)
- **What:** keep all 2,231 species but shrink embeddings (PQ product quantisation
  or int8) → ~100-150MB download, sub-ms search.
- **Why:** covers everyone, still phone-friendly.
- **Cost:** small top-1 accuracy hit (PQ8 ≈ -1-2pt typically; must be measured
  on the AU bake-off before trusting it). More engineering.

### Option C — Tiered download (AU default + opt-in EU)
- **What:** app downloads AU index by default; "add European species (+120MB)"
  is an in-app opt-in.
- **Why:** power users / EU farmers get full coverage without burdening everyone.
- **Cost:** two index artifacts to build + version, more app logic.

### Option D — Hybrid retrieval with optional cloud fallback
- **What:** on-device AU index first; unresolved/low-confidence queries go to a
  hosted full index.
- **Why:** best coverage.
- **Cost:** violates the project's "no cloud API at runtime" guard rail; needs
  explicit sign-off to add an optional cloud path. **Not recommended for v1.**

## 4 · My recommendation

**Option A for v1** (AU-scoped default, ~40-90MB download), with **Option C**
as the immediate follow-up (EU opt-in) once the full index exists. Skip D unless
the product explicitly wants cloud fallback. Option B is worth prototyping in
parallel — quantising is cheap to try and the bake-off harness exists to
measure the accuracy hit.

## 5 · Decision needed

- [ ] Confirm Option A (AU-scoped index as the shipped phone bundle) for v1.
- [ ] Whether to build the full index now (7-9h CPU job) or only the AU index first.
- [ ] Whether an optional cloud fallback (Option D) is ever on the table (guard-rail change).

*See also: `docs/model-understanding-and-blindspots.md` (the phone path is
currently unbuilt), `docs/data-roadmap.md` (§3.4 index artifacts).*

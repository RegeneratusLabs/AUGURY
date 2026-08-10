# AUGURY — Photo-to-Indicators Pipeline Design

The full vision: farmer takes a photo → species identified → soil indicators returned.
Open source, all the way through.

---

## The pipeline

```
┌──────────┐     ┌────────────────┐     ┌──────────────────┐     ┌──────────────┐
│  Photo   │────▶│  Plant ID API  │────▶│  Species Lookup   │────▶│  AUGURY SLM  │
│  (phone) │     │  (iNaturalist  │     │  (deterministic)  │     │  (Qwen3-0.6B)│
│          │     │   or PlantNet)  │     │                   │     │              │
└──────────┘     └────────────────┘     └──────────────────┘     └──────────────┘
                        │                       │                       │
                   "Taraxacum              {moisture:...,          "Dandelions tell
                    officinale"             pH:...,                 you your soil
                    (92% confidence)        fertility:...}          is compacted..."
                        │                       │                       │
                        ▼                       ▼                       ▼
                 ┌──────────────────────────────────────────────────────────┐
                 │                    AUGURY Server (Flask)                   │
                 │                                                          │
                 │  /api/identify-from-photo    ← POST image                │
                 │  /api/chat                   ← text query (existing)     │
                 │  /api/feedback               ← thumbs up/down (existing) │
                 └──────────────────────────────────────────────────────────┘
```

---

## Plant Identification: Two options

### Option A: iNaturalist (recommended — free, unlimited, no attribution)

**Why**: Better for agricultural/pasture weeds (trained on real-world observations).
Completely free, no daily limits, no API key, no attribution required.
Perfect for open source.

**The catch**: No CORS headers. Can't call directly from a browser PWA.
Needs a server-side proxy — which we already have (Flask server).

```
Browser ──▶ Flask /api/identify-from-photo ──▶ iNaturalist CV API
                (server-side proxy)              POST /v1/computervision/score_image
```

**Endpoint**: `POST https://api.inaturalist.org/v1/computervision/score_image`
**No API key needed**. Rate limit: ~100 req/min per IP (generous).
**Latency**: 1-2 seconds.
**Output**: `[{taxon: {name, preferred_common_name}, score: 0.95}, ...]`

### Option B: PlantNet (simpler PWA, but limited free tier)

**Why**: CORS-enabled — direct browser-to-API calls possible. 78K+ species.
Great for European species. Requires attribution ("powered by Pl@ntNet" logo).

**The catch**: 500 free IDs/day. Need API key. Attribution required.
For an open source project, attribution is fine — the catch is the 500/day cap.

```
Browser ──▶ PlantNet API (direct, CORS-enabled)
             POST https://my-api.plantnet.org/v2/identify/all?api-key=KEY
```

**Endpoint**: `POST https://my-api.plantnet.org/v2/identify/all?api-key=KEY`
**Free tier**: 500 identifications/day.
**Latency**: 1-3 seconds.
**Output**: `[{score: 0.92, species: {scientificNameWithoutAuthor, commonNames}}]`

### Decision

**Use iNaturalist as primary, PlantNet as fallback.** The Flask server already exists —
adding a proxy endpoint is trivial. iNaturalist is unlimited and free. We add PlantNet
as an optional alternative if the user provides their own API key.

---

## Handling multiple candidates

Both APIs return a ranked list. The UX flow:

1. User takes photo → uploaded to server
2. Server queries iNaturalist → returns top 5 matches with confidence scores
3. If top match confidence > 85%: auto-select, go straight to indicators
4. If top match confidence 50-85%: show top 3, user taps to confirm
5. If top match confidence < 50%: show top 5 with "none of these" option,
   fall back to text search
6. Confirmed species → AUGURY lookup → conversational response

This prevents wrong identifications from cascading into wrong soil advice.

---

## Server architecture

```
augury_server.py
├── /                        ← Chat interface (existing, HTML served)
├── /api/chat                ← Text chat endpoint (existing)
├── /api/identify-from-photo ← NEW: accepts image, returns species + indicators
├── /api/feedback            ← Feedback collection (existing, needs fix)
│
├── species_lookup.py        ← NEW: Species database module
│   ├── SpeciesDB class
│   ├── .search(query)       ← fuzzy match on scientific + common names
│   ├── .get_indicators(species_name, region)
│   └── .get_common_name(species_name)
│
├── plant_id.py              ← NEW: Plant identification clients
│   ├── identify_inaturalist(image_bytes)  ← primary
│   └── identify_plantnet(image_bytes, api_key) ← optional
│
└── response_formatter.py    ← NEW: Structured data → conversational response
    └── format_indicators(species, indicators, region)
       Uses the AUGURY SLM (Qwen3-0.6B GGUF) for natural language generation
```

---

## The full user flow

```
1. USER opens AUGURY on phone (PWA or hosted URL)
2. USER taps camera button → phone camera opens (capture="environment")
3. USER takes photo of a weed in their paddock
4. Photo sent to server → iNaturalist API
5. iNaturalist returns: "Taraxacum officinale (Dandelion), 93% confidence"
6. Species lookup: {moisture: "compacted, dry...", pH: "5.5-7.0...", ...}
7. AUGURY SLM formats into conversational response
8. USER sees:
   ┌─────────────────────────────────────────┐
   │  🔍 Identified: Dandelion                │
   │     (Taraxacum officinale)               │
   │     Confidence: 93%                      │
   │                                         │
   │  Dandelions are telling you something    │
   │  about your soil. Their deep taproots    │
   │  indicate compaction — they're one of    │
   │  nature's primary soil-breakers. You're  │
   │  likely looking at compacted ground with │
   │  decent fertility, probably slightly     │
   │  acidic around pH 5.5 to 7.0...          │
   │                                         │
   │  [👍 Helpful]  [👎 Not quite]           │
   └─────────────────────────────────────────┘
9. USER provides feedback → stored with photo query + species + response
```

---

## Future: On-device plant ID

The ultimate goal — no API dependency, truly offline:

1. Fine-tune MobileNetV3 or ViT-Tiny on weed-specific datasets
   - PlantNet 300K dataset (CC-BY, 306K images, 1,081 species)
   - DeepWeeds (Australian weeds, 17K images)
   - Custom AU pasture weeds dataset
2. Convert to ONNX/TensorFlow Lite for phone deployment
3. Run entirely on-device alongside the GGUF model

This is the long-term vision. The iNaturalist API path gets us shipping now
while we build the on-device capability.

---

## What to build first

| Priority | Component | Effort | Impact |
|---|---|---|---|
| 1 | `species_lookup.py` — JSON database + fuzzy match + common names | 1-2 hours | Foundation for everything |
| 2 | `plant_id.py` — iNaturalist API client | 30 min | Photo pipeline works |
| 3 | `/api/identify-from-photo` endpoint | 30 min | Wires it all together |
| 4 | Camera UI in the chat interface | 1 hour | User-facing feature |
| 5 | Candidate selection UI | 1 hour | Handles uncertain IDs |
| 6 | `response_formatter.py` — SLM-powered formatting | 2 hours | Conversational responses |
| 7 | Train new AUGURY SLM (Qwen3-0.6B, formatting task) | Colab session | Better responses |
| 8 | Fix feedback loop (record questions) | 10 min | Data for iteration |

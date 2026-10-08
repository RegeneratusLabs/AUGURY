# Third-party plant-ID APIs vs. AUGURY's on-device model — research report

**Prepared:** 2026-10-08 (UTC)
**Scope:** whether to keep the custom on-device photo-ID model (DINOv2-base embeddings + kNN over own gallery) or call a third-party plant-ID API with user confirmation from a shortlist.
**Market:** Australia first (farmers, agronomists, regenerative agriculture); UK/Europe later. Free or low-cost Google Play app.

## How to read this report

Every factual claim is tagged:

- **[V]** = **verified** — I fetched the cited page/file directly on 2026-10-08 and the claim is a direct quote or an arithmetic consequence of a quoted price. URL given inline.
- **[I]** = **inference / not verified** — my reasoning, an unverified vendor claim, or something I could not confirm from a primary source.

**Method note:** the `web_search` tool was unavailable in this session (no API key configured), so I could not do open-ended discovery. I fetched known/guessed URLs directly, used the Europe PMC REST API for literature, Hugging Face's model API for licence metadata, and `curl` for status probing. This means the "newer 2025–2026 APIs" sweep is **not exhaustive** — see *What I could not verify*.

**Currency note:** prices are quoted in the currency the vendor publishes (EUR for Pl@ntNet and Kindwise, USD for Google). **I have not applied any AUD conversion** — no FX rate was verified. Date seen is 2026-10-08 for all prices.

---

## 1. Executive summary

1. **There are only two credible third-party plant-ID APIs for a commercial app: Pl@ntNet and Kindwise/plant.id.** iNaturalist's computer-vision endpoint is undocumented and returns `401 Unauthorized`; Bing Visual Search was retired in 2025; Google Cloud Vision does generic labels, not species; and the smaller players I probed are dead or have no public API. **[V]**
2. **Pl@ntNet is the only one with a real "flora filter", and it has an Australian one.** `POST /v2/identify/{project}` takes a *project* (= flora/referential) path parameter, and **`k-australia` exists** — its species explorer page is titled *"Australia: Species - Pl@ntNet identify"* and lists Australian *Acacia* spp. There is also an "Invasive plants" thematic flora. **[V]**
3. **Neither API offers a self-service "my own species list" parameter.** You cannot upload AUGURY's 2,230-species table and constrain results to it. The closest mechanisms are Pl@ntNet's `project` flora and plant.id's `suggestion_filter` (continent/theme lists). **[V]**
4. **The legal terms are the decisive factor, and they cut against the API route for a kNN/retrieval design.**
   - plant.id **expressly forbids** using the service "to develop his/her own automatized system, program or application based on the same principle as FlowerChecker Digital Services" (T&C §17.3.3). **[V]**
   - plant.id also takes an **irrevocable, unlimited licence to reuse every submitted photo commercially, including for ML training, and to redistribute it under CC-BY-SA 4.0** (T&C §17.5). **[V]**
   - iNaturalist **prohibits commercial AI training on its data outright**, and its default content licence is **CC BY-NC**. **[V]**
   - Pl@ntNet's free tier is textually ambiguous about commercial use ≤500/day. **[V for the text; I for the reading]**
5. **The accuracy evidence strongly favours a purpose-built model over a general API for AUGURY's hard cases.** Published top-1 species accuracy for the best general apps is 57% (plant.id, British flora, 2020) and 79.2% (Flora Incognita, plot surveys, 2026); **graminoids/Poaceae are consistently the worst-performing group**, with four of six *Carex* species below 60% in both apps tested. **[V]**
6. **AUGURY's ~86% top-1 / ~93% top-3 claim is at or above published best-in-class for general flora, but it is not apples-to-apples** — it is a closed-set kNN task over a curated Australian weed gallery, not open-world flora identification. **[I]**
7. **On-device is viable and cheap; the API route is not cheap at scale.** Pl@ntNet Pro has a €1,000/yr floor; plant.id costs €1,500–2,000/month at 100k IDs/month. TinyWeedNet (2026) hits 97.26% on DeepWeeds with **0.48 M parameters** and <90 ms on a microcontroller. **[V]**
8. **Supplementary answer (OpenBMB):** the models actually in play are Apache-2.0 — MiniCPM5-1B (`license: apache-2.0`), MiniCPM-V-4, -4.5 and **-4.6** are all Apache-2.0 on Hugging Face. **MiniCPM-V-2.6 is the exception**: gated, and its model card declares no SPDX licence. And off-the-shelf VLMs are **not** a viable fine-grained plant-ID component — the best closed VLM scored 49.7% vs 91.4% for a fine-tuned CNN on the same benchmark. **[V]**

---

## 2. Q1 — Pl@ntNet API

Source of record: `https://my.plantnet.org/doc/...`, the OpenAPI spec at **`https://my-api.plantnet.org/swagger.json`** (Swagger 2.0, API version **2.2.2**), and the terms at `https://my.plantnet.org/terms_of_use`. All fetched 2026-10-08. **[V]**

### 2.1 Endpoints

Base: `https://my-api.plantnet.org/v2/`. Documented routes (from the swagger spec): **[V]**

| Route | Purpose |
|---|---|
| `POST /v2/identify/{project}` | Main single-species identification |
| `GET /v2/identify/{project}` | Same, by image URL |
| `GET /v2/projects` | List usable floras/referentials (supports `lat`, `lon`) |
| `GET /v2/projects/{project}/species` | Species list for a flora |
| `GET /v2/projects/{project}/species/align` | Species-name alignment |
| `GET /v2/species` | Global species list / prefix search |
| `POST /v2/diseases/identify` | Disease identification (limited taxa) |
| `POST /v2/varieties/identify` | Cultivated varieties (limited crops) |
| `POST /v2/survey/tiles/{project}` | Multi-species quadrat/plot ID (beta, gated) |
| `POST /v2/cost/survey/{project}` | Cost estimate for survey calls |
| `GET /v2/quota`, `/v2/quota/daily`, `/v2/quota/history` | Quota introspection |
| `GET /v2/prediction/geo/species` | Geo-based species prediction |
| `GET /v2/ai-taxonomist/anura/identify` | Separate (amphibian) model |
| `GET /v2/guarden/...` | GUARDEN project routes |

### 2.2 Free tier and commercial use — **this is the crux**

Direct quotes from `https://my.plantnet.org/terms_of_use` §Access policy: **[V]**

> "**Pl@ntNet API is free of use up to 500 identification queries per day.** It is also **free of use for specific non-profit educational and scientific purposes**: please contact us…"
> "**Pl@ntNet API is paying for commercial usage beyond 500 identification requests per day.**"
> "**It is not allowed to create more than one free account per person or per legal entity.**"
> "It is also forbidden to create several free accounts submitting queries from the same IP address."

**Two readings, and they conflict [I]:**
- **Literal reading:** commercial use is permitted free up to 500/day; payment starts *beyond* 500/day. On this reading a small commercial app using ~33 IDs/day pays nothing.
- **Purpose reading:** the free tier is "free of use for specific non-profit educational and scientific purposes", so *any* commercial use is paid. On this reading even 10 IDs/day requires a Pro contract.

I cannot resolve this from the published text. **Recommendation: get written confirmation from Pl@ntNet before shipping a commercial build on the free tier.** This is a one-email question with a €1,000/yr consequence. **[I]**

Also note the **2026-02-13 changelog**: on the free plan, requests that *return an error now consume 1 credit* — a bad-request loop burns your daily quota. Pro is unaffected. **[V]**

### 2.3 Paid tier and prices

From `https://my.plantnet.org/doc/getting-started/pro-plan` and `/terms_of_use` (all EUR, excl. tax, seen 2026-10-08): **[V]**

- **Pro Plan = contract-based, one-year term.**
- **Initial payment: €1,000** (billed 30 days after signature), covering contract setup + **200,000 requests** valid for the full contract duration, **no carry-over** year to year.
- **Final billing at contract end**, only on requests beyond the initial 200,000:
  - ≤ 3 M total: **€0.005 / identification** (i.e. €5 per 1,000)
  - \> 3 M: €0.004 / identification
  - \> 30 M: €0.003 / identification
  - \> 300 M: €0.002 / identification
- The terms page states the same numbers as "5 € for 1,000 additional requests", "4 euros/1,000… over 3 million per year", etc.
- Worked example **published by Pl@ntNet**: 2,000,000 total requests → final bill **€9,000**. Arithmetic check: (2,000,000 − 200,000) × €0.005 = €9,000. ✅ **[V]**
- Invoicing in USD or EUR; "Amounts are given in euros on an indicative basis but payments will be invoiced in USD at the exchange rate in force on the date of the billing." **[V]**

### 2.4 Rate limits

- **20 simultaneous requests per client** (hard, in all cases). **[V]**
- **Pro customers: security quota of 1M requests/day.** **[V]**
- Free tier: **500/day per account, per request type**, resetting at **00:00:00 UTC**. Quota is exposed in `RateLimit-Policy`, `RateLimit` and `Retry-After` headers and via `/v2/quota/daily`. Exceeding it returns **HTTP 429**. **[V]**
- The docs' own examples show `identify: 5000` for a contractualised account, i.e. the Pro daily cap is negotiated/set above 500. **[V]**

### 2.5 Ranked shortlist and confidence scores — **yes**

- "Single-species identification returns a **top-list of probable plant species, presented in decreasing order of confidence score**. Confidence scores are between 0 and 1." **[V]**
- Response fields: `results[]` (each with `score` and `species{scientificNameWithoutAuthor, scientificNameAuthorship, genus, family, commonNames}` plus `gbif.id` and `powo.id`), `bestMatch` (top-1 shortcut), `predictedOrgans[]`, `otherResults[]` (genus/family — **off by default** since 2025-09-23, enable with `detailed=true`), `version`, `remainingIdentificationRequests`. **[V]**
- **`nb-results`** caps the shortlist length ("Fewer results improve response time"). **[V]**
- Up to **5 images per request**, all of the same individual; total POST ≤ 50 MB; JPEG/PNG only. **[V]**

### 2.6 The "project"/flora filter — **yes, and Australia is supported**

This directly answers your hypothesis. From the swagger spec and `https://my.plantnet.org/doc/api/identify`: **[V]**

- The **`project` path parameter** is the flora filter: *"Referential in which to search the plant (use one of the available projects or `all` to get the results of the most relevant project)"*.
- The docs describe projects as: *"Also known as 'floras' or 'referentials', 'projects' are lists of species-level taxa, related to a geographical area or a theme."*
- `GET /v2/projects` **accepts `lat` and `lon`** to *"filter and sort projects according to geolocation"* — so you can programmatically pick the right flora for a GPS fix. **[V]**
- Floras are built on **Kew's POWO/ WCVP checklist** and **TDWG WGSRPD level-2** geographical areas, plus thematic floras. The docs explicitly state: *"Thematic floras such as 'Useful plants', 'Invasive plants', 'Crops' will be kept, as well as floras dedicated to local areas of interest such as 'Cévennes', 'Ordesa', 'LEWA in KENYA'."* **[V]**
- **`k-australia` is a real flora. [V]** I verified this by fetching `https://identify.plantnet.org/k-australia/species`: the page title is **`Australia: Species - Pl@ntNet identify`**, it contains `australia/identify`, `australia/families`, `australia/genera` links and Australian *Acacia* species (e.g. *Acacia abbreviata*, *A. acanthaster*, *A. acinacea*), and its largest per-genus `speciesCount` is ~1,788. A control fetch of a deliberately bogus flora id returned a 151 KB page with zero *Acacia* hits, versus 281 KB for `k-australia` — so this is not a catch-all SPA artifact. **[V]**
- **Caveat on enumeration:** `GET /v2/projects` requires an API key and returned `401 {"error":"Unauthorized"}` when I called it, so **I could not enumerate the full flora list or confirm whether separate `k-new-south-wales` / `k-queensland` floras exist.** I probed those ids via the web explorer, but that URL is a client-side-routed SPA that returns HTTP 200 for *any* path (a bogus id also returned 200), so **those probes are meaningless and I make no claim about them.** **[V for the method failure; I for any state-level flora]**
- **No self-service custom species list.** The `POST /v2/identify/{project}` parameter set is: `project` (path), `include-related-images`, `no-reject`, `nb-results`, `lang` (includes `en-au`), `type` (`kt`|`legacy`), `detailed`, `api-key`/`authenix-access-token`, plus form fields `images` and `organs`. **There is no allowlist / custom-list / `filters` / `exclude` parameter on the identify route.** **[V]**
- Bespoke floras evidently exist for partners (the "Cévennes"/"LEWA in KENYA" examples), so a **negotiated** AUGURY flora is plausible — but that is an inference about what a Pro contract could include, **not a documented feature**. **[I]**

### 2.7 Caching, storage, and data reuse

- **Images are not stored by Pl@ntNet.** *"The photos sent by the user are not stored in the database. They are only kept in our server volatile memory during the identification process."* **[V]**
- **Query history is stored:** *"We store the query history of each user (i.e. the date, time and image URL(s) of the submitted queries). We don't store the images themselves, only the image URL(s)."* **[V]**
- **Caching/storing the *results* is not addressed in the ToU.** There is no clause permitting or prohibiting it explicitly. However the IP clause is broad: *"No element of the Pl@ntNet application shall be copied, reproduced, modified, republished, downloaded, distorted, transmitted or distributed, howsoever done, partially or integrally, without the written and prior authorization from Pl@ntNet…"* — **this is the clause to worry about if you plan to persist results or build a species table from API output.** **[V for the quote; I for its application to cached results]**
- **Returned images** (only with `include-related-images=true`, and **species-illustration images are Pro-only** since 2026-03-03) are usually **CC BY-SA**; attribution format is *"Photo(s): [Contributor Username] / Pl@ntNet, CC BY-SA"*, with `author`, `license`, `citation` fields supplied per image. **[V]**
- **Attribution for API use:** *"Any free use of Pl@ntNet API **might** acknowledge Pl@ntNet with the following sentence: 'The image-based plant species identification service used, is based on the Pl@ntNet recognition API…'"* plus a logo. Note the soft "might". **But the non-profit plan page is mandatory:** *"The 'Non-profit' plan requires that you add a 'Powered by Pl@ntNet' mention and logo in your app or website."* **[V]**

### 2.8 Model, latency, and performance caveats

- **Model identity is ambiguous in their own docs.** The FAQ says *"Current model: **InceptionV3**"*, but the introduction cites the **DINOv2** paper (Oquab et al. 2024) as a description of the engine, and the survey docs give a minimum tile size of **518 px**, which is a DINOv2-style input. **Treat the FAQ's "InceptionV3" as possibly stale. [V for both quotes; I for which is current]** — worth noting because it means Pl@ntNet may be architecturally close to AUGURY's own DINOv2 approach.
- **Model updates:** 2025-09-24 — WCVP v13, **77k identifiable species**, gains on aerial/UAV views; 2026-01-08 — new model for WCVP floras. Version strings in examples: `"2025-01-17 (7.3)"`. Models updated roughly two-monthly with a non-regression policy. **[V]**
- **Latency is not documented numerically.** Only qualitative statements: POST is faster than GET; fewer `nb-results` improves response time; `detailed=true` is slower. There is a public status page at `https://plantnet.github.io/status/`. **I could not verify a p50/p95 latency figure. [V for the absence; I for any number]**
- **Input quality gates:** images resized to max **1280 px** on the long side (never upscaled); *"Identification performance is not guaranteed for images smaller than 800x800px"*; JPEG q90 recommended. Organ informativeness ranking: **flower > fruit > leaf > entire plant > bark**; *"Leaves are also often much less discriminative than flowers and fruits."* **This matters a lot for a weed app where users photograph leaves.** **[V]**

---

## 3. Q2 — Alternatives

### 3.1 plant.id (Kindwise)

Sources: `https://www.kindwise.com/pricing`, `/plant-id`, `/faq`, `/handbook`, `/suggestion_filters`, `https://plant.id/api/v3/openapi.yaml`, and the API T&C PDF (v3) resolved from `https://www.kindwise.com/terms-and-conditions` → `https://cdn.prod.website-files.com/64876ae345f1e27598fafc02/6853d59465d761e68644128a_KW%20API%20T%26C%20v3.docx.pdf`. All fetched 2026-10-08. **[V]**

**Pricing (EUR, seen 2026-10-08).** "The cost of each identification call is one credit." **[V]**

| Tier | Purchased volume | Price per request | Minimum order |
|---|---|---|---|
| Free trial | 100 credits after registration | free | — |
| A | from 1,000 credits | **€0.05** | €50 |
| B | from 10,000 credits | **€0.03** | €300 |
| C | from 50,000 credits | **€0.02** | €1,000 |
| D | from 200,000 credits | **€0.015** | €3,000 |
| E | from 800,000 credits | **€0.012** | €9,600 |
| F | from 1,500,000 credits | **€0.01** | €15,000 |

- "Purchased credits are valid for 3 months (this does not apply to purchases under 30,000 credits)." **The parenthetical is ambiguous** — it could mean small purchases never expire, or that different validity applies. Flagged. **[V for the text; I for the meaning]**
- **Credit multipliers:** health assessment adds 1 credit (2 total); the Detail endpoint costs **0.5 credits**; Search, usage info, retrieval, deletion and feedback are **free**. **[V]**
- **Discounts for narrower class sets:** *"We offer significant discounts for identifying fewer classes, like invasive plants, medicinal mushrooms, or beetles. Please contact support@kindwise.com."* **[V]** — relevant, since AUGURY only needs weeds.
- **NGOs** "with reliable track record and environmental focus are eligible for special pricing and have the same benefits as Business accounts." **[V]**
- **Billing modes:** *Prepaid* (buy credits) or *Retroactive* (monthly invoice on actual usage, by arrangement). **[V]**
- **Free/agent trials:** the demo sites allow **10 identifications/month**; the agent trial at `agents.kindwise.com` allows **10 requests per client IP per rolling 24 hours**. **[V]**

**Ranked shortlist — yes.** From `https://plant.id/api/v3/openapi.yaml`: the response has `result.classification.suggestions[]`, each with `id`, `name`, `probability`, `similar_images` (if requested) and `details`. Separately, `result.is_plant.probability` is the "probability that images contain a plant — you can apply your own threshold". The FAQ adds: **"The response includes up to 10 suggestions with the highest confidence. Suggestions with confidence <1% are omitted."** **[V]**

**Species constraint parameter — yes, a region/theme filter.** Request attributes include **[V]**:
- **`suggestion_filter`** — *"restricts the output of the model to specified list of classes (region or plant type) and adjusts the probabilities"*, combinable with `AND`/`OR`/parentheses. Documented examples: `{"classification": "vegetable"}`, `{"classification": "houseplant OR continent__europe"}`, `{"classification": "(continent__northern_america OR continent__europe) AND tree"}`.
- The filter list at `https://plant.id/suggestion_filters` includes **`continent__australasia`**, **`graminoid`**, **`weedy_plant`**, **`invasive_plant`**, `vascular_plants`, `tree`, `shrub`, `aquatic_plant`, and others. **This is the closest thing any vendor offers to AUGURY's need** — but note it is a *continent* (Australasia), not Australia, and it is a vendor-defined list, not your own.
- **`latitude` / `longitude`** — "increases the identification accuracy". **`datetime`** — season context. **`classification_level`** — `species` (default) | `all` (adds infraspecies/cultivars) | `genus`. **`classification_raw`** — bypass post-processing. **[V]**
- Caveat from the FAQ: some categories are *"somewhat ambiguous"* and they *"aim to reflect the predominant viewpoint of the northern hemisphere, where most of our customers are located."* Genera are included wholesale if any species qualifies (e.g. all *Ambrosia* are "weedy"). **[V]** — that's a meaningful precision problem for an Australian weed app.

**Coverage and accuracy claims:** **35,000+ classes**; *"93% Correct species in over 9/10 queries within the top three results"*; they cite the AoB Plants paper and an alien-street-trees study as independent support. Three models (genus, species, infraspecific) are combined and post-processed. **[V]**

**Latency and SLA:** *"average transaction delay from Europe is ~150ms and the average identification takes ~350ms… usually the overall latency is around 0.5 seconds."* SLA: **availability >99.5%**, **max 3 s per identification request**, result availability **≥3 months**. They note a dedicated regional backend is available for a fee. Data centre is **Central Europe** — **Australian round-trip latency will be higher than the European figure; I did not verify an AU measurement.** **[V for the figures; I for AU]**

**Rate limits:** *"There are no limits or caps on the number of API requests"* — throughput guarantees are governed by the SLA instead. Deployments cause ~20 s unavailability about twice a month. **[V]**

**Image guidance:** optimal **1–2 MP**, never larger than 2 MP; up to 5 images per call. **[V]**

**Data and privacy (critical):** **[V]**
- T&C §6.14: *"All Client's submitted photographs and queries, as well as all Outputs from the Digital Services, are available to the Client via the API key for **6 months** after receipt."*
- Third-party personal data appearing in photos is *"anonymized after 6 months of receipt"*; faces are blurred before further use.
- The handbook states the identification result "is available for 6 months" and can be re-fetched in other languages/details.

### 3.2 iNaturalist / Seek — **not usable as a third-party commercial CV API**

- **The CV endpoint is not a public API.** `POST https://api.inaturalist.org/v1/computervision/score_image` returned **`{"error":"Unauthorized","status":401}`** when I called it on 2026-10-08. **[V]**
- **It is not in the documented spec.** I downloaded `https://api.inaturalist.org/v1/swagger.json` (iNaturalist API v1.3.0) and grepped it: **zero occurrences of "computervision"**. The documented tags are Annotations, Comments, Controlled Terms, Flags, Identifications, Messages, Observations, Places, Posts, Projects, Search, Taxa, Users, Tiles, UTFGrid — **no computer-vision tag**. **[V]**
- **No open model weights.** `https://huggingface.co/api/models?author=inaturalist` returned **0 models**. The CV model architecture is reported in the literature as Xception (2023–2024 era). **[V]**
- **Rate limits (from the spec's own description):** *"we throttle API usage to a max of 100 requests per minute, though we ask that you try to keep it to 60 requests per minute or lower, and to keep under 10,000 requests per day. If we notice usage that has serious impact on our performance we may institute blocks without notification."* **[V]**
- **Terms:** *"Use of this API is subject to the iNaturalist Terms of Service… The API is intended to support application development, not data scraping."* **[V]**
- **Licensing — the killer clauses** (iNaturalist ToS, archived snapshot `web/20260911052554`, i.e. 2026-09-11, retrieved via `web.archive.org` because inaturalist.org returns 403 to automated fetches): **[V]**
  - *"Unless you specify otherwise when you post Content, you agree to license Content you contribute to the Platform under the **Creative Commons Attribution Noncommercial license (CC BY-NC)**."*
  - **"Prohibited Use for Commercial AI Training. Users may not use any iNaturalist data for training artificial intelligence, machine learning models, large language models, or similar networks, algorithms, or systems for commercial purposes."**
  - iNaturalist grants *itself* a licence to repackage data for **GBIF** and the **AWS Open Data** programme.
- **AWS Open Data mirror:** the registry page states the licence is *"Creative Commons or Public Domain (CC0), varying by image"*, and the iNaturalist open-data README confirms **CC-BY-NC photos are included** (attribution example given: `"© Login, some rights reserved (CC-BY-NC)"`). **So the open dataset is not a commercially clean training corpus.** **[V]**
- **Seek** is iNaturalist's own app; the AoB Plants 2020 evaluation notes it *"works offline"* and *"Uses location to filter species, but can operate offline."* **Whether Seek's on-device model is licensable or extractable is not published; assume not. [V for the quote; I for the conclusion]**

### 3.3 Google Cloud Vision / Google Lens

- **Vision API does not do species-level plant ID.** It returns generic labels. The relevant feature is Label Detection. **[I — this is well-established but the Vision docs page I fetched is a pricing page and does not itself state the label taxonomy; I did not fetch a Vision label-taxonomy page.]**
- **Pricing** (`https://cloud.google.com/vision/pricing`, USD, seen 2026-10-08): **first 1,000 units/month free**, then **$1.50 per 1,000 units** for units 1,001–5,000,000, and **$1.00 per 1,000** above 5,000,001. Each feature applied to an image is a separate billable unit. Web Detection is $3.50/1,000; Object Localization $2.25/1,000. **[V]**
- **No official public Google Lens API for third parties.** I could not find one and **did not verify its absence from an authoritative page** — treat as unverified. Google Lens behaviour is only observable through the consumer app, which is not a licensable integration path. **[I]**

### 3.4 Bing / Microsoft — **retired**

- **"Bing Search APIs retiring on August 11, 2025"** — *"Bing Search APIs will be retired on August 11, 2025. Any existing instances of Bing Search APIs will be decommissioned completely, and the product will no longer be available to be used or new customer signup."* (`https://learn.microsoft.com/en-us/lifecycle/announcements/bing-search-api-retirement`, announcement dated 2025-05-16.) **[V]**
- Corroborating: the Bing Visual Search overview page now redirects to `learn.microsoft.com/en-us/**previous-versions**/bing/search-apis/bing-visual-search/overview`, and `microsoft.com/en-us/bing/apis/pricing` returns **404**. **[V]**
- This also matches the AoB Plants 2020 result where "Bing" scored **3% correct to species** and **67% wrong at family level or worse** — it was never competitive. **[V]**

### 3.5 Other / newer options — mostly dead ends

I probed these directly on 2026-10-08: **[V]**

| Option | Result |
|---|---|
| **PlantIn** (`plantin.app`) | **DNS does not resolve** — domain appears defunct. |
| **Flora Incognita** (`floraincognita.com/api/`) | **404** — no public API. Free app, central-European flora focus, expanding to North America. |
| **PictureThis / Glority** (`glority.com`) | Site is up, but its advertised APIs are **OCR and vehicle-licence-plate recognition**; no public plant-ID API. `/api` returns 403. |
| **Ximilar** (`ximilar.com/plant-identification-api/`) | **404** — that product page no longer exists. |
| **Eden AI** (`edenai.co/feature/plant-identification-api`) | **404**. |
| **Plantician** (`plantician.com`) | **403** (Cloudflare challenge) — could not verify existence, pricing, or terms. |
| **Blom.ai**, **PlantVision.ai**, **Clarifai** | DNS resolution failures from this environment — could not verify. |
| **PlantSnap** | No public API found; scored 24% species / 54% wrong-family in AoB Plants 2020. |
| **Leafsnap** | No API found. The original Leafsnap dataset/model is a 2011-era research artifact; **I did not verify a current licence or distribution.** |

**Bottom line [I]:** outside Pl@ntNet and Kindwise, the commercial plant-ID API market is essentially empty for a developer who wants documented pricing and a licence. This is consistent with the consolidation visible in the 2026 literature, where evaluations test iNaturalist, Pl@ntNet and Flora Incognita rather than a long tail of APIs.

---

## 4. Q3 — Offline / on-device options

### 4.1 Base models and their licences

| Model | Licence (verified) | Size / params | Notes |
|---|---|---|---|
| **facebook/dinov2-base** | **Apache-2.0** — HF `cardData.license = "apache-2.0"`; GitHub `facebookresearch/dinov2` LICENSE is Apache-2.0 | **86,580,480 params** (F32) ≈ 346 MB fp32 / ~173 MB fp16 | AUGURY's current encoder. Commercially clean. **[V]** |
| **facebook/dinov3-vits16-pretrain-lvd1689m** | **`license: "other"` → `dinov3-license`**; **gated: "manual"** (requires name, DOB, country, affiliation, job title, IP geolocation, and accepting terms) | **21,596,544 params** (F32) ≈ 86 MB fp32 / ~43 MB fp16 | Custom Meta licence, not OSI-approved. **[V]** |
| **imageomics/bioclip** | **MIT** | open_clip ViT-B/16, ~4.2 GB repo | Trained on **TreeOfLife-10M**, 450K+ taxa. Zero-shot species classification. **[V]** |
| **imageomics/bioclip-2** | **MIT** | CLIP **ViT-L/14** (LAION-2B backbone) | Trained on **TreeOfLife-200M**. A newer `bioclip-2.5-vith14` exists. **[V]** |
| **openbmb/MiniCPM5-1B** | **Apache-2.0** | **1,080,632,832 params** (BF16) | Text-only. The GGUF formatter AUGURY uses. **[V]** |
| **openbmb/MiniCPM-V-4.6** | **Apache-2.0** | **1,300,428,016 params** (1.3B) | Newest VLM; SigLIP2-400M + Qwen3.5-0.8B; iOS/Android/HarmonyOS edge code open-sourced. **[V]** |
| **openbmb/MiniCPM-V-4** / **-4_5** | **Apache-2.0** | 4.06 B / 8.70 B params (BF16) | **[V]** |
| **openbmb/MiniCPM-o-4_5** | **Apache-2.0** | 9,371,787,666 params | **[V]** |
| **openbmb/MiniCPM-V-2_6** | ⚠️ **gated ("auto"), and `cardData` declares NO licence field** | 8,099,175,152 params | The GitHub repo LICENSE is Apache-2.0, but the HF card does not assert an SPDX licence. **[V]** |
| **Pl@ntNet model weights** | **Not released** | — | The API is the only access path. **[V]** |
| **iNaturalist CV weights** | **Not released** | — | 0 models on HF under the `inaturalist` author. **[V]** |

**DINOv3 licence detail** (`https://raw.githubusercontent.com/facebookresearch/dinov3/main/LICENSE.md`, last updated 2025-08-19): it grants a *"non-exclusive, worldwide, non-transferable and royalty-free limited license… to use, reproduce, distribute, copy, create derivative works of, and make modifications to the DINO Materials."* **It does not contain an explicit non-commercial restriction**, but it is a bespoke revocable licence (Meta may terminate on breach), requires acknowledgement in publications, forbids reverse-engineering, and imposes ITAR/trade-control and military-use restrictions. **It is not equivalent to Apache-2.0 and I would not ship it in a commercial app without legal review. [V for the text; I for the risk assessment]**

### 4.2 Datasets

| Dataset | Licence (verified) | Content | AU relevance |
|---|---|---|---|
| **DeepWeeds** | **CC BY 4.0** for images, annotations and source code (repo contents Apache-2.0) | **17,509 images**, **8 Australian weed species** from Queensland pastoral grasslands: Chinee apple, Snake weed, Lantana, Prickly acacia, Siam weed, Parthenium, Rubber vine, Parkinsonia. Published ResNet50 accuracy **95.7%** (closed-set). Also on TensorFlow Datasets. **[V]** | **High** — but note these are mostly **woody shrubs, not grasses**, and the 95.7% is a closed-set 9-class task, not open-world ID. |
| **iNaturalist Open Dataset** (AWS) | *"Creative Commons or Public Domain (CC0), varying by image"* — **CC-BY-NC images are included** | Monthly snapshots of observations/photos/taxa | **Not commercially clean as a whole.** Only the CC0/CC-BY/CC-BY-SA subset is usable. **[V]** |
| **PlantCLEF 2024** | Access via registration; **licence not stated on the overview page I fetched** | Training set = *"south western Europe subset of the Pl@ntNet training data… 7.8k plant species… about 1.4 million images extended with some images with trusted labels aggregated from the GBIF platform"* | Low for AU; useful for Europe phase. **Licence must be checked before use.** **[V for content; unverified for licence]** |
| **TreeOfLife-10M / -200M** | Used by BioCLIP (MIT model licence); **dataset licence itself not verified** | 450K+ taxa | **[I]** |
| **PlantVillage** | Not verified in this session | Crop disease imagery, not weed ID | Low |
| **Weed Phenological Dataset (WPD)** | Described in a 2026 paper; **licence not verified** | Annotated **early growth stages** for weed seedling classification | Potentially relevant to the seedling problem. **[V for existence]** |

### 4.3 Practical phone constraints

**Google Play size limits** (`https://support.google.com/googleplay/android-developer/answer/9859372`, fetched 2026-10-08) — all limits are **compressed download size**: **[V]**

| Component | Limit |
|---|---|
| Base module | **500 MB** |
| Individual feature modules | 500 MB |
| Individual asset packs | 1.5 GB |
| Cumulative total for all modules + install-time asset packs | 4 GB |
| Cumulative total for on-demand / fast-follow asset packs | 30 GB |
| Total maximum compressed download size | 34 GB |
| Legacy APK (non-bundle) | 100 MB |

- **Apps above 200 MB trigger a non-blocking warning dialog** for users installing over mobile data. **[V]**
- Apps larger than 1 GB must target API 21+. Fast-follow and on-demand asset packs **do not count toward the Play Store listing size**. **[V]**

**Consequences for AUGURY [I]:**
- The README states the mobile build is **~368 MB template-only vs ~1.06 GB with the MiniCPM formatter**. Both fit comfortably inside the 500 MB base-module limit; 368 MB is above the 200 MB mobile-data warning threshold but well within limits. **[V for the sizes from the repo README; I for the fit assessment]**
- **DINOv2-base at ~86 M params (≈173 MB fp16)** is a large encoder for a phone but is already what AUGURY ships; ViT-S-class alternatives (e.g. DINOv3 ViT-S/16 at 21.6 M params, ~43 MB fp16) would be ~4× smaller — at the cost of the licence concerns above.
- **BioCLIP/BioCLIP-2 are attractive on licence (MIT) but ViT-L/14 is heavy** (~300 M+ params, ~600 MB fp16) — likely a download-on-demand asset pack rather than bundled, or use BioCLIP (ViT-B/16) instead. **[I]**
- **TinyWeedNet (2026)** demonstrates the floor: **0.48 M parameters, <2 MB flash, 97.26% on DeepWeeds, sub-90 ms inference, ~39 mJ/inference on an STM32H7 MCU.** For a *closed-set* weed task, an extremely small model is sufficient — which suggests AUGURY's kNN-over-gallery design is already in the right regime and does not need a heavy encoder. **[V]**

---

## 5. Q4 — Legal / licence obligations of the API route

### 5.1 If AUGURY calls Pl@ntNet and displays the species name

- **A species name is a fact and is not copyrightable** — displaying "Lolium rigidum" carries no attribution obligation in itself. **[I — standard copyright principle, not verified against Australian statute in this session]**
- **Pl@ntNet's contractual (not copyright) obligations are what bind you.** The ToU asks free users to acknowledge Pl@ntNet with a specific sentence and logo ("might"), and the **Non-profit plan requires** the "Powered by Pl@ntNet" mention and logo. If you are on the **Pro plan**, the governing document is the **signed copyright licence** (`.../copyright_licence_PlantNet_API_english_v5.1_EUR.pdf` / `_USD.pdf`), **which I did not fetch or read** — that is where the actual Pro-plan attribution and reuse terms live. **[V for the links and the plan requirements; unverified for the Pro licence body]**
- **Storing the result:** not expressly prohibited, but the broad IP clause ("No element of the Pl@ntNet application shall be copied, reproduced, modified, republished, downloaded… without the written and prior authorization") is the risk. **Pl@ntNet stores your query history (date, time, image URLs) on their side.** **[V for the text; I for the risk]**
- **Building a species database from Pl@ntNet output:** Pl@ntNet does publish its own species lists through `/v2/species` and `/v2/projects/{project}/species` (with genus/family since 2025-05-16, images Pro-only since 2026-03-03), and `GET /v2/projects/{project}/species/align` exists for name alignment. **Using these routes to bulk-populate AUGURY's 2,230-species table is exactly the scenario the IP clause appears aimed at, and I would not do it without written permission. [I]**
- **Their images** (if you use `include-related-images`) are **CC BY-SA** and require per-image attribution *and* share-alike — **CC BY-SA is a copyleft licence; mixing those images into your app's assets would impose share-alike obligations. Prefer not to use them.** **[V for the licence; I for the copyleft consequence]**

### 5.2 If AUGURY calls plant.id and displays the species name

The Kindwise/FlowerChecker T&C v3 is unusually explicit. Key clauses, quoted: **[V]**

- **§17.2.1 — commercial use is expressly permitted:** a licence *"for the proper performance of the rights and obligations set forth in these Terms and Conditions… as well as for development, testing, operation and support of mobile application, drones and other similar applications, devices and programs, **including commercial purposes**."* ✅
- **§17.3.1 — you may NOT sublicense or assign the *service* licence** without FlowerChecker's prior written consent. (But see §17.4 below — this does **not** apply to Output content.)
- **§17.3.3 — the anti-competition clause:** you may not *"use FlowerChecker Digital Services in a manner that could cause any damage to FlowerChecker, in particular **to use FlowerChecker Digital Services to develop his/her own automatized system, program or application based on the same principle as FlowerChecker Digital Services**."* ⚠️ **This is the clause that most directly bears on the AUGURY decision: using plant.id output to build or improve your own competing ID system is prohibited.**
- **§17.4 — the Output content licence:** for copyright works in the Output (photographs, text descriptions), the Client gets a **non-exclusive licence**, for *"further processing of the Output in relation to the end users through the service of a mobile or other application, **including commercial use**"* (§17.4.1), **territorially and quantitatively unlimited** (§17.4.2), for the duration of the property rights (§17.4.3), **transferable to a third party** (§17.4.4) and **sublicensable** (§17.4.5), in both cases with FlowerChecker's express consent given in advance.
  - This is the "Sublicensable content" feature listed on the Business pricing tier. **So you may store and display plant.id's returned content, including in a commercial app.** ✅
- **§17.5 — the photo grant, and the big one for user privacy:** *"The Client grants a license to FlowerChecker for all photographs provided from its devices and/or its end users. This license is non-exclusive, unlimited and irrevocable. Under this license, FlowerChecker is entitled to **use and modify photographs for commercial purposes, especially for developing FlowerChecker software including developing machine learning or other forms of artificial intelligence** and for providing photographs to customers of FlowerChecker Digital Services… License granted according to this Sect. 17.5. **also entitles FlowerChecker to share provided photographs under the license CC-BY-SA 4.0 or later.**"*
  - **In plain terms: every photo AUGURY users submit to plant.id becomes permanently usable by Kindwise for commercial ML training and re-shareable under CC BY-SA 4.0.** Faces are blurred first. For a farmers/agronomists app, this is a privacy and trust disclosure you would have to surface in the UI, and it may be a GDPR/Privacy-Act issue given photos can contain people and geolocatable farm property. **[V for the clause; I for the compliance implication]**
- **§"trade secrets":** *"All competitively significant, identifiable, valuable and in relevant business circles not normally available facts and information related to the Parties… are considered trade secrets."* Reinforced by the FAQ: *"Full lists [of classes] are considered our trade secrets. We do not provide them publicly, but only in response to well-founded requests and after the signing of a Non-Disclosure Agreement."* **You cannot obtain or reconstruct their class list to build a species DB. [V]**
- **§6.14 / retention:** photographs, queries and Outputs are available to you via the API for **6 months**. This is a *retrieval window*, not a *storage prohibition* — §17.4 grants you an unlimited-duration licence to the Output content. **[V]**
- **API key security:** Kindwise explicitly *"don't recommend call kindwise backend directly from the app"* and recommend a backend proxy; an experimental HMAC-SHA256 key/secret scheme exists for keyless clients. **This means the API route requires AUGURY to run a server — breaking the "no cloud required" property.** **[V]**

### 5.3 If AUGURY called iNaturalist

- **Don't, for a commercial app.** The CV endpoint is unauthorized (401) and undocumented, *and* the ToS contains an explicit **"Prohibited Use for Commercial AI Training"** clause plus a **CC BY-NC** default content licence. **[V]**

### 5.4 Summary of the licence question

| Question | Pl@ntNet | plant.id (Kindwise) |
|---|---|---|
| Commercial use permitted? | **Ambiguous on free tier**; Pro contract clearly permits | **Yes, expressly (§17.2.1)** |
| May I store the result? | Not addressed; broad IP clause is a risk | **Yes — Output licence is unlimited and sublicensable (§17.4)** |
| May I build a species DB from output? | Risky (IP clause + Pro licence unread) | **No — class list is a trade secret; §17.3.3 bars building a competing system** |
| Are user photos reused by the vendor? | **No** — images kept in volatile memory only | **Yes — irrevocable commercial ML licence + CC-BY-SA redistribution (§17.5)** |
| Attribution required? | Free/non-profit: "Powered by Pl@ntNet" + logo | Content: yes for CC-BY-sourced images/descriptions |

---

## 6. Q5 — Accuracy reality check

### 6.1 Published comparison — AoB PLANTS 2020 (British flora)

**Jones (2020), "What plant is that? Tests of automated image recognition apps for plant identification on plants from the British flora", *AoB PLANTS* 12(6): plaa052, `PMC7640754`.** Nine apps, **38 images of British/Irish higher plants, five replicates each**. **[V]**

Percentage of tests correct at each level (first identification returned):

| App | % species | ≥80% | ≥50% | %misleadingly wrong | %wrong (family or worse) | Mean score |
|---|---|---|---|---|---|---|
| **Plant.id** | **57** | 70 | 73 | 3 | 27 | **69.8** |
| Flora Incognita | 46 | 56 | 64 | 7 | 14 | — |
| Google Lens | 45 | 56 | 71 | 8 | 28 | 63.3 |
| Seek (iNaturalist) | 35 | 55 | 68 | 4 | 12 | — |
| **Pl@ntNet** | **39** | 49 | 55 | 11 | **43** | **52.1** |
| PlantSnap | 24 | 38 | 47 | 32 | 54 | 39.x |
| Candide | 1 | 18 | 35 | 25 | 61 | — |
| **Bing** | **3** | 17 | 23 | **57** | **67** | — |
| iPlant | 1 | 8 | 24 | 40 | 60 | — |

- *"There were large differences in performance with the best apps identifying **>50 % of samples tested to genus or better**."* **[V]**
- **By organ (Plant.id):** flower **76**, fruit **67**, leaf **62**, whole plant 71, herb 65, **monocot 66**, woody **92**. **[V]**
- **Monocots (grasses are monocots):** Google Lens **70**, Plant.id **66**, Pl@ntNet **50** — all well below the woody-plant scores. **[V]**
- Caveats: **n = 38 images**, British flora, 2020, and the author notes images were *"subjectively chose[n]"*. **Small and dated — treat as directional, not definitive.** **[V for the caveat]**

### 6.2 Poaceae / grasses — consistently the worst group

- **PLoS ONE 2026**, `PMC12952603`, *"Investigating key drivers influencing AI-based detection and identification of plants"* (iNaturalist vs Pl@ntNet, Ontario, invasive alien plants): *"we also found **significantly lower identification accuracy for species in the Poaceae family** and for photographs featuring only leaves."* Also: *"restricting location significantly hinders iNaturalist's ability to identify IAP."* **[V]**
- **Alberta 2026**, `PMC13394787`, *"Evaluating species identification apps as a tool for small plot-based surveys of vascular plants"* — **the single most relevant study to AUGURY**: **5,291 field images, 119 species, 54 plots of 0.8 m², in graminoid-dominated grassland and forest**; compared **Flora Incognita vs iNaturalist**; **top-1 ID accuracy as a function of growth form, reproductive state and image quality.** **[V]**
  - **Overall top-1 species accuracy: Flora Incognita 79.2%, iNaturalist 66.5%.** Genus level: 88.x% and 73.x% respectively.
  - Reference expert accuracy for plot-based surveys: **90–95%** — *"No groups reached the reference expert accuracy."*
  - **"However, graminoid identification accuracy was poor."**
  - **"The largest effect was whether a plant was a graminoid or not; all other growth forms… had similarly high ID accuracy."**
  - *"In both apps, **all growth forms, except graminoids**, fell within the range of reference ID accuracy."*
  - *"Species below the mean reference accuracy were **predominantly graminoids**."*
  - *"Previous studies… have identified **Poaceae to be among the families with the lowest accuracies**."*
  - *"Among the six **Carex** species we observed, **four species had < 60% accuracy in both apps**."*
  - **Confidence scores were highest for herbs and lowest for graminoids** — i.e. the model is least confident exactly where it is least accurate (better calibrated than a VLM).
  - **Reproductive structures mattered most:** *"The increase was highest for graminoids; we observed **32.5% and 50.x%**"* improvement; overall **+8.1% in iNaturalist** for graminoids from reproductive structures.
  - **Multi-image fusion:** *"The exception was graminoids, where we found **19.6% improvement in Flora Incognita** and 9.x% in iNaturalist"*; overall +6% (iNat) and +1.7% (Flora Incognita).
  - **74% of the graminoid images collected featured only vegetative structures** — which is exactly the AUGURY use case (farmers photographing leaves/tillers).
  - Mechanism: *"Narrow lamina, minute vegetative features like ligules or auricles, and small, often concealed florets… make photographing graminoids challenging in the field."*
  - **Caveat: this study tested Flora Incognita and iNaturalist, not Pl@ntNet or plant.id.** **[V]**

### 6.3 Seedlings and rosettes

- **Seedling-stage identification is an active but separate research field, and the evidence is about *detection* rather than open-world species ID. [V]**
  - `PMC12852093` (2026), *"Taxonomical loss for weed seedlings image classification"*: introduces the **Weed Phenological Dataset (WPD)** *"with annotated early growth stages"* and a hierarchical taxonomic loss for few-shot learning. *"Accurate classification of weed seedlings is a key challenge… to advance precision weed management."* **[V]**
  - `PMC13074724` (2026), *"Weed Discrimination at the Seedling Stage in Dryland Fields Under Maize-Soybean Rotation"*: notes *"weeds and crops at the seedling stage… exhibit **high similarity in morphological structure**, scale distribution, and spatial arrangement"* and uses YOLOv11n for detection. **[V]**
  - `PMC13265910` (2026), HybridViT-CAB: classifies into **four** classes — broadleaf weeds, grass, sedge… i.e. **grass/sedge is treated as a coarse class, not a species.** **[V]**
  - **I found no published evaluation of Pl@ntNet or plant.id specifically on seedling or rosette-stage plants.** This is a genuine evidence gap. **[V for the absence]**
- **Practical read-across for AUGURY [I]:** the literature consistently shows (a) early stages are morphologically ambiguous, (b) grass/sedge is often collapsed to a coarse class, and (c) AUGURY's own design already addresses this by letting the *user confirm/choose* from a shortlist and by using a curated AU weed gallery rather than open-world ID.

### 6.4 Vendor claims

- **plant.id:** *"**93%** Correct species in over 9/10 queries within the top three results"* on **35,000+ classes**. They cite AoB Plants 2020 and an alien-street-trees study as independent support. **[V — this is a vendor claim; note AoB Plants 2020 actually measured 57% top-1 for plant.id, and 73% at the "≥50%" level. The 93% figure is a different (top-3, vendor's own) metric.]**
- **Pl@ntNet:** no headline accuracy number is published on the API docs. The FAQ says *"Accuracy is obtained by testing the model on a set of private datasets of different nature, from the easiest… to the most difficult (e.g. very similar species of complex and/or data deficient genera)"* — and warns performance *"varies from one species to another and depends mainly on the number of images illustrating them in the training database."* **[V]**
- **iNaturalist's own statement (2023-09-21, quoted in PLoS ONE 2026):** *"the correct suggestion was included among the nearby subset in **94% of observations**, both for the gridded version and for the Geomodel."* This is a **top-n recall** figure, not top-1 accuracy. **[V]**

### 6.5 How AUGURY's claim compares

AUGURY's README states: **85.87% top-1 / 92.83% top-3 on 920 unseen images on-device**, and **81.8% top-1 / 89.7% top-3 on 184 Australian weeds (alias-merged)**. **[V — from the repo README]**

| Comparison | Figure | Apples-to-apples? |
|---|---|---|
| AUGURY (claimed) | **85.9% top-1 / 92.8% top-3** | Closed-set kNN over a curated AU weed gallery |
| plant.id (vendor, top-3) | 93% top-3 | Open-world, 35k classes |
| plant.id (AoB Plants 2020, top-1) | 57% species | Open-world, British flora, n=38 |
| Pl@ntNet (AoB Plants 2020, top-1) | 39% species | Open-world, British flora, n=38 |
| Flora Incognita (Alberta 2026, top-1) | 79.2% species | Open-world, plot surveys, 5,291 images |
| iNaturalist (Alberta 2026, top-1) | 66.5% species | Open-world, plot surveys |
| Best general app on **graminoids** | **"poor"**; 4/6 *Carex* <60% | Open-world |

**Assessment [I]:** AUGURY's top-1 claim (85.9%) **exceeds** every published top-1 figure I found for general-purpose tools, including on the hardest group (graminoids). Its top-3 (92.8%) is essentially identical to plant.id's *claimed* 93% top-3. **But the comparison is not like-for-like**: AUGURY's number comes from a closed set of Australian weeds with a gallery-based kNN, whereas the published figures are open-world flora identification. **A closed-set task is intrinsically easier** — the correct answer is guaranteed to be in the gallery, which is not true for a general API. The honest framing is: *AUGURY is very strong on its own curated AU weed set; that is not evidence it beats Pl@ntNet on an arbitrary Australian plant.* To make the claim defensible, AUGURY should benchmark on an **open-world** AU weed set (e.g. held-out DeepWeeds species it did not train on, or ALA/herbarium images) with species **not** in its gallery included as distractors.

---

## 7. Q6 — Cost at scale

Assumptions: 1 identification = 1 API request = 1 credit. Month = 30 days. **No AUD conversion applied** (no FX rate verified). All prices as published on 2026-10-08.

### 7.1 Pl@ntNet

The Pro plan is an **annual contract** with a **€1,000 floor** covering 200,000 requests/yr, then €0.005/ID up to 3 M/yr. **[V]**

| IDs/month | IDs/year | Included in €1,000? | Overage | Annual cost | **Monthly cost** | Effective €/ID |
|---|---|---|---|---|---|---|
| 1,000 | 12,000 | Yes (all) | 0 | €1,000 | **€83.33** | €0.0833 |
| 10,000 | 120,000 | Yes (all) | 0 | €1,000 | **€83.33** | €0.00833 |
| 100,000 | 1,200,000 | 200,000 in; 1,000,000 over | 1,000,000 × €0.005 = €5,000 | €6,000 | **€500.00** | €0.005 |

- Verified against Pl@ntNet's own published example (2 M requests → €9,000): (2,000,000 − 200,000) × €0.005 = €9,000 ✅ **[V]**
- **Free tier alternative:** 500 IDs/day ≈ **15,000 IDs/month theoretical maximum**, at €0 — *if* commercial use ≤500/day is permitted (the ambiguity in §2.2). Note the hard constraint is **500/day**, not 15,000/month: a burst of 600 IDs in one day is blocked even if the month is quiet. **[V for the cap; I for the applicability]**
- The €1,000 floor means **Pl@ntNet is more expensive than plant.id at low volume** (€83/mo vs €50/mo at 1,000 IDs/mo) but cheaper at very high volume (€500/mo vs €1,500–2,000/mo at 100,000 IDs/mo).

### 7.2 plant.id (Kindwise)

1 credit per identification; choose the tier by purchase volume. **[V]**

| IDs/month | Best tier | Unit price | **Monthly cost** | Annual cost |
|---|---|---|---|---|
| 1,000 | A (from 1,000 credits, min €50) | €0.05 | **€50** | €600 |
| 10,000 | B (from 10,000 credits, min €300) | €0.03 | **€300** | €3,600 |
| 100,000 | D (from 200,000 credits, min €3,000) | €0.015 | **€1,500** | €18,000 |
| 100,000 | C (from 50,000 credits, min €1,000) | €0.02 | **€2,000** | €24,000 |

- The 100,000/month row shows the value of buying in 200,000-credit blocks: €3,000 per two months = €1,500/month, **provided** the 3-month credit validity works in your favour. **If credits purchased under 30,000 don't expire but larger ones expire in 3 months, buying 200,000 credits for 2 months of usage is safe; buying 800,000 (Tier E, €9,600) for 8 months of usage would expire.** **[V for prices; I for the expiry interaction]**
- **Health assessment would double these costs** (2 credits/ID) — not needed for AUGURY. **[V]**
- **A narrower class set (weeds only) may attract a discount** — Kindwise invite you to ask. **Unquantified.** **[V for the offer; unverified for the amount]**
- Free: **100 credits once**, plus 10 demo IDs/month, plus the 10-per-IP-per-day agent trial. Negligible for production. **[V]**

### 7.3 Google Cloud Vision (for completeness — **not a species-ID substitute**)

Label Detection, first 1,000 units/month free, then $1.50/1,000. **[V]**

| IDs/month | Billable units | **Monthly cost (USD)** |
|---|---|---|
| 1,000 | 0 | **$0.00** |
| 10,000 | 9,000 | **$13.50** |
| 100,000 | 99,000 | **$148.50** |

Cheap — but it returns generic labels ("Plant", "Flower"), not species. **[I]** Not a solution.

### 7.4 Cost comparison at a glance

| IDs/month | Pl@ntNet Pro | plant.id | Google Vision (labels only) | AUGURY on-device |
|---|---|---|---|---|
| 1,000 | €83.33 | €50 | $0.00 | **€0** (marginal) |
| 10,000 | €83.33 | €300 | $13.50 | **€0** |
| 100,000 | €500.00 | €1,500–2,000 | $148.50 | **€0** |

**On-device marginal cost is zero; the cost is model size and engineering.** Note that a *server-proxy* is required for plant.id key security (their own recommendation), so the API route also carries hosting cost and breaks AUGURY's "no cloud required" property. **[V for the recommendation; I for the hosting estimate]**

---

## 8. Comparison table

| Option | On-device vs API | Cost (as published 2026-10-08) | Quota / limits | Licence & commercial terms | AU weed suitability | Ranked shortlist |
|---|---|---|---|---|---|---|
| **AUGURY custom (DINOv2 + kNN)** | **On-device** | €0 marginal; engineering + ~173 MB encoder | None | DINOv2-base **Apache-2.0** ✅; own gallery | **Built for it**; 85.9% top-1 / 92.8% top-3 claimed | Yes (kNN scores) |
| **Pl@ntNet API** | API | Free ≤500/day (commercial use **ambiguous**); Pro **€1,000/yr** incl. 200k, then €0.005/ID | 500/day free; **20 concurrent**; 1M/day Pro | Pro contract permits commercial use; free tier purpose-limited; broad IP clause; **images not stored by them** | **`k-australia` flora exists** ✅; "Invasive plants" thematic flora; grasses/leaves weak | **Yes** — scores 0–1, ranked; `nb-results` |
| **plant.id (Kindwise)** | API (**server proxy recommended**) | 100 free credits; **€0.05 → €0.01/ID** by tier; min order €50–€15,000 | "No limits or caps"; SLA >99.5% uptime, 3 s max | Commercial use ✅; Output licence unlimited + sublicensable ✅; **§17.3.3 bars building a competing system** ⚠️; **§17.5 irrevocable photo reuse + CC-BY-SA** ⚠️ | `continent__australasia`, `graminoid`, `weedy_plant`, `invasive_plant` filters; N-hemisphere bias ⚠️ | **Yes** — up to 10 suggestions with `probability`; `<1%` omitted; `is_plant` gate |
| **iNaturalist CV** | API | **N/A — not offered** | 100 req/min, 60/min requested, 10,000/day (general API) | **CV endpoint 401/undocumented**; default content **CC BY-NC**; **commercial AI training prohibited** ❌ | Untestable | Unknown |
| **Google Cloud Vision** | API | First 1,000/mo free, then **$1.50/1,000** | Standard GCP quotas | Commercial ✅ | ❌ Generic labels, no species | ❌ No |
| **Bing Visual Search** | — | **Retired 2025-08-11** ❌ | — | — | — | — |
| **Flora Incognita** | App only | Free app | — | **No public API (404)** | Central-European flora focus | Unknown |
| **PlantIn / Ximilar plant API / Eden AI plant** | — | **Dead or 404** ❌ | — | — | — | — |
| **PictureThis / Glority** | App only | — | — | **No public plant-ID API** | — | — |
| **BioCLIP / BioCLIP-2** | On-device (own model) | €0 marginal | None | **MIT** ✅ | Broad (450K+ taxa); not AU-tuned | Yes (zero-shot probabilities) |
| **DeepWeeds** | Dataset | Free | — | **CC BY 4.0** ✅ | **8 AU weed species, Queensland** (mostly woody, not grasses) | n/a |
| **MiniCPM5-1B / MiniCPM-V-4.6** | On-device | €0 marginal | None | **Apache-2.0** ✅ | Not a fine-grained species ID tool ❌ (see §11) | n/a |

---

## 9. Sources

All URLs fetched or queried on **2026-10-08** unless a different date is shown.

**Pl@ntNet**
- https://my.plantnet.org/terms_of_use — free-tier text, 500/day, Pro pricing, 20 concurrent, 1M/day
- https://my.plantnet.org/doc/getting-started/pro-plan — €1,000 / 200,000 requests, tiered overage, worked example
- https://my.plantnet.org/doc/api/identify — shortlist, scores, `project`, `nb-results`, organs
- https://my.plantnet.org/doc/references/newfloras — POWO/TDWG floras, thematic floras incl. "Invasive plants"
- https://my.plantnet.org/doc/references/using-images — CC BY-SA image attribution
- https://my.plantnet.org/doc/references/changelog — model updates, 77k species, free-plan error credits, Pro-only species images
- https://my.plantnet.org/doc/api/quota — quota headers, 429, UTC reset
- https://my.plantnet.org/doc/api/survey — survey beta, 1 credit/tile, 518 px tiles
- https://my.plantnet.org/doc/getting-started/faq — image sizes, organ ranking, "InceptionV3", no-performance-guarantee
- https://my.plantnet.org/doc/getting-started/researchers — non-profit plan requires logo
- https://my.plantnet.org/doc/getting-started/introduction — DINOv2 citation, CORS/key exposure
- https://my-api.plantnet.org/swagger.json — OpenAPI 2.0 spec, API v2.2.2, full parameter list
- https://my-api.plantnet.org/v2/projects — returned 401 Unauthorized (no key)
- https://identify.plantnet.org/k-australia/species — title "Australia: Species - Pl@ntNet identify"

**Kindwise / plant.id**
- https://www.kindwise.com/pricing — tier table, €0.05→€0.01, 3-month validity, NGO pricing
- https://www.kindwise.com/faq — credits, 10 suggestions, <1% omitted, latency, SLA, suggestion filters, trade-secret class list, image licences
- https://www.kindwise.com/plant-id — 35,000+ classes, 93% top-3 claim, three-model pipeline
- https://www.kindwise.com/handbook — 6-month result retrieval, GBIF/iNat IDs, description licences
- https://www.kindwise.com/llms.txt — agent trial 10/IP/24h, product map
- https://plant.id/suggestion_filters — `continent__australasia`, `graminoid`, `weedy_plant`, `invasive_plant`
- https://plant.id/api/v3/openapi.yaml — response schema, `suggestion_filter`, `classification_level`, `is_plant`
- https://cdn.prod.website-files.com/64876ae345f1e27598fafc02/6853d59465d761e68644128a_KW%20API%20T%26C%20v3.docx.pdf — **API T&C v3** (§6.14, §17.2–17.5)

**iNaturalist**
- https://api.inaturalist.org/v1/swagger.json — API v1.3.0, rate limits, ToS pointer, photo-licence domains, **no computervision route**
- https://api.inaturalist.org/v1/computervision/score_image — POST → `401 Unauthorized`
- http://web.archive.org/web/20260911052554/https://www.inaturalist.org/terms — **ToS snapshot 2026-09-11**: CC BY-NC default; "Prohibited Use for Commercial AI Training"
- https://registry.opendata.aws/inaturalist-open-data/ — "Creative Commons or Public Domain (CC0), varying by image"
- https://raw.githubusercontent.com/inaturalist/inaturalist-open-data/main/README.md — CC-BY-NC attribution example
- https://huggingface.co/api/models?author=inaturalist — **0 models**

**Google / Microsoft**
- https://cloud.google.com/vision/pricing — Label Detection free 1,000, then $1.50/$1.00 per 1,000
- https://learn.microsoft.com/en-us/lifecycle/announcements/bing-search-api-retirement — Bing Search APIs retired **2025-08-11**
- https://learn.microsoft.com/en-us/previous-versions/bing/search-apis/bing-visual-search/overview — now under previous-versions

**Models and datasets**
- https://huggingface.co/api/models/facebook/dinov2-base — Apache-2.0, 86,580,480 params
- https://raw.githubusercontent.com/facebookresearch/dinov2/main/LICENSE — Apache-2.0
- https://huggingface.co/api/models/facebook/dinov3-vits16-pretrain-lvd1689m — license "other", gated "manual", 21,596,544 params
- https://raw.githubusercontent.com/facebookresearch/dinov3/main/LICENSE.md — DINOv3 License, last updated 2025-08-19
- https://huggingface.co/api/models/imageomics/bioclip — MIT, TreeOfLife-10M, 450K+ taxa
- https://huggingface.co/api/models/imageomics/bioclip-2 — MIT, ViT-L/14, TreeOfLife-200M
- https://huggingface.co/api/models/openbmb/MiniCPM5-1B — Apache-2.0, 1,080,632,832 params
- https://huggingface.co/api/models/openbmb/MiniCPM-V-4.6 — Apache-2.0, 1,300,428,016 params
- https://huggingface.co/api/models/openbmb/MiniCPM-V-4 — Apache-2.0, 4,059,533,040 params
- https://huggingface.co/api/models/openbmb/MiniCPM-V-4_5 — Apache-2.0, 8,695,895,280 params
- https://huggingface.co/api/models/openbmb/MiniCPM-o-4_5 — Apache-2.0, 9,371,787,666 params
- https://huggingface.co/api/models/openbmb/MiniCPM-V-2_6 — gated "auto", **no licence field in cardData**, 8,099,175,152 params
- https://raw.githubusercontent.com/OpenBMB/MiniCPM-V/main/LICENSE — Apache-2.0
- https://raw.githubusercontent.com/OpenBMB/MiniCPM-V/main/README.md — MiniCPM-V 4.6 (1.3B, SigLIP2-400M + Qwen3.5-0.8B, iOS/Android/HarmonyOS)
- https://raw.githubusercontent.com/OpenBMB/MiniCPM/main/LICENSE — Apache-2.0
- https://raw.githubusercontent.com/AlexOlsen/DeepWeeds/master/README.md — CC BY 4.0, 17,509 images, 8 AU weeds, 95.7% ResNet50
- https://www.imageclef.org/PlantCLEF2024 — SW-Europe Pl@ntNet subset, 7.8k species, 1.4M images

**Accuracy literature**
- https://europepmc.org/article/MED/PMC7640754 (AoB PLANTS 2020, plaa052, DOI 10.1093/aobpla/plaa052) — full text via `.../PMC7640754/fullTextXML`
- https://europepmc.org/article/MED/PMC12952603 (PLoS ONE 2026, DOI 10.1371/journal.pone.0342712) — Poaceae lower accuracy; location restriction
- https://europepmc.org/article/MED/PMC13394787 (2026) — **Alberta graminoid grassland plot survey**, Flora Incognita 79.2% vs iNaturalist 66.5%; graminoids poor
- https://europepmc.org/article/MED/PMC12986848 (2026) — **OpenPlant**: DenseNet-121 91.37% vs Gemini-2.0 49.70%, GPT-4V 42.60%; VLM ECE 37–69%
- https://europepmc.org/article/MED/PMC12950715 (2026) — **TinyWeedNet**: 0.48 M params, 97.26% DeepWeeds, <90 ms on STM32H7
- https://europepmc.org/article/MED/PMC12852093 (2026) — Weed Phenological Dataset, seedling-stage taxonomic loss
- https://europepmc.org/article/MED/PMC13074724 (2026) — seedling-stage weed/crop discrimination, YOLOv11n
- https://europepmc.org/article/MED/PMC13265910 (2026) — HybridViT-CAB: broadleaf / grass / sedge as **coarse classes**
- https://api.crossref.org/works/10.1111/2041-210X.14486 — Lefort et al. 2025, *Methods in Ecology and Evolution*, Pl@ntNet cooperative learning

**Platform constraints**
- https://support.google.com/googleplay/android-developer/answer/9859372 — Play size limits: base 500 MB, asset packs 1.5 GB, total 34 GB, >200 MB warning, legacy APK 100 MB
- https://developer.android.com/guide/playcore/asset-delivery — Play Asset Delivery, >200 MB apps, fast-follow/on-demand not counted in listing size

**AUGURY internal (for the comparison)**
- `README.md` — DINOv2-base + kNN; 81.8%/89.7% on 184 AU weeds; 85.87%/92.83% on 920 unseen on-device; MiniCPM5-1B LoRA GGUF 688 MB; mobile ~368 MB vs ~1.06 GB
- `docs/openbmb-playbook.md` — "Model catalog (verified 2026-08-11, all Apache-2.0)"; MiniCPM5-1B 1.1B text formatter

---

## 10. What I could not verify

Be explicit about the holes. **None of these change the headline conclusions, but several could change a decision.**

1. **`web_search` was unavailable** (no API key configured for this session). I could only fetch URLs I already knew or could guess. **The 2025–2026 "new plant-ID API" sweep is therefore not exhaustive** — a new entrant could exist that I never found. If this matters, re-run with search enabled.
2. **The full Pl@ntNet flora list.** `GET /v2/projects` requires a key and returned 401. I **confirmed `k-australia` exists** via its species-explorer page, but I could **not** confirm whether `k-australasia`, `k-new-south-wales`, `k-queensland`, `k-victoria`, `k-tasmania` etc. exist. My URL probes of those ids were **invalid** because the explorer SPA returns HTTP 200 for any path (a bogus id also returned 200). **Anyone with a free Pl@ntNet key can settle this in one call.**
3. **The Pl@ntNet Pro copyright licence PDFs** (`copyright_licence_PlantNet_API_english_v5.1_EUR.pdf` and `_USD.pdf`) — I found the links but did **not** download or read them. **The Pro plan's actual attribution, caching and data-reuse terms live there**, not in the public ToU. This is the most important outstanding document.
4. **Whether Pl@ntNet permits commercial use on the free tier.** The ToU text is genuinely self-contradictory (see §2.2). Needs a written answer from Pl@ntNet.
5. **Pl@ntNet latency.** No published p50/p95 figure. Qualitative statements only.
6. **Pl@ntNet's current model architecture.** Their FAQ says InceptionV3; their introduction cites DINOv2. One of these is stale.
7. **Kindwise credit-expiry semantics.** "Purchased credits are valid for 3 months (this does not apply to purchases under 30,000 credits)" has two plausible readings with different cost consequences for low-volume buyers.
8. **Kindwise's weed-only discount.** Offered by email but not quantified anywhere public.
9. **An official Google Lens API.** I found none and did not verify its absence from an authoritative page. Treat "no Lens API" as unverified.
10. **Google Vision's label taxonomy** (i.e. proof that it does not emit species names). I verified the pricing but not the label list.
11. **iNaturalist's live ToS.** inaturalist.org returns 403 to automated fetches; I used a **2026-09-11 Wayback snapshot**. The clauses are almost certainly current, but they are from an archive, not the live page.
12. **Plantician.** 403 (Cloudflare) — existence, pricing and terms unverified. It may be a real option.
13. **Blom.ai, PlantVision.ai, Clarifai, Ximilar's current plant offering** — DNS/404 failures from this environment; unverified rather than confirmed-dead.
14. **Leafsnap's** current status, licence and dataset availability — not verified.
15. **Dataset licences for TreeOfLife-10M/-200M, the Weed Phenological Dataset, and PlantCLEF.** I verified the *model* licences (BioCLIP = MIT) but not the *training data* licences. **This matters: an MIT model trained on restrictively-licensed images is not automatically clean to use commercially.**
16. **No published accuracy for Pl@ntNet or plant.id on seedlings/rosettes.** Genuine evidence gap. The seedling literature is about detection and coarse classes, not open-world species ID.
17. **No AU-specific accuracy benchmark for Pl@ntNet or plant.id.** I found no study measuring either on Australian weeds. **The Alberta and British studies are the closest proxies and neither is Australian.**
18. **No AUD conversions and no FX rate** — deliberately omitted; all figures are in vendor currency as published.
19. **The exact graminoid top-1 percentage in the Alberta 2026 study** is presented in a figure/supplementary table I could not extract as text. I have the qualitative finding ("poor", "all other growth forms within reference range") and the *Carex* <60% figure, but not the single graminoid top-1 number.

---

## 11. Supplementary — OpenBMB MiniCPM licences and on-device VLM viability

*Added at the parent's request: "is the OpenBMB model the right path forward?" The model in play is a fine-tuned MiniCPM5-1B GGUF used as a prose formatter, not a vision model; an earlier proposal considered forking OpenBMB/MiniCPM-V-Apps.*

### 11.1 MiniCPM licence terms — the answer is "Apache-2.0, with one exception"

The "MiniCPM Model License requiring free registration for commercial use" concern applies to **older MiniCPM generations**, not to the models AUGURY is actually using. Verified licence metadata from the Hugging Face model API and the GitHub LICENSE files, all on 2026-10-08: **[V]**

| Model | `cardData.license` / tag | Gated? | Params |
|---|---|---|---|
| **openbmb/MiniCPM5-1B** | **`apache-2.0`** ✅ | **No** | 1,080,632,832 |
| **openbmb/MiniCPM-V-4.6** | **`apache-2.0`** ✅ | **No** | 1,300,428,016 |
| openbmb/MiniCPM-V-4_5 | **`apache-2.0`** ✅ | No | 8,695,895,280 |
| openbmb/MiniCPM-V-4 | **`apache-2.0`** ✅ | No | 4,059,533,040 |
| openbmb/MiniCPM-o-4_5 | **`apache-2.0`** ✅ | No | 9,371,787,666 |
| **openbmb/MiniCPM-V-2_6** | ⚠️ **no licence field at all in `cardData`** | **Yes — `gated: "auto"`** | 8,099,175,152 |

- The **GitHub LICENSE files are Apache-2.0** in both the `MiniCPM-V` and `MiniCPM` repos: *"Copyright OpenBMB — Licensed under the Apache License, Version 2.0"*. **[V]**
- **`MiniCPM5-1B` — the model AUGURY actually fine-tunes as the formatter — is unambiguously Apache-2.0 and ungated.** Its HF tags include `on-device`, `edge-ai`, `tool-calling`, `long-context`; it was created 2026-05-21 and last modified 2026-08-17. **[V]** This confirms and extends `docs/openbmb-playbook.md` ("all Apache-2.0", verified 2026-08-11).
- **The one caveat: MiniCPM-V-2.6.** The HF repo is **gated** (you must be authenticated and granted access) and its model card **declares no SPDX licence**, so the HF API reports no `license:` tag. The GitHub repo LICENSE is Apache-2.0, but the *weights* are behind a gate. **If any AUGURY artifact depends on MiniCPM-V-2.6 weights, verify the terms attached to that gated repo before commercial distribution.** Note also that the **GGUF conversions** `openbmb/MiniCPM-V-2_6-gguf` and `openbmb/MiniCPM-V-4_5-gguf` are ungated but declare **no licence metadata at all** — the base repo's licence is the thing to rely on. **[V]**
- **Practical conclusion for AUGURY [I]:** the MiniCPM licence question is **not** a blocker. `MiniCPM5-1B` (Apache-2.0) is safe to fine-tune, quantise to GGUF, and ship or not ship. `MiniCPM-V-4.6` (Apache-2.0, 1.3B, with official iOS/Android/HarmonyOS edge deployment code) is the natural choice if a vision model is ever wanted. **The only licence risk is MiniCPM-V-2.6, which AUGURY does not appear to need.**

### 11.2 Is an on-device VLM a realistic replacement for fine-grained plant ID? — **No, on current evidence**

This is the more important half of the question, and the 2026 evidence is unusually clear.

**OpenPlant (2026), `PMC12986848`** — *"OpenPlant: A Large-Scale Benchmark Dataset for Agricultural Plant Classification Using CNNs, ViTs, and VLMs"* — benchmarked **10 CNNs, 6 ViTs and 12 VLMs** (open- and closed-source) on the same large agricultural plant dataset. **[V]**

| Model class | Best result |
|---|---|
| **CNN** | **DenseNet-121: 91.37% accuracy** (ResNet-101 best overall composite score, 96.95%) |
| **Best closed-source VLM** | **Gemini-2.0: 49.70%** |
| GPT-4V | 42.60% |
| Gemma-3 | 37.20% |
| Pure ViT (e.g. ViT-Base) | F1 **25.91%** — *"weaker performance on long-tailed data"* |

Additional findings, quoted: **[V]**
- **"This indicates that VLMs struggle with the same challenging cases as pure vision models."**
- **"for 2554 hard samples (incorrectly predicted by 16 CNNs and ViTs), VLMs achieved more than 50% accuracy in 384 samples"** — i.e. VLMs rescued only ~15% of the cases the small models got wrong.
- **Calibration is poor:** *"most VLMs exhibit poor calibration, with values ranging from **37% (Gemini-2.0) to 69% (InternVL2.5-4B)**"* expected calibration error. **A model that is wrong ~50% of the time but reports high confidence is exactly the hallucination failure mode that matters for a soil-health app.**
- **"large models tend to classify low-frequency samples into high-frequency categories"** — a systematic bias toward common species, which is the opposite of what an Australian weed app needs (rare/regionally-specific taxa).
- *"CNNs performed better than pure vision transformers."*

**Corroborating evidence:**
- **AoB PLANTS 2020** found **Bing (a general vision system) scored 3% correct to species and 67% wrong at family level or worse** — general-purpose vision systems are not species identifiers. **[V]**
- The **Alberta 2026** study found even *purpose-built* apps fail on graminoids; a general VLM has no specialised grass features to fall back on. **[V]**
- **TinyWeedNet (2026)** shows the opposite end of the spectrum: a **0.48 M-parameter CNN** reaches **97.26%** on DeepWeeds with **<90 ms** inference and **~39 mJ** per inference on an STM32H7 MCU, in **under 2 MB of flash**. **For a closed-set weed task, you need a tiny CNN, not a billion-parameter VLM.** **[V]**

**On-device VLM practicality (sizes and feasibility):** **[V for the sizes; I for the feasibility judgement]**

| Model | Params | Approx. Q4 quantised size | On-device plausibility |
|---|---|---|---|
| MiniCPM-V 4.6 | 1.30 B | ~0.7–0.8 GB | Feasible on flagship phones; official iOS/Android/HarmonyOS edge code open-sourced |
| MiniCPM-V 4 | 4.06 B | ~2.3 GB | Heavy; flagship only |
| MiniCPM-V 4.5 | 8.70 B | ~4.9 GB | Not realistic as a bundled app asset |
| MiniCPM-o 4.5 | 9.37 B | ~5.3 GB | Not realistic on phone |

*(Quantised sizes are my arithmetic at ~4.5 bits/param; **the vendors' own GGUF sizes were not verified in this session.**)*

**Does anyone publish plant/weed species-ID accuracy for VLMs?** Yes — OpenPlant (above) is precisely that, and it is the strongest evidence available. I also found a 2026 review (`PMC13499205`) covering AI for biodiversity, and `PMC12607614` (EyeInvaS, 2025) benchmarking nine deep-learning models on 54 invasive alien species in China, where **EfficientNetV2** — a CNN, not a VLM — was best. **[V]**

**Hallucination tendency:** I found no study that measured *species-name hallucination* rates for VLMs directly (i.e. confidently naming a species absent from the image). The closest evidence is the **poor calibration (ECE 37–69%)** and the **majority-class bias** in OpenPlant, plus the general finding that VLMs fail on the same hard cases as small models. **Treat "VLMs hallucinate species names" as strongly suggested but not directly quantified in the sources I found. [I]**

### 11.3 Verdict on the OpenBMB question

- **Licence: yes, the right path.** MiniCPM5-1B is Apache-2.0 and ungated; MiniCPM-V-4.6 is Apache-2.0 with first-party Android edge deployment code. **AUGURY's current use of MiniCPM5-1B purely as a prose formatter is licence-clean and architecturally sound.** Avoid MiniCPM-V-2.6. **[V/I]**
- **As a vision component: no.** AUGURY's own README is right that the formatter is a *voice*, not a *perceiver*, and should not ship in the mobile build. The 2026 OpenPlant benchmark shows that swapping the DINOv2 + kNN perceptual layer for a small VLM would likely **halve** accuracy (91.4% → ~50%) while adding ~0.7 GB and per-answer generation latency. **The existing division of labour — retrieval for perception, deterministic database for facts, optional LLM for prose — is well matched to the evidence.** **[I]**
- **If a VLM is ever added on-device**, MiniCPM-V-4.6 is the right candidate (Apache-2.0, 1.3B, official Android edge code), but it should be used for **explanation and dialogue**, never as the source of a species name or a soil indicator. **[I]**

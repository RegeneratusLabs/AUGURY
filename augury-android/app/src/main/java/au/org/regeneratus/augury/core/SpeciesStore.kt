package au.org.regeneratus.augury.core

import java.io.File
import java.io.InputStream
import java.math.BigDecimal
import java.math.RoundingMode

/**
 * AUGURY — [SpeciesStore]
 *
 * Kotlin port of the **runtime** surface of `scripts/species_lookup.py`
 * ([SpeciesDB]) plus the two runtime helpers the funnel needs from
 * `scripts/augury_funnel.py` (`classify_specificity`, `_best_plant_match`).
 *
 * The build-time parsing of `data/training/weeds_indicators_merged_train.jsonl`
 * and the `_sanitize()` curation pass are deliberately **not** ported: the app
 * ships `data/app/augury-ondevice.json`, which is that pipeline's output. Ship
 * the parsed database, not the parser.
 *
 * What is ported, and from where:
 *
 * | Kotlin                              | Python                                   |
 * |-------------------------------------|------------------------------------------|
 * | [load]/index                        | `SpeciesDB._load` + `_load_synonyms`     |
 * | [getIndicators]                     | `SpeciesDB.get_indicators`               |
 * | [canonicalGroup]                    | `SpeciesDB._canonical_group`             |
 * | [search]                            | `SpeciesDB.search`                       |
 * | [classifySpecificity]               | `augury_funnel.classify_specificity`     |
 * | [bestPlantMatch]                    | `AuguryFunnel._best_plant_match`         |
 * | [resolveQuery]                      | `_extract_regex` → `resolve` (one name)  |
 *
 * Two deliberate, documented departures — see [KNOWN_PYTHON_BUGS]:
 *
 * 1. `search()` step 5 identifies a fuzzy scientific-name hit by the matched
 *    **lowercased scientific name** and treats that string as a DB key. That
 *    holds for the training DB (keys are `scientific_name.lower()` by
 *    construction) but not for `augury-ondevice.json`, where five species differ
 *    (`'cenchrus spp'` vs `'Cenchrus spp.'`, …). There it raises `KeyError` and
 *    aborts the whole search. This port indexes scientific names explicitly.
 * 2. `_sanitize()` deletes junk keys from the DB; the app DB keeps them and tags
 *    them `specificity: "junk"` so a user who pastes "dandelion clay" still gets
 *    an honest answer (`scripts/junk_keys.py`). This port keeps them and filters
 *    at match time, exactly like `_best_plant_match`.
 *
 * No `android.*` types are used anywhere in this file: it runs on the JVM and on
 * a device without an emulator.
 */
class SpeciesStore private constructor(
    private val species: LinkedHashMap<String, Species>,
    private val canonical: Map<String, String>,
) {

    /** One species row from the on-device database. */
    class Species internal constructor(
        val key: String,
        val commonName: String?,
        val scientificName: String,
        val declaredSpecificity: String,
        val hasIndicators: Boolean,
        /** region -> (indicator key -> value), both insertion-ordered. */
        internal val regions: LinkedHashMap<String, LinkedHashMap<String, String>>,
        internal val sources: MutableMap<String, String>,
    ) {
        /** Python's `common_names` list; the app DB carries exactly one. */
        internal val commonNames: MutableList<String> =
            ArrayList<String>().also { if (!commonName.isNullOrEmpty()) it.add(commonName) }
    }

    /** A `search()` hit — mirrors one dict from `SpeciesDB.search`. */
    data class SpeciesMatch(
        val scientificName: String,
        val commonNames: List<String>,
        val matchType: String,
        val score: Double,
        val key: String,
    )

    /** The `get_indicators()` return value, field for field. */
    data class IndicatorResult(
        val scientificName: String,
        val commonNames: List<String>,
        val region: String,
        val requestedRegion: String?,
        val regionFallback: Boolean,
        /** Insertion-ordered: the first sibling to define a label wins. */
        val indicators: Map<String, String>,
        val source: String,
        val canonicalKey: String,
        val mergedFrom: List<String>,
    )

    /** Python's `info["match"]`, added by `AuguryFunnel.resolve`. */
    data class MatchInfo(
        val query: String,
        val matchType: String,
        val score: Double,
        val specificity: String,
        /**
         * The matched database key. `resolve()` keeps this in a local variable and
         * dedups on it; carried here so the de-duplication can be reproduced.
         */
        val key: String,
    )

    /** A resolved species: `get_indicators()` enriched with match provenance. */
    data class ResolvedSpecies(val info: IndicatorResult, val match: MatchInfo) {
        val scientificName: String get() = info.scientificName
        val commonNames: List<String> get() = info.commonNames
        val region: String get() = info.region
        val requestedRegion: String? get() = info.requestedRegion
        val regionFallback: Boolean get() = info.regionFallback
        val indicators: Map<String, String> get() = info.indicators
        val source: String get() = info.source
        val canonicalKey: String get() = info.canonicalKey
        val mergedFrom: List<String> get() = info.mergedFrom
        val specificity: String get() = match.specificity
    }

    // ── indexes (mirrors SpeciesDB's private attributes) ──────────────────────

    /** `self._common_index` — lowercased common name -> species key. */
    private val commonIndex = LinkedHashMap<String, String>()

    /** `self._scientific_names` — in file order, duplicates allowed. */
    private val scientificNames = ArrayList<String>()

    /** lowercased scientific name -> key (see KNOWN_PYTHON_BUGS #1). */
    private val sciNameToKey = LinkedHashMap<String, String>()

    val speciesCount: Int get() = species.size
    val commonNameCount: Int get() = commonIndex.size
    val curatedSynonymCount: Int get() = curatedSynonyms
    private var curatedSynonyms = 0

    /** Insertion-ordered indicator keys actually present, for diagnostics. */
    val indicatorKeys: Set<String>
        get() {
            val out = LinkedHashSet<String>()
            for (sp in species.values) for (r in sp.regions.values) out.addAll(r.keys)
            return out
        }

    init {
        for ((key, sp) in species) {
            scientificNames.add(sp.scientificName)
            val cn = sp.commonName
            if (!cn.isNullOrEmpty()) {
                val lower = cn.lowercase()
                if (!commonIndex.containsKey(lower)) commonIndex[lower] = key
            }
            sciNameToKey.putIfAbsent(sp.scientificName.lowercase(), key)
        }
    }

    // ── loading ──────────────────────────────────────────────────────────────

    companion object {
        /** Bundled JVM resources, copied verbatim from `data/vision/` and `data/research/`. */
        const val CANONICAL_MAP_RESOURCE = "canonical_map.json"
        const val SYNONYMS_RESOURCE = "common_name_synonyms.json"

        /** Non-species artefacts. Copied from `scripts/junk_keys.py` (JUNK_KEYS). */
        val JUNK_KEYS: Set<String> = setOf(
            // PSEUDO_SPECIES — UK soil associations, not plants
            "chicory clay", "dandelion clay", "goosegrass clay", "plantains clay",
            "fumitory loam", "rushes excess", "timothy heavy",
            // TRUNCATED_KEYS — truncated mid-word upstream
            "tripleurosper perforatum", "rhynchosinapi cheiranthos",
            // MISSPELLED_KEYS
            "astrebia spp",
            // MISC_JUNK
            "unknown",
        )

        /** `AuguryFunnel.CLAY_PSEUDO_SPECIES` — honoured when asked for literally. */
        val CLAY_PSEUDO_SPECIES: Set<String> =
            setOf("dandelion clay", "plantains clay", "goosegrass clay", "chicory clay")

        /** `GENUS_BUCKET_RE = re.compile(r"\bspp\.?$", re.I)`. */
        private val GENUS_BUCKET_RE = Regex("\\bspp\\.?$", RegexOption.IGNORE_CASE)

        /**
         * `augury_funnel.classify_specificity`.
         *
         * `"exact_species"` | `"genus_bucket"` | `"junk"`. Callable as
         * `SpeciesStore.classifySpecificity(key)`, matching the Python module-level
         * function.
         */
        fun classifySpecificity(key: String?): String {
            val k = (key ?: "").trim()
            if (k.lowercase() in JUNK_KEYS) return "junk"
            if (GENUS_BUCKET_RE.containsMatchIn(k)) return "genus_bucket"
            return "exact_species"
        }

        /** Load from the raw JSON texts (no file system access). */
        fun fromJson(
            speciesJson: String,
            canonicalJson: String? = null,
            synonymsJson: String? = null,
        ): SpeciesStore {
            val doc = Json.parse(speciesJson) as? Map<*, *>
                ?: throw IllegalArgumentException("augury-ondevice.json: root is not an object")
            val canonical = canonicalMapFrom(canonicalJson)
            val store = SpeciesStore(parseSpecies(doc), canonical)
            store.applySynonyms(synonymsJson)
            return store
        }

        /** Load from files by path — the headless-test entry point. */
        fun fromFiles(
            speciesPath: File,
            canonicalPath: File? = null,
            synonymsPath: File? = null,
        ): SpeciesStore = fromJson(
            speciesPath.readText(),
            canonicalPath?.takeIf { it.isFile }?.readText(),
            synonymsPath?.takeIf { it.isFile }?.readText(),
        )

        /**
         * Production entry point: the species database is supplied as a stream
         * (an Android `AssetManager` stream, in the app), while the canonical map
         * and vernacular synonyms are read from the bundle's JVM resources — the
         * canonical pairs are never hardcoded in Kotlin.
         */
        fun bundled(
            speciesStream: InputStream,
            canonicalStream: InputStream? = resourceStream(CANONICAL_MAP_RESOURCE),
            synonymsStream: InputStream? = resourceStream(SYNONYMS_RESOURCE),
        ): SpeciesStore = fromJson(
            speciesStream.bufferedReader(Charsets.UTF_8).use { it.readText() },
            canonicalStream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() },
            synonymsStream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() },
        )

        /** `None` when the resource is absent, so the store degrades gracefully. */
        fun resourceStream(name: String): InputStream? =
            SpeciesStore::class.java.classLoader?.getResourceAsStream(name)

        private fun canonicalMapFrom(canonicalJson: String?): Map<String, String> {
            if (canonicalJson.isNullOrBlank()) return emptyMap()
            val root = Json.parse(canonicalJson) as? Map<*, *> ?: return emptyMap()
            val canon = root["canonical"] as? Map<*, *> ?: return emptyMap()
            val out = LinkedHashMap<String, String>()
            for ((k, v) in canon) if (k is String && v is String) out[k] = v
            return out
        }

        private fun parseSpecies(doc: Map<*, *>): LinkedHashMap<String, Species> {
            val rows = doc["species"] as? List<*> ?: emptyList<Any?>()
            val out = LinkedHashMap<String, Species>()
            for (row in rows) {
                val r = row as? Map<*, *> ?: continue
                val key = ((r["key"] as? String) ?: continue).trim().lowercase()
                val commonName = (r["common_name"] as? String)?.trim()?.takeIf { it.isNotEmpty() }
                val regions = LinkedHashMap<String, LinkedHashMap<String, String>>()
                val sources = HashMap<String, String>()
                for (regionRow in (r["regions"] as? List<*> ?: emptyList<Any?>())) {
                    val rr = regionRow as? Map<*, *> ?: continue
                    val region = (rr["region"] as? String) ?: continue
                    val ind = LinkedHashMap<String, String>()
                    for ((ik, iv) in (rr["indicators"] as? Map<*, *> ?: emptyMap<Any?, Any?>())) {
                        if (ik is String && iv is String) ind[ik] = iv
                    }
                    regions[region] = ind
                    sources[region] = (rr["source"] as? String) ?: ""
                }
                out[key] = Species(
                    key = key,
                    commonName = commonName,
                    scientificName = (r["scientific_name"] as? String) ?: key,
                    declaredSpecificity = (r["specificity"] as? String) ?: "exact_species",
                    hasIndicators = (r["has_indicators"] as? Boolean) ?: regions.isNotEmpty(),
                    regions = regions,
                    sources = sources,
                )
            }
            return out
        }
    }

    /**
     * `SpeciesDB._load_synonyms` — curated vernacular names
     * (`data/research/common_name_synonyms.json`), applied last so they win, and
     * only when the target key exists. A synonym never overwrites an existing
     * exact common-name mapping.
     */
    private fun applySynonyms(synonymsJson: String?) {
        if (synonymsJson.isNullOrBlank()) return
        val root = Json.parse(synonymsJson) as? Map<*, *> ?: return
        val synonyms = root["synonyms"] as? Map<*, *> ?: return
        var added = 0
        for ((commonRaw, keyRaw) in synonyms) {
            if (commonRaw !is String || keyRaw !is String) continue
            val key = keyRaw.lowercase()
            val cn = commonRaw.lowercase().trim()
            if (cn.isEmpty() || !species.containsKey(key)) continue
            if (!commonIndex.containsKey(cn)) {
                commonIndex[cn] = key
                val cnList = species[key]!!.commonNames
                if (commonRaw !in cnList) cnList.add(commonRaw)
                added++
            }
        }
        curatedSynonyms = added
    }

    // ── canonical identity ───────────────────────────────────────────────────

    /**
     * `SpeciesDB._canonical_group` — every DB key denoting the same plant as
     * [key], including [key] itself, with the canonical entry first.
     */
    fun canonicalGroup(key: String): List<String> {
        val target = canonical[key]
        val out = ArrayList<String>()
        if (target != null) {
            out.add(target)
            for ((k, v) in canonical) if (v == target) out.add(k)
        } else {
            out.add(key)
            for ((k, v) in canonical) if (v == key) out.add(k)
        }
        return out
    }

    // ── lookup ───────────────────────────────────────────────────────────────

    /**
     * `SpeciesDB.get_indicators`.
     *
     * Region policy: the requested region wins; otherwise "Australia", "UK",
     * "Europe", then any region that actually carries rows. When the served
     * region differs from the requested one, [IndicatorResult.regionFallback] is
     * `true` and [IndicatorResult.requestedRegion] is preserved so callers can
     * disclose it.
     *
     * Canonical policy: the whole canonical group is resolved and its indicator
     * rows are **merged** (union of labels; the canonical entry wins collisions).
     * The group is ordered canonical-first, so the answer does not depend on
     * which name the caller happened to use. Identity, however, follows the
     * **queried** key: "thistles" stays a genus-level answer and is never
     * relabelled as *Cirsium vulgare*.
     *
     * Returns `null` when the species is unknown or carries no usable rows
     * anywhere — the honest no-data path.
     */
    fun getIndicators(name: String, region: String? = null): IndicatorResult? {
        val queried = name.trim().lowercase()
        if (queried.isEmpty()) return null

        val group = canonicalGroup(queried)
        // Canonical entry leads, then the remaining siblings sorted. Without the
        // sort, a label defined differently on both sides (`cirsium spp` vs
        // `cirsium vulgare`) resolved differently depending on which name the
        // caller typed.
        val lead = if (group.isNotEmpty() && species.containsKey(group[0])) group[0] else queried
        val keys = ArrayList<String>()
        keys.add(lead)
        for (k in group.filter { it != lead && species.containsKey(it) }.sorted()) keys.add(k)

        val infos = keys.filter { species.containsKey(it) }.map { it to species[it]!! }
        if (infos.isEmpty()) return null
        val key = infos[0].first
        val mergedFrom = infos.map { it.first }

        // Identity follows the QUERIED key, not the canonical lead: data merges,
        // identity does not. A genus bucket must not be relabelled as a species.
        val identity = if (species.containsKey(queried)) queried else key
        val idInfo = species[identity]!!

        val order = ArrayList<String>(4)
        if (!region.isNullOrEmpty()) order.add(region)
        order.add("Australia")
        order.add("UK")
        order.add("Europe")

        for (r in order) {
            if (infos.any { it.second.regions.containsKey(r) }) {
                val inds = mergedIndicators(infos, r)
                if (inds.isNotEmpty()) return result(key, idInfo, r, region, inds, mergedFrom)
            }
        }

        // Any remaining region with actual data, in first-seen order.
        val seen = LinkedHashSet<String>()
        for ((_, inf) in infos) seen.addAll(inf.regions.keys)
        for (r in seen) {
            val inds = mergedIndicators(infos, r)
            if (inds.isNotEmpty()) return result(key, idInfo, r, region, inds, mergedFrom)
        }

        // Species known, but no indicator rows anywhere.
        return null
    }

    private fun mergedIndicators(
        infos: List<Pair<String, Species>>,
        region: String,
    ): LinkedHashMap<String, String> {
        val out = LinkedHashMap<String, String>()
        for ((_, inf) in infos) {
            val inds = inf.regions[region] ?: continue
            for ((ik, iv) in inds) {
                if (iv.isEmpty() || iv.trim().isEmpty()) continue
                if (!out.containsKey(ik)) out[ik] = iv // canonical-first sibling wins
            }
        }
        return out
    }

    private fun result(
        key: String,
        idInfo: Species,
        region: String,
        requestedRegion: String?,
        indicators: LinkedHashMap<String, String>,
        mergedFrom: List<String>,
    ): IndicatorResult = IndicatorResult(
        scientificName = idInfo.scientificName,
        commonNames = mergedCommonNames(mergedFrom),
        region = region,
        requestedRegion = requestedRegion,
        regionFallback = !requestedRegion.isNullOrEmpty() && region != requestedRegion,
        indicators = indicators,
        source = idInfo.sources[region] ?: "",
        canonicalKey = key,
        mergedFrom = mergedFrom,
    )

    /** `SpeciesDB._merged_common_names` — dedup case-insensitively, order kept. */
    private fun mergedCommonNames(keys: List<String>): List<String> {
        val out = ArrayList<String>()
        val seen = HashSet<String>()
        for (k in keys) {
            for (cn in species[k]?.commonNames ?: emptyList<String>()) {
                if (seen.add(cn.lowercase())) out.add(cn)
            }
        }
        return out
    }

    // ── search ───────────────────────────────────────────────────────────────

    /**
     * `SpeciesDB.search` — picker-grade name resolution.
     *
     * Six steps, in Python's order: exact scientific, exact common, partial
     * scientific, partial common, fuzzy scientific, fuzzy common. Common names
     * are matched hard because non-technical users type them, but a hit that
     * rests only on a generic token ("khaki weed" vs "onion weed") is rejected —
     * see [GENERIC_TOKENS]. Plural/singular stems are tried ("docks" → "dock").
     *
     * Fuzzy scoring is CPython's `difflib.SequenceMatcher.ratio` ported exactly
     * (including `autojunk`), so scores match Python's to the digit.
     */
    fun search(query: String, limit: Int = 5): List<SpeciesMatch> {
        val queryLower = query.trim().lowercase()
        if (queryLower.isEmpty()) return emptyList()

        // "docks" → "dock", "thistles" → "thistle", "cherries" → "cherry".
        val stem: String? = when {
            queryLower.endsWith("ies") && queryLower.length > 4 ->
                queryLower.substring(0, queryLower.length - 3) + "y"
            queryLower.endsWith("s") && queryLower.length > 3 && !queryLower.endsWith("ss") ->
                queryLower.substring(0, queryLower.length - 1)
            else -> null
        }
        val variants = if (stem != null) listOf(queryLower, stem) else listOf(queryLower)

        val results = ArrayList<SpeciesMatch>()

        // 1. Exact scientific name.
        species[queryLower]?.let {
            results.add(SpeciesMatch(it.scientificName, it.commonNames, "exact_scientific", 1.0, queryLower))
        }

        // 2. Exact common name.
        commonIndex[queryLower]?.let { key ->
            if (results.none { it.key == key }) {
                val info = species[key]!!
                results.add(SpeciesMatch(info.scientificName, info.commonNames, "exact_common", 1.0, key))
            }
        }

        // 3. Partial scientific name (name in query OR query in name).
        if (results.size < limit) {
            for (v in variants) {
                for (name in scientificNames) {
                    val nameLower = name.lowercase()
                    if (!(nameLower.contains(v) || v.contains(nameLower))) continue
                    val key = sciNameToKey[nameLower] ?: continue // KNOWN_PYTHON_BUGS #1
                    if (results.any { it.key == key }) continue
                    val info = species[key] ?: continue
                    val matchLen = nameLower.length
                    val score = minOf(0.9, 0.6 + (matchLen.toDouble() / maxOf(v.length, 1)) * 0.3)
                    results.add(SpeciesMatch(info.scientificName, info.commonNames, "partial_scientific", round2(score), key))
                }
            }
        }

        // 4. Partial common name. Guard: a match resting only on a generic token
        //    is a false friend and is rejected.
        if (results.size < limit) {
            for (v in variants) {
                for ((cnLower, key) in commonIndex) {
                    if (!(cnLower.contains(v) || v.contains(cnLower))) continue
                    if (results.any { it.key == key }) continue
                    if ((contentTokens(v) intersect contentTokens(cnLower)).isEmpty()) continue
                    val info = species[key] ?: continue
                    val score = minOf(0.85, 0.55 + (cnLower.length.toDouble() / maxOf(v.length, 1)) * 0.3)
                    results.add(SpeciesMatch(info.scientificName, info.commonNames, "partial_common", round2(score), key))
                }
            }
        }

        // 5. Fuzzy scientific name. Long queries are skipped: fuzzy matching on
        //    sentences produces unreliable false positives. Scored by token
        //    overlap as well as edit distance so "sow thistle" cannot beat
        //    "sonchus" on edit distance alone.
        if (results.size < limit && queryLower.length <= 40) {
            val want = maxOf(limit - results.size, 3)
            val possibilities = scientificNames.map { it.lowercase() }
            for (match in getCloseMatches(queryLower, possibilities, want, 0.6)) {
                if (results.any { it.key == match }) continue
                val key = sciNameToKey[match] ?: continue // KNOWN_PYTHON_BUGS #1
                val info = species[key] ?: continue
                val seq = SequenceMatcher.ratio(queryLower, match)
                val tok = tokenOverlap(queryLower, match)
                results.add(SpeciesMatch(info.scientificName, info.commonNames, "fuzzy_scientific", round2(0.5 * seq + 0.5 * tok), key))
            }
        }

        // 6. Fuzzy common name — catches vernacular names the DB never learned.
        //    Guarded by content-token overlap so generic filler cannot match.
        if (results.size < limit && queryLower.length <= 40) {
            val qTokens = contentTokens(queryLower)
            if (qTokens.isNotEmpty()) {
                val best = ArrayList<ScoredCommonName>()
                for ((cnLower, key) in commonIndex) {
                    if (results.any { it.key == key }) continue
                    val cnTokens = contentTokens(cnLower)
                    if (cnTokens.isEmpty() || (qTokens intersect cnTokens).isEmpty()) continue
                    val seq = SequenceMatcher.ratio(queryLower, cnLower)
                    val tok = (qTokens intersect cnTokens).size.toDouble() /
                        maxOf(qTokens.size, cnTokens.size)
                    if (seq >= 0.6 || tok >= 0.5) best.add(ScoredCommonName(0.5 * seq + 0.5 * tok, key, cnLower))
                }
                // Python: sorted(best, reverse=True) — tuple order, descending.
                best.sortWith(
                    compareByDescending<ScoredCommonName> { it.score }
                        .thenByDescending { it.key }
                        .thenByDescending { it.commonName }
                )
                for (b in best.take(limit - results.size)) {
                    val info = species[b.key]!!
                    results.add(
                        SpeciesMatch(
                            info.scientificName, info.commonNames, "fuzzy_common",
                            round2(minOf(b.score, 0.85)), b.key,
                        )
                    )
                }
            }
        }

        return if (results.size > limit) ArrayList(results.subList(0, limit)) else results
    }

    private class ScoredCommonName(val score: Double, val key: String, val commonName: String)

    /**
     * `AuguryFunnel._best_plant_match` — the top match, preferring real species
     * over pseudo-species and junk. Deliberately does **not** promote a genus
     * bucket to a species: "soursob" must stay *Oxalis spp.*, not become
     * *Oxalis acetosella* (a European wood-sorrel).
     */
    fun bestPlantMatch(query: String): SpeciesMatch? {
        if (query.isBlank()) return null
        val queryLower = query.trim().lowercase()
        val matches = search(query, 5)
        if (matches.isEmpty()) return null
        if (queryLower in CLAY_PSEUDO_SPECIES) return matches[0]
        return matches.firstOrNull { it.key !in CLAY_PSEUDO_SPECIES && classifySpecificity(it.key) != "junk" }
    }

    /**
     * Resolve one supplied species name end to end, as the funnel does for a
     * single name: match the query, re-match on the matched scientific name
     * (`AuguryFunnel.resolve` searches by `scientific_name`), then look the
     * indicators up by key.
     *
     * Returns `null` when nothing scores >= 0.5 or when the species carries no
     * indicator rows.
     */
    fun resolveQuery(query: String, region: String? = null): ResolvedSpecies? {
        val whole = bestPlantMatch(query) ?: return null
        if (whole.score < 0.5) return null
        val match = bestPlantMatch(whole.scientificName) ?: return null
        if (match.score < 0.5) return null
        val info = getIndicators(match.key, region) ?: return null
        return ResolvedSpecies(
            info,
            MatchInfo(query, match.matchType, match.score, classifySpecificity(match.key), match.key),
        )
    }

    /** Instance alias so call sites can read naturally; same logic as the companion. */
    fun specificityOf(key: String?): String = classifySpecificity(key)

    // ── generic-token guards (SpeciesDB.GENERIC_TOKENS) ──────────────────────

    private val GENERIC_TOKENS = setOf(
        "weed", "weeds", "grass", "grasses", "thistle", "thistles", "dock",
        "docks", "sedge", "rush", "rushes", "clover", "plant", "plants",
        "common", "wild", "native", "annual", "perennial", "black", "red",
        "white", "yellow", "blue", "purple", "giant", "creeping", "spiny",
        "prickly", "slender", "small", "large", "water", "marsh", "swamp",
        "couch", "brome", "fescue", "sorrel", "burr", "bur", "cress",
    )

    private val TOKEN_RE = Regex("[a-z0-9]+")

    /** `SpeciesDB._content_tokens` — alphanumeric tokens minus generic filler. */
    private fun contentTokens(text: String?): Set<String> =
        TOKEN_RE.findAll((text ?: "").lowercase())
            .map { it.value }
            .filter { it !in GENERIC_TOKENS && it.length > 2 }
            .toSet()

    /** `SpeciesDB._token_overlap`. */
    private fun tokenOverlap(a: String, b: String): Double {
        val ta = contentTokens(a)
        val tb = contentTokens(b)
        if (ta.isEmpty() || tb.isEmpty()) return 0.0
        return (ta intersect tb).size.toDouble() / maxOf(ta.size, tb.size)
    }

    private fun getCloseMatches(
        word: String,
        possibilities: List<String>,
        n: Int,
        cutoff: Double,
    ): List<String> {
        val result = ArrayList<Pair<Double, String>>()
        for (x in possibilities) {
            val r = SequenceMatcher.ratio(x, word)
            if (r >= cutoff) result.add(r to x)
        }
        result.sortWith(
            compareByDescending<Pair<Double, String>> { it.first }.thenByDescending { it.second }
        )
        return result.take(n).map { it.second }
    }

    /** Python's `round(x, 2)`: correct rounding of the binary double, half-to-even. */
    private fun round2(value: Double): Double =
        BigDecimal(value).setScale(2, RoundingMode.HALF_EVEN).toDouble()

    /** Documented Python defects this port works around. Reported, not fixed upstream. */
    val KNOWN_PYTHON_BUGS: List<String> = listOf(
        "species_lookup.search() step 5 uses the lowercased scientific name as a DB " +
            "key; augury-ondevice.json has 5 species where key != scientific_name.lower(), " +
            "which raises KeyError there. This port indexes scientific names explicitly.",
        "species_lookup._sanitize() deletes junk keys, but the shipped app DB keeps and " +
            "tags them; this port follows the app DB and filters at match time.",
    )
}

// ─────────────────────────────────────────────────────────────────────────────
// difflib port — CPython Lib/difflib.py SequenceMatcher, isjunk=None, autojunk=True
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Exact port of `difflib.SequenceMatcher.ratio` for the `isjunk=None` case used
 * by `species_lookup.search`. `quick_ratio`/`real_quick_ratio` are upper bounds
 * used only as prefilters by `get_close_matches`, so omitting them cannot change
 * which candidates pass the cutoff. `autojunk` is implemented because it *can*
 * change the result for long strings.
 */
internal object SequenceMatcher {

    fun ratio(a: String, b: String): Double {
        val matches = matchingBlocksSize(a, b)
        val total = a.length + b.length
        return if (total == 0) 1.0 else 2.0 * matches / total
    }

    private fun chainB(b: String): HashMap<Char, MutableList<Int>> {
        val b2j = HashMap<Char, MutableList<Int>>()
        for (i in b.indices) {
            val list = b2j.getOrPut(b[i]) { ArrayList() }
            list.add(i)
        }
        val n = b.length
        if (n >= 200) { // autojunk
            val ntest = n / 100 + 1
            val popular = b2j.filterValues { it.size > ntest }.keys.toList()
            for (elt in popular) b2j.remove(elt)
        }
        return b2j
    }

    /** Sum of `get_matching_blocks()` block sizes — `ratio` only needs the total. */
    private fun matchingBlocksSize(a: String, b: String): Int {
        val b2j = chainB(b)
        // Python pops from a list (LIFO); the total is order-independent.
        val queue = ArrayDeque<IntArray>()
        queue.addLast(intArrayOf(0, a.length, 0, b.length))
        var total = 0
        while (queue.isNotEmpty()) {
            val q = queue.removeLast()
            val alo = q[0]; val ahi = q[1]; val blo = q[2]; val bhi = q[3]
            val m = findLongestMatch(a, b, b2j, alo, ahi, blo, bhi)
            val i = m[0]; val j = m[1]; val k = m[2]
            if (k > 0) {
                total += k
                if (alo < i && blo < j) queue.addLast(intArrayOf(alo, i, blo, j))
                if (i + k < ahi && j + k < bhi) queue.addLast(intArrayOf(i + k, ahi, j + k, bhi))
            }
        }
        return total
    }

    /** `SequenceMatcher.find_longest_match` (returns i, j, size). */
    private fun findLongestMatch(
        a: String,
        b: String,
        b2j: HashMap<Char, MutableList<Int>>,
        alo: Int,
        ahi: Int,
        blo: Int,
        bhi: Int,
    ): IntArray {
        var besti = alo
        var bestj = blo
        var bestsize = 0
        var j2len = HashMap<Int, Int>()
        for (i in alo until ahi) {
            val newj2len = HashMap<Int, Int>()
            for (j in b2j[a[i]] ?: emptyList<Int>()) {
                if (j < blo) continue
                if (j >= bhi) break
                val k = (j2len[j - 1] ?: 0) + 1
                newj2len[j] = k
                if (k > bestsize) {
                    besti = i - k + 1
                    bestj = j - k + 1
                    bestsize = k
                }
            }
            j2len = newj2len
        }
        // isjunk is None, so none of b is junk: only the two plain extensions run.
        while (besti > alo && bestj > blo && a[besti - 1] == b[bestj - 1]) {
            besti--; bestj--; bestsize++
        }
        while (besti + bestsize < ahi && bestj + bestsize < bhi &&
            a[besti + bestsize] == b[bestj + bestsize]
        ) {
            bestsize++
        }
        return intArrayOf(besti, bestj, bestsize)
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Minimal JSON reader (no android.org.json, no third-party dependency)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * A small recursive-descent JSON parser.
 *
 * The port must stay free of `android.*` types so it can be unit-tested on the
 * JVM without Robolectric, and `org.json` is an Android framework class. The
 * database is plain JSON (objects, arrays, strings, numbers, booleans, null), so
 * a self-contained reader is both sufficient and dependency-free.
 *
 * Objects come back as [LinkedHashMap] and arrays as [ArrayList], preserving the
 * document order the Python port relies on (common-name precedence, region
 * order, canonical map iteration).
 */
internal object Json {

    fun parse(text: String): Any? {
        val p = Parser(text)
        p.skipWhitespace()
        val value = p.readValue()
        p.skipWhitespace()
        require(p.atEnd()) { "trailing content at offset ${p.offset}" }
        return value
    }

    private class Parser(private val s: String) {
        var offset = 0
        fun atEnd() = offset >= s.length
        fun skipWhitespace() {
            while (offset < s.length && (s[offset] == ' ' || s[offset] == '\t' ||
                    s[offset] == '\n' || s[offset] == '\r')
            ) offset++
        }

        fun readValue(): Any? {
            require(!atEnd()) { "unexpected end of JSON" }
            return when (s[offset]) {
                '{' -> readObject()
                '[' -> readArray()
                '"' -> readString()
                't' -> { expect("true"); true }
                'f' -> { expect("false"); false }
                'n' -> { expect("null"); null }
                else -> readNumber()
            }
        }

        private fun expect(literal: String) {
            require(s.startsWith(literal, offset)) { "expected $literal at $offset" }
            offset += literal.length
        }

        private fun readObject(): LinkedHashMap<String, Any?> {
            val out = LinkedHashMap<String, Any?>()
            offset++ // '{'
            skipWhitespace()
            if (!atEnd() && s[offset] == '}') { offset++; return out }
            while (true) {
                skipWhitespace()
                val key = readString()
                skipWhitespace()
                require(!atEnd() && s[offset] == ':') { "expected ':' at $offset" }
                offset++
                skipWhitespace()
                out[key] = readValue()
                skipWhitespace()
                require(!atEnd()) { "unterminated object" }
                when (s[offset]) {
                    ',' -> offset++
                    '}' -> { offset++; return out }
                    else -> throw IllegalArgumentException("expected ',' or '}' at $offset")
                }
            }
        }

        private fun readArray(): ArrayList<Any?> {
            val out = ArrayList<Any?>()
            offset++ // '['
            skipWhitespace()
            if (!atEnd() && s[offset] == ']') { offset++; return out }
            while (true) {
                skipWhitespace()
                out.add(readValue())
                skipWhitespace()
                require(!atEnd()) { "unterminated array" }
                when (s[offset]) {
                    ',' -> offset++
                    ']' -> { offset++; return out }
                    else -> throw IllegalArgumentException("expected ',' or ']' at $offset")
                }
            }
        }

        private fun readString(): String {
            require(!atEnd() && s[offset] == '"') { "expected string at $offset" }
            offset++
            val sb = StringBuilder()
            while (true) {
                require(!atEnd()) { "unterminated string" }
                when (val c = s[offset]) {
                    '"' -> { offset++; return sb.toString() }
                    '\\' -> {
                        offset++
                        require(!atEnd()) { "unterminated escape" }
                        when (val e = s[offset]) {
                            '"' -> sb.append('"')
                            '\\' -> sb.append('\\')
                            '/' -> sb.append('/')
                            'b' -> sb.append('\b')
                            'f' -> sb.append('\u000C')
                            'n' -> sb.append('\n')
                            'r' -> sb.append('\r')
                            't' -> sb.append('\t')
                            'u' -> {
                                require(offset + 4 < s.length) { "bad \\u escape" }
                                sb.append(s.substring(offset + 1, offset + 5).toInt(16).toChar())
                                offset += 4
                            }
                            else -> throw IllegalArgumentException("bad escape \\$e at $offset")
                        }
                        offset++
                    }
                    else -> { sb.append(c); offset++ }
                }
            }
        }

        private fun readNumber(): Double {
            val start = offset
            if (!atEnd() && (s[offset] == '-' || s[offset] == '+')) offset++
            while (!atEnd() && (s[offset].isDigit() || s[offset] == '.' ||
                    s[offset] == 'e' || s[offset] == 'E' || s[offset] == '-' || s[offset] == '+')
            ) offset++
            require(offset > start) { "invalid number at $start" }
            return s.substring(start, offset).toDouble()
        }
    }
}

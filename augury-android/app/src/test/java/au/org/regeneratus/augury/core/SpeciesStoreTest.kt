package au.org.regeneratus.augury.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Behavioural tests for [SpeciesStore], written against the shipped database
 * (`data/app/augury-ondevice.json`, 2,256 species) rather than against mocks.
 *
 * These pin the documented traps:
 *
 * * identity follows the **queried** key while data merges;
 * * a genus bucket is never promoted to a species ("soursob" must stay
 *   *Oxalis spp.*, not become *Oxalis acetosella*);
 * * a label defined differently on both sides of a canonical pair resolves the
 *   same way whichever name was asked first;
 * * region fallback is flagged (and disclosed downstream).
 */
class SpeciesStoreTest {

    private val store get() = AuguryTestSupport.store

    // ── specificity tagging ─────────────────────────────────────────────────

    @Test
    fun `specificity tags match augury_funnel classify_specificity`() {
        assertEquals("genus_bucket", SpeciesStore.classifySpecificity("cirsium spp"))
        assertEquals("genus_bucket", SpeciesStore.classifySpecificity("Oxalis spp."))
        assertEquals("exact_species", SpeciesStore.classifySpecificity("lantana camara"))
        assertEquals("junk", SpeciesStore.classifySpecificity("rushes excess"))
        assertEquals("exact_species", SpeciesStore.classifySpecificity(""))
        assertEquals("junk", SpeciesStore.classifySpecificity("unknown"))
        assertEquals("junk", SpeciesStore.classifySpecificity("Dandelion Clay"))
    }

    @Test
    fun `every shipped species tag agrees with the junk_keys registry`() {
        // The database carries a baked `specificity`; the port recomputes it from
        // the key + the copied JUNK_KEYS set. They must agree for all 2,256 rows.
        var checked = 0
        for (key in allKeys()) {
            val declared = AuguryTestSupport.declaredSpecificity(key)
            assertEquals("specificity for '$key'", declared, SpeciesStore.classifySpecificity(key))
            checked++
        }
        assertEquals(2256, checked)
    }

    @Test
    fun `the junk key set is exactly the one in scripts junk_keys py`() {
        assertEquals(
            setOf(
                "chicory clay", "dandelion clay", "goosegrass clay", "plantains clay",
                "fumitory loam", "rushes excess", "timothy heavy",
                "tripleurosper perforatum", "rhynchosinapi cheiranthos",
                "astrebia spp", "unknown",
            ),
            SpeciesStore.JUNK_KEYS,
        )
        // 11 = PSEUDO_SPECIES(7) + TRUNCATED_KEYS(2) + MISSPELLED_KEYS(1) + MISC_JUNK(1),
        // verified against scripts/junk_keys.py. (Was 10 — a miscount in this
        // assertion only; the set literal above always matched Python element-for-element.)
        assertEquals(11, SpeciesStore.JUNK_KEYS.size)
    }

    // ── search ──────────────────────────────────────────────────────────────

    @Test
    fun `non-technical users type common names and those resolve`() {
        val cases = mapOf(
            "capeweed" to "arctotheca calendula",
            "lantana" to "lantana camara",
            "khaki weed" to "alternanthera pungens",
            "caltrop" to "tribulus terrestris",
            "paterson's curse" to "echium plantagineum",
            "yorkshire fog" to "holcus lanatus",
            "dandelion" to "taraxacum officinale",
            "blackberry" to "rubus fruticosus",
            "soursob" to "oxalis spp.",
            "serrated tussock" to "nassella trichotoma",
        )
        for ((query, key) in cases) {
            val top = store.search(query, 1).firstOrNull()
            assertEquals("search('$query')", key, top?.key)
        }
    }

    @Test
    fun `plural and singular stems both resolve`() {
        // "docks" → stem "dock" reaches the DB key `curled dock` through the
        // *scientific* name "Curled dock" (step 3, partial_scientific, 0.9).
        assertEquals("curled dock", store.search("docks", 1).first().key)
        // CORRECTED EXPECTATION (previously "curled dock"). "dock" is not a stem
        // case: data/research/common_name_synonyms.json maps the curated synonym
        // "dock" to `rumex crispus`, so it is an exact_common hit at 1.0 and
        // outranks the 0.9 partial_scientific hit above. Measured on the reference
        // implementation over this same database:
        //   SpeciesDB.search("dock",  top_n=1) -> [('rumex crispus', 'exact_common', 1.0)]
        //   SpeciesDB.search("docks", top_n=1) -> [('curled dock', 'partial_scientific', 0.9)]
        // (Note also that search() reports the *lowercased scientific name* as a
        // hit's key in steps 3 and 5 — the fabrication recorded under
        // `known_python_bugs` in the golden fixture. For `curled dock` the key and
        // the lowercased scientific name coincide; the fixture's `prosopis spp.`
        // probe is where they visibly differ.)
        assertEquals("rumex crispus", store.search("dock", 1).first().key)
        assertEquals("cirsium spp", store.search("thistles", 1).first().key)

        // The two spellings still denote one plant — the canonical map is what
        // unifies them, which is the property this test exists to protect.
        assertEquals(
            "curled dock and its synonym target are one canonical plant",
            store.canonicalGroup(store.search("docks", 1).first().key)[0],
            store.canonicalGroup(store.search("dock", 1).first().key)[0],
        )
    }

    @Test
    fun `search is case insensitive and tolerant of partial input`() {
        assertEquals("lantana camara", store.search("LANTANA", 1).first().key)
        assertEquals("lantana camara", store.search("  Lantana  ", 1).first().key)
        assertTrue(store.search("rumex", 1).first().key.startsWith("rumex"))
        assertEquals("cirsium vulgare", store.search("cirsium vulg", 1).first().key)
    }

    @Test
    fun `generic-token false friends are rejected`() {
        // "khaki weed" must not be *answered* with "onion weed" on the word
        // "weed" alone. The guard lives in step 4 (partial common name) and in
        // `_best_plant_match`; step 5 (fuzzy scientific) deliberately has none,
        // so the reference does surface "onion weed" as a weak edit-distance hit.
        // Measured on the reference implementation over this same database:
        //   SpeciesDB.search("khaki weed", top_n=5)
        //     -> [('alternanthera pungens', 'exact_common',     1.0),
        //         ('onion weed',          'fuzzy_scientific', 0.3)]
        //   AuguryFunnel._best_plant_match("khaki weed") -> 'alternanthera pungens'
        // CORRECTED EXPECTATION (previously `"onion weed" !in keys`, which the
        // fixture — generated by the real Python — contradicts). Both halves are
        // pinned instead: the false friend may only arrive on a weak fuzzy score,
        // and the top match must never be it.
        val matches = store.search("khaki weed", 5)
        val keys = matches.map { it.key }
        assertTrue("khaki weed should resolve to Alternanthera pungens", "alternanthera pungens" in keys)

        val onion = matches.first { it.key == "onion weed" }
        assertEquals("fuzzy_scientific", onion.matchType)
        assertTrue("a generic-token false friend may only arrive on a weak score", onion.score < 0.5)

        val top = store.bestPlantMatch("khaki weed")!!
        assertEquals("khaki weed must never be answered with onion weed", "alternanthera pungens", top.key)
        assertEquals("exact_common", top.matchType)
    }

    @Test
    fun `search honours the requested limit for exact hits`() {
        assertEquals(1, store.search("lantana", 1).size)
        assertTrue(store.search("lantana", 5).size <= 5)
        assertEquals(emptyList<SpeciesStore.SpeciesMatch>(), store.search("", 5))
        assertEquals(emptyList<SpeciesStore.SpeciesMatch>(), store.search("   ", 5))
    }

    // ── specificity / genus honesty ─────────────────────────────────────────

    @Test
    fun `soursob resolves to Oxalis spp and is NOT promoted to a species`() {
        val match = store.bestPlantMatch("soursob")
        assertNotNull(match)
        assertEquals("oxalis spp.", match!!.key)
        assertEquals("genus_bucket", SpeciesStore.classifySpecificity(match.key))
        // The past regression picked Oxalis acetosella, a European wood-sorrel.
        assertFalse(match.scientificName.contains("acetosella"))

        val resolved = store.resolveQuery("soursob", "Australia")!!
        assertEquals("Oxalis spp.", resolved.scientificName)
        assertEquals("genus_bucket", resolved.specificity)
    }

    @Test
    fun `docks and thistles are genus-aware and both resolve`() {
        // The picker supplies the two names; extraction is out of scope.
        val names = listOf("docks", "thistles")
        val resolved = names.mapNotNull { store.resolveQuery(it, "Australia") }
        assertEquals(listOf("Curled dock", "Cirsium spp"), resolved.map { it.scientificName })
        assertEquals(listOf("exact_species", "genus_bucket"), resolved.map { it.specificity })
        assertTrue(resolved[1].indicators.isNotEmpty())
    }

    @Test
    fun `junk keys are never chosen by bestPlantMatch`() {
        // "dandelion" would otherwise be followed by "dandelion clay" (a UK soil
        // association, not a plant, tagged junk in the shipped DB).
        assertEquals("taraxacum officinale", store.bestPlantMatch("dandelion")!!.key)
        // "spear thistle" is a *real* DB key in this build (a canonical alias of
        // cirsium vulgare), so the reference returns it verbatim as an
        // exact_scientific hit: it is not junk, so nothing is skipped.
        //   AuguryFunnel._best_plant_match("spear thistle") -> 'spear thistle'
        //   SpeciesDB.search("spear thistle", top_n=5)[0]
        //     -> ('spear thistle', 'exact_scientific', 1.0)   [pinned by the fixture]
        // Reconciling the alias with the species is the canonical group's job,
        // never bestPlantMatch's — canonicalising here would relabel the answer
        // and break the fixture's "spear thistle", "curled dock" and "docks"
        // probes' scientific_name / resolved_keys.
        // CORRECTED EXPECTATION (previously "cirsium vulgare").
        val spear = store.bestPlantMatch("spear thistle")!!
        assertEquals("spear thistle", spear.key)
        assertEquals("exact_scientific", spear.matchType)
        assertFalse(SpeciesStore.classifySpecificity(spear.key) == "junk")
        assertEquals("cirsium vulgare", store.canonicalGroup(spear.key)[0])
        // The canonical pair stays reachable from the same query, so resolving
        // the alias to its species needs no special case in bestPlantMatch.
        val vulgare = store.search("spear thistle", 5).first { it.key == "cirsium vulgare" }
        assertEquals("partial_common", vulgare.matchType)
        assertEquals(0.85, vulgare.score, 0.0)
        // …but a user who literally pastes the association still gets an answer.
        assertEquals("dandelion clay", store.bestPlantMatch("dandelion clay")!!.key)
    }

    // ── canonical identity ──────────────────────────────────────────────────

    @Test
    fun `the canonical map is read from the shipped resource not hardcoded`() {
        val fromResource = AuguryTestSupport.canonicalMapFromResource
        assertEquals(21, fromResource.size)
        assertTrue(fromResource.containsKey("curled dock"))
        assertEquals("rumex crispus", fromResource["curled dock"])
        // …and the bundled copy is byte-identical to the source of truth.
        val bundled = SpeciesStore.resourceStream(SpeciesStore.CANONICAL_MAP_RESOURCE)!!
            .bufferedReader(Charsets.UTF_8).use { it.readText() }
        assertEquals(AuguryTestSupport.canonicalMapFile.readText(), bundled)
    }

    @Test
    fun `both members of every canonical pair resolve to the same merged rows`() {
        var pairs = 0
        for ((a, b) in AuguryTestSupport.canonicalMapFromResource) {
            val ra = store.getIndicators(a, "Australia")
            val rb = store.getIndicators(b, "Australia")
            if (ra == null || rb == null) continue // one side absent from this DB build
            pairs++
            // The Python test compares as a set of pairs because insertion order
            // "legitimately differs"; with canonical-first group ordering the port
            // produces the same order too, so assert the stronger property.
            assertEquals("indicators for '$a' vs '$b'", ra.indicators, rb.indicators)
            assertEquals("indicator order for '$a' vs '$b'",
                ra.indicators.keys.toList(), rb.indicators.keys.toList())
            assertEquals("merged_from for '$a' vs '$b'", ra.mergedFrom, rb.mergedFrom)
            assertEquals("canonical_key for '$a' vs '$b'", ra.canonicalKey, rb.canonicalKey)
            assertEquals("common_names for '$a' vs '$b'", ra.commonNames, rb.commonNames)
        }
        assertTrue("expected fragmented pairs in this DB build", pairs >= 15)
    }

    @Test
    fun `identity follows the queried key while data merges`() {
        // Asking about "thistles" must NOT relabel the answer as Cirsium vulgare:
        // that is a species claim the user never made.
        val thistles = store.getIndicators("thistles", "Australia")!!
        assertEquals("Cirsium spp", thistles.scientificName)
        assertEquals("cirsium vulgare", thistles.canonicalKey)
        assertTrue(thistles.mergedFrom.contains("cirsium vulgare"))

        val vulgare = store.getIndicators("cirsium vulgare", "Australia")!!
        assertEquals("Cirsium vulgare", vulgare.scientificName)

        // Data is identical either way; identity is not.
        assertEquals(thistles.indicators, vulgare.indicators)
        assertFalse(thistles.scientificName == vulgare.scientificName)

        // The same for a common-name alias of a real species.
        assertEquals("Curled dock", store.getIndicators("curled dock", "Australia")!!.scientificName)
        assertEquals("Rumex crispus", store.getIndicators("rumex crispus", "Australia")!!.scientificName)
    }

    @Test
    fun `the merge is stable regardless of which name was asked first`() {
        // cirsium spp and cirsium vulgare define "General indicators" differently
        // in the raw data; ordering the group canonical-first makes the merged
        // answer independent of the query.
        val a = store.getIndicators("cirsium spp", "Australia")!!
        val b = store.getIndicators("cirsium vulgare", "Australia")!!
        assertEquals(
            "High fertility, overgrazing, soil disturbance.",
            a.indicators["General indicators"],
        )
        assertEquals(a.indicators["General indicators"], b.indicators["General indicators"])
        assertEquals(a.mergedFrom, listOf("cirsium vulgare", "cirsium spp", "spear thistle"))

        // And the canonical entry always leads the group.
        assertEquals("cirsium vulgare", store.canonicalGroup("cirsium spp")[0])
        assertEquals("cirsium vulgare", store.canonicalGroup("cirsium vulgare")[0])
        assertEquals("rumex crispus", store.canonicalGroup("curled dock")[0])
    }

    @Test
    fun `merging does not drop rows from either side`() {
        val merged = store.getIndicators("curled dock", "Australia")!!
        val labels = merged.indicators.keys
        for (side in listOf("curled dock", "rumex crispus")) {
            val region = merged.region
            val raw = AuguryTestSupport.rawIndicators(side, region)
            val missing = raw.keys - labels
            assertTrue("$side lost $missing in the merge", missing.isEmpty())
        }
    }

    @Test
    fun `unfragmented species are unchanged by the merge`() {
        val r = store.getIndicators("nassella trichotoma", "Australia")!!
        assertEquals(listOf("nassella trichotoma"), r.mergedFrom)
        assertTrue(r.indicators.isNotEmpty())
    }

    // ── region policy ───────────────────────────────────────────────────────

    @Test
    fun `a region with no data falls back and says so`() {
        // Centaurea cyanus (cornflower) is UK-only in this DB build.
        val r = store.getIndicators("centaurea cyanus", "Australia")!!
        assertEquals("UK", r.region)
        assertEquals("Australia", r.requestedRegion)
        assertTrue("regionFallback must be set", r.regionFallback)
        assertTrue(r.indicators.isNotEmpty())
    }

    @Test
    fun `the requested region wins when it has data`() {
        val au = store.getIndicators("holcus lanatus", "Australia")!!
        assertEquals("Australia", au.region)
        assertFalse(au.regionFallback)
        val uk = store.getIndicators("holcus lanatus", "UK")!!
        assertEquals("UK", uk.region)
        assertFalse(uk.regionFallback)
        assertFalse("AU and UK data must differ", au.indicators == uk.indicators)
    }

    @Test
    fun `a sibling can supply the requested region`() {
        // "curled dock" itself is UK-only, but its canonical sibling rumex crispus
        // has Australian rows, so no fallback is reported.
        val r = store.getIndicators("curled dock", "Australia")!!
        assertEquals("Australia", r.region)
        assertFalse(r.regionFallback)
        assertEquals("Curled dock", r.scientificName)
    }

    @Test
    fun `unknown species and species with no rows return null`() {
        assertNull(store.getIndicators("asdfghjkl qwerty", "Australia"))
        assertNull(store.getIndicators("", "Australia"))
        // Known to the DB but carrying no indicator rows anywhere — the honest
        // no-data path that produces the deterministic refusal.
        for (key in listOf("bothriochloa macra", "cheilanthes sieberi", "glycine tabacina")) {
            assertNull("'$key' should have no usable indicators", store.getIndicators(key, "Australia"))
            assertNull("'$key' should not resolve", store.resolveQuery(key, "Australia"))
        }
    }

    // ── indicator passthrough ───────────────────────────────────────────────

    @Test
    fun `indicator values are passed through verbatim`() {
        val probes = listOf(
            "amaranthus retroflexus", "plantago major", "nassella neesiana",
            "conyza canadensis", "galium aparine",
        )
        for (key in probes) {
            val fromStore = store.getIndicators(key, "Australia")!!
            val fromJson = AuguryTestSupport.rawIndicators(key, "Australia")
            assertEquals("indicators for '$key'", fromJson, fromStore.indicators)
        }
    }

    @Test
    fun `Ph and Soil pH remain distinct keys`() {
        val r = store.getIndicators("amaranthus retroflexus", "Australia")!!
        assertTrue("expected both Ph and Soil pH", "Ph" in r.indicators && "Soil pH" in r.indicators)
        assertFalse(r.indicators["Ph"] == r.indicators["Soil pH"])
        // The two-key shape is not unique to one species either.
        val p = store.getIndicators("plantago major", "Australia")!!
        assertTrue("Ph" in p.indicators && "Soil pH" in p.indicators)
    }

    @Test
    fun `all twelve free-form indicator keys survive the port`() {
        assertEquals(
            setOf(
                "Moisture", "Fertility", "Soil pH", "Salinity", "Structure", "Ph",
                "General indicators", "Species", "Other indicators", "Disturbance",
                "Soil type", "Organic matter",
            ),
            store.indicatorKeys,
        )
    }

    // ── the app database itself ─────────────────────────────────────────────

    @Test
    fun `the shipped database is indexed as documented`() {
        assertEquals(2256, store.speciesCount)
        assertEquals(98, store.curatedSynonymCount)
        assertTrue("common-name index should be large", store.commonNameCount > 2200)
        // The bundled vernacular synonym map is the curated one, byte for byte.
        val bundled = SpeciesStore.resourceStream(SpeciesStore.SYNONYMS_RESOURCE)!!
            .bufferedReader(Charsets.UTF_8).use { it.readText() }
        assertEquals(AuguryTestSupport.synonymsFile.readText(), bundled)
    }

    // ── display names for the photo path ────────────────────────────────────

    @Test
    fun `a canonical index key resolves to the vernacular name`() {
        // The retrieval index's keys are lowercased scientific names; the confirm
        // card must show the name the audience uses, not the Latin binomial.
        assertEquals("Dandelion", store.displayNameForKey("taraxacum officinale"))
        assertEquals("Capeweed", store.displayNameForKey("arctotheca calendula"))
        assertEquals("Yarrow", store.displayNameForKey("achillea millefolium"))
    }

    @Test
    fun `every species the shipped index can return resolves to a display name`() {
        // All 173 canonical keys in index-v3 are in the database, so a null here
        // means the accessor is wrong, not the data.
        val keys = AuguryTestSupport.visionIndexKeys()
        var named = 0
        for (key in keys) {
            val name = store.displayNameForKey(key)
            assertNotNull("no display name for index key '$key'", name)
            assertTrue("blank display name for index key '$key'", name!!.isNotBlank())
            if (store.commonNamesForKey(key).isNotEmpty()) named++
        }
        assertEquals(173, keys.size)
        // 170 of the index's 173 species carry a common name in the database; the
        // three that do not fall back to its scientific spelling (tested below).
        assertEquals(170, named)
    }

    @Test
    fun `a species with no vernacular name falls back to the database's spelling`() {
        // The database's `scientific_name`, not the lowercased index key: it keeps
        // the capital the index drops, which is why this is worth a lookup at all.
        assertEquals("Cynodon dactylon", store.displayNameForKey("cynodon dactylon"))
        assertTrue(store.commonNamesForKey("cynodon dactylon").isEmpty())
    }

    @Test
    fun `the scientific spelling is the database's, not the lowercased index key`() {
        assertEquals("Cirsium vulgare", store.scientificNameForKey("cirsium vulgare"))
        assertEquals("Taraxacum officinale", store.scientificNameForKey("taraxacum officinale"))
        assertNull(store.scientificNameForKey("not a real species at all"))
    }

    @Test
    fun `the display lookup is direct, never a fuzzy search`() {
        // An unknown key must resolve to nothing rather than borrowing a similar
        // species' name onto a candidate the user is asked to confirm.
        assertNull(store.displayNameForKey("not a real species at all"))
        assertTrue(store.commonNamesForKey("").isEmpty())
        // Case and surrounding whitespace are the only normalisation applied.
        assertEquals("Dandelion", store.displayNameForKey("  Taraxacum Officinale  "))
    }

    private fun allKeys(): List<String> = AuguryTestSupport.speciesKeys()
}

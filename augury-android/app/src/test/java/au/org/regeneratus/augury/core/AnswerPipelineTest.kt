package au.org.regeneratus.augury.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * End-to-end coverage of the cases the porting brief names explicitly, through
 * [AuguryAnswerer] — the shipped entry point, not the individual helpers.
 *
 * `tests/test_funnel_behaviour.py` exists because `scripts/intent.py` shipped
 * with a green self-test that nothing imported, so a dead guard rail looked live
 * for a whole session. These tests therefore go through `answer()`.
 */
class AnswerPipelineTest {

    private val store get() = AuguryTestSupport.store
    private val composer = StoryComposer()
    private val answerer by lazy { AuguryAnswerer(store, composer) }

    private val region = "Australia"

    // ── management / advice ─────────────────────────────────────────────────

    @Test
    fun `what herbicide should I use on lantana is refused as management`() {
        val r = answerer.answer("What herbicide should I use on lantana?", listOf("lantana"), region)
        assertTrue(r.refused)
        assertEquals("management", r.refusedReason)
        assertEquals("management", r.intent)
        assertEquals(emptyList<String>(), r.species)
        assertTrue(r.response.contains("management, herbicide or dosing advice"))
        // The species resolves perfectly well — that must not rescue the answer.
        assertNotNull(store.resolveQuery("lantana", region))
    }

    @Test
    fun `what does lime-loving capeweed indicate answers normally`() {
        val r = answerer.answer("What does lime-loving capeweed indicate?", listOf("capeweed"), region)
        assertFalse("an explicit indicator question wins over incidental advice vocabulary", r.refused)
        assertEquals("indicator", r.intent)
        assertNull(r.refusedReason)
        assertEquals(listOf("Arctotheca calendula"), r.species)
        assertTrue(r.response.contains("Capeweed"))
    }

    @Test
    fun `every python management probe declines through the entry point`() {
        val management = listOf(
            "What herbicide should I use on lantana?" to listOf("lantana"),
            "Can you recommend a spray for capeweed?" to listOf("capeweed"),
            "Should I lime my paddock to fix acidity?" to listOf("capeweed"),
            "How do I kill serrated tussock?" to listOf("serrated tussock"),
            "What's the best way to control blackberry?" to listOf("blackberry"),
            "How much glyphosate per hectare?" to emptyList(),
            "Should I apply urea to the paddock?" to emptyList(),
        )
        for ((q, supplied) in management) {
            val r = answerer.answer(q, supplied, region)
            assertTrue("'$q' was answered: ${r.response.take(60)}", r.refused)
            assertEquals("'$q' reason", "management", r.refusedReason)
            assertEquals("'$q' intent", "management", r.intent)
            assertEquals("'$q' species", emptyList<String>(), r.species)
        }
    }

    // ── refusals that are not about intent ──────────────────────────────────

    @Test
    fun `an empty message is refused deterministically`() {
        for (message in listOf("", "   ", "\n")) {
            val r = answerer.answer(message, listOf("lantana"), region)
            assertTrue(r.refused)
            assertEquals("empty", r.refusedReason)
            assertEquals("other", r.intent)
            assertEquals(emptyList<String>(), r.species)
            assertEquals(StoryComposer.EMPTY_MESSAGE_RESPONSE, r.response)
        }
    }

    @Test
    fun `a species with no indicators refuses deterministically`() {
        // NOTE: the brief named Nassella trichotoma as the no-indicator example,
        // but in data/app/augury-ondevice.json it carries seven indicator keys
        // (see `nassella trichotoma does carry indicators in this database
        // build`). These four are the species that genuinely carry none.
        for (key in listOf("bothriochloa macra", "cheilanthes sieberi", "glycine tabacina", "chloris truncata")) {
            val r = answerer.answer(key, listOf(key), region)
            assertTrue("'$key' should be refused", r.refused)
            assertEquals("'$key' reason", "no_species", r.refusedReason)
            assertEquals("'$key' species", emptyList<String>(), r.species)
            assertEquals(StoryComposer.NO_SPECIES_RESPONSE, r.response)
        }
    }

    @Test
    fun `nassella trichotoma does carry indicators in this database build`() {
        // Recorded because the brief's premise does not hold for the shipped DB:
        // serrated tussock is fully populated, so it answers rather than refusing.
        val r = answerer.answer("serrated tussock", listOf("serrated tussock"), region)
        assertFalse(r.refused)
        assertEquals(listOf("Nassella trichotoma"), r.species)
        assertTrue(r.response.contains("📋 **Soil pH:**"))
    }

    @Test
    fun `an unrecognised name refuses with no species`() {
        val r = answerer.answer("asdfghjkl qwerty", listOf("asdfghjkl qwerty"), region)
        assertTrue(r.refused)
        assertEquals("no_species", r.refusedReason)
        assertEquals(StoryComposer.NO_SPECIES_RESPONSE, r.response)
    }

    // ── multi-species and disclosures ───────────────────────────────────────

    @Test
    fun `docks and thistles renders both and discloses the genus-level match`() {
        val r = answerer.answer("I have docks and thistles in my paddock", listOf("docks", "thistles"), region)
        assertFalse(r.refused)
        assertEquals(listOf("Curled dock", "Cirsium spp"), r.species)
        assertTrue("both species must be rendered", r.response.contains("**Curled dock"))
        assertTrue("both species must be rendered", r.response.contains("**Spear thistle"))
        assertTrue("the genus-level match must be disclosed", r.response.contains("genus-level match"))
        assertEquals(
            listOf("exact_species", "genus_bucket"),
            r.matches.map { it.specificity },
        )
    }

    @Test
    fun `soursob stays a genus-level answer and is never promoted`() {
        val r = answerer.answer("soursob", listOf("soursob"), region)
        assertFalse(r.refused)
        assertEquals(listOf("Oxalis spp."), r.species)
        assertEquals("genus_bucket", r.matches.single().specificity)
        assertTrue(r.response.contains("genus-level match"))
        assertFalse("must not become a European wood-sorrel", r.response.contains("acetosella"))
    }

    @Test
    fun `a region fallback is disclosed in the visible text`() {
        val r = answerer.answer("cornflower", listOf("centaurea cyanus"), region)
        assertFalse(r.refused)
        assertTrue("the flag must be set", r.resolved.single().regionFallback)
        assertEquals("UK", r.resolved.single().region)
        assertTrue(
            "silence here is the failure mode: ${r.response.takeLast(200)}",
            r.response.contains("no Australia indicator data for Centaurea cyanus"),
        )
        assertTrue(r.response.contains("showing UK data instead"))
        assertTrue(r.response.contains("it was not recorded for Australia"))
    }

    @Test
    fun `species-level answers carry no genus note`() {
        for (name in listOf("serrated tussock", "paterson's curse", "lantana", "caltrop")) {
            val r = answerer.answer(name, listOf(name), region)
            assertFalse("'$name' should resolve", r.refused)
            assertFalse("'$name' must not be labelled genus-level", r.response.contains("genus-level"))
        }
    }

    // ── grounding guard rail through the pipeline ───────────────────────────

    @Test
    fun `a model draft with an invented number is repaired and reported`() {
        val facts = store.resolveQuery("dandelion", region)!!
        val modelDraft = "Dandelion indicates acidic conditions, likely below 6.5"
        val r = answerer.answer("what does dandelion indicate?", listOf("dandelion"), region, modelText = modelDraft)

        assertFalse(r.refused)
        assertEquals(listOf("Taraxacum officinale"), r.species)
        assertFalse("the invented number must not reach the user", r.response.contains("6.5"))
        assertTrue(r.response.contains("Dandelion indicates acidic conditions."))
        assertEquals(1, r.groundingRepairs.size)
        assertEquals("neutralised", r.groundingRepairs[0].action)
        assertEquals(listOf("6.5"), r.groundingRepairs[0].removed)
        // The facts used for the check are the ones injected, and they contain no
        // number at all — that is exactly why 6.5 is unsupported.
        assertTrue(composer.factLines(listOf(facts)).none { Grounding.payloadNumbers(listOf(it)).isNotEmpty() })
    }

    @Test
    fun `template mode never reports a repair`() {
        val r = answerer.answer("dandelion", listOf("dandelion"), region)
        assertFalse(r.refused)
        assertEquals(emptyList<Grounding.GroundingRepair>(), r.groundingRepairs)
    }

    // ── contract shape ──────────────────────────────────────────────────────

    @Test
    fun `the payload mirrors the python answer dict`() {
        val r = answerer.answer("what does dandelion indicate?", listOf("dandelion"), region)
        assertNotNull(r.response)
        assertEquals(1, r.species.size)
        assertEquals(1, r.matches.size)
        assertFalse(r.refused)
        assertNull(r.refusedReason)
        assertEquals("indicator", r.intent)
        assertEquals(emptyList<Grounding.GroundingRepair>(), r.groundingRepairs)
        // matches carry the resolve() provenance the Python attaches.
        val m = r.matches.single()
        assertEquals("dandelion", m.query)
        assertEquals("exact_scientific", m.matchType)
        assertEquals(1.0, m.score, 0.0)
        assertEquals("exact_species", m.specificity)
        assertEquals("taraxacum officinale", m.key)
    }
}

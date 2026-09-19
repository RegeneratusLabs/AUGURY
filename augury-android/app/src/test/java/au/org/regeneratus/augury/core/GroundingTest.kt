package au.org.regeneratus.augury.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * `scripts/grounding.py` — the structural grounding guard rail.
 *
 * The case that makes this module mandatory is reproduced verbatim from the
 * field test: running the real GGUF with the real prompt, on facts containing
 * `Soil pH: neutral to slightly acidic`, the model produced
 *
 *     "Dandelion indicates acidic conditions, likely below 6.5"
 *
 * "6.5" appears nowhere in the injected facts. That is an invented number, and
 * this module is what neutralises it.
 *
 * The port is asserted against fixtures produced by the real Python
 * (`tools/emit_golden_fixtures.py`), not against a hand-written expectation.
 */
class GroundingTest {

    @Test
    fun `the field-test hallucination is neutralised and reported`() {
        val facts = listOf("Soil pH: neutral to slightly acidic")
        val invented = "Dandelion indicates acidic conditions, likely below 6.5"

        // It is genuinely unsupported: the facts carry no number at all.
        val report = Grounding.verify(invented, facts)
        assertFalse("the facts contain no numbers at all", report.clean)
        assertEquals(listOf("6.5"), report.unsupportedValues)
        assertEquals(emptyList<String>(), report.payloadValues)

        val (cleaned, events) = Grounding.repair(invented, facts)
        assertFalse("the invented threshold must not survive", cleaned.contains("6.5"))
        assertTrue(
            "the true qualitative claim must survive",
            cleaned.contains("Dandelion indicates acidic conditions"),
        )
        assertEquals(listOf(Grounding.GroundingRepair(
            action = "neutralised",
            removed = listOf("6.5"),
            before = invented,
            after = "Dandelion indicates acidic conditions.",
        )), events)
    }

    @Test
    fun `a number that IS in the facts is left completely alone`() {
        val facts = listOf("Ph: wide (pH 5.0-9.0)")
        val answer = "Prickly acacia tolerates a pH range of 5.0-9.0, so it is not a pH indicator."
        val report = Grounding.verify(answer, facts)
        assertTrue(report.clean)
        assertEquals(listOf("5.0", "9.0"), report.payloadValues)
        val (cleaned, events) = Grounding.repair(answer, facts)
        assertEquals("a clean answer must be returned byte-identical", answer, cleaned)
        assertEquals(emptyList<Grounding.GroundingRepair>(), events)
    }

    @Test
    fun `only the sentence carrying the invented number is touched`() {
        val facts = listOf("Moisture: dry soils")
        val answer = "Docks indicate dry soils. Apply 400 mm of water."
        val (cleaned, events) = Grounding.repair(answer, facts)
        assertTrue("the supported sentence survives", cleaned.startsWith("Docks indicate dry soils."))
        assertFalse(cleaned.contains("400"))
        assertEquals(1, events.size)
        // Neutralising cannot help (there is no threshold to rewrite), stripping
        // leaves fewer than 4 words, so Python drops the sentence.
        assertEquals("dropped_sentence", events[0].action)
        assertEquals(listOf("400"), events[0].removed)
    }

    @Test
    fun `python's own string-mangling behaviour is reproduced not corrected`() {
        // KNOWN PYTHON BEHAVIOUR, reported and deliberately not "fixed": both
        // _neutralise regexes consume the leading whitespace of the clause but
        // leave the following word glued to its neighbour, so "a pH below 6.0 in
        // most situations" neutralises to "a pHin most situations". A faithful
        // port reproduces it; the fixture is generated from the real module.
        val facts = listOf("Moisture: dry, well-drained soils", "Fertility: low fertility")
        val answer = "Docks indicate dry, well-drained soils with low fertility. " +
            "They prefer a pH below 6.0 in most situations. Thistles indicate overgrazing."
        val (cleaned, _) = Grounding.repair(answer, facts)
        assertEquals(
            "Docks indicate dry, well-drained soils with low fertility. " +
                "They prefer a pHin most situations. Thistles indicate overgrazing.",
            cleaned,
        )
        // The invented number itself is still gone, which is what matters.
        assertFalse(cleaned.contains("6.0"))
    }

    @Test
    fun `every grounding probe matches the python module`() {
        var compared = 0
        for (probe in AuguryTestSupport.goldenList("grounding_probes")) {
            val id = AuguryTestSupport.str(probe["id"])!!
            val facts = AuguryTestSupport.strings(probe["facts"])
            val answer = AuguryTestSupport.str(probe["answer"])!!

            val (cleaned, events) = Grounding.repair(answer, facts)
            assertEquals("[$id] cleaned text", AuguryTestSupport.str(probe["cleaned"]), cleaned)
            assertEquals("[$id] repair event count", AuguryTestSupport.list(probe["events"]).size, events.size)
            AuguryTestSupport.list(probe["events"]).forEachIndexed { i, raw ->
                val e = AuguryTestSupport.map(raw)
                assertEquals("[$id] event $i action", AuguryTestSupport.str(e["action"]), events[i].action)
                assertEquals("[$id] event $i removed", AuguryTestSupport.strings(e["removed"]), events[i].removed)
                assertEquals("[$id] event $i before", AuguryTestSupport.str(e["before"]), events[i].before)
                assertEquals("[$id] event $i after", AuguryTestSupport.str(e["after"]), events[i].after)
            }

            val verify = AuguryTestSupport.map(probe["verify"])
            val report = Grounding.verify(answer, facts)
            assertEquals("[$id] supported", AuguryTestSupport.strings(verify["supported"]), report.supported)
            assertEquals("[$id] unsupported_values", AuguryTestSupport.strings(verify["unsupported_values"]), report.unsupportedValues)
            assertEquals("[$id] payload_values", AuguryTestSupport.strings(verify["payload_values"]), report.payloadValues)
            assertEquals("[$id] clean", AuguryTestSupport.bool(verify["clean"]), report.clean)
            assertEquals("[$id] unsupported claim count", AuguryTestSupport.list(verify["unsupported"]).size, report.unsupported.size)
            compared++
        }
        assertEquals("expected all 8 grounding probes in the fixture", 8, compared)
    }

    @Test
    fun `numeric claims carry their context for auditing`() {
        val claims = Grounding.extractNumericClaims("Lantana indicates acidic conditions, likely below 6.5")
        assertEquals(1, claims.size)
        assertEquals("6.5", claims[0].value)
        assertTrue(claims[0].context.contains("likely below 6.5"))
        assertEquals(claims[0].end - claims[0].start, "6.5".length)
    }

    @Test
    fun `sentence splitting matches python`() {
        assertEquals(
            listOf("One.", "Two!", "Three?"),
            Grounding.sentences("One. Two!  Three?"),
        )
        assertEquals(emptyList<String>(), Grounding.sentences("   "))
    }
}

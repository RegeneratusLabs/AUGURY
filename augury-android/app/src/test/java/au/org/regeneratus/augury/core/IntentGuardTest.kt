package au.org.regeneratus.augury.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * `scripts/intent.py` behaviour, including the 14 probes from that module's own
 * `__main__` self-test and the deliberate precedence rule: **an explicit
 * indicator question wins over the management classifier**.
 *
 * The regression this pins (from `tests/test_funnel_behaviour.py`): intent.py
 * shipped with a green self-test but was never imported, so through the real
 * entry point "What herbicide should I use on lantana?" returned a lantana soil
 * story.
 */
class IntentGuardTest {

    /** Python's `probes` list, verbatim. */
    private val pythonProbes = listOf(
        "What herbicide should I use on lantana?" to "management",
        "Can you recommend a spray for capeweed?" to "management",
        "Should I lime my paddock to fix acidity?" to "management",
        "How do I kill serrated tussock?" to "management",
        "What's the best way to control blackberry?" to "management",
        "How much glyphosate per hectare?" to "management",
        "Should I apply urea to the paddock?" to "management",
        "what does dandelion indicate about my soil?" to "indicator",
        "I have docks and thistles in my paddock" to "other",
        "What does capeweed tell me about my soil?" to "indicator",
        "Tell me about quantum physics" to "other",
        "asdfghjkl" to "other",
        "" to "other",
        "What does lime-loving capeweed indicate?" to "indicator",
    )

    @Test
    fun `intent py self-test probes all classify identically`() {
        val bad = pythonProbes.filter { (q, want) -> IntentGuard.classify(q) != want }
        assertEquals("probes classified differently from intent.py: $bad", emptyList<Pair<String, String>>(), bad)
    }

    @Test
    fun `indicator question wins over incidental management vocabulary`() {
        // The documented precedence. "lime" is in MANAGEMENT_RE; "indicate" is in
        // INDICATOR_RE, and the indicator check runs first.
        assertEquals(IntentGuard.INDICATOR, IntentGuard.classify("What does lime-loving capeweed indicate?"))
        assertTrue(Regex("lime", RegexOption.IGNORE_CASE).containsMatchIn("What does lime-loving capeweed indicate?"))
    }

    @Test
    fun `management request with a resolvable species is still management`() {
        // "lantana" resolves perfectly well in the database; that must not save it.
        assertEquals(IntentGuard.MANAGEMENT, IntentGuard.classify("What herbicide should I use on lantana?"))
    }

    @Test
    fun `empty and whitespace-only messages are other`() {
        assertEquals(IntentGuard.OTHER, IntentGuard.classify(null))
        assertEquals(IntentGuard.OTHER, IntentGuard.classify(""))
        assertEquals(IntentGuard.OTHER, IntentGuard.classify("   \n\t "))
    }

    @Test
    fun `decline response matches the python refusal text`() {
        val expected = "I can only tell you what weeds indicate about your soil — I don't give " +
            "management, herbicide or dosing advice.\n\n" +
            "If you tell me which weeds you're seeing, I'll explain what they suggest " +
            "about moisture, pH, fertility, structure and salinity."
        assertEquals(expected, IntentGuard.declineResponse("management"))
        // Any non-management kind falls through to the generic refusal.
        assertTrue(IntentGuard.declineResponse("other").startsWith("I can only help with what weeds"))
    }

    @Test
    fun `decline text offers a redirect rather than a dead end`() {
        val low = IntentGuard.declineResponse("management").lowercase()
        assertTrue("decline should name what it won't do", "herbicide" in low || "management" in low)
        assertTrue("decline should redirect to indicators", "indicate" in low || "soil" in low)
    }

    @Test
    fun `tell me about quantum physics is not an indicator question`() {
        // INDICATOR_RE's negative lookahead exists for exactly this.
        assertEquals(IntentGuard.OTHER, IntentGuard.classify("Tell me about quantum physics"))
        assertEquals(IntentGuard.INDICATOR, IntentGuard.classify("Tell me about capeweed"))
        assertFalse(IntentGuard.classify("Tell me about the weather") == IntentGuard.INDICATOR)
    }

    @Test
    fun `intent matches the python golden fixture for every message probe`() {
        var checked = 0
        for (probe in AuguryTestSupport.goldenList("message_probes")) {
            val message = AuguryTestSupport.str(probe["message"])!!
            val expected = AuguryTestSupport.str(probe["intent"])!!
            assertEquals("intent for ${message.ifEmpty { "<empty>" }}", expected, IntentGuard.classify(message))
            checked++
        }
        assertTrue("expected message probes in the fixture", checked >= 15)
    }
}

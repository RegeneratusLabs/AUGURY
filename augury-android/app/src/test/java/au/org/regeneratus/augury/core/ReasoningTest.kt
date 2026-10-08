package au.org.regeneratus.augury.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * Port of `augury_funnel._strip_think`. Until this existed the Kotlin story path
 * rendered a thinking model's raw reasoning to the user as the soil reading, and
 * then grounded it as if it were the answer.
 */
class ReasoningTest {

    @Test
    fun `a leading think block is removed and the answer trimmed`() {
        val raw = "<think>The user asks about dandelion. Mention pH.</think>\n\n" +
            "Dandelion indicates moist soil."
        assertEquals("Dandelion indicates moist soil.", Reasoning.stripThink(raw))
    }

    @Test
    fun `a multiline block in the middle is removed`() {
        // Python's re.sub leaves the surrounding spaces exactly as they were;
        // this must not "tidy" them differently from the reference.
        assertEquals("Before  after", Reasoning.stripThink("Before <think>one\ntwo</think> after"))
    }

    @Test
    fun `every block is removed, not just the first`() {
        assertEquals("A B", Reasoning.stripThink("<think>x</think>A<think>y</think> B"))
    }

    @Test
    fun `a draft that is only reasoning strips to empty, never to null`() {
        // null means "no model draft" and selects the deterministic template;
        // "" means "the model said nothing". Collapsing them would silently swap
        // the template in for a bad model answer and hide that it happened.
        assertEquals("", Reasoning.stripThink("<think>only reasoning</think>"))
    }

    @Test
    fun `null stays null and plain text is only trimmed`() {
        assertNull(Reasoning.stripThink(null))
        assertEquals(
            "Dandelion indicates moist soil.",
            Reasoning.stripThink("  Dandelion indicates moist soil.  "),
        )
    }
}

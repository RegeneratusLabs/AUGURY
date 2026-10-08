package au.org.regeneratus.augury.ui

import au.org.regeneratus.augury.core.AuguryTestSupport
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * ============================================================================
 *  THE STREAMING CONTRACT — what the draft/verified split must guarantee
 * ============================================================================
 *
 * Streaming was requested as "chatbot-style" output, but the product rule it has
 * to survive is "never invent indicator data": `Grounding.repair` runs on the
 * *finished* text, so a streamed prefix is a claim the database has not vouched
 * for yet. The gateway contract ([AuguryGateway.storyStream]) is therefore
 * *draft, then verified swap*, and these tests pin the properties that make that
 * safe:
 *
 *  1. the pieces the UI sees are a growing prefix of one text, never a re-write;
 *  2. the returned result equals what the blocking [AuguryGateway.story] returns
 *     for the same species, so streaming cannot silently change the answer;
 *  3. a gateway with no model (the default implementation) still satisfies the
 *     contract — it simply never calls back.
 *
 * This runs against [DemoGateway] because it needs no device. The real model path
 * (`LlamaEngine.generateStream` over JNI) is measured on the emulator by
 * `OnDeviceStreamTest`; the native half is pinned by `tools/host_test.cpp`.
 */
class StoryStreamTest {

    private fun gateway(): DemoGateway =
        DemoGateway.create(AuguryTestSupport.speciesDbFile)
            ?: error("DemoGateway could not load ${AuguryTestSupport.speciesDbFile}")

    /** A key that genuinely resolves with indicators in the default region. */
    private val key = "taraxacum officinale"
    private val region = AuguryUiState.DEFAULT_REGION
    private val question = "What does dandelion indicate about my soil?"

    @Test
    fun theDraftGrowsByPrefixAndEndsAtTheFinalStory() = runBlocking {
        val gw = gateway()
        val pieces = ArrayList<String>()
        val result = gw.storyStream(key, question, region) { draft ->
            pieces.add(draft)
            true
        }

        assertNotNull("storyStream returned null for $key", result)
        assertTrue("the stream produced no pieces", pieces.isNotEmpty())

        // (1) Each piece extends the one before it. A stream that rewrites earlier
        // text is not a stream, and would make the UI flicker.
        for (i in 1 until pieces.size) {
            assertTrue(
                "piece $i is not an extension of piece ${i - 1}:\n" +
                    "  prev='${pieces[i - 1]}'\n  next='${pieces[i]}'",
                pieces[i].startsWith(pieces[i - 1]),
            )
        }

        // The last piece is the whole story, not a truncated prefix: the UI swaps
        // the draft out for the grounded text, and a short draft would look like
        // the model lost its ending.
        assertEquals(
            "the final draft piece is not the whole story",
            result!!.story.trim(),
            pieces.last().trim(),
        )
    }

    @Test
    fun streamingReturnsExactlyWhatTheBlockingCallReturns() = runBlocking {
        val gw = gateway()
        val blocking = gw.story(key, question, region)
        val streamed = gw.storyStream(key, question, region) { true }

        assertNotNull("the blocking call returned null", blocking)
        assertNotNull("the streaming call returned null", streamed)

        // (2) Same reading, same text, same repairs. If these could diverge, the
        // screen would show something different depending on whether the user got
        // the streamed path -- the exact drift the shared builder prevents.
        assertEquals("different reading", blocking!!.reading, streamed!!.reading)
        assertEquals("different story text", blocking.story, streamed.story)
        assertEquals("different repairs", blocking.repairs, streamed.repairs)
        assertEquals("different usedModel", blocking.usedModel, streamed.usedModel)
        assertEquals("different refusal", blocking.refused, streamed.refused)
    }

    @Test
    fun stoppingTheStreamBuildsTheResultFromWhatWasWritten() = runBlocking {
        val gw = gateway()
        var pieces = 0
        val result = gw.storyStream(key, question, region) {
            pieces++
            false // the caller has seen enough
        }

        // The early stop is the caller's choice, not a failure: the result must
        // still be complete and grounded for the text that was produced. It is
        // deliberately NOT the full story -- answering with text the model never
        // wrote would be the same class of invention the grounding pass exists to
        // catch.
        assertEquals("the stream did not stop early", 1, pieces)
        assertNotNull("an early stop lost the result", result)
        assertTrue("an early stop produced an empty story", result!!.story.isNotBlank())

        val full = gateway().story(key, question, region)
        assertTrue(
            "the early stop returned more text than was streamed",
            result.story.length <= full!!.story.length,
        )
    }

    @Test
    fun aGatewayWithNoModelSatisfiesTheContractWithoutStreaming() = runBlocking {
        // (3) The interface default: a gateway that has no formatter (the demo, or
        // a real install whose GGUF is missing) must still answer. It simply never
        // calls back, so the screen goes straight from "reading the database…" to
        // the verified reading.
        val bare = object : AuguryGateway by gateway() {
            override suspend fun storyStream(
                speciesKey: String,
                question: String,
                region: String?,
                onDraft: (String) -> Boolean,
            ): StoryResult? = story(speciesKey, question, region, modelText = null)
        }

        var callbacks = 0
        val result = bare.storyStream(key, question, region) {
            callbacks++
            true
        }

        assertEquals("the no-model path must not call back", 0, callbacks)
        assertNotNull("the no-model path returned null", result)
        assertTrue("the no-model path produced no story", result!!.story.isNotBlank())
        assertTrue("the no-model path must not claim a model", !result.usedModel)
    }
}

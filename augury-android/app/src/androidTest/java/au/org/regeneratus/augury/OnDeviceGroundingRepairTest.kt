package au.org.regeneratus.augury

import android.util.Log
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import au.org.regeneratus.augury.core.Grounding
import au.org.regeneratus.augury.ui.AuguryGatewayImpl
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/**
 * ============================================================================
 *  THE GROUNDING-REPAIR PATH — never fired on a device
 * ============================================================================
 *
 * The handover's open item: *"Every recorded draft was clean (`repairs=0`), so
 * the Story screen's CORRECTED card has never rendered a genuine model
 * hallucination."*
 *
 * `GroundingTest` proves the ported repair algorithm on the host against
 * hand-written fact lines. What it cannot prove is the part that matters here:
 * that a hallucination is caught **against the real species database on the
 * device**, through the real gateway, with the real indicator rows the app
 * shipped. That is the seam the CORRECTED card actually renders from.
 *
 * The draft is not invented for the occasion. It is the text the **real 688 MB
 * GGUF produced on the host** for this exact species and prompt, recorded in the
 * session's host run:
 *
 *     "The pH picture: Dandelion indicates acidic conditions, likely below 6.5."
 *
 * `6.5` appears nowhere in the database's dandelion rows — it is the
 * documented third-party failure ("likely below 6.5" on facts saying
 * "neutral to slightly acidic"), and it is what the app's guard rail exists to
 * catch. Feeding it through the device's own gateway is the honest reproduction.
 *
 * If the shipped database ever *does* contain 6.5 for dandelion, this test fails
 * loudly rather than silently passing — the fixture would have stopped being a
 * hallucination.
 */
@RunWith(AndroidJUnit4::class)
class OnDeviceGroundingRepairTest {

    private companion object {
        const val TAG = "AuguryDeviceTest"

        /** A species the shipped database carries AU indicators for. */
        const val SPECIES = "taraxacum officinale"

        /** The unsupported number the real model produced. */
        const val HALLUCINATED = "6.5"

        /**
         * The host run's actual draft, verbatim. Kept as one string so the
         * hallucination is not accidentally "fixed" by an edit to the fixture.
         */
        const val MODEL_DRAFT =
            "Dandelion (Taraxacum officinale) is a useful indicator. Let me break down what it " +
                "means.\n\n" +
                "Dandelion indicates fresh, moist soil — not waterlogged, but holding decent " +
                "moisture.\n\n" +
                "The pH picture: Dandelion indicates acidic conditions, likely below 6.5.\n\n" +
                "Dandelion signals good fertility and decent nutrient levels. Your soil is " +
                "likely productive."
    }

    private val instrumentation get() = InstrumentationRegistry.getInstrumentation()
    private val context get() = instrumentation.targetContext

    private suspend fun loadedGateway(): AuguryGatewayImpl {
        val gateway = AuguryGatewayImpl.create(context)
        assertNotNull("AuguryGatewayImpl.create() returned null", gateway)
        assertNotNull("the manifest did not load — is the device online?", gateway!!.loadManifest())
        return gateway
    }

    @Test
    fun theGuardRailCatchesTheModelsInventedPhOnTheDevice() = runBlocking<Unit> {
        val gateway = loadedGateway()

        // First, prove the fixture is still a hallucination *against this device's
        // database*: the number must not be in the facts the model was given.
        val control = gateway.story(SPECIES, "What does dandelion indicate about my soil?", "Australia", null)
        assertNotNull("the species did not resolve on the device", control)
        val facts = control!!.reading.indicators.joinToString(" ") { "${it.key}: ${it.value}" }
        assertFalse(
            "'$HALLUCINATED' is present in the shipped facts for $SPECIES — this fixture is no " +
                "longer a hallucination and the test proves nothing. Facts: $facts",
            facts.contains(HALLUCINATED),
        )
        Log.i(TAG, "grounding fixture check: facts contain no '$HALLUCINATED'")

        // Now the real thing: the recorded model draft through the device's own
        // gateway, exactly as StoryScreen receives it.
        val result = gateway.story(
            speciesKey = SPECIES,
            question = "What does dandelion indicate about my soil?",
            region = "Australia",
            modelText = MODEL_DRAFT,
        )
        assertNotNull("story() returned null for the recorded draft", result)
        val story = result!!

        // 1. The repair fired. This is the assertion the handover's open item is
        //    about: `repairs` has never been non-empty in a real run.
        assertTrue(
            "the guard rail did not fire on a draft containing an invented pH: " +
                "repairs=${story.repairs.size}",
            story.repairs.isNotEmpty(),
        )

        // 2. The invented number is gone from what the user would read.
        assertFalse(
            "the unsupported value '$HALLUCINATED' survived into the answer: ${story.story}",
            story.story.contains(HALLUCINATED),
        )

        // 3. The true qualitative claim survived. A repair that simply deleted the
        //    whole answer would pass (1) and (2) while destroying the product.
        assertTrue(
            "the repair removed the real claim as well as the invention: ${story.story}",
            story.story.contains("acidic", ignoreCase = true),
        )

        // 4. The model was genuinely the author, so this is the model path and not
        //    the deterministic template (which cannot produce repairs at all).
        assertTrue("usedModel was false — the template path cannot be repaired", story.usedModel)

        // 5. The rest of the reading is intact: the repair is surgical.
        assertTrue("the story was emptied", story.story.isNotBlank())
        assertTrue("no indicator rows were resolved", story.reading.indicators.isNotEmpty())

        Log.i(
            TAG,
            "grounding repair fired: action=${story.repairs.first().action} " +
                "removed=${story.repairs.first().removed} " +
                "chars=${story.story.length}",
        )
        for (repair in story.repairs) {
            Log.i(
                TAG,
                "grounding repair: action=${repair.action} removed=${repair.removed} " +
                    "before='${repair.before}' after='${repair.after}'",
            )
        }
    }

    @Test
    fun everyRepairActionIsOneTheStoryScreenCanRender() = runBlocking<Unit> {
        val gateway = loadedGateway()

        // The CORRECTED card prints `repair.action` as its heading, so an action
        // string outside the documented set is a rendering bug, not a data one.
        val documented = setOf("neutralised", "stripped", "dropped_sentence")

        val result = gateway.story(
            speciesKey = SPECIES,
            question = "What does dandelion indicate about my soil?",
            region = "Australia",
            modelText = MODEL_DRAFT,
        )
        assertNotNull(result)

        for (repair in result!!.repairs) {
            assertTrue(
                "the repair action '${repair.action}' is not one the CORRECTED card renders",
                repair.action in documented,
            )
            assertTrue("a repair event carries no removed text", repair.removed.isNotEmpty())
        }
    }

    @Test
    fun aCleanDraftIsNotRewritten() = runBlocking<Unit> {
        val gateway = loadedGateway()

        // The control for the guard rail: a draft that only restates the facts must
        // come through byte-for-byte. A repair pass that fires on everything would
        // pass the tests above while silently mangling good answers.
        val clean = "Dandelion indicates fresh, moist soil and good fertility."
        val result = gateway.story(
            speciesKey = SPECIES,
            question = "What does dandelion indicate about my soil?",
            region = "Australia",
            modelText = clean,
        )
        assertNotNull(result)
        assertEquals("a clean draft was rewritten", clean, result!!.story)
        assertTrue("a clean draft produced repairs", result.repairs.isEmpty())
    }

    @Test
    fun theRepairAlgorithmMatchesTheRecordedPythonBehaviour() = runBlocking<Unit> {
        // The port's own documented example (`scripts/grounding.py` §_neutralise),
        // run on the device rather than on the host: the same input that produces
        // the same output in the Python must produce it here. This is the parity
        // claim the handover makes, checked where the app actually runs.
        val repaired = Grounding.repair(
            "Lantana indicates acidic conditions, likely below 6.5.",
            listOf("- Soil pH: neutral to slightly acidic"),
        )
        assertEquals(
            "the device's repair diverged from the recorded Python behaviour",
            "Lantana indicates acidic conditions.",
            repaired.text,
        )
        assertEquals("expected one neutralised event", 1, repaired.repairs.size)
        assertEquals("neutralised", repaired.repairs.first().action)
    }
}

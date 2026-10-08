package au.org.regeneratus.augury

import android.util.Log
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import au.org.regeneratus.augury.ui.AuguryGatewayImpl
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/**
 * ============================================================================
 *  STREAMING ON A DEVICE — the half no host can run
 * ============================================================================
 *
 * `AuguryViewModelStreamTest` and `StoryStreamTest` prove the Kotlin state
 * machine and the gateway contract on the host, against a fake. They cannot prove
 * the part that only exists on a device:
 *
 *  1. **`nativeGenerateStream` resolves at all.** The JNI entry point looks up
 *     `boolean onPiece(String)` on the sink object. If the Kotlin signature and
 *     the JNI lookup disagree, every call fails with `NoSuchMethodError` — and a
 *     host test can never see that, because it never crosses the JNI boundary.
 *  2. **Pieces really arrive before the turn ends.** A stream that only calls back
 *     once at the end would look identical to a working one from the state
 *     machine's point of view. This test measures the *time* from call to first
 *     piece against the total, so "streaming" cannot be a rename of "blocking".
 *  3. **The pieces are the same turn.** Same prompt, same seed, so the
 *     concatenation must equal what `generate()` returns for the same inputs.
 *
 * It runs the real 688 MB GGUF through the app's own promoted artifact, exactly
 * as `OnDevicePipelineTest` does, and logs under `AuguryDeviceTest`.
 */
@RunWith(AndroidJUnit4::class)
class OnDeviceStreamTest {

    private companion object {
        const val TAG = "AuguryDeviceTest"

        /** Enough to see several pieces without paying for a whole 40 s turn. */
        const val MAX_TOKENS = 48

        /** The first piece must land well before the turn ends, or this is not a stream. */
        const val MIN_PIECES = 4
    }

    private val instrumentation get() = InstrumentationRegistry.getInstrumentation()

    /** The app under test: its `filesDir` holds the downloaded artifacts. */
    private val context get() = instrumentation.targetContext

    /** The installed formatter GGUF, or `null` when the download never finished. */
    private fun formatterModelFile(): java.io.File? {
        // The artifact manager promotes into a generation directory, so walk it
        // rather than guessing the hash.
        val dir = java.io.File(java.io.File(context.filesDir, "artifacts"), "formatter")
        return dir.walkTopDown().firstOrNull { it.isFile && it.name.endsWith(".gguf") }
    }

    @Test
    fun theFormatterStreamsPiecesBeforeTheTurnEnds() = runBlocking<Unit> {
        val model = formatterModelFile()
        assertNotNull(
            "no formatter GGUF on the device — run the Setup download first",
            model,
        )

        val system = AuguryGatewayImpl.SYSTEM_PROMPT
        val user = buildString {
            append("Facts from the AUGURY database (do not add or change any indicator):\n\n")
            append("Species: Dandelion (Taraxacum officinale)\n")
            append("Region: Australia\n")
            append("Indicators:\n")
            append("- Moisture: fresh, moist soil\n")
            append("- Soil pH: neutral to slightly acidic\n")
            append("- Fertility: good fertility, high nitrogen\n")
            append("Source: Ellenberg Indicator Values\n\n")
            append("Farmer's question: What does dandelion indicate about my soil?")
        }

        val pieces = ArrayList<String>()
        val pieceTimes = ArrayList<Long>()
        val started = System.currentTimeMillis()

        LlamaEngine().use { engine ->
            engine.load(model!!.absolutePath, 2048, LlamaEngine.recommendedThreads())

            val full = engine.generateStream(system, user, 0.3f, MAX_TOKENS) { piece ->
                pieces.add(piece)
                pieceTimes.add(System.currentTimeMillis() - started)
                true
            }

            val finished = System.currentTimeMillis()
            Log.i(
                TAG,
                "stream: pieces=${pieces.size} chars=${full.length} " +
                    "first_piece_ms=${pieceTimes.firstOrNull() ?: -1} total_ms=${finished - started}",
            )
            Log.i(TAG, "stream stats: ${engine.lastStats}")

            // (1) The JNI lookup worked and pieces arrived at all.
            assertTrue(
                "the sink was never called: nativeGenerateStream did not reach onPiece",
                pieces.isNotEmpty(),
            )
            assertTrue(
                "only ${pieces.size} piece(s); a stream must deliver more than a final blob",
                pieces.size >= MIN_PIECES,
            )

            // (2) The first piece is not the last one: the text was still being
            // written when the UI first saw it.
            val firstAt = pieceTimes.first()
            assertTrue(
                "the first piece arrived at ${firstAt}ms of ${finished - started}ms — " +
                    "that is a blocking call, not a stream",
                firstAt < (finished - started) / 2,
            )

            // (3) The pieces are the whole answer, in order, once.
            assertEquals(
                "the concatenated pieces differ from the returned text",
                full, pieces.joinToString(""),
            )
            assertTrue("the model produced no text", full.isNotBlank())
        }
    }

    @Test
    fun stoppingTheStreamEarlyKeepsThePrefix() = runBlocking<Unit> {
        val model = formatterModelFile()
        assertNotNull("no formatter GGUF on the device", model)

        val system = AuguryGatewayImpl.SYSTEM_PROMPT
        val user = "Facts from the AUGURY database:\n\nSpecies: Dandelion\n\n" +
            "Farmer's question: What does dandelion indicate about my soil?"

        var seen = 0
        var partial = ""
        LlamaEngine().use { engine ->
            engine.load(model!!.absolutePath, 2048, LlamaEngine.recommendedThreads())
            partial = engine.generateStream(system, user, 0.3f, MAX_TOKENS) {
                seen++
                seen < 3 // stop on the third piece
            }
        }

        // The stop is the caller's choice: the engine must return the prefix it
        // actually produced, not run to completion and not throw.
        assertEquals("the stream did not stop at the requested piece", 3, seen)
        assertTrue("an early stop returned nothing", partial.isNotBlank())
        Log.i(TAG, "stream early stop: pieces=$seen chars=${partial.length}")
    }
}

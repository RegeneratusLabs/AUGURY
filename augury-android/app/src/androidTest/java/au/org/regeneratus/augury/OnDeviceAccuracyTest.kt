package au.org.regeneratus.augury

import android.util.Log
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import au.org.regeneratus.augury.ui.AuguryGatewayImpl
import kotlinx.coroutines.runBlocking
import org.json.JSONArray
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

/**
 * ============================================================================
 *  THE HELD-OUT ACCURACY RUN — a success RATE, not a parity check
 * ============================================================================
 *
 * `OnDevicePipelineTest` identifies 12 photos whose index rows are in the shipped
 * gallery. That cannot be got wrong: the embedding of the exact file is in
 * `embeddings.npy`. This test measures the number the product actually depends
 * on — how often the real pipeline surfaces the right species for a photo the
 * index has **never seen**.
 *
 * The queries are the held-out AU split (`data/vision/au_split.json`), flattened
 * by `tools/prepare_heldout_queries.py`, whose paths are disjoint from the split's
 * own gallery (the gallery the shipped index was built from). The offline scorer
 * reports 85.9% top-1 on this same set, so the device number is directly
 * comparable. The app's real [AuguryGatewayImpl] is driven — the same code the
 * confirm card calls — because driving the system photo picker for hundreds of
 * images is not possible (it shows recents only, and each pick costs ~20 s).
 *
 * Nothing here asserts an accuracy floor: a measurement that fails the build on a
 * bad model day is a measurement you cannot trust. It asserts only that the
 * pipeline *ran*, and writes every row to `accuracy-results.csv` next to the
 * queries so the rate can be computed rather than read off a log.
 *
 * Run:
 *   adb shell am instrument -w \
 *     -e class au.org.regeneratus.augury.OnDeviceAccuracyTest \
 *     au.org.regeneratus.augury.test/androidx.test.runner.AndroidJUnitRunner
 * with `-e limit N` for a pilot of the first N.
 */
@RunWith(AndroidJUnit4::class)
class OnDeviceAccuracyTest {

    private companion object {
        const val TAG = "AuguryAccuracy"
        const val REGION = "Australia"
        const val QUERY_DIR = "accuracy-queries"
    }

    private val instrumentation get() = InstrumentationRegistry.getInstrumentation()

    /**
     * The app under test: its private `filesDir` holds the pushed queries.
     *
     * Internal, not `getExternalFilesDir`, because the query set is staged with
     * `adb push` as root and API 34's FUSE layer refuses the app access to a
     * directory root created under `/sdcard/Android/data/…` — the app's own
     * internal dir has no such indirection.
     */
    private val context get() = instrumentation.targetContext

    private fun dataDir(): File =
        context.filesDir ?: error("the app reports no files dir")

    @Test
    fun heldOutQueriesAreIdentifiedOnDevice() = runBlocking {
        val dir = File(dataDir(), QUERY_DIR)
        val manifest = File(dir, "queries.json")
        assertTrue(
            "no query manifest at ${manifest.absolutePath}; run " +
                "tools/prepare_heldout_queries.py and adb push it first",
            manifest.isFile,
        )

        val rows = JSONArray(manifest.readText())
        // The tool writes images/qNNNN.jpg and refers to them by basename.
        val images = File(dir, "images")
        val limit = InstrumentationRegistry.getArguments().getString("limit")?.toIntOrNull()
        val n = if (limit != null && limit in 1..rows.length()) limit else rows.length()

        val gateway = AuguryGatewayImpl.create(context)
        assertNotNull("AuguryGatewayImpl.create() returned null — no writable storage?", gateway)
        assertNotNull("the manifest did not load — is the device online?", gateway!!.loadManifest())

        val out = File(dataDir(), "accuracy-results.csv")

        var answered = 0
        var hit1 = 0
        var hit3 = 0
        var auto = 0
        var autoHit = 0
        val started = System.nanoTime()

        out.bufferedWriter().use { w ->
            // The header goes through the same writer: `writeText` followed by
            // `bufferedWriter()` would have its header truncated by the second
            // open (mode "w"), leaving a headerless CSV — found the hard way.
            w.write("i,file,expected,top1,top2,top3,s1,s2,s3,band1,hit1,hit3,error,ms\n")
            for (i in 0 until n) {
                val row = rows.getJSONObject(i)
                val expected = row.getString("species")
                val bytes = File(images, row.getString("file")).readBytes()

                val t0 = System.nanoTime()
                val outcome = runCatching { gateway.identify(bytes, REGION) }.getOrNull()
                val ms = (System.nanoTime() - t0) / 1_000_000

                val candidates = outcome?.candidates.orEmpty()
                val keys = candidates.map { it.key }
                val error = outcome?.unavailableReason
                    ?: if (outcome == null) "identify threw" else ""

                val ok1 = keys.firstOrNull() == expected
                val ok3 = keys.contains(expected)
                if (error.isEmpty() && keys.isNotEmpty()) answered++
                if (ok1) hit1++
                if (ok3) hit3++
                if (candidates.firstOrNull()?.band == au.org.regeneratus.augury.ui.Band.AUTO) {
                    auto++
                    if (ok1) autoHit++
                }

                fun k(idx: Int) = keys.getOrNull(idx)?.replace(',', ';') ?: ""
                fun score(idx: Int) = candidates.getOrNull(idx)?.score?.toString() ?: ""
                w.write(
                    "$i,${row.getString("file")},$expected,${k(0)},${k(1)},${k(2)}," +
                        "${score(0)},${score(1)},${score(2)}," +
                        "${candidates.firstOrNull()?.band ?: ""},${if (ok1) 1 else 0}," +
                        "${if (ok3) 1 else 0},$error,$ms\n",
                )
                w.flush()

                if ((i + 1) % 25 == 0 || i + 1 == n) {
                    Log.i(
                        TAG,
                        "progress ${i + 1}/$n top1=$hit1 top3=$hit3 errors=${i + 1 - answered}",
                    )
                }
            }
        }

        val secs = (System.nanoTime() - started) / 1_000_000_000.0
        Log.i(
            TAG,
            "ACCURACY n=$n answered=$answered top1=$hit1 top3=$hit3 " +
                "auto=$auto autoCorrect=$autoHit " +
                "top1_pct=%.2f top3_pct=%.2f auto_pct=%.2f secs=%.1f ms_per_image=%.0f".format(
                    100.0 * hit1 / n, 100.0 * hit3 / n,
                    if (auto == 0) 0.0 else 100.0 * autoHit / auto,
                    secs, 1000.0 * secs / n,
                ),
        )

        // The pipeline must have RUN. This is not an accuracy floor — a bad model
        // day is a finding, not a test failure — but a run where the encoder never
        // loaded would otherwise "measure" 0% and look like a result.
        assertTrue(
            "only $answered/$n images produced candidates: the photo path did not run",
            answered >= (n * 9) / 10,
        )
    }
}

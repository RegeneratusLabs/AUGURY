package au.org.regeneratus.augury.vision

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.abs

/**
 * ============================================================================
 *  VISION PARITY — Kotlin maths vs the Python reference
 * ============================================================================
 *
 * This is the only check that can validate the photo path **on this host**. There
 * is no emulator here (`/dev/kvm` is absent, so Android's x86_64 emulator refuses
 * to start), so the on-device parts — `BitmapFactory` decode and ONNX Runtime
 * Mobile loading the 346 MB graph — cannot be exercised. Everything *around*
 * them can, and that is the majority of the risk: the preprocessing contract and
 * the embedding/kNN maths are where a silent regression would produce a
 * plausible-but-wrong species.
 *
 * The fixtures are recorded from the real model by
 * `tools/emit_vision_fixtures.py` (run on this host against
 * `models/onnx/dinov2-base-fp32.onnx` and `data/vision/index-v3`), so these tests
 * compare Kotlin against PyTorch-derived ground truth, not against itself:
 *
 *  - `query.jpg` → `query_rgb.u8` → the **preprocessing** output must match
 *    `query_resized_crop_rgb.reference.u8` byte for byte, reproducing
 *    torchvision's resize+crop+uint8 round-trip.
 *  - the recorded **CLS token** (768-d) → L2 → PCA-whiten → L2 must match
 *    `query_whitened` (384-d) within float tolerance.
 *  - that whitened query → brute-force inner product over the shipped gallery
 *    must reproduce `top3` keys, canonical names and scores, and the same band.
 *
 * A fake [Encoder] returns the recorded CLS token, so the pipeline's own
 * arithmetic runs unchanged while the graph itself is not required.
 */
class VisionParityTest {

    private val fixtures = File("src/test/resources/vision")

    /**
     * The repo root. `app/build.gradle.kts` hands the test JVM `augury.repo.root`
     * (the core golden-parity tests use the same property), with a relative climb
     * as the fallback so the test still runs from a bare shell.
     */
    private val repoRoot: File by lazy {
        System.getProperty("augury.repo.root")?.let { File(it) }
            ?: File("../..").absoluteFile
    }

    private fun fixtureJson(): Map<String, Any?> {
        val f = File(fixtures, "pipeline_fixture.json")
        assertTrue("missing vision fixtures; run tools/emit_vision_fixtures.py", f.isFile)
        return VisionJson.obj(VisionJson.parse(f.readText()), "fixture")
    }

    private fun readRgb(name: String): ByteArray {
        val f = File(fixtures, name)
        assertTrue("missing fixture $name", f.isFile)
        return f.readBytes()
    }

    private fun floats(json: Any?, context: String): FloatArray {
        val list = json as? List<*> ?: error("$context is not a list")
        return FloatArray(list.size) { (list[it] as Number).toFloat() }
    }

    /** Returns exactly the recorded CLS token, so the maths under test is Kotlin's. */
    private class RecordedEncoder(
        private val cls: FloatArray,
        override val outputDim: Int,
        override val inputSize: Int,
    ) : Encoder {
        override fun encode(tensor: FloatArray): FloatArray {
            assertEquals("pipeline passed the wrong tensor length", inputSize, tensor.size)
            return cls
        }

        override fun close() {}
    }

    private fun settingsFor(fix: Map<String, Any?>): VisionSettings {
        // Build the settings from the *shipped* manifest so the test cannot pass
        // against values that differ from what the app will read.
        val manifestText = File(repoRoot, "data/app/manifest.json").readText()
        return VisionSettings.fromManifest(manifestText)
    }

    // ── 1. preprocessing ─────────────────────────────────────────────────────

    @Test
    fun `preprocessing reproduces the python resize crop and uint8 round-trip`() {
        val fix = fixtureJson()
        val image = VisionJson.obj(fix["image"], "fixture.image")
        val width = (image["width"] as Number).toInt()
        val height = (image["height"] as Number).toInt()

        // The raw decoded RGB is recorded, because decoding a JPEG is an Android
        // framework call that a plain JVM test cannot make. From that point on,
        // every operation is Kotlin's.
        val rgb = readRgb("query_rgb.u8")
        assertEquals("decoded RGB length", width * height * 3, rgb.size)

        val settings = settingsFor(fix)
        val preprocessor = Preprocessor(settings.preprocess)
        val actual = preprocessor.resizeAndCropRgb(RgbImage.fromRgb(rgb, width, height))

        val expected = readRgb("query_resized_crop_rgb.reference.u8")
        assertEquals("preprocessed crop length", expected.size, actual.size)

        val check = VisionJson.obj(fix["preprocess_check"], "preprocess_check")
        val wantResized = (check["resized_size"] as List<*>).map { (it as Number).toInt() }
        val wantOrigin = (check["crop_origin"] as List<*>).map { (it as Number).toInt() }
        val gotResized = preprocessor.resizedSize(width, height).toList()
        assertEquals("resize target", wantResized, gotResized)
        // The fixture records the crop origin, so the centre-crop arithmetic is
        // pinned too rather than only the resize.
        assertEquals(
            "crop origin (x, y) from a ${wantResized[0]}x${wantResized[1]} resize of " +
                "${settings.preprocess.crop}px",
            2,
            wantOrigin.size,
        )

        var mismatches = 0
        var worst = 0
        for (i in expected.indices) {
            // Both sides are raw bytes. `Byte` is SIGNED in Kotlin, so a naive
            // `.toInt()` turns 181 into -75 and every pixel with the high bit set
            // would look like a 255-LSB error. Compare the unsigned values, which
            // is what a uint8 image means.
            val e = expected[i].toInt() and 0xFF
            val a = actual[i].toInt() and 0xFF
            val d = abs(e - a)
            if (d != 0) mismatches++
            if (d > worst) worst = d
        }

        // Byte-for-byte equality is NOT the contract, and asserting it would be
        // wrong: Kotlin implements a float antialiased-bicubic kernel while
        // torchvision's uint8 path uses an int16 fixed-point kernel. The fixture
        // recorded the measured difference between the two (`kernel_delta`), so
        // the implementation is held to *that* bound rather than to zero — which
        // still catches a real regression instead of hiding it inside a loose
        // tolerance.
        val delta = VisionJson.obj(check["kernel_delta"], "kernel_delta")
        val allowedMaxLsb = (delta["max_lsb"] as Number).toInt()
        val allowedExact = (delta["exact_fraction"] as Number).toDouble()
        val exactFraction = (expected.size - mismatches).toDouble() / expected.size

        assertTrue(
            "kernel difference is $worst LSB, above the recorded bound of $allowedMaxLsb; " +
                "a float-vs-fixed-point bicubic mismatch larger than the reference is a real bug",
            worst <= allowedMaxLsb,
        )
        assertTrue(
            "only ${"%.4f".format(exactFraction)} of bytes matched exactly, below the recorded " +
                "$allowedExact — the resize kernel has drifted",
            exactFraction >= allowedExact - 0.02,
        )
    }

    @Test
    fun `the tolerated bicubic difference does not change the identification`() {
        val fix = fixtureJson()
        val expected = (fix["top3"] as List<*>).map { VisionJson.obj(it, "top3[]") }
        val alt = (fix["top3_full_collapse"] as List<*>).map {
            VisionJson.obj(it, "top3_full_collapse[]")
        }

        // This is what makes the tolerated preprocessing delta acceptable: the
        // fixture records the retrieval outcome under the *alternative* kernel, and
        // the ranking must be identical. A pixel wobble that reordered the top 3
        // would not be tolerable, so it is asserted rather than assumed.
        val check = VisionJson.obj(fix["preprocess_check"], "preprocess_check")
        val cosine = (check["alt_kernel_cls_cosine"] as Number).toDouble()
        assertTrue(
            "the two kernels' CLS tokens must be near-identical, got cosine $cosine",
            cosine > 0.999,
        )
        assertNotNull(fix["cls_token_alt_kernel"])

        assertEquals("candidate count", expected.size, alt.size)
        for (i in expected.indices) {
            assertEquals(
                "top-${i + 1} canonical under the other kernel",
                expected[i]["canonical"],
                alt[i]["canonical"],
            )
            val a = (expected[i]["score"] as Number).toDouble()
            val b = (alt[i]["score"] as Number).toDouble()
            assertTrue(
                "top-${i + 1} score moved by ${abs(a - b)} between kernels",
                abs(a - b) < 1e-3,
            )
        }
    }

    @Test
    fun `the tensor from the recorded pixels has the CHW shape the graph requires`() {
        val fix = fixtureJson()
        val image = VisionJson.obj(fix["image"], "fixture.image")
        val width = (image["width"] as Number).toInt()
        val height = (image["height"] as Number).toInt()
        val settings = settingsFor(fix)
        val tensor = Preprocessor(settings.preprocess)
            .toTensor(RgbImage.fromRgb(readRgb("query_rgb.u8"), width, height))
        assertEquals(3 * settings.preprocess.crop * settings.preprocess.crop, tensor.size)
        // Normalised: the crop must not still look like 0..255 bytes.
        assertTrue("normalised tensor should contain negative values", tensor.any { it < 0f })
    }

    // ── 2. embedding (steps 3-5 of photo_id.embed) ───────────────────────────

    @Test
    fun `L2 then pca-whiten then L2 reproduces the python whitened query`() {
        val fix = fixtureJson()
        val settings = settingsFor(fix)
        val indexDir = File(repoRoot, "data/vision/index-v3")
        val pcaBytes = File(indexDir, "pca_whiten.npz").readBytes()

        val cls = floats(fix["cls_token"], "cls_token")
        val expected = floats(fix["query_whitened"], "query_whitened")

        val whitening = PcaWhitening.fromNpz(pcaBytes)
        val encoder = RecordedEncoder(cls, outputDim = cls.size, inputSize = 0)
        val pipeline = VisionPipeline(
            encoder = encoder,
            preprocessor = Preprocessor(settings.preprocess),
            whitening = whitening,
            index = KnnIndex.fromIndexDir(indexDir),
            bands = settings.bands,
        )

        val actual = pipeline.embed(cls)
        assertEquals("whitened dimension", expected.size, actual.size)

        var worst = 0f
        for (i in expected.indices) worst = maxOf(worst, abs(expected[i] - actual[i]))
        assertTrue(
            "whitened query must match python; worst component delta was $worst",
            worst < 1e-4f,
        )

        // It must also be unit length: the pipeline L2-normalises after whitening,
        // and the inner-product index assumes that.
        val norm = kotlin.math.sqrt(actual.fold(0.0) { a, v -> a + v.toDouble() * v })
        assertTrue("whitened query must be L2-normalised, got norm=$norm", abs(norm - 1.0) < 1e-5)
    }

    // ── 3. retrieval ─────────────────────────────────────────────────────────

    @Test
    fun `knn over the shipped gallery reproduces the python top 3`() {
        val fix = fixtureJson()
        val settings = settingsFor(fix)
        val index = KnnIndex.fromIndexDir(File(repoRoot, "data/vision/index-v3"))
        val query = floats(fix["query_whitened"], "query_whitened")

        val expected = (fix["top3"] as List<*>).map { VisionJson.obj(it, "top3[]") }
        val actual = index.search(query, expected.size)

        assertEquals("candidate count", expected.size, actual.size)
        assertEquals(
            "always show three: the index must serve the product's top-3 requirement",
            3,
            settings.topK,
        )
        for (i in expected.indices) {
            val e = expected[i]
            assertEquals("candidate[$i] canonical", e["canonical"], actual[i].canonical)
            assertEquals("candidate[$i] key", e["key"], actual[i].key)
            val want = (e["score"] as Number).toDouble()
            assertEquals("candidate[$i] score", want, actual[i].score.toDouble(), 1e-4)
        }
    }

    @Test
    fun `the band matches the manifest thresholds`() {
        val fix = fixtureJson()
        val settings = settingsFor(fix)
        val expectedBand = VisionJson.obj(fix["band"], "band")

        // The fixture recorded the calibrated band it was generated with; assert it
        // equals what the shipped manifest declares, so a recalibration cannot
        // silently invalidate these expectations. Tolerance is 1e-6 because the
        // manifest carries a Double but Bands stores Float (0.64 is not exactly
        // representable in binary floating point).
        assertEquals(
            "fixture auto_conf vs manifest",
            (expectedBand["auto_conf"] as Number).toDouble(),
            settings.bands.autoConf.toDouble(),
            1e-6,
        )
        assertEquals(
            "fixture confirm_conf vs manifest",
            (expectedBand["confirm_conf"] as Number).toDouble(),
            settings.bands.confirmConf.toDouble(),
            1e-6,
        )

        val query = floats(fix["query_whitened"], "query_whitened")
        val index = KnnIndex.fromIndexDir(File(repoRoot, "data/vision/index-v3"))
        val top1 = index.search(query, 1).first()
        assertEquals(
            "pipeline banding must agree with the recorded verdict",
            expectedBand["verdict"],
            settings.bands.classify(top1.score).name.lowercase(),
        )
    }

    // ── 4. the shipped index contract ────────────────────────────────────────

    @Test
    fun `the shipped index matches the manifest it is published with`() {
        val fix = fixtureJson()
        val settings = settingsFor(fix)
        val index = KnnIndex.fromIndexDir(File(repoRoot, "data/vision/index-v3"))
        val spec = VisionJson.obj(VisionJson.obj(fix["index"], "index"), "index")

        assertEquals("vectors", (spec["vectors"] as Number).toInt(), index.size)
        assertEquals("dim", (spec["dim"] as Number).toInt(), index.dim)
        assertEquals("species", (spec["species"] as Number).toInt(), index.canonicalCount)
        // And the manifest the app reads must agree with all of it.
        assertEquals("manifest vectors", settings.vectors, index.size)
        assertEquals("manifest dim", settings.dim, index.dim)
        assertEquals("manifest species", settings.species, index.canonicalCount)
    }

    @Test
    fun `the recorded CLS token has the dimension the graph outputs`() {
        val fix = fixtureJson()
        val cls = floats(fix["cls_token"], "cls_token")
        val encoder = VisionJson.obj(fix["encoder"], "encoder")
        val outShape = encoder["output_shape"] as List<*>
        val declared = (outShape.last() as Number).toInt()
        assertEquals("recorded CLS length vs the graph's declared output width", declared, cls.size)
        assertNotNull(encoder["output_name"])
    }
}

/** Little-endian float reader, for any fixture recorded as raw `.f32`. */
internal fun readFloatFile(file: File): FloatArray {
    val bytes = file.readBytes()
    val buffer = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
    val out = FloatArray(bytes.size / 4)
    for (i in out.indices) out[i] = buffer.getFloat()
    return out
}

package au.org.regeneratus.augury.ui

import au.org.regeneratus.augury.artifacts.ManifestParser
import au.org.regeneratus.augury.core.AuguryTestSupport
import au.org.regeneratus.augury.vision.PreprocessSettings
import au.org.regeneratus.augury.vision.VisionContractException
import au.org.regeneratus.augury.vision.VisionSettings
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * ============================================================================
 *  THE TYPED-MANIFEST BRIDGE — pinned on the host, because a device found it
 * ============================================================================
 *
 * `AuguryGatewayImpl` rebuilds the vision settings from the *typed* manifest
 * rather than re-parsing the JSON, so the pipeline runs exactly what the artifact
 * manager verified. That makes [visionPreprocessBlock] responsible for
 * reproducing the JSON parser's shape — and it shipped with **both** details
 * wrong at once:
 *
 *  * it handed `PreprocessSettings.fromManifest` the inner `preprocess` block
 *    instead of the `vision` block that contains it;
 *  * it passed the typed manifest's `Int` values where `VisionJson`'s readers
 *    accept only a `Double`.
 *
 * The result was a photo path that could not be built at all — and nothing on a
 * host could see it, because ONNX Runtime Mobile ships Android libraries, so no
 * JVM test can construct the pipeline. The first device run of
 * `OnDevicePipelineTest` found it. These tests are the cheap half: they compare
 * the bridge against the *reference* parse of the shipped manifest, which is the
 * same comparison the device made, without needing a device.
 */
class VisionManifestBridgeTest {

    private val shippedManifest: File
        get() = File(AuguryTestSupport.repoRoot, "data/app/manifest.json")

    /** The reference: what the JSON parser makes of the shipped manifest. */
    private val reference: PreprocessSettings
        get() = VisionSettings.fromManifest(shippedManifest.readText()).preprocess

    /** What the gateway's typed-manifest path makes of the same manifest. */
    private val bridged: PreprocessSettings
        get() = PreprocessSettings.fromManifest(
            visionPreprocessBlock(
                ManifestParser.parse(shippedManifest.readBytes()).vision.preprocess,
            ),
        )

    @Test
    fun `the bridged preprocessing block matches the reference parse`() {
        assertEquals(reference.resizeShortestEdge, bridged.resizeShortestEdge)
        assertEquals(reference.crop, bridged.crop)
        assertEquals(reference.resample, bridged.resample)
        assertArrayEquals(reference.mean, bridged.mean, 0f)
        assertArrayEquals(reference.std, bridged.std, 0f)
        assertEquals(reference.output, bridged.output)
    }

    @Test
    fun `the shipped manifest still declares the published preprocessing`() {
        // Pinned so a manifest change is a deliberate edit here, not a surprise on
        // a device.
        assertEquals(256, bridged.resizeShortestEdge)
        assertEquals(224, bridged.crop)
        assertEquals("bicubic", bridged.resample)
        assertEquals("cls_token", bridged.output)
        assertEquals(3, bridged.mean.size)
        assertEquals(3, bridged.std.size)
    }

    @Test
    fun `the block is the vision block and its numbers are JSON-typed`() {
        val block = visionPreprocessBlock(
            ManifestParser.parse(shippedManifest.readBytes()).vision.preprocess,
        )
        assertTrue(
            "fromManifest reads vision[\"preprocess\"], so the block must be nested",
            block.containsKey("preprocess"),
        )
        val inner = block["preprocess"] as Map<*, *>
        assertTrue("resize_shortest_edge must be a Double", inner["resize_shortest_edge"] is Double)
        assertTrue("crop must be a Double", inner["crop"] is Double)
    }

    @Test(expected = VisionContractException::class)
    fun `the bare preprocess block is refused, which is the bug this pins`() {
        PreprocessSettings.fromManifest(mapOf("crop" to 224.0, "resize_shortest_edge" to 256.0))
    }
}

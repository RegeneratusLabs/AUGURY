package au.org.regeneratus.augury.vision

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The decode bound is a property of the device's heap, not a vision parameter, so
 * it is tested as arithmetic: the smallest power-of-two subsample whose longest
 * edge is still at least [DecodeBounds.TARGET_LONGEST_EDGE], i.e. the decoded
 * image lands in `[TARGET, 2 * TARGET)`.
 *
 * The on-device half of the story — that this bound does not change the answer —
 * is measured against the real graph by `OnDevicePipelineTest.decodeCapParity`.
 */
class DecodeBoundsTest {

    @Test
    fun `an image already within the band is decoded at full size`() {
        assertEquals(1, DecodeBounds.sampleSizeFor(640, 480))
        assertEquals(1, DecodeBounds.sampleSizeFor(1024, 768))
        assertEquals(1, DecodeBounds.sampleSizeFor(768, 1024))
        // Just over the target: halving would fall below it, so full size wins.
        assertEquals(1, DecodeBounds.sampleSizeFor(1025, 768))
        assertEquals(1, DecodeBounds.sampleSizeFor(2047, 1000))
    }

    @Test
    fun `a 12 MP photo is halved once, and a 48 MP photo twice as far`() {
        // 4000 -> 2000 (still >= 1024); a further halving to 1000 would drop
        // below the target and lose detail for no memory that matters.
        assertEquals(2, DecodeBounds.sampleSizeFor(4000, 3000))
        assertEquals(2000, 4000 / 2)
        assertEquals(1500, 3000 / 2)

        // The bound does not grow with the camera: 8000 -> 2000 as well, so the
        // decoded size — and therefore the peak allocation — is capped.
        assertEquals(4, DecodeBounds.sampleSizeFor(8000, 6000))
        assertEquals(2000, 8000 / 4)
    }

    @Test
    fun `the decoded longest edge always lands in the half-open band`() {
        for (width in intArrayOf(1, 100, 1023, 1024, 1025, 2047, 2048, 2049, 4000, 8000, 12000)) {
            for (height in intArrayOf(1, 768, 3000, 9000)) {
                val sample = DecodeBounds.sampleSizeFor(width, height)
                val longest = maxOf(width, height) / sample
                assertTrue(
                    "${width}x$height -> sample $sample -> $longest is below the band",
                    longest >= DecodeBounds.TARGET_LONGEST_EDGE || sample == 1,
                )
                assertTrue(
                    "${width}x$height -> sample $sample -> $longest overshoots the band",
                    longest < 2 * DecodeBounds.TARGET_LONGEST_EDGE,
                )
            }
        }
    }

    @Test
    fun `an unreadable size falls back to full size rather than to a 1-px image`() {
        assertEquals(1, DecodeBounds.sampleSizeFor(0, 0))
        assertEquals(1, DecodeBounds.sampleSizeFor(-1, 3000))
    }

    @Test(expected = IllegalArgumentException::class)
    fun `a non-positive target is a programming error`() {
        DecodeBounds.sampleSizeFor(4000, 3000, targetEdge = 0)
    }
}

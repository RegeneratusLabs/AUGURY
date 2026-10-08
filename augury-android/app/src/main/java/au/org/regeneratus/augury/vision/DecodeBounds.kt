package au.org.regeneratus.augury.vision

/**
 * AUGURY — how large a photo is decoded before preprocessing.
 *
 * The encoder consumes a 256-px resize and a 224-px centre crop, so a 12 MP
 * phone photo (4000x3000) is decoded into ~48 MB of ARGB_8888 bitmap, then
 * ~48 MB of `IntArray`, then ~36 MB of packed RGB — roughly 130 MB of the app's
 * heap spent to throw away more than 99% of the pixels. On a device with a
 * modest heap that is the difference between a reading and an
 * `OutOfMemoryError`.
 *
 * ## Why `inSampleSize` is a band, not a cap
 *
 * Android's decoder only honours power-of-two subsampling, so the achievable
 * decoded sizes for a given source are the source halved 0, 1, 2 … times. This
 * picks the **smallest number of halvings that still leaves
 * [TARGET_LONGEST_EDGE] pixels on the longest edge**, which puts the decoded
 * image in `[TARGET, 2 * TARGET)`. Choosing the other direction — the largest
 * number of halvings that stays under the target — would decode a 1025-px photo
 * to 512 px, throwing away half the detail to save a few MB that are not the
 * problem; this way the cost is bounded just as firmly (never more than
 * `2 * TARGET` on the longest edge, ~33 MB at the current value) while staying
 * as close as possible to the reference pipeline, which resizes the original
 * image once.
 *
 * [TARGET_LONGEST_EDGE] is deliberately **not** in the manifest. The manifest
 * describes the model — its resize, crop, mean and std — and this is a property
 * of the device's heap, so a data change must never be able to raise it.
 *
 * Kept free of `android.*` types (like [EncoderContract]) so the arithmetic runs
 * in a plain JVM test. The claim that it does not change the *answer* is measured
 * against the real graph on a device by `OnDevicePipelineTest.decodeCapParity`.
 */
object DecodeBounds {

    /** The decoded longest edge never falls below this, and never reaches twice it. */
    const val TARGET_LONGEST_EDGE = 1024

    /**
     * The smallest power-of-two `inSampleSize` whose longest edge is still at
     * least [targetEdge], so the decoded image lands in
     * `[targetEdge, 2 * targetEdge)`. `1` means "decode at full size" — also the
     * answer for a missing or nonsensical size, so a header that cannot be read
     * falls back to the behaviour that existed before this bound rather than to a
     * 1-px image.
     */
    fun sampleSizeFor(
        width: Int,
        height: Int,
        targetEdge: Int = TARGET_LONGEST_EDGE,
    ): Int {
        require(targetEdge > 0) { "targetEdge must be > 0, got $targetEdge" }
        if (width <= 0 || height <= 0) return 1
        var longest = maxOf(width, height)
        var sample = 1
        while (longest / 2 >= targetEdge) {
            longest /= 2
            sample *= 2
        }
        return sample
    }
}

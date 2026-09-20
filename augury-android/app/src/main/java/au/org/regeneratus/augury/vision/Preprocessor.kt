package au.org.regeneratus.augury.vision

import kotlin.math.abs
import kotlin.math.ceil
import kotlin.math.floor

/**
 * AUGURY — a decoded RGB image, without an Android dependency.
 *
 * `Bitmap.getPixels()` hands back ARGB_8888 ints; [fromArgb] turns those into
 * the packed RGB byte array the preprocessor wants. Keeping this type free of
 * `android.graphics` is what lets the whole pixel path run in a plain JVM unit
 * test — which is the only place it *can* run on a host with no emulator.
 */
class RgbImage(val width: Int, val height: Int, val rgb: ByteArray) {

    init {
        require(width > 0 && height > 0) { "image must not be empty ($width x $height)" }
        require(rgb.size == width * height * 3) {
            "expected ${width * height * 3} RGB bytes for ${width}x$height, got ${rgb.size}"
        }
    }

    companion object {
        /** From `Bitmap.getPixels(...)` output (ARGB_8888, alpha ignored). */
        fun fromArgb(pixels: IntArray, width: Int, height: Int): RgbImage {
            require(pixels.size >= width * height) {
                "expected at least ${width * height} pixels, got ${pixels.size}"
            }
            val rgb = ByteArray(width * height * 3)
            var out = 0
            for (i in 0 until width * height) {
                val p = pixels[i]
                rgb[out++] = ((p shr 16) and 0xFF).toByte()
                rgb[out++] = ((p shr 8) and 0xFF).toByte()
                rgb[out++] = (p and 0xFF).toByte()
            }
            return RgbImage(width, height, rgb)
        }

        /** From packed RGB bytes (the layout of a decoded JPEG in a test resource). */
        fun fromRgb(rgb: ByteArray, width: Int, height: Int): RgbImage =
            RgbImage(width, height, rgb)
    }
}

/**
 * AUGURY — the preprocessing half of protocol `vision.clip-token-l2-pca-knn-ip@1`.
 *
 * ```
 * resize shortest edge 256 (bicubic, aspect kept)
 *   -> center crop 224 x 224
 *   -> RGB, /255
 *   -> (x - mean) / std per channel
 *   -> CHW float32 tensor for `pixel_values`
 * ```
 *
 * Every parameter comes from [PreprocessSettings], which comes from the
 * manifest. Nothing in this file is a tunable constant.
 *
 * ## The resampling kernel
 *
 * The reference runs HuggingFace's DINOv2 image processor, which (on this
 * toolchain) resizes through `torchvision`'s antialiased bicubic. That kernel is
 * characterised exactly and ported here:
 *
 * * Catmull-Rom cubic, `a = -0.5`;
 * * `align_corners = false`, i.e. output pixel `o` samples input
 *   `(o + 0.5) * scale - 0.5`;
 * * antialiasing: for downscaling the kernel is stretched by `scale` (support
 *   `2 * scale`, argument `(x - center) / scale`); for upscaling the plain
 *   support-2 kernel is used;
 * * samples outside the image are dropped and the remaining weights
 *   renormalised.
 *
 * This was validated against `torchvision` itself on the host (see
 * `docs/vision-kotlin-verification.md`): <= 2.1e-05 max absolute difference on a
 * float32 resize, and the uint8 output agrees with the reference within 4 LSB on
 * 100% of pixels, 82% of them exact. The residual is torchvision's int16
 * fixed-point uint8 kernel, not a difference in the maths.
 *
 * Like `torchvision` on a uint8 input, the resized image is clamped to [0, 255]
 * and rounded before the crop; the rounding step matters because it is part of
 * the reference pipeline (a float that overshoots white is not allowed to
 * brighten the normalised tensor).
 */
class Preprocessor(val settings: PreprocessSettings) {

    init {
        settings.requireSupported()
    }

    /** The resized image size (w, h) this preprocessor will produce for [width] x [height]. */
    fun resizedSize(width: Int, height: Int): IntArray {
        val shortest = settings.resizeShortestEdge
        return if (width <= height) {
            intArrayOf(shortest, (shortest.toLong() * height / width).toInt())
        } else {
            intArrayOf((shortest.toLong() * width / height).toInt(), shortest)
        }
    }

    /** Full pipeline: pixels in, `[3, crop, crop]` CHW float32 out. */
    fun toTensor(image: RgbImage): FloatArray = toTensorFromCrop(resizeAndCropRgb(image))

    /**
     * Resize + center crop as uint8 HWC RGB, `crop * crop * 3` bytes. This is
     * the reference's intermediate image and the Kotlin/reference comparison
     * point in the parity test.
     */
    fun resizeAndCropRgb(image: RgbImage): ByteArray {
        val size = resizedSize(image.width, image.height)
        val outWidth = size[0]
        val outHeight = size[1]
        val resized = resize(image, outWidth, outHeight)
        val originX = ((outWidth - settings.crop) / 2.0).toInt()
        val originY = ((outHeight - settings.crop) / 2.0).toInt()
        require(originX >= 0 && originY >= 0) {
            "crop ${settings.crop} does not fit in the resized ${outWidth}x$outHeight image"
        }
        val crop = settings.crop
        val out = ByteArray(crop * crop * PreprocessSettings.CHANNELS)
        var outIndex = 0
        for (y in 0 until crop) {
            var src = ((originY + y) * outWidth + originX) * PreprocessSettings.CHANNELS
            for (x in 0 until crop) {
                out[outIndex++] = resized[src++]
                out[outIndex++] = resized[src++]
                out[outIndex++] = resized[src++]
            }
        }
        return out
    }

    /** `/255` then per-channel normalisation, HWC uint8 -> CHW float32. */
    fun toTensorFromCrop(croppedRgb: ByteArray): FloatArray {
        val crop = settings.crop
        val expected = crop * crop * PreprocessSettings.CHANNELS
        require(croppedRgb.size == expected) {
            "expected $expected bytes for a ${crop}x$crop RGB crop, got ${croppedRgb.size}"
        }
        val plane = crop * crop
        val out = FloatArray(PreprocessSettings.CHANNELS * plane)
        var src = 0
        for (i in 0 until plane) {
            for (c in 0 until PreprocessSettings.CHANNELS) {
                val value = (croppedRgb[src++].toInt() and 0xFF) / 255.0f
                out[c * plane + i] = (value - settings.mean[c]) / settings.std[c]
            }
        }
        return out
    }

    // ── resampling ───────────────────────────────────────────────────────────

    /**
     * Separable antialiased bicubic resize, unclamped float HWC (0..255 scale).
     *
     * Split out from [resizeAndCropRgb] because this is the part that must match
     * `torchvision`'s float kernel; the host parity test compares this output
     * directly against it (see `docs/vision-kotlin-verification.md`).
     */
    internal fun resizeToFloat(image: RgbImage, outWidth: Int, outHeight: Int): FloatArray {
        val channels = PreprocessSettings.CHANNELS
        val widthWeights = AxisWeights(image.width, outWidth)
        val heightWeights = AxisWeights(image.height, outHeight)

        // Pass 1: horizontal. Intermediate is float; only the final pass rounds.
        val horizontal = FloatArray(outWidth * image.height * channels)
        for (y in 0 until image.height) {
            val srcRow = y * image.width * channels
            val dstRow = y * outWidth * channels
            for (x in 0 until outWidth) {
                val start = widthWeights.start[x]
                val weights = widthWeights.weights[x]
                val dst = dstRow + x * channels
                for (c in 0 until channels) {
                    var sum = 0.0
                    var src = srcRow + start * channels + c
                    for (w in weights.indices) {
                        sum += weights[w].toDouble() * (image.rgb[src].toInt() and 0xFF)
                        src += channels
                    }
                    horizontal[dst + c] = sum.toFloat()
                }
            }
        }

        // Pass 2: vertical.
        val out = FloatArray(outWidth * outHeight * channels)
        var dst = 0
        for (y in 0 until outHeight) {
            val start = heightWeights.start[y]
            val weights = heightWeights.weights[y]
            for (x in 0 until outWidth) {
                for (c in 0 until channels) {
                    var sum = 0.0
                    var src = (start * outWidth + x) * channels + c
                    for (w in weights.indices) {
                        sum += weights[w].toDouble() * horizontal[src]
                        src += outWidth * channels
                    }
                    out[dst++] = sum.toFloat()
                }
            }
        }
        return out
    }

    /**
     * Resize then clamp and round to 8-bit — exactly what `torchvision` does when
     * its resized float tensor is cast back to a uint8 image.
     */
    private fun resize(image: RgbImage, outWidth: Int, outHeight: Int): ByteArray {
        val floats = resizeToFloat(image, outWidth, outHeight)
        return ByteArray(floats.size) { clampToByte(floats[it].toDouble()) }
    }

    private fun clampToByte(value: Double): Byte {
        val rounded = floor(value + 0.5)
        // The literals must be explicitly Byte: `0`/`255` are Int, and a `when`
        // mixing Int and Byte branches infers `Number & Comparable<*>`, which does
        // not satisfy the declared Byte return type.
        return when {
            rounded <= 0.0 -> 0.toByte()
            rounded >= 255.0 -> 255.toByte()
            else -> rounded.toInt().toByte()
        }
    }

    /**
     * Per-output-pixel source window and weights along one axis: the sparse form
     * of the dense weight matrix the host reference builds.
     */
    private class AxisWeights(inSize: Int, outSize: Int) {
        val start = IntArray(outSize)
        val weights = Array(outSize) { FloatArray(0) }

        init {
            val scale = inSize.toDouble() / outSize
            for (o in 0 until outSize) {
                val center = (o + 0.5) * scale - 0.5
                val support = if (scale >= 1.0) 2.0 * scale else 2.0
                val first = floor(center - support).toInt() + 1
                val last = ceil(center + support).toInt() - 1
                var sum = 0.0
                val values = ArrayList<Float>(last - first + 1)
                var index = first
                var writeIndex = -1
                while (index <= last) {
                    val argument = if (scale >= 1.0) (index - center) / scale else index - center
                    val weight = cubic(argument)
                    if (index in 0 until inSize) {
                        if (writeIndex < 0) writeIndex = index
                        values.add(weight.toFloat())
                        sum += weight
                    }
                    index++
                }
                if (writeIndex < 0 || sum == 0.0) {
                    throw VisionContractException(
                        "degenerate resize weights for $inSize -> $outSize at output $o"
                    )
                }
                val normalised = FloatArray(values.size)
                for (i in values.indices) normalised[i] = (values[i] / sum).toFloat()
                start[o] = writeIndex
                weights[o] = normalised
            }
        }

        /** Catmull-Rom cubic (`a = -0.5`), the kernel torchvision's AA mode uses. */
        private fun cubic(x: Double): Double {
            val a = -0.5
            val ax = abs(x)
            return when {
                ax <= 1.0 -> (a + 2) * ax * ax * ax - (a + 3) * ax * ax + 1.0
                ax < 2.0 -> a * ax * ax * ax - 5 * a * ax * ax + 8 * a * ax - 4 * a
                else -> 0.0
            }
        }
    }
}

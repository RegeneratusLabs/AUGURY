package au.org.regeneratus.augury.vision

import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.zip.ZipInputStream

/**
 * AUGURY — a reader for the two NumPy containers the vision index ships.
 *
 * The index tarball contains exactly three files this package cares about:
 *
 * * `embeddings.npy` — `16580 x 384` float32, C-order (the *post*-whitened gallery);
 * * `keys.json` — one species key per embedding row (plain JSON, see [KnnIndex]);
 * * `pca_whiten.npz` — a zipped pair `W.npy` (`768 x 384` float32), `mu.npy`
 *   (`768` float32), plus the scalars `dim` and `whiten`.
 *
 * `.npy` is a trivial format — magic, a Python-literal header, then raw
 * C-contiguous data — so the app parses it directly rather than taking a
 * dependency on a numerical library. Only the dtypes the index actually uses are
 * accepted (`<f4`, `<f8`, `<i8`, `<i4`, `<u1`); anything else fails loudly,
 * because a wrong dtype reading silently as floats is exactly the "plausible
 * garbage" failure the protocol gate exists to prevent.
 *
 * Nothing here is Android-specific: it runs in plain JVM unit tests.
 */
internal object Npy {

    /** One parsed array: shape, dtype tag, and the raw little-endian data bytes. */
    /**
     * One parsed array: shape, dtype tag, memory order, and the raw
     * little-endian data bytes.
     *
     * [fortranOrder] matters and is not a detail: numpy stored the shipped
     * `pca_whiten.npz`'s `W` (768x384) F-contiguous, so its bytes are
     * **column-major**. Reading them as row-major silently *transposes* the PCA
     * matrix, which would produce a plausible-looking but wrong embedding for
     * every photo. The accessors below normalise to C order so callers cannot
     * make that mistake.
     */
    class Raw(
        val descr: String,
        val shape: IntArray,
        val data: ByteArray,
        val fortranOrder: Boolean = false,
    ) {

        /** Total element count implied by [shape]. */
        val size: Int = shape.fold(1) { acc, d -> acc * d }

        val rows: Int get() = if (shape.size == 2) shape[0] else if (shape.size == 1) shape[0] else 1
        val cols: Int get() = if (shape.size == 2) shape[1] else 1

        /**
         * Where element `i` of the **C-order** sequence lives in the raw byte
         * sequence.
         *
         * An F-contiguous 2-D array stores its data column by column, so logical
         * `[row][col]` sits at flat `col * rows + row`. Element `i` of the C-order
         * sequence is logical `[i / cols][i % cols]`, which therefore lives at
         * `(i % cols) * rows + i / cols`.
         *
         * (The inverse mapping — `(i % rows) * cols + i / rows` — transposes in
         * the wrong direction and yields a plausible but incorrect matrix. That
         * was a real bug: it produced a whitened query 0.28 away from the
         * reference instead of matching to 3e-8.)
         */
        private fun cOrderIndex(i: Int): Int {
            if (!fortranOrder || shape.size != 2) return i
            val r = rows
            val c = cols
            return (i % c) * r + (i / c)
        }

        /**
         * The data as a flat float32 array in C order.
         *
         * `<f4` is read directly; `<f8` is narrowed (the index stores its PCA
         * matrices as float32, but a future build may not). Integer dtypes are
         * rejected here — call [asLongs] for those — so a type mix-up cannot be
         * mistaken for valid features.
         */
        fun asFloats(context: String): FloatArray {
            val buffer = ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN)
            return when (descr) {
                "<f4" -> FloatArray(size) {
                    buffer.position(cOrderIndex(it) * 4); buffer.float
                }
                "<f8" -> FloatArray(size) {
                    buffer.position(cOrderIndex(it) * 8); buffer.double.toFloat()
                }
                else -> throw VisionContractException(
                    "$context: expected a float array but the dtype is '$descr'"
                )
            }
        }

        /** The data as a flat long array (for integer scalars such as `dim`). */
        fun asLongs(context: String): LongArray {
            val buffer = ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN)
            return when (descr) {
                "<i8" -> LongArray(size) {
                    buffer.position(cOrderIndex(it) * 8); buffer.long
                }
                "<i4" -> LongArray(size) {
                    buffer.position(cOrderIndex(it) * 4); buffer.int.toLong()
                }
                else -> throw VisionContractException(
                    "$context: expected an integer array but the dtype is '$descr'"
                )
            }
        }
    }

    private val MAGIC = byteArrayOf(0x93.toByte(), 'N'.code.toByte(), 'U'.code.toByte(),
        'M'.code.toByte(), 'P'.code.toByte(), 'Y'.code.toByte())

    /** Parse a `.npy` byte array. */
    fun parse(bytes: ByteArray, context: String): Raw {
        if (bytes.size < 10) throw VisionContractException("$context: too short to be a .npy file")
        for (i in MAGIC.indices) {
            if (bytes[i] != MAGIC[i]) throw VisionContractException("$context: bad .npy magic")
        }
        val major = bytes[6].toInt()
        val headerLength: Int
        val headerStart: Int
        when (major) {
            1 -> {
                headerLength = (bytes[8].toInt() and 0xFF) or ((bytes[9].toInt() and 0xFF) shl 8)
                headerStart = 10
            }
            2, 3 -> {
                if (bytes.size < 12) throw VisionContractException("$context: truncated .npy header")
                headerLength = (bytes[8].toInt() and 0xFF) or
                    ((bytes[9].toInt() and 0xFF) shl 8) or
                    ((bytes[10].toInt() and 0xFF) shl 16) or
                    ((bytes[11].toInt() and 0xFF) shl 24)
                headerStart = 12
            }
            else -> throw VisionContractException("$context: unsupported .npy version $major")
        }
        if (headerLength <= 0 || headerStart + headerLength > bytes.size) {
            throw VisionContractException("$context: corrupt .npy header length $headerLength")
        }
        val header = String(bytes, headerStart, headerLength, Charsets.US_ASCII)
        val descr = stringField(header, "'descr'", context)
        val fortran = boolField(header, "'fortran_order'", context)
        val shape = intListField(header, "'shape'", context)
        val dataStart = headerStart + headerLength
        val data = bytes.copyOfRange(dataStart, bytes.size)
        // Fortran order is carried on the Raw rather than rejected: the shipped
        // pca_whiten.npz stores W F-contiguous, and the accessors transpose it
        // back to C order so callers never see a silently swapped matrix.
        val raw = Raw(descr, shape, data, fortranOrder = fortran)
        val expectedBytes = raw.size * bytesPerElement(descr, context)
        if (data.size < expectedBytes) {
            throw VisionContractException(
                "$context: truncated data — header declares ${raw.size} elements " +
                    "($expectedBytes bytes) but only ${data.size} bytes follow"
            )
        }
        return raw
    }

    /**
     * Read one named member out of an `.npz` (a plain zip of `.npy` members).
     *
     * Returns null when the archive has no such member, so the caller can decide
     * whether that is fatal.
     */
    fun parseNpzMember(npz: ByteArray, member: String, context: String): Raw? {
        ZipInputStream(ByteArrayInputStream(npz)).use { zip ->
            while (true) {
                val entry = zip.nextEntry ?: return null
                if (entry.name == member) {
                    return parse(readAll(zip), "$context/$member")
                }
            }
        }
    }

    /** Names of the members of an `.npz`, in archive order. */
    fun npzMembers(npz: ByteArray): List<String> {
        val out = ArrayList<String>()
        ZipInputStream(ByteArrayInputStream(npz)).use { zip ->
            while (true) {
                val entry = zip.nextEntry ?: return out
                out.add(entry.name)
            }
        }
    }

    private fun readAll(zip: ZipInputStream): ByteArray {
        val out = ByteArrayOutputStream(1 shl 16)
        val buffer = ByteArray(1 shl 16)
        while (true) {
            val read = zip.read(buffer)
            if (read < 0) break
            out.write(buffer, 0, read)
        }
        return out.toByteArray()
    }

    private fun bytesPerElement(descr: String, context: String): Int = when (descr) {
        "<f4", "<i4" -> 4
        "<f8", "<i8" -> 8
        "<u1", "|u1" -> 1
        else -> throw VisionContractException("$context: unsupported dtype '$descr'")
    }

    // ── header field extraction ──────────────────────────────────────────────
    // The header is a Python dict literal; the three keys this reader needs are
    // always present and always spelled the same way by numpy.

    private fun stringField(header: String, key: String, context: String): String {
        val at = header.indexOf(key)
        if (at < 0) throw VisionContractException("$context: header has no $key")
        val colon = header.indexOf(':', at)
        val open = header.indexOf('\'', colon + 1)
        val close = header.indexOf('\'', open + 1)
        if (colon < 0 || open < 0 || close < 0) {
            throw VisionContractException("$context: malformed $key in header")
        }
        return header.substring(open + 1, close)
    }

    private fun boolField(header: String, key: String, context: String): Boolean {
        val at = header.indexOf(key)
        if (at < 0) throw VisionContractException("$context: header has no $key")
        val colon = header.indexOf(':', at)
        val value = header.substring(colon + 1).trimStart()
        return when {
            value.startsWith("True") -> true
            value.startsWith("False") -> false
            else -> throw VisionContractException("$context: malformed $key in header")
        }
    }

    private fun intListField(header: String, key: String, context: String): IntArray {
        val at = header.indexOf(key)
        if (at < 0) throw VisionContractException("$context: header has no $key")
        val open = header.indexOf('(', at)
        val close = header.indexOf(')', open + 1)
        if (open < 0 || close < 0) throw VisionContractException("$context: malformed $key in header")
        val inner = header.substring(open + 1, close).trim()
        if (inner.isEmpty()) return IntArray(0)
        // numpy writes a 1-element shape as `(768,)`, and a 0-d scalar as `()`.
        // The trailing comma yields an empty part, which is not an error — drop
        // empty parts rather than rejecting the array.
        return inner.split(',')
            .map { it.trim() }
            .filter { it.isNotEmpty() }
            .map { part ->
                part.toIntOrNull()
                    ?: throw VisionContractException("$context: malformed $key entry '$part'")
            }
            .toIntArray()
    }
}

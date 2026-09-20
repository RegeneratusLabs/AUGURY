package au.org.regeneratus.augury.artifacts

import java.io.InputStream
import java.nio.file.Files
import java.nio.file.Path
import java.security.MessageDigest

/**
 * AUGURY — streaming SHA-256.
 *
 * The artifact pipeline's only integrity primitive: every byte that reaches a
 * generation directory has passed through [ofFile] and matched the manifest.
 * Hashing is streamed with a 1 MiB buffer, so verifying the 688 MB formatter
 * costs a linear read and no meaningful heap (`docs/mobile-app-decision.md` §5).
 *
 * Deliberately hand-rolled hex rather than `java.util.HexFormat`: that class is
 * Java 17 and is not present on Android's runtime, and this file must run on
 * both the device and a plain JVM unit test.
 */
object Sha256 {

    /** Read size for file/stream hashing. Large enough that syscall overhead vanishes. */
    const val BUFFER_BYTES: Int = 1 shl 20

    private val HEX = "0123456789abcdef".toCharArray()

    fun hex(bytes: ByteArray): String = hex(bytes, 0, bytes.size)

    fun hex(bytes: ByteArray, offset: Int, length: Int): String {
        val out = CharArray(length * 2)
        var i = offset
        var j = 0
        val end = offset + length
        while (i < end) {
            val b = bytes[i].toInt() and 0xff
            out[j++] = HEX[b ushr 4]
            out[j++] = HEX[b and 0x0f]
            i++
        }
        return String(out)
    }

    /**
     * Hex digest of an in-memory array.
     *
     * Distinct from [hex], which merely *encodes* arbitrary bytes as hex. Using
     * [hex] where a digest is meant silently produces a longer non-digest string —
     * which the manifest parser then rejects, correctly, as "not a 64-character
     * hex SHA-256".
     */
    fun of(bytes: ByteArray): String =
        hex(MessageDigest.getInstance("SHA-256").digest(bytes))

    /** Hex digest of a file, read in [BUFFER_BYTES] chunks. */
    fun ofFile(path: Path): String {
        val digest = MessageDigest.getInstance("SHA-256")
        val buffer = ByteArray(BUFFER_BYTES)
        Files.newInputStream(path).use { input ->
            while (true) {
                val read = input.read(buffer)
                if (read < 0) break
                digest.update(buffer, 0, read)
            }
        }
        return hex(digest.digest())
    }

    fun ofStream(input: InputStream): String {
        val digest = MessageDigest.getInstance("SHA-256")
        val buffer = ByteArray(BUFFER_BYTES)
        while (true) {
            val read = input.read(buffer)
            if (read < 0) break
            digest.update(buffer, 0, read)
        }
        return hex(digest.digest())
    }
}

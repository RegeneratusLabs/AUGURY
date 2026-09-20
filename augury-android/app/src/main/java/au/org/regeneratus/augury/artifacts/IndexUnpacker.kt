package au.org.regeneratus.augury.artifacts

import org.apache.commons.compress.archivers.tar.TarArchiveEntry
import org.apache.commons.compress.archivers.tar.TarArchiveInputStream
import java.nio.file.Files
import java.nio.file.Path
import java.util.zip.GZIPInputStream

/**
 * AUGURY — index tarball unpacking.
 *
 * The retrieval index ships as a gzipped tar (`vision-index-v3.tar.gz`) holding
 * `embeddings.npy`, `keys.json`, `pca_whiten.npz` and `band_config.json`.
 * `java.util.zip` supplies the gzip half; commons-compress (already declared in
 * `app/build.gradle.kts`) supplies the tar reader.
 *
 * TWO RULES ARE ENFORCED HERE
 * ---------------------------
 * 1. **No `index.faiss`, ever.** The app does brute-force kNN over ~16.6k × 384
 *    floats in plain Kotlin; FAISS is deliberately not a dependency and
 *    `scripts/app/publish_app_hf.sh` refuses to publish a tarball containing it.
 *    An archive that carries it is a hard error here too — silently ignoring it
 *    would hide a publish-side regression and waste 20 MB on every phone.
 *    (Hard constraint §8 item 9.)
 * 2. **Nothing escapes the destination.** Entry names are validated the way a
 *    tar extractor must: no absolute paths, no `..`, no backslashes, no drive
 *    letters, and no symlink/hardlink entries. A malicious or corrupted archive
 *    cannot write outside the generation directory.
 *
 * Unpacking happens *after* the tarball's SHA-256 has matched the manifest, into
 * a scratch directory that is only moved into the generation directory when the
 * whole archive extracted cleanly. A truncated tarball therefore leaves no
 * half-generation behind.
 */
class IndexUnpacker(
    /** Entry names (or basenames) that must never appear in an index archive. */
    private val forbiddenEntries: Set<String> = DEFAULT_FORBIDDEN_ENTRIES,
    private val maxEntries: Int = DEFAULT_MAX_ENTRIES,
    private val maxTotalBytes: Long = DEFAULT_MAX_TOTAL_BYTES,
    private val bufferBytes: Int = DEFAULT_BUFFER_BYTES,
) {

    /**
     * Extracts [archive] into [destination], which is created.
     *
     * @return the relative names of the files written, in archive order.
     * @throws IndexUnpackException on a forbidden entry, an unsafe path, a
     *   malformed archive, or a breach of the size/entry caps.
     */
    fun unpack(archive: Path, destination: Path): List<String> {
        if (!Files.isRegularFile(archive)) {
            throw IndexUnpackException("index archive $archive does not exist")
        }
        if (Files.exists(destination)) {
            // Never merge into an existing tree: a stale file could survive and
            // be loaded with the new generation.
            GenerationStore.deleteRecursively(destination)
        }
        Files.createDirectories(destination)

        val written = ArrayList<String>()
        var totalBytes = 0L

        try {
            GZIPInputStream(Files.newInputStream(archive), bufferBytes).use { gzip ->
                TarArchiveInputStream(gzip).use { tar ->
                    while (true) {
                        val entry = tar.nextEntry ?: break
                        val name = entry.name ?: throw IndexUnpackException("index archive has an entry with no name")
                        checkForbidden(name)
                        if (written.size >= maxEntries) {
                            throw IndexUnpackException(
                                "index archive has more than $maxEntries entries; refusing to unpack"
                            )
                        }
                        val target = resolveEntry(destination, name, entry)
                        if (target == null) continue // directory entry, already created

                        val declared = entry.size
                        if (declared < 0 || totalBytes + declared > maxTotalBytes) {
                            throw IndexUnpackException(
                                "index archive expands beyond the $maxTotalBytes byte limit; refusing to unpack"
                            )
                        }
                        Files.createDirectories(target.parent)
                        Files.newOutputStream(target).use { out ->
                            val buffer = ByteArray(bufferBytes)
                            while (true) {
                                val read = tar.read(buffer)
                                if (read < 0) break
                                totalBytes += read
                                if (totalBytes > maxTotalBytes) {
                                    throw IndexUnpackException(
                                        "index archive expands beyond the $maxTotalBytes byte limit; refusing to unpack"
                                    )
                                }
                                out.write(buffer, 0, read)
                            }
                        }
                        if (Files.size(target) != declared) {
                            throw IndexUnpackException(
                                "index archive entry \"$name\" is truncated: ${Files.size(target)} of $declared bytes"
                            )
                        }
                        written += name
                    }
                }
            }
        } catch (e: IndexUnpackException) {
            GenerationStore.deleteRecursively(destination)
            throw e
        } catch (e: Exception) {
            GenerationStore.deleteRecursively(destination)
            throw IndexUnpackException("could not unpack index archive $archive: ${e.message}", e)
        }

        if (written.isEmpty()) {
            GenerationStore.deleteRecursively(destination)
            throw IndexUnpackException("index archive $archive contains no files")
        }
        return written
    }

    private fun checkForbidden(name: String) {
        val lower = name.lowercase()
        val base = lower.substringAfterLast('/')
        for (forbidden in forbiddenEntries) {
            val needle = forbidden.lowercase()
            if (lower == needle || base == needle) {
                throw IndexUnpackException(
                    "refusing to unpack the index archive: it contains \"$name\". " +
                        "$needle is deliberately excluded — the app performs brute-force kNN in Kotlin " +
                        "and must not ship FAISS. Re-publish the index with " +
                        "scripts/app/publish_app_hf.sh, which rejects this archive too."
                )
            }
        }
    }

    /** @return the file to write, or `null` when the entry was a directory. */
    private fun resolveEntry(destination: Path, name: String, entry: TarArchiveEntry): Path? {
        if (name.isEmpty()) throw IndexUnpackException("index archive has an entry with an empty name")
        if (name.startsWith("/") || name.startsWith("\\")) {
            throw IndexUnpackException("index archive entry \"$name\" is an absolute path")
        }
        if (name.contains('\\') || name.contains('\u0000')) {
            throw IndexUnpackException("index archive entry \"$name\" contains an illegal character")
        }
        if (Regex("^[A-Za-z]:").containsMatchIn(name)) {
            throw IndexUnpackException("index archive entry \"$name\" looks like a Windows absolute path")
        }
        if (entry.isSymbolicLink || entry.isLink) {
            throw IndexUnpackException("index archive entry \"$name\" is a link, which is not accepted")
        }
        val normalized = destination.resolve(name).normalize()
        if (!normalized.startsWith(destination.normalize())) {
            throw IndexUnpackException("index archive entry \"$name\" escapes the destination directory")
        }
        if (entry.isDirectory) {
            Files.createDirectories(normalized)
            return null
        }
        return normalized
    }

    companion object {
        /**
         * The FAISS index is intentionally absent from the published tarball —
         * see `docs/mobile-app-decision.md` §5 and hard constraint §8 item 9.
         */
        val DEFAULT_FORBIDDEN_ENTRIES: Set<String> = setOf("index.faiss")

        const val DEFAULT_MAX_ENTRIES = 4096
        /** 2 GiB: far above the ~42 MB real index, far below "fills the phone". */
        const val DEFAULT_MAX_TOTAL_BYTES = 2147483648L
        const val DEFAULT_BUFFER_BYTES = 64 * 1024
    }
}

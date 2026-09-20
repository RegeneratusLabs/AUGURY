package au.org.regeneratus.augury.artifacts

import org.apache.commons.compress.archivers.tar.TarArchiveEntry
import org.apache.commons.compress.archivers.tar.TarArchiveOutputStream
import org.apache.commons.compress.archivers.tar.TarConstants
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.io.ByteArrayOutputStream
import java.nio.file.Files
import java.util.zip.GZIPOutputStream

/**
 * Index unpacking: the four published entries must land intact, and the two
 * things the pipeline must refuse — `index.faiss` and anything that would write
 * outside the destination — must be refused.
 */
class IndexUnpackerTest {

    @Test
    fun `unpacks the published index layout`() {
        TempDir().use { temp ->
            val archive = temp.resolve("vision-index-v3.tar.gz")
            val entries = indexEntries()
            Files.write(archive, tarGz(entries))
            val destination = temp.resolve("generation")

            val written = IndexUnpacker().unpack(archive, destination)

            assertEquals(entries.keys.toList(), written)
            for ((name, bytes) in entries) {
                assertTrue("$name missing", Files.isRegularFile(destination.resolve(name)))
                assertTrue("$name differs", Files.readAllBytes(destination.resolve(name)).contentEquals(bytes))
            }
            assertFalse(Files.exists(destination.resolve("index.faiss")))
        }
    }

    @Test
    fun `rejects a tarball that contains index faiss`() {
        TempDir().use { temp ->
            val archive = temp.resolve("bad.tar.gz")
            val entries = indexEntries()
            entries["index.faiss"] = ByteArray(32)
            Files.write(archive, tarGz(entries))
            val destination = temp.resolve("generation")

            try {
                IndexUnpacker().unpack(archive, destination)
                fail("expected IndexUnpackException")
            } catch (e: IndexUnpackException) {
                assertTrue(e.message!!, e.message!!.contains("index.faiss is deliberately excluded"))
                assertTrue(e.message!!, e.message!!.contains("brute-force kNN"))
            }
            assertFalse("a refused archive must leave nothing behind", Files.exists(destination))
        }
    }

    @Test
    fun `rejects a nested index faiss`() {
        TempDir().use { temp ->
            val archive = temp.resolve("bad.tar.gz")
            val entries = indexEntries()
            entries["sub/dir/index.faiss"] = ByteArray(32)
            Files.write(archive, tarGz(entries))

            try {
                IndexUnpacker().unpack(archive, temp.resolve("generation"))
                fail("expected IndexUnpackException")
            } catch (e: IndexUnpackException) {
                assertTrue(e.message!!, e.message!!.contains("index.faiss"))
            }
        }
    }

    @Test
    fun `rejects an entry that escapes the destination`() {
        TempDir().use { temp ->
            val archive = temp.resolve("evil.tar.gz")
            val entries = LinkedHashMap<String, ByteArray>()
            entries["../escaped.txt"] = "owned".toByteArray()
            Files.write(archive, tarGz(entries))
            val destination = temp.resolve("nested/generation")

            try {
                IndexUnpacker().unpack(archive, destination)
                fail("expected IndexUnpackException")
            } catch (e: IndexUnpackException) {
                assertTrue(e.message!!, e.message!!.contains("escapes the destination"))
            }
            assertFalse(Files.exists(temp.resolve("nested/escaped.txt")))
        }
    }

    @Test
    fun `rejects an absolute entry path`() {
        TempDir().use { temp ->
            val archive = temp.resolve("evil.tar.gz")
            val entries = LinkedHashMap<String, ByteArray>()
            entries["/tmp/escaped.txt"] = "owned".toByteArray()
            Files.write(archive, tarGz(entries))

            try {
                IndexUnpacker().unpack(archive, temp.resolve("generation"))
                fail("expected IndexUnpackException")
            } catch (e: IndexUnpackException) {
                assertTrue(e.message!!, e.message!!.contains("absolute path"))
            }
        }
    }

    @Test
    fun `rejects a symlink entry`() {
        TempDir().use { temp ->
            val archive = temp.resolve("evil.tar.gz")
            Files.write(archive, tarGzWithSymlink())
            val destination = temp.resolve("generation")

            try {
                IndexUnpacker().unpack(archive, destination)
                fail("expected IndexUnpackException")
            } catch (e: IndexUnpackException) {
                assertTrue(e.message!!, e.message!!.contains("link"))
            }
            assertFalse(Files.exists(destination.resolve("sneaky.txt")))
        }
    }

    @Test
    fun `rejects an archive with no files`() {
        TempDir().use { temp ->
            val archive = temp.resolve("empty.tar.gz")
            Files.write(archive, tarGz(emptyMap()))

            try {
                IndexUnpacker().unpack(archive, temp.resolve("generation"))
                fail("expected IndexUnpackException")
            } catch (e: IndexUnpackException) {
                assertTrue(e.message!!, e.message!!.contains("contains no files"))
            }
        }
    }

    @Test
    fun `rejects an archive beyond the entry cap`() {
        TempDir().use { temp ->
            val archive = temp.resolve("many.tar.gz")
            Files.write(archive, tarGz(indexEntries()))

            try {
                IndexUnpacker(maxEntries = 2).unpack(archive, temp.resolve("generation"))
                fail("expected IndexUnpackException")
            } catch (e: IndexUnpackException) {
                assertTrue(e.message!!, e.message!!.contains("more than 2 entries"))
            }
        }
    }

    @Test
    fun `rejects an archive beyond the expanded size cap`() {
        TempDir().use { temp ->
            val archive = temp.resolve("big.tar.gz")
            Files.write(archive, tarGz(indexEntries()))

            try {
                IndexUnpacker(maxTotalBytes = 512).unpack(archive, temp.resolve("generation"))
                fail("expected IndexUnpackException")
            } catch (e: IndexUnpackException) {
                assertTrue(e.message!!, e.message!!.contains("limit"))
            }
            assertFalse(Files.exists(temp.resolve("generation")))
        }
    }

    @Test
    fun `rejects something that is not a tar gz at all`() {
        TempDir().use { temp ->
            val archive = temp.resolve("junk.tar.gz")
            Files.write(archive, "this is not gzip".toByteArray())

            try {
                IndexUnpacker().unpack(archive, temp.resolve("generation"))
                fail("expected IndexUnpackException")
            } catch (e: IndexUnpackException) {
                assertTrue(e.message!!, e.message!!.contains("could not unpack"))
            }
        }
    }

    @Test
    fun `unpacking into an existing directory replaces it rather than merging`() {
        TempDir().use { temp ->
            val archive = temp.resolve("index.tar.gz")
            Files.write(archive, tarGz(indexEntries()))
            val destination = temp.resolve("generation")
            Files.createDirectories(destination)
            Files.write(destination.resolve("stale.txt"), "old".toByteArray())

            IndexUnpacker().unpack(archive, destination)

            assertFalse("a stale file must not survive into a new generation", Files.exists(destination.resolve("stale.txt")))
        }
    }

    private fun tarGzWithSymlink(): ByteArray {
        val bytes = ByteArrayOutputStream()
        GZIPOutputStream(bytes).use { gzip ->
            TarArchiveOutputStream(gzip).use { tar ->
                tar.putArchiveEntry(TarArchiveEntry("sneaky.txt", TarConstants.LF_SYMLINK).apply {
                    linkName = "/etc/passwd"
                })
                tar.closeArchiveEntry()
                val entry = TarArchiveEntry("keys.json")
                val data = "{}".toByteArray()
                entry.size = data.size.toLong()
                tar.putArchiveEntry(entry)
                tar.write(data)
                tar.closeArchiveEntry()
            }
        }
        return bytes.toByteArray()
    }
}

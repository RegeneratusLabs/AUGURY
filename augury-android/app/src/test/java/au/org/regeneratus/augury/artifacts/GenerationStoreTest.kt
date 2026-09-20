package au.org.regeneratus.augury.artifacts

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.nio.file.Files
import java.nio.file.Path

/**
 * The generation store is where "a partial download must never be promoted"
 * becomes structural: a generation directory is only loadable once it carries a
 * completion record *and* its id is in the `current` pointer, and promotion is
 * only reachable after SHA-256 verification.
 */
class GenerationStoreTest {

    private val payload = "PAYLOAD-BYTES".toByteArray()

    @Test
    fun `a promoted generation must carry a completion record`() {
        TempDir().use { temp ->
            val store = GenerationStore(temp.resolve("artifacts"))
            Files.createDirectories(store.generationDir("formatter", "gen1"))

            try {
                store.promote("formatter", "gen1")
                fail("expected GenerationMissingException")
            } catch (e: GenerationMissingException) {
                assertTrue(e.message!!, e.message!!.contains("no artifact.json record"))
            }
            assertNull(store.currentGeneration("formatter"))
            assertNull(store.resolveCurrent("formatter"))
        }
    }

    @Test
    fun `a completed generation stays invisible until the pointer flips`() {
        TempDir().use { temp ->
            val store = GenerationStore(temp.resolve("artifacts"))
            complete(store, "formatter", "gen1")

            assertNull("no pointer, no load", store.currentGeneration("formatter"))
            assertNull(store.resolveCurrent("formatter"))

            store.promote("formatter", "gen1")

            assertEquals("gen1", store.currentGeneration("formatter"))
            assertEquals(store.generationDir("formatter", "gen1"), store.resolveCurrent("formatter"))
        }
    }

    @Test
    fun `the pointer file contains exactly the generation id and no temp file survives`() {
        TempDir().use { temp ->
            val store = GenerationStore(temp.resolve("artifacts"))
            complete(store, "facts", "genA")
            store.promote("facts", "genA")

            val pointer = store.currentPointerFile("facts")
            assertEquals("genA", String(Files.readAllBytes(pointer), Charsets.UTF_8))
            assertFalse(Files.exists(pointer.resolveSibling("current.tmp")))
        }
    }

    @Test
    fun `the previous generation is retained for rollback and older ones are pruned`() {
        TempDir().use { temp ->
            val store = GenerationStore(temp.resolve("artifacts"))

            for (generation in listOf("gen1", "gen2", "gen3")) {
                complete(store, "formatter", generation)
                store.promote("formatter", generation)
            }

            assertEquals("gen3", store.currentGeneration("formatter"))
            assertEquals("gen2", store.previousGeneration("formatter"))
            assertTrue(Files.isDirectory(store.generationDir("formatter", "gen2")))
            assertFalse("a third generation is 688 MB of dead weight", Files.exists(store.generationDir("formatter", "gen1")))
            assertEquals(listOf("gen2", "gen3"), store.listGenerations("formatter"))
        }
    }

    @Test
    fun `pruning never touches in-progress staging state`() {
        TempDir().use { temp ->
            val store = GenerationStore(temp.resolve("artifacts"))
            complete(store, "vision-index", "gen1")
            store.promote("vision-index", "gen1")
            val part = store.partFile("vision-index", "gen2")
            Files.createDirectories(part.parent)
            Files.write(part, ByteArray(1024))

            complete(store, "vision-index", "gen2")
            store.promote("vision-index", "gen2")

            assertTrue("deleting a part file would defeat resume", Files.exists(part))
        }
    }

    @Test
    fun `promoting the generation that is already current is a no-op`() {
        TempDir().use { temp ->
            val store = GenerationStore(temp.resolve("artifacts"))
            // Complete-and-promote one generation at a time. `promote` prunes
            // everything that is neither `current` nor `previous`, so a second
            // generation that is merely *completed* before the first promotion is
            // (correctly) deleted as dead weight and cannot be promoted later.
            complete(store, "facts", "gen1")
            store.promote("facts", "gen1")
            complete(store, "facts", "gen2")
            store.promote("facts", "gen2")

            val promotion = store.promote("facts", "gen2")

            assertFalse(promotion.pointerMoved)
            assertEquals("gen2", promotion.generation)
            assertEquals("gen1", promotion.previous)
            assertTrue(Files.isDirectory(store.generationDir("facts", "gen1")))
        }
    }

    @Test
    fun `rollback swaps current and previous without any download`() {
        TempDir().use { temp ->
            val store = GenerationStore(temp.resolve("artifacts"))
            // See the note above: each generation must be promoted before the next
            // one is completed, or pruning reclaims it.
            complete(store, "formatter", "gen1")
            store.promote("formatter", "gen1")
            complete(store, "formatter", "gen2")
            store.promote("formatter", "gen2")

            val restored = store.rollback("formatter")

            assertEquals("gen1", restored)
            assertEquals("gen1", store.currentGeneration("formatter"))
            assertEquals("gen2", store.previousGeneration("formatter"))
            assertTrue(Files.isDirectory(store.generationDir("formatter", "gen1")))
        }
    }

    @Test
    fun `rollback with nothing retained returns null`() {
        TempDir().use { temp ->
            val store = GenerationStore(temp.resolve("artifacts"))
            complete(store, "formatter", "gen1")
            store.promote("formatter", "gen1")

            assertNull(store.rollback("formatter"))
            assertEquals("gen1", store.currentGeneration("formatter"))
        }
    }

    @Test
    fun `a corrupt completion record makes the generation unloadable`() {
        TempDir().use { temp ->
            val store = GenerationStore(temp.resolve("artifacts"))
            complete(store, "formatter", "gen1")
            store.promote("formatter", "gen1")

            Files.write(
                store.generationDir("formatter", "gen1").resolve(GenerationStore.RECORD_FILE),
                "not json".toByteArray(),
            )

            assertNull("an unreadable record must never be trusted", store.resolveCurrent("formatter"))
            try {
                store.promote("formatter", "gen1")
                fail("expected GenerationMissingException")
            } catch (_: GenerationMissingException) {
                // expected
            }
        }
    }

    @Test
    fun `a pointer that is not a plain directory name is ignored`() {
        TempDir().use { temp ->
            val store = GenerationStore(temp.resolve("artifacts"))
            Files.createDirectories(store.currentPointerFile("formatter").parent)
            Files.write(store.currentPointerFile("formatter"), "../../etc".toByteArray())

            assertNull(store.currentGeneration("formatter"))
        }
    }

    @Test
    fun `an unsafe generation id is refused before it becomes a path`() {
        TempDir().use { temp ->
            val store = GenerationStore(temp.resolve("artifacts"))
            try {
                store.generationDir("formatter", "../escape")
                fail("expected ArtifactException")
            } catch (e: ArtifactException) {
                assertTrue(e.message!!, e.message!!.contains("invalid generation"))
            }
        }
    }

    @Test
    fun `prune keeps exactly current and previous and deletes everything else`() {
        TempDir().use { temp ->
            val store = GenerationStore(temp.resolve("artifacts"))
            for (generation in listOf("gen1", "gen2", "gen3", "gen4")) {
                complete(store, "facts", generation)
                store.promote("facts", generation)
            }

            store.prune("facts")

            assertEquals(listOf("gen3", "gen4"), store.listGenerations("facts"))
        }
    }

    private fun complete(store: GenerationStore, name: String, generation: String) {
        val dir = store.generationDir(name, generation)
        Files.createDirectories(dir)
        Files.write(store.payloadPath(dir), payload)
        GenerationRecord.write(
            dir,
            GenerationRecord(
                name = name,
                generation = generation,
                sha256 = Sha256.of(payload),
                bytes = payload.size.toLong(),
                protocol = "test.protocol@1",
                repo = "test/repo",
                path = "payload.bin",
                revision = null,
                unpack = false,
                entries = listOf("payload.bin"),
            ),
        )
    }

    private fun GenerationStore.payloadPath(dir: Path): Path = dir.resolve("payload.bin")
}

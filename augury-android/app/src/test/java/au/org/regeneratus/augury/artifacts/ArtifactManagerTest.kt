package au.org.regeneratus.augury.artifacts

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.nio.file.Files
import java.nio.file.Path

/**
 * The pipeline end to end, on a pure JVM: a fake HTTP server, a fake network, a
 * temp filesystem root. Every security-critical invariant from §8 item 6 is
 * asserted by its **observable consequence** — what is on disk and what the
 * pointer says afterwards — rather than by inspecting internals:
 *
 * * a corrupted body fails SHA-256 and is not promoted;
 * * a truncated body is not promoted (and the partial is kept for resume);
 * * a resumed download produces the correct hash and is promoted;
 * * a manifest this shell cannot execute downloads nothing;
 * * a tampered manifest is rejected at fetch time.
 */
class ArtifactManagerTest {

    @Test
    fun `installs every artifact, verifies it and flips every pointer`() {
        TempDir().use { temp ->
            val harness = Harness(temp)
            val bundle = TestFixtures.bundle()
            harness.serve(bundle)

            val result = harness.manager.install(bundle.manifest, bundle.source)

            assertEquals(4, result.artifacts.size)
            assertEquals(4, result.downloaded.size)
            assertTrue("network bytes should be counted", result.bytesDownloaded > 0)
            assertEquals(
                listOf("formatter", "facts", "vision-index", "vision-encoder-dinov2-base-fp32"),
                result.artifacts.map { it.artifact.name },
            )

            // Plain payloads land under their published filename.
            val formatter = harness.manager.activeDirectory("formatter")!!
            assertTrue(
                Files.readAllBytes(formatter.resolve("MiniCPM5-1B-AUGURY-Q4_K_M.gguf"))
                    .contentEquals("FORMATTER-BYTES".toByteArray()),
            )
            val facts = harness.manager.activeDirectory("facts")!!
            assertTrue(
                Files.readAllBytes(facts.resolve("augury-ondevice.json"))
                    .contentEquals("FACTS-BYTES".toByteArray()),
            )

            // The tarball is unpacked, not kept.
            val index = harness.manager.activeDirectory("vision-index")!!
            assertTrue(Files.isRegularFile(index.resolve("embeddings.npy")))
            assertTrue(Files.isRegularFile(index.resolve("keys.json")))
            assertTrue(Files.isRegularFile(index.resolve("pca_whiten.npz")))
            assertTrue(Files.isRegularFile(index.resolve("band_config.json")))
            assertFalse(Files.exists(index.resolve("vision-index-v3.tar.gz")))
            assertFalse(Files.exists(index.resolve("index.faiss")))

            // Every pointer names the generation the manifest asked for.
            for (artifact in bundle.manifest.artifacts()) {
                assertEquals(
                    artifact.spec.generation,
                    harness.store.currentGeneration(artifact.name),
                )
                assertNotNull(harness.manager.activeRecord(artifact.name))
            }
        }
    }

    @Test
    fun `a corrupted body fails sha256 and is never promoted`() {
        TempDir().use { temp ->
            val harness = Harness(temp)
            val bundle = TestFixtures.bundle()
            harness.serve(bundle)
            harness.transport.corruptBody = true

            try {
                harness.manager.install(bundle.manifest, bundle.source)
                fail("expected ArtifactVerificationException")
            } catch (e: ArtifactVerificationException) {
                assertEquals("formatter", e.artifactName)
                assertTrue(e.message!!, e.message!!.contains("NOT installed"))
            }

            assertNull("no pointer may name a corrupt artifact", harness.store.currentGeneration("formatter"))
            assertNull(harness.manager.activeDirectory("formatter"))
            assertTrue(harness.store.listGenerations("formatter").isEmpty())
            assertFalse(
                "the corrupt bytes must be discarded, not left to be resumed from",
                Files.exists(harness.store.partFile("formatter", bundlerGeneration(bundle, "formatter"))),
            )
        }
    }

    @Test
    fun `a truncated download is not promoted and keeps its partial for resume`() {
        TempDir().use { temp ->
            val harness = Harness(temp)
            // The body must be larger than `truncateResponseTo`, otherwise the fake
            // serves the whole body, declares the matching length and never
            // truncates — the test would then be asserting the wrong thing.
            val bundle = TestFixtures.bundle(formatterBytes = ByteArray(4096) { (it % 251).toByte() })
            harness.serve(bundle)
            harness.transport.truncateResponseTo = 1000

            try {
                harness.manager.install(bundle.manifest, bundle.source)
                fail("expected TruncatedBodyException")
            } catch (_: TruncatedBodyException) {
                // expected
            }

            assertNull(harness.store.currentGeneration("formatter"))
            assertTrue(harness.store.listGenerations("formatter").isEmpty())
            assertTrue(
                "the partial must survive so the next attempt resumes instead of restarting",
                Files.exists(harness.store.partFile("formatter", bundlerGeneration(bundle, "formatter"))),
            )
        }
    }

    @Test
    fun `a resumed download produces the correct hash and is promoted`() {
        TempDir().use { temp ->
            val harness = Harness(temp)
            // The fixture body must be long enough to hold the 100-byte prefix the
            // test pretends a previous run left behind (the default fixture is only
            // 15 bytes, so `copyOfRange(0, 100)` would itself throw).
            val bundle = TestFixtures.bundle(formatterBytes = ByteArray(300) { (it % 251).toByte() })
            harness.serve(bundle)

            // Simulate a previous run that died after 100 bytes of the formatter.
            val formatterBytes = bundle.formatterBytes
            val part = harness.store.partFile("formatter", bundlerGeneration(bundle, "formatter"))
            Files.createDirectories(part.parent)
            Files.write(part, formatterBytes.copyOfRange(0, 100))

            val result = harness.manager.install(bundle.manifest, bundle.source)

            assertEquals(4, result.downloaded.size)
            assertTrue(
                "the resumed artifact must have been asked for with a Range header",
                harness.transport.requests.any { request ->
                    request.headers.entries.any { it.key.equals("Range", ignoreCase = true) && it.value == "bytes=100-" }
                },
            )
            val payload = harness.manager.activeDirectory("formatter")!!
                .resolve("MiniCPM5-1B-AUGURY-Q4_K_M.gguf")
            assertTrue(Files.readAllBytes(payload).contentEquals(formatterBytes))
        }
    }

    @Test
    fun `only the artifacts whose generation changed are re-downloaded`() {
        TempDir().use { temp ->
            val harness = Harness(temp)
            val first = TestFixtures.bundle()
            harness.serve(first)
            harness.manager.install(first.manifest, first.source)

            // A publisher updates ONLY the formatter, exactly what §3.2 promises
            // is possible without touching the other three artifacts.
            val second = TestFixtures.bundle(formatterBytes = "FORMATTER-BYTES-V2".toByteArray())
            harness.serve(second)
            harness.transport.requests.clear()

            val result = harness.manager.install(second.manifest, second.source)

            assertEquals(listOf("formatter"), result.downloaded.map { it.artifact.name })
            assertEquals(
                listOf("facts", "vision-index", "vision-encoder-dinov2-base-fp32"),
                result.skipped.map { it.artifact.name },
            )
            assertTrue(Files.readAllBytes(
                harness.manager.activeDirectory("formatter")!!.resolve("MiniCPM5-1B-AUGURY-Q4_K_M.gguf"),
            ).contentEquals("FORMATTER-BYTES-V2".toByteArray()))
        }
    }

    @Test
    fun `a publisher rollback to the previous generation costs no bytes and is loadable`() {
        TempDir().use { temp ->
            val harness = Harness(temp)
            val first = TestFixtures.bundle()
            harness.serve(first)
            harness.manager.install(first.manifest, first.source)

            val second = TestFixtures.bundle(formatterBytes = "FORMATTER-BYTES-V2".toByteArray())
            harness.serve(second)
            harness.manager.install(second.manifest, second.source)

            // The manifest goes back to the first generation. The bytes are still
            // on disk as `previous`, so this must be a pointer flip.
            harness.transport.requests.clear()
            val result = harness.manager.install(first.manifest, first.source)

            assertEquals(0, harness.transport.requestCount())
            assertTrue(result.downloaded.isEmpty())
            assertEquals(
                first.manifest.formatter.generation,
                harness.store.currentGeneration("formatter"),
            )
            assertTrue(Files.readAllBytes(
                harness.manager.activeDirectory("formatter")!!.resolve("MiniCPM5-1B-AUGURY-Q4_K_M.gguf"),
            ).contentEquals("FORMATTER-BYTES".toByteArray()))
        }
    }

    @Test
    fun `a second install of the same manifest downloads nothing`() {
        TempDir().use { temp ->
            val harness = Harness(temp)
            val bundle = TestFixtures.bundle()
            harness.serve(bundle)
            harness.manager.install(bundle.manifest, bundle.source)
            harness.transport.requests.clear()

            val result = harness.manager.install(bundle.manifest, bundle.source)

            assertEquals(0, harness.transport.requestCount())
            assertEquals(4, result.skipped.size)
            assertTrue(result.downloaded.isEmpty())
            assertEquals(0L, result.bytesDownloaded)
        }
    }

    @Test
    fun `a metered connection refuses to start unless the user overrides it`() {
        TempDir().use { temp ->
            val harness = Harness(temp)
            harness.network.metered = true
            val bundle = TestFixtures.bundle()
            harness.serve(bundle)

            try {
                harness.manager.install(bundle.manifest, bundle.source)
                fail("expected MeteredConnectionException")
            } catch (e: MeteredConnectionException) {
                assertTrue(e.message!!, e.message!!.contains("Wi-Fi"))
            }
            assertEquals("not one artifact byte may move", 0, harness.transport.requestCount())

            val result = harness.manager.install(
                bundle.manifest,
                bundle.source,
                InstallOptions(wifiOnly = true, allowMetered = true),
            )
            assertEquals(4, result.downloaded.size)
        }
    }

    @Test
    fun `a missing network is reported before any request`() {
        TempDir().use { temp ->
            val harness = Harness(temp)
            harness.network.online = false
            val bundle = TestFixtures.bundle()
            harness.serve(bundle)

            try {
                harness.manager.install(bundle.manifest, bundle.source)
                fail("expected OfflineException")
            } catch (_: OfflineException) {
                // expected
            }
            assertEquals(0, harness.transport.requestCount())
        }
    }

    @Test
    fun `an already satisfied plan does not require a network at all`() {
        TempDir().use { temp ->
            val harness = Harness(temp)
            val bundle = TestFixtures.bundle()
            harness.serve(bundle)
            harness.manager.install(bundle.manifest, bundle.source)

            harness.network.online = false
            val result = harness.manager.install(bundle.manifest, bundle.source)

            assertEquals(4, result.skipped.size)
        }
    }

    @Test
    fun `progress is reported per artifact and in aggregate`() {
        TempDir().use { temp ->
            val harness = Harness(temp)
            val bundle = TestFixtures.bundle(indexBytes = tarGz(indexEntries(padTo = 200_000)))
            harness.serve(bundle)
            val listener = RecordingListener()

            val result = harness.manager.install(bundle.manifest, bundle.source, listener = listener)

            assertEquals(4, listener.started.size)
            assertEquals(4, listener.installed.size)
            assertTrue("expected byte progress", listener.artifactProgress.isNotEmpty())
            assertTrue(listener.overall.isNotEmpty())
            val last = listener.overall.last()
            assertEquals("the aggregate must finish at the plan's total", listener.planBytes, last.downloadedBytes)
            assertEquals(listener.planBytes, last.totalBytes)
            assertTrue("the clock is injected, so a rate must be computable", last.bytesPerSecond > 0.0)
            assertEquals(bundle.manifest.generation, result.manifestGeneration)
        }
    }

    @Test
    fun `an index tarball containing index faiss is a hard error and is not promoted`() {
        TempDir().use { temp ->
            val harness = Harness(temp)
            val entries = indexEntries()
            entries["index.faiss"] = ByteArray(64)
            val bundle = TestFixtures.bundle(indexBytes = tarGz(entries))
            harness.serve(bundle)

            try {
                harness.manager.install(bundle.manifest, bundle.source)
                fail("expected IndexUnpackException")
            } catch (e: IndexUnpackException) {
                assertTrue(e.message!!, e.message!!.contains("index.faiss"))
            }

            assertNull(harness.store.currentGeneration("vision-index"))
            assertTrue(harness.store.listGenerations("vision-index").isEmpty())
            assertFalse(Files.exists(harness.store.unpackScratchDir(
                "vision-index",
                bundlerGeneration(bundle, "vision-index"),
            )))
        }
    }

    @Test
    fun `rehash detects on-disk corruption and re-downloads`() {
        TempDir().use { temp ->
            val harness = Harness(temp)
            val bundle = TestFixtures.bundle()
            harness.serve(bundle)
            harness.manager.install(bundle.manifest, bundle.source)

            val payload = harness.manager.activeDirectory("formatter")!!
                .resolve("MiniCPM5-1B-AUGURY-Q4_K_M.gguf")
            val damaged = Files.readAllBytes(payload)
            damaged[0] = (damaged[0].toInt() xor 0xFF).toByte()
            Files.write(payload, damaged)

            harness.transport.requests.clear()
            val result = harness.manager.install(
                bundle.manifest,
                bundle.source,
                InstallOptions(rehashInstalled = true),
            )

            assertEquals(listOf("formatter"), result.downloaded.map { it.artifact.name })
            assertTrue(Files.readAllBytes(payload).contentEquals("FORMATTER-BYTES".toByteArray()))
        }
    }

    @Test
    fun `fetching the manifest rejects one that was edited after publication`() {
        TempDir().use { temp ->
            val harness = Harness(temp)
            val bundle = TestFixtures.bundle()
            harness.transport.serve(
                bundle.source.url,
                bundle.text.replace("\"species\": 173", "\"species\": 174"),
            )

            try {
                harness.manager.fetchManifest(bundle.source)
                fail("expected ManifestRejectedException")
            } catch (e: ManifestRejectedException) {
                assertTrue(e.message!!, e.message!!.contains("generation digest mismatch"))
            }
        }
    }

    @Test
    fun `fetching the manifest parses a valid published manifest`() {
        TempDir().use { temp ->
            val harness = Harness(temp)
            val bundle = TestFixtures.bundle()
            harness.serve(bundle)
            harness.manager.fetchManifest(bundle.source)
        }
    }

    @Test
    fun `the plan reports the true download cost before anything is fetched`() {
        TempDir().use { temp ->
            val harness = Harness(temp)
            val bundle = TestFixtures.bundle()
            harness.serve(bundle)

            val plan = harness.manager.plan(bundle.manifest)

            assertEquals(4, plan.toDownload.size)
            assertEquals(bundle.bodies.values.sumOf { it.size.toLong() }, plan.bytesToDownload)
            assertFalse(plan.isComplete)
            assertEquals(0, harness.transport.requestCount())
        }
    }

    @Test
    fun `rollback through the manager restores the retained generation`() {
        TempDir().use { temp ->
            val harness = Harness(temp)
            val first = TestFixtures.bundle()
            harness.serve(first)
            harness.manager.install(first.manifest, first.source)
            val second = TestFixtures.bundle(formatterBytes = "FORMATTER-BYTES-V2".toByteArray())
            harness.serve(second)
            harness.manager.install(second.manifest, second.source)

            val restored = harness.manager.rollback("formatter")

            assertEquals(first.manifest.formatter.generation, restored)
            assertEquals(first.manifest.formatter.generation, harness.manager.installedGeneration("formatter"))
            assertNotNull(harness.manager.activeRecord("formatter"))
        }
    }

    @Test
    fun `a manifest with an unimplemented protocol never reaches the downloader`() {
        TempDir().use { temp ->
            val harness = Harness(temp)
            val bundle = TestFixtures.bundle(encoderProtocol = "vision.something-else@1")
            harness.serve(bundle)

            try {
                harness.manager.install(bundle.manifest, bundle.source)
                fail("expected AppUpdateRequiredException")
            } catch (_: AppUpdateRequiredException) {
                // expected
            }
            assertEquals(0, harness.transport.requestCount())
        }
    }

    // ── harness ─────────────────────────────────────────────────────────────

    private class Harness(temp: TempDir) {
        val store = GenerationStore(temp.resolve("artifacts"))
        val transport = FakeTransport()
        val network = FakeNetwork()

        /** A monotonic 1 ms-per-call clock, so rates are deterministic. */
        private var ticks = 0L

        val manager = ArtifactManager(
            store = store,
            transport = transport,
            network = network,
            timeSource = {
                val now = ticks
                ticks += 1_000_000L
                now
            },
        )

        fun serve(bundle: TestBundle) = bundle.serveTo(transport)
    }

    private class RecordingListener : ArtifactProgressListener {
        val started = ArrayList<String>()
        val installed = ArrayList<String>()
        val artifactProgress = ArrayList<Pair<String, Long>>()
        val overall = ArrayList<Overall>()
        var planBytes = 0L
        var finished: InstallResult? = null

        override fun onPlanResolved(plan: InstallPlan) {
            planBytes = plan.bytesToDownload
        }

        override fun onArtifactStarted(artifact: ManifestArtifact, resumeFromBytes: Long, totalBytes: Long) {
            started += artifact.name
        }

        override fun onArtifactProgress(
            artifact: ManifestArtifact,
            bytesDownloaded: Long,
            totalBytes: Long,
            bytesPerSecond: Double,
        ) {
            artifactProgress += artifact.name to bytesDownloaded
        }

        override fun onArtifactInstalled(
            artifact: ManifestArtifact,
            generation: String,
            directory: Path,
            skipped: Boolean,
        ) {
            installed += artifact.name
        }

        override fun onOverallProgress(downloadedBytes: Long, totalDownloadBytes: Long, bytesPerSecond: Double) {
            overall += Overall(downloadedBytes, totalDownloadBytes, bytesPerSecond)
        }

        override fun onFinished(result: InstallResult) {
            finished = result
        }
    }

    private data class Overall(val downloadedBytes: Long, val totalBytes: Long, val bytesPerSecond: Double)

    private fun bundlerGeneration(bundle: TestBundle, name: String): String =
        bundle.manifest.artifacts().first { it.name == name }.spec.generation
}

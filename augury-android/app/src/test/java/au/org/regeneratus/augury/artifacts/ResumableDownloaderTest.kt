package au.org.regeneratus.augury.artifacts

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.nio.file.Files

/**
 * The `Range` protocol, exercised against a fake server that can behave the way
 * real CDNs and proxies do: honour the range, ignore it, answer `416`, or cut the
 * body short.
 *
 * The property under test throughout is that a resume may never produce a file
 * that is not byte-identical to a fresh download. The downloader does not decide
 * that itself — SHA-256 does, in `ArtifactManagerTest` — but a resume that
 * appends at the wrong offset would always fail that check, so the offsets are
 * asserted here.
 */
class ResumableDownloaderTest {

    private val url = "https://fake.invalid/datasets/test/repo/resolve/main/blob.bin"

    /** Larger than several 64 KiB buffers, so progress and cancellation have room. */
    private val body = ByteArray(300_000) { (it % 251).toByte() }

    @Test
    fun `a fresh download sends no Range header and writes the whole body`() {
        TempDir().use { temp ->
            val transport = FakeTransport().apply { serve(url, body) }
            val target = temp.resolve("blob.part")

            val report = ResumableDownloader(transport).download(url, target, body.size.toLong())

            assertEquals(null, transport.lastRangeHeader())
            assertEquals(body.size.toLong(), report.bytes)
            assertEquals(0L, report.resumedFromBytes)
            assertFalse(report.serverHonouredRange)
            assertTrue(Files.readAllBytes(target).contentEquals(body))
        }
    }

    @Test
    fun `a partial file resumes with Range and completes byte for byte`() {
        TempDir().use { temp ->
            val transport = FakeTransport().apply { serve(url, body) }
            val target = temp.resolve("blob.part")
            val have = 100_000
            Files.write(target, body.copyOfRange(0, have))

            val report = ResumableDownloader(transport).download(url, target, body.size.toLong())

            assertEquals("bytes=$have-", transport.lastRangeHeader())
            assertEquals(have.toLong(), report.resumedFromBytes)
            assertTrue(report.serverHonouredRange)
            assertEquals("a clean resume is not a restart", 0, report.restarts)
            assertTrue(Files.readAllBytes(target).contentEquals(body))
        }
    }

    @Test
    fun `a server that ignores Range restarts instead of appending a second copy`() {
        TempDir().use { temp ->
            val transport = FakeTransport().apply {
                serve(url, body)
                ignoreRange = true
            }
            val target = temp.resolve("blob.part")
            Files.write(target, body.copyOfRange(0, 100_000))

            val report = ResumableDownloader(transport).download(url, target, body.size.toLong())

            assertEquals("bytes=100000-", transport.lastRangeHeader())
            assertFalse(report.serverHonouredRange)
            assertEquals(1, report.restarts)
            assertEquals("a doubled file would be 400000 bytes", body.size.toLong(), report.bytes)
            assertTrue(Files.readAllBytes(target).contentEquals(body))
        }
    }

    @Test
    fun `416 with a matching total treats the partial file as complete`() {
        TempDir().use { temp ->
            val transport = FakeTransport().apply { serve(url, body) }
            val target = temp.resolve("blob.part")
            Files.write(target, body)

            val report = ResumableDownloader(transport).download(url, target, body.size.toLong())

            assertEquals(body.size.toLong(), report.bytes)
            assertTrue(report.serverHonouredRange)
            assertTrue(Files.readAllBytes(target).contentEquals(body))
        }
    }

    @Test
    fun `416 on an over-long partial restarts from zero`() {
        TempDir().use { temp ->
            val transport = FakeTransport().apply { serve(url, body) }
            val target = temp.resolve("blob.part")
            Files.write(target, ByteArray(body.size + 50) { 7 })

            val report = ResumableDownloader(transport).download(url, target, expectedBytes = null)

            assertEquals(body.size.toLong(), report.bytes)
            assertEquals(1, report.restarts)
            assertTrue(Files.readAllBytes(target).contentEquals(body))
        }
    }

    @Test
    fun `a truncated body is reported and the partial file is kept for resume`() {
        TempDir().use { temp ->
            val transport = FakeTransport().apply {
                serve(url, body)
                truncateResponseTo = 1000
            }
            val target = temp.resolve("blob.part")

            try {
                ResumableDownloader(transport).download(url, target, body.size.toLong())
                fail("expected TruncatedBodyException")
            } catch (e: TruncatedBodyException) {
                assertTrue(e.message!!, e.message!!.contains("declared"))
            }
            assertTrue("the partial must survive so the next attempt resumes", Files.exists(target))
            assertEquals(1000L, Files.size(target))
        }
    }

    @Test
    fun `a completed download of the wrong length is rejected`() {
        TempDir().use { temp ->
            val transport = FakeTransport().apply { serve(url, body) }
            val target = temp.resolve("blob.part")

            try {
                ResumableDownloader(transport).download(url, target, expectedBytes = body.size + 1L, label = "blob")
                fail("expected ArtifactSizeMismatchException")
            } catch (e: ArtifactSizeMismatchException) {
                assertEquals("blob", e.artifactName)
                assertEquals(body.size + 1L, e.expectedBytes)
                assertEquals(body.size.toLong(), e.actualBytes)
            }
        }
    }

    @Test
    fun `a partial longer than the manifest allows is discarded before requesting anything`() {
        TempDir().use { temp ->
            val transport = FakeTransport().apply { serve(url, body) }
            val target = temp.resolve("blob.part")
            Files.write(target, ByteArray(body.size + 10))

            val report = ResumableDownloader(transport).download(url, target, body.size.toLong())

            assertEquals(null, transport.lastRangeHeader())
            assertTrue(Files.readAllBytes(target).contentEquals(body))
            assertEquals(body.size.toLong(), report.bytes)
        }
    }

    @Test
    fun `progress reports bytes, total and a positive rate`() {
        TempDir().use { temp ->
            val transport = FakeTransport().apply { serve(url, body) }
            val target = temp.resolve("blob.part")
            val ticks = longArrayOf(0L)
            val downloader = ResumableDownloader(
                transport,
                timeSource = {
                    val value = ticks[0]
                    ticks[0] += 1_000_000_000L
                    value
                },
            )
            val seen = ArrayList<DownloadProgress>()

            downloader.download(url, target, body.size.toLong()) { seen += it }

            assertTrue("expected several progress callbacks", seen.size >= 4)
            assertEquals(body.size.toLong(), seen.last().bytesDownloaded)
            assertEquals(body.size.toLong(), seen.last().totalBytes)
            assertTrue("rate should be positive with a ticking clock: ${seen.last()}", seen.last().bytesPerSecond > 0.0)
            assertTrue(seen.all { it.bytesDownloaded <= it.totalBytes })
        }
    }

    @Test
    fun `cancellation stops the transfer and keeps what was already written`() {
        TempDir().use { temp ->
            val transport = FakeTransport().apply { serve(url, body) }
            val target = temp.resolve("blob.part")
            val cancelled = booleanArrayOf(false)
            val token = CancellationToken { cancelled[0] }
            var first = true

            try {
                ResumableDownloader(transport).download(
                    url = url,
                    target = target,
                    expectedBytes = body.size.toLong(),
                    cancel = token,
                    onProgress = {
                        if (first) {
                            first = false
                            cancelled[0] = true
                        }
                    },
                )
                fail("expected ArtifactCancelledException")
            } catch (_: ArtifactCancelledException) {
                // expected
            }
            assertTrue(Files.exists(target))
            assertTrue("some bytes should have landed", Files.size(target) > 0)
            assertTrue("but not all of them", Files.size(target) < body.size)
        }
    }

    @Test
    fun `a mid-stream network failure propagates and leaves the partial in place`() {
        TempDir().use { temp ->
            val transport = FakeTransport().apply {
                serve(url, body)
                failMidStreamAfter = 5000
            }
            val target = temp.resolve("blob.part")

            try {
                ResumableDownloader(transport).download(url, target, body.size.toLong())
                fail("expected an IOException")
            } catch (e: java.io.IOException) {
                assertTrue(e.message!!, e.message!!.contains("simulated network failure"))
            }
            assertTrue(Files.exists(target))
            assertEquals(5000L, Files.size(target))
        }
    }

    @Test
    fun `an unexpected http status is reported with the url`() {
        TempDir().use { temp ->
            val transport = FakeTransport().apply {
                serve(url, body)
                statusOverride = 503
            }

            try {
                ResumableDownloader(transport).download(url, temp.resolve("blob.part"), body.size.toLong())
                fail("expected DownloadHttpException")
            } catch (e: DownloadHttpException) {
                assertEquals(503, e.statusCode)
                assertEquals(url, e.url)
            }
        }
    }
}

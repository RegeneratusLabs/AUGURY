package au.org.regeneratus.augury.artifacts

import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.StandardOpenOption

/**
 * AUGURY — resumable HTTP download.
 *
 * The first launch moves ~1.06 GB over a phone connection
 * (`docs/mobile-app-decision.md` §5), so a download that restarts from zero on
 * every interruption is not acceptable. This class implements exactly the
 * protocol the handover asks for:
 *
 * * if a partial file exists, resume with `Range: bytes=<len>-`;
 * * a server that **ignores** `Range` and answers `200` is handled by truncating
 *   the partial file and restarting — never by appending a second copy;
 * * `206` is validated: its `Content-Range` must start at the byte we asked for,
 *   otherwise the file is discarded and re-fetched (a mismatched offset means a
 *   silently corrupted artifact otherwise);
 * * `416` is handled both ways: an unsatisfied Content-Range whose total equals
 *   our length means the partial file is already complete, anything else
 *   restarts cleanly;
 * * a body shorter than its `Content-Length` raises [TruncatedBodyException] and
 *   **leaves the partial file in place**, so the next attempt resumes instead of
 *   re-downloading — the partial is not promoted, it is only kept.
 *
 * This class never decides that a file is good. It guarantees bytes on disk and
 * reports what it did; SHA-256 verification and the promote decision belong to
 * [ArtifactManager]. A truncated body can therefore never be promoted, because
 * promotion is unreachable until verification passes.
 */
data class DownloadProgress(
    /** Bytes on disk including the resumed prefix. */
    val bytesDownloaded: Long,
    /** Expected total, or `-1` when neither the manifest nor the server declares one. */
    val totalBytes: Long,
    /** Average rate over this download attempt. */
    val bytesPerSecond: Double,
)

data class DownloadReport(
    val bytes: Long,
    /** Bytes that were already on disk when this attempt started. */
    val resumedFromBytes: Long,
    /** True when the successful attempt was served as `206 Partial Content`. */
    val serverHonouredRange: Boolean,
    /** How many times the server forced a clean restart (ignored `Range`, or `416`). */
    val restarts: Int,
)

/** Cooperative cancellation, checked between read chunks. */
fun interface CancellationToken {
    fun isCancelled(): Boolean

    companion object {
        val NONE: CancellationToken = CancellationToken { false }
    }
}

class ResumableDownloader(
    private val transport: HttpTransport,
    private val bufferBytes: Int = DEFAULT_BUFFER_BYTES,
    private val timeSource: () -> Long = { System.nanoTime() },
    private val maxRestarts: Int = DEFAULT_MAX_RESTARTS,
) {

    /**
     * Downloads [url] into [target], resuming when [target] already holds bytes.
     *
     * @param expectedBytes the manifest's `bytes` for this artifact, or `null` if unknown.
     * @param label artifact name used in error messages.
     */
    fun download(
        url: String,
        target: Path,
        expectedBytes: Long?,
        label: String = target.fileName.toString(),
        cancel: CancellationToken = CancellationToken.NONE,
        onProgress: (DownloadProgress) -> Unit = {},
    ): DownloadReport {
        target.parent?.let { Files.createDirectories(it) }

        var existing = if (Files.exists(target)) Files.size(target) else 0L
        // A partial that is already longer than the artifact cannot be resumed;
        // it can only be a leftover of a different generation or a bad range.
        if (expectedBytes != null && existing > expectedBytes) {
            Files.deleteIfExists(target)
            existing = 0L
        }

        val startedAt = timeSource()
        var restarts = 0
        var resumedFrom = existing

        while (true) {
            val headers = if (existing > 0) mapOf("Range" to "bytes=$existing-") else emptyMap()
            val report = transport.execute(HttpRequest(url, headers)).use { response ->
                handle(response, url, target, existing, expectedBytes, label, cancel, onProgress, startedAt, restarts)
            }
            if (report != null) return report

            restarts++
            if (restarts > maxRestarts) {
                throw DownloadProtocolException(
                    "$label: the server forced $restarts clean restarts at $url; giving up rather than looping"
                )
            }
            Files.deleteIfExists(target)
            existing = 0L
            resumedFrom = 0L
        }
    }

    /**
     * Returns the completed report, or `null` when the caller must restart from
     * byte zero (the server declined the resume in a way that is safe to retry).
     */
    private fun handle(
        response: HttpResponse,
        url: String,
        target: Path,
        existing: Long,
        expectedBytes: Long?,
        label: String,
        cancel: CancellationToken,
        onProgress: (DownloadProgress) -> Unit,
        startedAt: Long,
        restarts: Int,
    ): DownloadReport? {
        when (response.statusCode) {
            HTTP_OK -> {
                // 200 to a ranged request means the server ignored Range. The
                // body starts at byte zero, so any prefix we hold must go.
                val ignoredRange = existing > 0
                if (ignoredRange) Files.deleteIfExists(target)
                val written = pump(response, target, append = false, baseOffset = 0, expectedBytes = expectedBytes, cancel = cancel, onProgress = onProgress, startedAt = startedAt)
                return completed(
                    target, written, resumedFrom = 0, honouredRange = false,
                    restarts = restarts + if (ignoredRange) 1 else 0,
                    expectedBytes = expectedBytes, label = label,
                )
            }

            HTTP_PARTIAL -> {
                val range = response.contentRange()
                val rangeStart = range?.start
                if (rangeStart == null) {
                    throw DownloadProtocolException(
                        "$label: 206 Partial Content from $url without a usable Content-Range header"
                    )
                }
                if (rangeStart != existing) {
                    // The server resumed somewhere else. Appending would corrupt
                    // the file; start again from zero.
                    return null
                }
                val written = pump(response, target, append = existing > 0, baseOffset = existing, expectedBytes = expectedBytes, cancel = cancel, onProgress = onProgress, startedAt = startedAt)
                return completed(
                    target, existing + written, resumedFrom = existing,
                    honouredRange = true, restarts = restarts, expectedBytes = expectedBytes, label = label,
                )
            }

            HTTP_RANGE_NOT_SATISFIABLE -> {
                val total = response.contentRange()?.total
                if (existing > 0 && total != null && total == existing) {
                    // An unsatisfied range whose total equals what we already have:
                    // file is the entire entity. Verification still decides.
                    if (expectedBytes != null && existing != expectedBytes) {
                        throw ArtifactSizeMismatchException(label, expectedBytes, existing)
                    }
                    return DownloadReport(existing, existing, serverHonouredRange = true, restarts = restarts)
                }
                return null
            }

            else -> throw DownloadHttpException(response.statusCode, url, "$label: HTTP ${response.statusCode} from $url")
        }
    }

    /** Streams the response body into [target]; returns the bytes written by this response. */
    private fun pump(
        response: HttpResponse,
        target: Path,
        append: Boolean,
        baseOffset: Long,
        expectedBytes: Long?,
        cancel: CancellationToken,
        onProgress: (DownloadProgress) -> Unit,
        startedAt: Long,
    ): Long {
        val declaredLength = response.contentLength()
        val openOptions = if (append) {
            arrayOf(StandardOpenOption.CREATE, StandardOpenOption.WRITE, StandardOpenOption.APPEND)
        } else {
            arrayOf(StandardOpenOption.CREATE, StandardOpenOption.WRITE, StandardOpenOption.TRUNCATE_EXISTING)
        }
        val buffer = ByteArray(bufferBytes)
        var written = 0L
        Files.newOutputStream(target, *openOptions).use { out ->
            response.body.use { input ->
                while (true) {
                    if (cancel.isCancelled()) {
                        throw ArtifactCancelledException("cancelled while downloading ${target.fileName}")
                    }
                    val read = input.read(buffer)
                    if (read < 0) break
                    out.write(buffer, 0, read)
                    written += read
                    val total = expectedBytes ?: declaredLength?.let { baseOffset + it } ?: -1L
                    onProgress(DownloadProgress(baseOffset + written, total, rate(baseOffset + written, startedAt)))
                }
            }
        }
        if (declaredLength != null && written != declaredLength) {
            throw TruncatedBodyException(
                "${target.fileName}: the server declared $declaredLength bytes for this response but sent $written; " +
                    "keeping the partial file so the next attempt can resume"
            )
        }
        return written
    }

    private fun completed(
        target: Path,
        totalBytes: Long,
        resumedFrom: Long,
        honouredRange: Boolean,
        restarts: Int,
        expectedBytes: Long?,
        label: String,
    ): DownloadReport {
        val onDisk = Files.size(target)
        if (expectedBytes != null && onDisk != expectedBytes) {
            throw ArtifactSizeMismatchException(label, expectedBytes, onDisk)
        }
        return DownloadReport(onDisk, resumedFrom, honouredRange, restarts)
    }

    private fun rate(bytes: Long, startedAt: Long): Double {
        val elapsedNanos = timeSource() - startedAt
        if (elapsedNanos <= 0L) return 0.0
        return bytes.toDouble() / (elapsedNanos / 1_000_000_000.0)
    }

    companion object {
        const val DEFAULT_BUFFER_BYTES = 64 * 1024
        const val DEFAULT_MAX_RESTARTS = 2
        const val HTTP_OK = 200
        const val HTTP_PARTIAL = 206
        const val HTTP_RANGE_NOT_SATISFIABLE = 416
    }
}

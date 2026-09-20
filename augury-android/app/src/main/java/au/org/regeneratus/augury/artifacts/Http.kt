package au.org.regeneratus.augury.artifacts

import java.io.ByteArrayInputStream
import java.io.Closeable
import java.io.InputStream
import java.net.HttpURLConnection
import java.net.URL

/**
 * AUGURY — the HTTP surface the pipeline needs, behind an interface.
 *
 * Everything the downloader does goes through [HttpTransport], which is the
 * single seam that lets the whole pipeline run on a pure JVM: the unit tests
 * drive a file-backed fake that can serve 200/206/416, lie about `Range`,
 * truncate a body or corrupt a byte, with no device and no emulator.
 */
data class HttpRequest(
    val url: String,
    /** Extra request headers. `Range` is added by the downloader; `Accept-Encoding: identity` is added by the transport. */
    val headers: Map<String, String> = emptyMap(),
)

interface HttpResponse : Closeable {

    /** HTTP status code. */
    val statusCode: Int

    /** Response headers; lookup through [header] so casing never matters. */
    val headers: Map<String, String>

    /** Response body. The caller must fully consume or close it. */
    val body: InputStream

    fun header(name: String): String? =
        headers.entries.firstOrNull { it.key.equals(name, ignoreCase = true) }?.value

    /** `Content-Length`, or `null` when absent/chunked/unparseable. */
    fun contentLength(): Long? = header("Content-Length")?.trim()?.toLongOrNull()

    /** `Content-Range` in the `bytes start-end/total` form, or `null`. */
    fun contentRange(): ContentRange? = ContentRange.parse(header("Content-Range"))
}

interface HttpTransport {
    fun execute(request: HttpRequest): HttpResponse
}

/**
 * A parsed `Content-Range` header.
 *
 * Both forms the downloader must understand: `bytes 100-999/1000` for a
 * satisfied resume, and the `416` form where the range part is a single asterisk
 * and only the total is present ("the range you asked for does not exist, but
 * the entity is this long").
 */
data class ContentRange(val start: Long?, val end: Long?, val total: Long?) {

    /** True for the unsatisfied form sent with `416`, where only the total is present. */
    val isUnsatisfied: Boolean get() = start == null

    companion object {
        fun parse(raw: String?): ContentRange? {
            if (raw == null) return null
            val text = raw.trim()
            if (!text.startsWith("bytes", ignoreCase = true)) return null
            val spec = text.substring(5).trim()
            val slash = spec.indexOf('/')
            if (slash < 0) return null
            val rangePart = spec.substring(0, slash).trim()
            val total = spec.substring(slash + 1).trim().toLongOrNull()
            if (rangePart == "*") return ContentRange(null, null, total)
            val dash = rangePart.indexOf('-')
            if (dash < 0) return null
            val start = rangePart.substring(0, dash).trim().toLongOrNull() ?: return null
            val end = rangePart.substring(dash + 1).trim().toLongOrNull() ?: return null
            return ContentRange(start, end, total)
        }
    }
}

/**
 * The real transport: `HttpURLConnection`, which is the only HTTP client the
 * app has without a new dependency, and which follows Hugging Face's
 * `resolve/...` redirect to the CDN.
 *
 * `Accept-Encoding: identity` is set deliberately. Android's `HttpURLConnection`
 * will otherwise negotiate gzip and transparently decompress the body — which
 * silently invalidates a byte `Range` (the offsets the server counts are
 * compressed offsets, the offsets we count are plaintext ones) and would corrupt
 * every resumed download. Identity encoding is what makes `Range` mean the same
 * thing on both ends.
 */
class JavaHttpTransport(
    private val connectTimeoutMillis: Int = DEFAULT_CONNECT_TIMEOUT_MILLIS,
    private val readTimeoutMillis: Int = DEFAULT_READ_TIMEOUT_MILLIS,
    private val userAgent: String = DEFAULT_USER_AGENT,
) : HttpTransport {

    override fun execute(request: HttpRequest): HttpResponse {
        val connection = URL(request.url).openConnection() as HttpURLConnection
        try {
            connection.instanceFollowRedirects = true
            connection.connectTimeout = connectTimeoutMillis
            connection.readTimeout = readTimeoutMillis
            connection.requestMethod = "GET"
            connection.setRequestProperty("User-Agent", userAgent)
            connection.setRequestProperty("Accept-Encoding", "identity")
            for ((name, value) in request.headers) connection.setRequestProperty(name, value)

            val status = connection.responseCode
            val headers = LinkedHashMap<String, String>()
            for ((name, values) in connection.headerFields) {
                if (name == null || values == null) continue
                headers[name] = values.joinToString(", ")
            }
            val stream: InputStream = if (status >= 400) {
                connection.errorStream ?: ByteArrayInputStream(ByteArray(0))
            } else {
                connection.inputStream
            }
            return ConnectionResponse(status, headers, stream, connection)
        } catch (e: Throwable) {
            connection.disconnect()
            throw e
        }
    }

    private class ConnectionResponse(
        override val statusCode: Int,
        override val headers: Map<String, String>,
        override val body: InputStream,
        private val connection: HttpURLConnection,
    ) : HttpResponse {
        override fun close() {
            try {
                body.close()
            } catch (_: Exception) {
                // Nothing useful to do; the connection is torn down regardless.
            } finally {
                connection.disconnect()
            }
        }
    }

    companion object {
        const val DEFAULT_CONNECT_TIMEOUT_MILLIS = 30_000
        const val DEFAULT_READ_TIMEOUT_MILLIS = 60_000
        const val DEFAULT_USER_AGENT = "AUGURY-Android"
    }
}

/**
 * Whether a dataset or a model repo is being read.
 *
 * The segment is **not** symmetric, and getting it wrong is a 404 that looks
 * like "the artifact was never published":
 *
 * ```
 *   dataset : https://huggingface.co/datasets/<repo>/resolve/<rev>/<path>   -> 200
 *   model   : https://huggingface.co/<repo>/resolve/<rev>/<path>            -> 200
 *   model   : https://huggingface.co/models/<repo>/resolve/<rev>/<path>     -> 404
 * ```
 *
 * A model repo has **no** path prefix at all, so [segment] is empty for [MODEL]
 * and [HuggingFaceUrls.resolve] omits the slash entirely.
 */
enum class HuggingFaceRepoType(val segment: String) {
    DATASET("datasets"),
    MODEL(""),
    ;

    companion object {
        /**
         * Parses the manifest's `repo_type`. Absent means `"dataset"`, which
         * keeps older manifests working — every artifact except the GGUF lives in
         * a dataset repo.
         */
        fun fromManifest(raw: String?, context: String): HuggingFaceRepoType {
            val value = (raw ?: "dataset").trim().lowercase()
            return when (value) {
                "dataset" -> DATASET
                "model" -> MODEL
                else -> throw ManifestFormatException(
                    "manifest field $context: repo_type must be \"dataset\" or \"model\", found \"$raw\""
                )
            }
        }
    }
}

/**
 * Where the manifest lives. Every part is configurable, and the defaults are the
 * published contract from `scripts/app/publish_app_hf.sh`:
 * `RegeneratusLabs/augury-app/manifest.json` on Hugging Face.
 */
data class ManifestSource(
    val baseUrl: String = DEFAULT_BASE_URL,
    val repo: String = DEFAULT_REPO,
    val filename: String = DEFAULT_FILENAME,
    val revision: String = DEFAULT_REVISION,
    val repoType: HuggingFaceRepoType = HuggingFaceRepoType.DATASET,
) {
    /** `https://huggingface.co/datasets/RegeneratusLabs/augury-app/resolve/main/manifest.json` */
    val url: String
        get() = HuggingFaceUrls.resolve(baseUrl, repoType, repo, revision, filename)

    companion object {
        const val DEFAULT_BASE_URL = "https://huggingface.co"
        const val DEFAULT_REPO = "RegeneratusLabs/augury-app"
        const val DEFAULT_FILENAME = "manifest.json"

        /** The branch the manifest is read from before revisions are pinned. */
        const val DEFAULT_REVISION = "main"
    }
}

object HuggingFaceUrls {

    /**
     * Builds the `resolve` URL for one file.
     *
     * The dataset/model distinction is a *prefix that only datasets have*:
     *
     * ```
     *   dataset -> <base>/datasets/<repo>/resolve/<rev>/<path>
     *   model   -> <base>/<repo>/resolve/<rev>/<path>
     * ```
     *
     * A `null` revision falls back to [ManifestSource.DEFAULT_REVISION] — the
     * manifest's own artifact entries may leave `revision` null until the
     * publisher pins them (`--revision REPO=SHA`), and the app must still fetch
     * what the manifest points at.
     */
    fun resolve(
        baseUrl: String,
        repoType: HuggingFaceRepoType,
        repo: String,
        revision: String?,
        path: String,
    ): String {
        val base = baseUrl.trimEnd('/')
        val rev = (revision ?: ManifestSource.DEFAULT_REVISION).trim().ifEmpty { ManifestSource.DEFAULT_REVISION }
        val prefix = repoType.segment.trim('/').let { if (it.isEmpty()) "" else "/$it" }
        return "$base$prefix/${repo.trim('/')}/resolve/$rev/${encodePath(path)}"
    }

    /** Minimal escaping: spaces are legal in HF filenames and must not become a broken URL. */
    private fun encodePath(path: String): String = path.trimStart('/').replace(" ", "%20")
}

package au.org.regeneratus.augury.artifacts

import org.apache.commons.compress.archivers.tar.TarArchiveEntry
import org.apache.commons.compress.archivers.tar.TarArchiveOutputStream
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.Closeable
import java.io.IOException
import java.io.InputStream
import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.Paths
import java.util.zip.GZIPOutputStream

/**
 * Shared fakes and fixtures for the artifact-pipeline unit tests.
 *
 * Everything here is plain JVM: no `android.*`, no Robolectric, no device, no
 * emulator, no network. The three seams the production code exposes for exactly
 * this reason are exercised in full:
 *
 * * [FakeTransport] — a file-backed HTTP server that can serve 200/206/416,
 *   ignore `Range`, truncate a body or corrupt a byte;
 * * [FakeNetwork] — a settable connectivity/metered state;
 * * the filesystem root — every test gets a fresh directory under the module's
 *   `build/` tree (never `$TMPDIR`, which is read-only in this sandbox).
 */

/** A settable [NetworkStatus]. */
class FakeNetwork(
    var online: Boolean = true,
    var metered: Boolean = false,
) : NetworkStatus {
    override fun isOnline(): Boolean = online
    override fun isMetered(): Boolean = metered
}

/**
 * A local, in-memory HTTP server that speaks just enough of the range protocol
 * to exercise the downloader's real decision points.
 */
class FakeTransport : HttpTransport {

    private val bodies = LinkedHashMap<String, ByteArray>()

    /** Every request the pipeline made, in order. */
    val requests = ArrayList<HttpRequest>()

    /** Answer `200` with the whole body even when `Range` was requested. */
    var ignoreRange: Boolean = false

    /** Serve only this many bytes of the body while still declaring its full `Content-Length`. */
    var truncateResponseTo: Int? = null

    /** Flip the last byte of the served body, simulating corruption in transit. */
    var corruptBody: Boolean = false

    /** Answer this status for every request instead of the normal behaviour. */
    var statusOverride: Int? = null

    /** Throw [IOException] after this many bytes of the body. */
    var failMidStreamAfter: Int? = null

    fun serve(url: String, body: ByteArray) {
        bodies[url] = body
    }

    fun serve(url: String, body: String) = serve(url, body.toByteArray(Charsets.UTF_8))

    fun requestCount(): Int = requests.size

    fun lastRangeHeader(): String? = requests.lastOrNull()
        ?.headers?.entries?.firstOrNull { it.key.equals("Range", ignoreCase = true) }?.value

    override fun execute(request: HttpRequest): HttpResponse {
        requests += request

        statusOverride?.let { status ->
            return FakeResponse(status, mapOf("Content-Length" to "0"), ByteArrayInputStream(ByteArray(0)))
        }

        val full = bodies[request.url]
            ?: return FakeResponse(404, mapOf("Content-Length" to "0"), ByteArrayInputStream(ByteArray(0)))

        val rangeHeader = request.headers.entries
            .firstOrNull { it.key.equals("Range", ignoreCase = true) }?.value
        val start = rangeHeader?.let { parseRangeStart(it) }

        if (rangeHeader != null && !ignoreRange && start != null && start >= full.size.toLong()) {
            return FakeResponse(
                416,
                mapOf("Content-Range" to "bytes */${full.size}", "Content-Length" to "0"),
                ByteArrayInputStream(ByteArray(0)),
            )
        }

        val ranged = rangeHeader != null && !ignoreRange && start != null && start > 0
        // `parseRangeStart` yields a Long (it models an HTTP byte offset), but an
        // in-memory fake body cannot exceed Int.MAX_VALUE, so narrowing is safe here.
        val payload = if (ranged) full.copyOfRange(start!!.toInt(), full.size) else full
        val served = if (corruptBody && payload.isNotEmpty()) {
            payload.copyOf().also { it[it.size - 1] = (it[it.size - 1].toInt() xor 0xFF).toByte() }
        } else {
            payload
        }

        val declaredLength = served.size.toLong()
        val bodyBytes = truncateResponseTo?.let { limit -> served.copyOf(minOf(limit, served.size)) } ?: served

        val headers = LinkedHashMap<String, String>()
        headers["Content-Length"] = declaredLength.toString()
        val status: Int
        if (ranged) {
            status = 206
            headers["Content-Range"] = "bytes ${start}-${full.size - 1}/${full.size}"
        } else {
            status = 200
        }

        val stream: InputStream = failMidStreamAfter?.let { limit ->
            FailingInputStream(bodyBytes, limit)
        } ?: ByteArrayInputStream(bodyBytes)

        return FakeResponse(status, headers, stream)
    }

    private fun parseRangeStart(header: String): Long? {
        val match = Regex("^bytes=(\\d+)-$").find(header.trim()) ?: return null
        return match.groupValues[1].toLongOrNull()
    }

    private class FakeResponse(
        override val statusCode: Int,
        override val headers: Map<String, String>,
        override val body: InputStream,
    ) : HttpResponse {
        override fun close() {
            body.close()
        }
    }

    private class FailingInputStream(private val delegate: ByteArray, private val failAfter: Int) : InputStream() {
        private var position = 0
        override fun read(): Int {
            if (position >= failAfter) throw IOException("simulated network failure")
            if (position >= delegate.size) return -1
            return delegate[position++].toInt() and 0xff
        }

        override fun read(b: ByteArray, off: Int, len: Int): Int {
            if (position >= failAfter) throw IOException("simulated network failure")
            if (position >= delegate.size) return -1
            val count = minOf(len, failAfter - position, delegate.size - position)
            System.arraycopy(delegate, position, b, off, count)
            position += count
            return count
        }
    }
}

/** A temp directory under the module's `build/` tree, deleted on [close]. */
class TempDir : Closeable {
    val path: Path = Files.createTempDirectory(testsRoot(), "case-")

    fun resolve(vararg parts: String): Path = parts.fold(path) { acc, part -> acc.resolve(part) }

    override fun close() {
        GenerationStore.deleteRecursively(path)
    }

    companion object {
        /**
         * `$TMPDIR` is read-only in this sandbox and a device test never runs
         * there either, so temp state goes under the module's build directory.
         */
        private fun testsRoot(): Path {
            val repoRoot = System.getProperty("augury.repo.root")?.let { Paths.get(it) }
            val candidates = listOfNotNull(
                repoRoot?.resolve("augury-android/app/build/tmp/artifact-tests"),
                Paths.get(System.getProperty("user.dir") ?: ".").resolve("build/tmp/artifact-tests"),
            )
            for (candidate in candidates) {
                try {
                    Files.createDirectories(candidate)
                    return candidate
                } catch (_: Exception) {
                    // try the next candidate
                }
            }
            return Files.createTempDirectory("augury-artifact-tests")
        }
    }
}

/**
 * The four files the published index tarball contains.
 *
 * @param padTo when non-zero, `embeddings.npy` is grown to this many bytes so a
 *   test can produce multi-chunk progress without shipping a real index.
 */
fun indexEntries(padTo: Int = 0): LinkedHashMap<String, ByteArray> {
    val entries = LinkedHashMap<String, ByteArray>()
    val embeddingsSize = if (padTo > 0) padTo else 4096
    entries["embeddings.npy"] = ByteArray(embeddingsSize) { (it % 251).toByte() }
    entries["keys.json"] = """{"keys":["acacia","lantana"]}""".toByteArray()
    entries["pca_whiten.npz"] = ByteArray(512) { (it % 97).toByte() }
    entries["band_config.json"] = """{"auto_conf":0.64,"confirm_conf":0.3}""".toByteArray()
    return entries
}

/**
 * Builds a gzipped tar the way the publisher does, with two deliberate
 * properties the tests depend on:
 *
 * * **Reproducible.** `TarArchiveEntry(name)` stamps `mtime` with `Instant.now()`,
 *   so two calls made a second apart produce different bytes and therefore a
 *   different content-derived generation. A fixed epoch mtime makes the archive
 *   byte-for-byte stable, which is what lets
 *   `only the artifacts whose generation changed are re-downloaded` compare two
 *   bundles without the index generation drifting underneath it.
 * * **Name-preserving.** `TarArchiveEntry(name, preserveAbsolutePath = true)`
 *   keeps a deliberately hostile name (e.g. `/tmp/escaped.txt`) intact in the
 *   archive. The default constructor silently relativises it, which would make
 *   `rejects an absolute entry path` test the tar builder instead of
 *   [IndexUnpacker]'s absolute-path guard. It has no effect on relative names.
 */
fun tarGz(entries: Map<String, ByteArray>): ByteArray {
    val bytes = ByteArrayOutputStream()
    GZIPOutputStream(bytes).use { gzip ->
        TarArchiveOutputStream(gzip).use { tar ->
            for ((name, data) in entries) {
                val entry = TarArchiveEntry(name, true)
                entry.setModTime(0L)
                entry.size = data.size.toLong()
                tar.putArchiveEntry(entry)
                tar.write(data)
                tar.closeArchiveEntry()
            }
        }
    }
    return bytes.toByteArray()
}

/**
 * One complete fake publication: the manifest JSON plus every artifact body,
 * keyed by the URL the pipeline will ask for.
 */
class TestBundle(
    val source: ManifestSource,
    val text: String,
    val bodies: Map<String, ByteArray>,
    val formatterUrl: String,
    val factsUrl: String,
    val indexUrl: String,
    val encoderUrl: String,
) {
    val formatterBytes: ByteArray get() = bodies.getValue(formatterUrl)
    val factsBytes: ByteArray get() = bodies.getValue(factsUrl)
    val indexBytes: ByteArray get() = bodies.getValue(indexUrl)
    val encoderBytes: ByteArray get() = bodies.getValue(encoderUrl)

    val manifest: ArtifactManifest get() = ManifestParser.parse(text)

    fun serveTo(transport: FakeTransport) {
        transport.serve(source.url, text)
        for ((url, body) in bodies) transport.serve(url, body)
    }
}

/** Locates the repo checkout the same way the core tests do. */
object TestPaths {

    /** `data/app/manifest.json` is the anchor: if it is there, this is the repo root. */
    fun repoRoot(): java.io.File {
        System.getProperty("augury.repo.root")?.let { property ->
            val candidate = java.io.File(property)
            if (java.io.File(candidate, SHIPPED_MANIFEST).isFile) return candidate
        }
        var dir: java.io.File? = java.io.File("").absoluteFile
        while (dir != null) {
            if (java.io.File(dir, SHIPPED_MANIFEST).isFile) return dir
            dir = dir.parentFile
        }
        error("could not locate the AUGURY repo root from ${java.io.File("").absolutePath}")
    }

    fun shippedManifestFile(): java.io.File = java.io.File(repoRoot(), SHIPPED_MANIFEST)

    private const val SHIPPED_MANIFEST = "data/app/manifest.json"
}

object TestFixtures {

    const val BASE_URL = "https://fake.invalid"

    val SOURCE = ManifestSource(baseUrl = BASE_URL)

    fun url(repo: String, path: String, revision: String? = null): String =
        HuggingFaceUrls.resolve(BASE_URL, HuggingFaceRepoType.DATASET, repo, revision, path)

    /**
     * Builds a manifest that mirrors the shipped one field for field, sized down
     * to a few hundred bytes of fixture data. Every string that the gate inspects
     * is a parameter, so a test can make exactly one thing wrong.
     */
    fun bundle(
        formatterBytes: ByteArray = "FORMATTER-BYTES".toByteArray(),
        factsBytes: ByteArray = "FACTS-BYTES".toByteArray(),
        indexBytes: ByteArray = tarGz(indexEntries()),
        encoderBytes: ByteArray = "ENCODER-BYTES".toByteArray(),
        formatterPath: String = "MiniCPM5-1B-AUGURY-Q4_K_M.gguf",
        factsPath: String = "augury-ondevice.json",
        indexPath: String = "vision-index-v3.tar.gz",
        encoderPath: String = "dinov2-base-fp32.onnx",
        formatterRepo: String = "test/augury-1b",
        factsRepo: String = "test/augury-app",
        indexRepo: String = "test/augury-vision-index",
        encoderRepo: String = "test/augury-app",
        formatterProtocol: String = ShellCapabilities.FORMATTER_CHATML_GROUNDED_V1,
        factsProtocol: String = ShellCapabilities.SPECIES_DB_V1,
        indexProtocol: String = ShellCapabilities.VISION_CLIP_TOKEN_L2_PCA_KNN_IP_V1,
        encoderProtocol: String = ShellCapabilities.VISION_CLIP_TOKEN_L2_PCA_KNN_IP_V1,
        manifestSchema: Int = 1,
        factsSchema: Int = 1,
        indexSchema: Int = 1,
        indexBackend: String = "dinov2-base",
        encoderBackend: String = "dinov2-base",
        encoderQuant: String = "fp32",
        preprocessOutput: String = "cls_token",
        autoConf: String = "0.64",
        confirmConf: String = "0.3",
        revision: String? = null,
        generationOverride: String? = null,
    ): TestBundle {
        fun specJson(
            protocol: String,
            repo: String,
            path: String,
            bytes: ByteArray,
            extra: String = "",
        ): String {
            val sha = Sha256.of(bytes)
            return """
                |{
                |      "protocol": "$protocol",
                |      "repo": "$repo",
                |      "path": "$path",
                |      "revision": ${if (revision == null) "null" else "\"$revision\""},
                |      "bytes": ${bytes.size},
                |      "sha256": "$sha",
                |      "generation": "${sha.substring(0, 12)}"$extra
                |    }""".trimMargin()
        }

        val indexSpec = specJson(
            indexProtocol, indexRepo, indexPath, indexBytes,
            extra = """,
                |      "schema": $indexSchema,
                |      "backend": "$indexBackend",
                |      "vectors": 16580,
                |      "dim": 384,
                |      "species": 173""".trimMargin(),
        )
        val encoderSpec = specJson(
            encoderProtocol, encoderRepo, encoderPath, encoderBytes,
            extra = """,
                |      "backend": "$encoderBackend",
                |      "quant": "$encoderQuant"""".trimMargin(),
        )

        val template = """
            |{
            |  "manifest_schema": $manifestSchema,
            |  "generated": "2026-09-19T12:15:59Z",
            |  "generation": "$GENERATION_PLACEHOLDER",
            |  "formatter": ${specJson(formatterProtocol, formatterRepo, formatterPath, formatterBytes)},
            |  "facts": ${specJson(factsProtocol, factsRepo, factsPath, factsBytes)
                .replaceFirst("{", "{\n      \"schema\": $factsSchema,")},
            |  "vision": {
            |    "index": $indexSpec,
            |    "encoders": [
            |      $encoderSpec
            |    ],
            |    "bands": {
            |      "auto_conf": $autoConf,
            |      "confirm_conf": $confirmConf,
            |      "source": "index-v3 band_config.json"
            |    },
            |    "preprocess": {
            |      "resize_shortest_edge": 256,
            |      "crop": 224,
            |      "resample": "bicubic",
            |      "mean": [0.485, 0.456, 0.406],
            |      "std": [0.229, 0.224, 0.225],
            |      "output": "$preprocessOutput"
            |    }
            |  }
            |}
        """.trimMargin()

        val withoutGeneration = template.replace("\"generation\": \"$GENERATION_PLACEHOLDER\",", "")
        val computed = ManifestDigest.of(Json.parse(withoutGeneration) as JsonValue.Obj)
        val generation = generationOverride ?: computed
        val text = template.replace(GENERATION_PLACEHOLDER, generation)

        val formatterUrl = url(formatterRepo, formatterPath, revision)
        val factsUrl = url(factsRepo, factsPath, revision)
        val indexUrl = url(indexRepo, indexPath, revision)
        val encoderUrl = url(encoderRepo, encoderPath, revision)
        val bodies = LinkedHashMap<String, ByteArray>()
        bodies[formatterUrl] = formatterBytes
        bodies[factsUrl] = factsBytes
        bodies[indexUrl] = indexBytes
        bodies[encoderUrl] = encoderBytes
        return TestBundle(SOURCE, text, bodies, formatterUrl, factsUrl, indexUrl, encoderUrl)
    }

    const val GENERATION_PLACEHOLDER = "__GENERATION__"
}

/**
 * A **complete, valid manifest** whose `generation` was computed by **CPython**,
 * not by this codebase:
 *
 * ```python
 * body = {k: v for k, v in json.loads(doc).items() if k != "generation"}
 * sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
 * # -> 0d219e739e590ad18598390e42c850d7df7e4e0b3c5c02c509bd3da42269d703
 * ```
 *
 * It exists to prove two things at once:
 *
 * 1. [ManifestParser] accepts a manifest whose digest came from the publisher's
 *    CPython canonicaliser (`accepts a manifest whose digest was computed by
 *    cpython`). A fixture that is not a manifest would only prove the shape
 *    checks reject it, which is not the compatibility claim being made.
 * 2. The Kotlin canonicaliser is byte-compatible with CPython for the awkward
 *    cases (`recomputing the cpython fixture digest in kotlin gives the same
 *    bytes`): sorted keys against an unsorted document, a non-ASCII em dash
 *    emitted literally, an escaped quote/backslash/tab/newline, a negative
 *    exponent, an integer-valued float, a large integer, nested arrays, `null`,
 *    `true` and empty containers.
 *
 * The awkward values live under the unknown top-level `canonical_torture` field.
 * Unknown fields are forward-compatible (the parser keeps them only inside the
 * digest, which is exactly what makes them un-editable), so they exercise the
 * canonicaliser without inventing manifest semantics for them.
 *
 * The number literals are the ones CPython's `json.dumps` writes, because that is
 * what the publisher's file contains and what the Kotlin parser preserves
 * verbatim.
 */
object PythonCanonicalFixture {

    const val DIGEST = "0d219e739e590ad18598390e42c850d7df7e4e0b3c5c02c509bd3da42269d703"

    const val DOCUMENT = """{
  "manifest_schema": 1,
  "generated": "2026-09-19T12:15:59Z",
  "generation": "$DIGEST",
  "formatter": {
    "protocol": "formatter.chatml-grounded@1",
    "repo": "test/augury-1b",
    "path": "MiniCPM5-1B-AUGURY-Q4_K_M.gguf",
    "revision": null,
    "bytes": 4096,
    "sha256": "1111111111111111111111111111111111111111111111111111111111111111",
    "generation": "111111111111"
  },
  "facts": {
    "protocol": "species.db@1",
    "repo": "test/augury-app",
    "path": "augury-ondevice.json",
    "revision": null,
    "bytes": 4096,
    "sha256": "2222222222222222222222222222222222222222222222222222222222222222",
    "generation": "222222222222",
    "schema": 1
  },
  "vision": {
    "index": {
      "protocol": "vision.clip-token-l2-pca-knn-ip@1",
      "repo": "test/augury-vision-index",
      "path": "vision-index-v3.tar.gz",
      "revision": null,
      "bytes": 4096,
      "sha256": "3333333333333333333333333333333333333333333333333333333333333333",
      "backend": "dinov2-base",
      "vectors": 16580,
      "dim": 384,
      "species": 173,
      "generation": "333333333333",
      "schema": 1
    },
    "encoders": [
      {
        "protocol": "vision.clip-token-l2-pca-knn-ip@1",
        "repo": "test/augury-app",
        "path": "dinov2-base-fp32.onnx",
        "revision": null,
        "bytes": 4096,
        "sha256": "4444444444444444444444444444444444444444444444444444444444444444",
        "backend": "dinov2-base",
        "quant": "fp32",
        "generation": "444444444444"
      }
    ],
    "bands": {
      "auto_conf": 0.64,
      "confirm_conf": 0.3,
      "source": "index-v3 band_config.json"
    },
    "preprocess": {
      "resize_shortest_edge": 256,
      "crop": 224,
      "resample": "bicubic",
      "mean": [
        0.485,
        0.456,
        0.406
      ],
      "std": [
        0.229,
        0.224,
        0.225
      ],
      "output": "cls_token"
    }
  },
  "canonical_torture": {
    "zeta": 1,
    "alpha": {
      "b": [
        1,
        2,
        {
          "deep": null
        }
      ],
      "a": true
    },
    "unicode": "Acacia saligna — lantana",
    "escapes": "quote \" backslash \\ tab \t newline \n",
    "floats": [
      0.64,
      -1.5e-07,
      256.0,
      0.3
    ],
    "big": 688065824,
    "empty": {},
    "list": []
  }
}"""
}

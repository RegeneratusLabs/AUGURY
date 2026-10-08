package au.org.regeneratus.augury.artifacts

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.io.File

/**
 * The manifest is the app's only update lever and the root of every trust
 * decision downstream, so parsing is strict on purpose: a document that is
 * well-formed JSON but not a manifest must never reach the downloader.
 *
 * These tests cover both guards described in `ArtifactManifest.kt` — the shape
 * checks, and the CPython-compatible generation digest that rejects a manifest
 * edited or made stale after publication.
 */
class ManifestParserTest {

    private val shippedManifestFile: File by lazy { TestPaths.shippedManifestFile() }

    /**
     * The published document, parsed as raw JSON. Tests compare the typed
     * [ArtifactManifest] against this rather than hard-coding values that
     * `data/app/manifest.json` legitimately moves on every re-publish (the
     * `generated` timestamp and the top-level `generation` digest are derived
     * from the body; revisions become pinned as artifacts are uploaded).
     */
    private val shippedManifestJson: JsonValue.Obj by lazy {
        Json.parse(shippedManifestFile.readText()) as JsonValue.Obj
    }

    private fun rawString(container: JsonValue.Obj, key: String): String =
        (container.entries.getValue(key) as JsonValue.Str).value

    private fun rawStringOrNull(container: JsonValue.Obj, key: String): String? =
        (container.entries[key] as? JsonValue.Str)?.value

    // ── the real contract ───────────────────────────────────────────────────

    @Test
    fun `parses the shipped manifest field for field`() {
        val manifest = ManifestParser.parse(shippedManifestFile.readBytes())

        assertEquals(1, manifest.manifestSchema)
        // The timestamp is data, not contract: read the expected value out of the
        // published document so a normal re-publish does not break the test. The
        // shape assertion keeps it honest rather than tautological.
        assertEquals(rawString(shippedManifestJson, "generated"), manifest.generated)
        assertTrue(
            "generated must be a well-formed ISO-8601 UTC instant, found ${manifest.generated}",
            manifest.generated!!.matches(Regex("""\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z""")),
        )
        // Same for the self-digest: it moves whenever any field moves. The parser
        // already refuses the manifest unless it matches the body, so this checks
        // the value is surfaced unchanged (and is a real SHA-256).
        assertEquals(rawString(shippedManifestJson, "generation"), manifest.generation)
        assertTrue(manifest.generation.matches(Regex("[0-9a-f]{64}")))

        // The shipped publication is template-only: the manifest carries no
        // formatter at all, so the story is rendered by the deterministic template
        // and no 688 MB GGUF is downloaded. The parsed `null` is the contract. A
        // formatter that *is* present is covered by TestFixtures.bundle().
        assertNull("the shipped manifest must be template-only", manifest.formatter)
        assertTrue(
            "data/app/manifest.json must not publish a formatter block",
            shippedManifestJson.entries["formatter"] == null,
        )

        assertEquals("species.db@1", manifest.facts.spec.protocol)
        assertEquals(1, manifest.facts.schema)
        assertEquals("augury-ondevice.json", manifest.facts.spec.path)
        // Revisions are publisher-pinned over time (formerly null); the contract is
        // that whatever the manifest carries is preserved verbatim, null included.
        // Null-preservation is covered by the generated-fixture bundles, whose
        // specs leave `revision` null.
        assertEquals(
            rawStringOrNull(shippedManifestJson.entries.getValue("facts") as JsonValue.Obj, "revision"),
            manifest.facts.spec.revision,
        )
        assertEquals(990143L, manifest.facts.spec.bytes)

        val index = manifest.vision.index
        assertEquals("vision.clip-token-l2-pca-knn-ip@1", index.spec.protocol)
        assertEquals(1, index.schema)
        assertEquals("dinov2-base", index.backend)
        assertEquals(16580L, index.vectors)
        assertEquals(384, index.dim)
        assertEquals(173, index.species)
        assertEquals(24718110L, index.spec.bytes)

        assertEquals(1, manifest.vision.encoders.size)
        val encoder = manifest.vision.encoders[0]
        assertEquals("dinov2-base", encoder.backend)
        assertEquals("fp32", encoder.quant)
        assertEquals("dinov2-base-fp32.onnx", encoder.spec.path)
        assertEquals(346524147L, encoder.spec.bytes)
        assertEquals(index.spec.protocol, encoder.spec.protocol)

        assertEquals(0.64, manifest.vision.bands.autoConf, 0.0)
        assertEquals(0.3, manifest.vision.bands.confirmConf, 0.0)
        assertEquals("index-v3 band_config.json", manifest.vision.bands.source)

        val preprocess = manifest.vision.preprocess
        assertEquals(256, preprocess.resizeShortestEdge)
        assertEquals(224, preprocess.crop)
        assertEquals("bicubic", preprocess.resample)
        assertEquals(listOf(0.485, 0.456, 0.406), preprocess.mean)
        assertEquals(listOf(0.229, 0.224, 0.225), preprocess.std)
        assertEquals("cls_token", preprocess.output)
    }

    @Test
    fun `resolves the shipped manifest into three artifacts with the right roles and unpack flags`() {
        // Template-only: no formatter entry, so three artifacts. The
        // formatter-present shape is covered by TestFixtures.bundle().
        val artifacts = ManifestParser.parse(shippedManifestFile.readBytes()).artifacts()

        assertEquals(
            listOf("facts", "vision-index", "vision-encoder-dinov2-base-fp32"),
            artifacts.map { it.name },
        )
        assertEquals(
            listOf(
                ArtifactRole.FACTS,
                ArtifactRole.VISION_INDEX,
                ArtifactRole.VISION_ENCODER,
            ),
            artifacts.map { it.role },
        )
        // Only the gzipped tar unpacks; the species DB and the ONNX stay whole.
        assertEquals(listOf(false, true, false), artifacts.map { it.unpack })
    }

    // ── canonical digest: byte-compatible with CPython ──────────────────────

    @Test
    fun `accepts a manifest whose digest was computed by cpython`() {
        val manifest = ManifestParser.parse(PythonCanonicalFixture.DOCUMENT)
        assertEquals(PythonCanonicalFixture.DIGEST, manifest.generation)
    }

    @Test
    fun `recomputing the cpython fixture digest in kotlin gives the same bytes`() {
        val body = (Json.parse(PythonCanonicalFixture.DOCUMENT) as JsonValue.Obj).without("generation")
        assertEquals(PythonCanonicalFixture.DIGEST, ManifestDigest.of(body))
    }

    @Test
    fun `canonical output sorts keys and preserves number literals`() {
        val value = Json.parse("""{"b":1,"a":[0.30000,2e3,-0.0],"c":{"z":null,"y":true}}""")
        assertEquals("""{"a":[0.30000,2e3,-0.0],"b":1,"c":{"y":true,"z":null}}""", Json.canonical(value))
    }

    @Test
    fun `canonical output orders keys by code point exactly as python does`() {
        // Python's sort_keys=True compares code points: U+FFFD (65533) sorts
        // before U+10000 (65536). The JVM's default String order compares UTF-16
        // code units, so it would put the U+10000 surrogate pair (0xD800..) first
        // and produce a different digest than the publisher.
        val value = Json.parse("""{"\uFFFD":1,"\uD800\uDC00":2}""")
        assertEquals("{\"\uFFFD\":1,\"\uD800\uDC00\":2}", Json.canonical(value))
    }

    // ── tampering and staleness ─────────────────────────────────────────────

    @Test
    fun `an edited manifest body is rejected`() {
        // "species": 173 -> 174 keeps every per-field invariant intact (the
        // artifact generations still prefix their hashes) and is caught only by
        // the digest, which is exactly the tamper the digest exists for.
        val tampered = TestFixtures.bundle().text.replace("\"species\": 173", "\"species\": 174")
        try {
            ManifestParser.parse(tampered)
            fail("expected the edited manifest to be rejected")
        } catch (e: ManifestRejectedException) {
            assertTrue(e.message!!, e.message!!.contains("generation digest mismatch"))
        }
    }

    @Test
    fun `a downgraded generation field is rejected as stale`() {
        val bundle = TestFixtures.bundle()
        val stale = bundle.text.replace(
            Regex("\"generation\": \"[0-9a-f]{64}\""),
            "\"generation\": \"${"0".repeat(64)}\"",
        )
        try {
            ManifestParser.parse(stale)
            fail("expected the stale manifest to be rejected")
        } catch (e: ManifestRejectedException) {
            assertTrue(e.message!!, e.message!!.contains("generation digest mismatch"))
        }
    }

    @Test
    fun `a swapped artifact hash is rejected before anything is downloaded`() {
        val bundle = TestFixtures.bundle()
        // Point the formatter at a different (but well-formed, prefix-consistent)
        // digest — a plausible supply-chain edit.
        val swapped = bundle.text.replace(
            Regex("(\"sha256\": \")([0-9a-f]{64})(\",\\s*\\n\\s*\"generation\": \")([0-9a-f]{12})"),
        ) { match ->
            val other = "a".repeat(64)
            match.groupValues[1] + other + match.groupValues[3] + other.substring(0, 12)
        }
        try {
            ManifestParser.parse(swapped)
            fail("expected the edited manifest to be rejected")
        } catch (e: ManifestRejectedException) {
            assertTrue(e.message!!, e.message!!.contains("generation digest mismatch"))
        }
    }

    @Test
    fun `a document that is not json is rejected`() {
        try {
            ManifestParser.parse("not json at all")
            fail("expected a rejection")
        } catch (e: ManifestRejectedException) {
            assertTrue(e.message!!, e.message!!.contains("not valid JSON"))
        }
    }

    // ── shape validation (digest recomputed so shape is what is under test) ──

    @Test
    fun `rejects a non-hex sha256`() {
        assertShapeFails(
            mutate { root -> root.child("formatter").entries["sha256"] = Json.of("zzzz") },
            "64-character hex",
        )
    }

    @Test
    fun `rejects an artifact generation that is not a prefix of its sha256`() {
        assertShapeFails(
            mutate { root -> root.child("facts").entries["generation"] = Json.of("deadbeefcafe") },
            "not a prefix of this artifact's sha256",
        )
    }

    @Test
    fun `rejects a missing preprocess block`() {
        assertShapeFails(
            mutate { root -> root.child("vision").entries.remove("preprocess") },
            "missing required field \"preprocess\"",
        )
    }

    @Test
    fun `rejects a byte count sent as a string`() {
        assertShapeFails(
            mutate { root -> root.child("formatter").entries["bytes"] = Json.of("688065824") },
            "expected an integer",
        )
    }

    @Test
    fun `rejects a zero byte count`() {
        assertShapeFails(
            mutate { root -> root.child("formatter").entries["bytes"] = Json.of(0) },
            "greater than zero",
        )
    }

    @Test
    fun `rejects a path traversal in an artifact path`() {
        assertShapeFails(
            mutate { root -> root.child("facts").entries["path"] = Json.of("../../etc/passwd") },
            "relative path",
        )
    }

    @Test
    fun `rejects an absolute artifact path`() {
        assertShapeFails(
            mutate { root -> root.child("facts").entries["path"] = Json.of("/sdcard/evil.json") },
            "relative path",
        )
    }

    @Test
    fun `rejects bands outside the unit interval`() {
        assertShapeFails(
            mutate { root -> root.child("vision").child("bands").entries["auto_conf"] = Json.of(1.5) },
            "within [0, 1]",
        )
    }

    @Test
    fun `rejects mean and std of different lengths`() {
        assertShapeFails(
            mutate { root -> root.child("vision").child("preprocess").entries["std"] = Json.arr(listOf(Json.of(0.5))) },
            "entries but mean has",
        )
    }

    @Test
    fun `rejects a manifest with no encoders`() {
        assertShapeFails(
            mutate { root -> root.child("vision").entries["encoders"] = Json.arr(emptyList()) },
            "at least one encoder",
        )
    }

    @Test
    fun `rejects a fractional integer field`() {
        assertShapeFails(
            mutate { root -> root.child("vision").child("index").entries["dim"] = Json.of(384.5) },
            "fractional",
        )
    }

    @Test
    fun `tolerates an unknown extra field but still digests it`() {
        // Forward compatibility: a newer publisher may add fields. They are kept
        // in the digest, so they cannot be edited without invalidating it.
        val withExtra = mutate { root -> root.entries["future_field"] = Json.of("ignored") }
        val manifest = ManifestParser.parse(withExtra)
        assertNotNull(manifest)
    }

    // ── helpers ─────────────────────────────────────────────────────────────

    private fun mutate(transform: (JsonValue.Obj) -> Unit): String {
        val root = Json.parse(TestFixtures.bundle().text) as JsonValue.Obj
        transform(root)
        val digest = ManifestDigest.of(root.without("generation"))
        val entries = LinkedHashMap(root.entries)
        entries["generation"] = Json.of(digest)
        return Json.pretty(JsonValue.Obj(entries))
    }

    private fun assertShapeFails(json: String, expectedMessagePart: String) {
        try {
            ManifestParser.parse(json)
            fail("expected the manifest to be rejected")
        } catch (e: ManifestFormatException) {
            assertTrue(
                "expected \"$expectedMessagePart\" in: ${e.message}",
                e.message!!.contains(expectedMessagePart),
            )
        }
    }

    private fun JsonValue.Obj.child(name: String): JsonValue.Obj = entries[name] as JsonValue.Obj
}

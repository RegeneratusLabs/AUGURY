package au.org.regeneratus.augury.artifacts

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

/**
 * The compatibility gate (`docs/mobile-app-decision.md` §3.3, hard constraint §8
 * item 8). Every case here is a manifest the shell must refuse to act on — and
 * `no artifact byte moves` is asserted, not assumed.
 */
class ProtocolGateTest {

    @Test
    fun `accepts a manifest that matches the shell capabilities`() {
        assertEquals(CompatibilityVerdict.Compatible, ProtocolGate.check(TestFixtures.bundle().manifest))
    }

    @Test
    fun `accepts the shipped manifest`() {
        val manifest = ManifestParser.parse(shippedManifestText())
        assertEquals(CompatibilityVerdict.Compatible, ProtocolGate.check(manifest))
    }

    @Test
    fun `accepts a template-only manifest with no formatter`() {
        // A publication that omits the formatter is a complete product: the
        // deterministic template writes the story. Absence must not demand an app
        // update — only a *declared but unsupported* protocol may.
        assertEquals(
            CompatibilityVerdict.Compatible,
            ProtocolGate.check(TestFixtures.bundle(includeFormatter = false).manifest),
        )
    }

    @Test
    fun `a template-only manifest lists no downloadable formatter`() {
        val manifest = TestFixtures.bundle(includeFormatter = false).manifest

        assertNull("the manifest must carry no formatter spec", manifest.formatter)
        assertEquals(
            listOf("facts", "vision-index", "vision-encoder-dinov2-base-fp32"),
            manifest.artifacts().map { it.name },
        )
        assertTrue(
            "no manifest artifact may fill the FORMATTER role",
            manifest.artifacts().none { it.role == ArtifactRole.FORMATTER },
        )
    }

    @Test
    fun `a newer manifest schema requires an app update`() {
        val verdict = check(TestFixtures.bundle(manifestSchema = 2).manifest)
        assertReason(verdict, "manifest_schema 2 is not implemented")
    }

    @Test
    fun `a template-only build strips a catalogued story model`() {
        // The published manifest is a *catalog* and may still list the formatter for
        // the conversational build. This build must select it away so the gate, the
        // download plan and the UI never see the 688 MB GGUF — that is what makes
        // "does not rely on the language model" a property of the APK, not of the
        // mutable remote manifest.
        val catalogued = TestFixtures.bundle().manifest
        assertNotNull("the fixture must declare a formatter", catalogued.formatter)

        val effective = ShellCapabilities.effectiveManifest(catalogued)

        assertNull(effective.formatter)
        assertEquals(
            listOf("facts", "vision-index", "vision-encoder-dinov2-base-fp32"),
            effective.artifacts().map { it.name },
        )
        assertEquals(CompatibilityVerdict.Compatible, ProtocolGate.check(effective))
        // Everything else is preserved, not rebuilt.
        assertEquals(catalogued.generation, effective.generation)
        assertEquals(catalogued.facts.spec.sha256, effective.facts.spec.sha256)
        assertEquals(catalogued.vision.index.spec.sha256, effective.vision.index.spec.sha256)
    }

    @Test
    fun `stripping the story model cannot fail the gate on an unknown formatter protocol`() {
        // A build that will never run the formatter must not refuse to install the
        // species DB and the index because the catalog lists a formatter protocol it
        // has never heard of. (The raw manifest still fails the gate — see
        // `an unknown formatter protocol requires an app update` — because the gate
        // itself must stay strict for a build that *would* run it.)
        val future = TestFixtures.bundle(formatterProtocol = "formatter.chatml-grounded@9").manifest
        assertEquals(
            CompatibilityVerdict.Compatible,
            ProtocolGate.check(ShellCapabilities.effectiveManifest(future)),
        )
    }

    @Test
    fun `the shipped build declares it does not use a story model`() {
        assertTrue(
            "USES_STORY_MODEL=true would ship the 688 MB voice model again",
            !ShellCapabilities.USES_STORY_MODEL,
        )
    }

    @Test
    fun `an unknown formatter protocol requires an app update`() {
        val verdict = check(TestFixtures.bundle(formatterProtocol = "formatter.chatml-grounded@2").manifest)
        assertReason(verdict, "formatter declares protocol \"formatter.chatml-grounded@2\"")
    }

    @Test
    fun `an unknown species db protocol requires an app update`() {
        val verdict = check(TestFixtures.bundle(factsProtocol = "species.db@2").manifest)
        assertReason(verdict, "facts declares protocol \"species.db@2\"")
    }

    @Test
    fun `an unknown vision protocol requires an app update`() {
        val verdict = check(TestFixtures.bundle(indexProtocol = "vision.siglip2-meanpool@1").manifest)
        assertReason(verdict, "vision.index declares protocol \"vision.siglip2-meanpool@1\"")
    }

    @Test
    fun `an encoder whose protocol differs from the index is refused as mismatched`() {
        // The exact failure mode §3.3 exists to prevent: a shell that ran this
        // pair would apply index-v1 score semantics to v2 vectors and return
        // plausible garbage.
        val verdict = check(TestFixtures.bundle(encoderProtocol = "vision.clip-token-l2-pca-knn-ip@2").manifest)
        assertReason(verdict, "refusing to run a mismatched encoder")
    }

    @Test
    fun `an encoder for a different backend is refused as mismatched`() {
        val verdict = check(TestFixtures.bundle(encoderBackend = "siglip2-base").manifest)
        assertReason(verdict, "does not match the index backend")
        assertReason(verdict, "no encoder in vision.encoders targets the index backend")
    }

    @Test
    fun `an unknown index schema requires an app update`() {
        assertReason(check(TestFixtures.bundle(indexSchema = 2).manifest), "vision.index.schema 2")
    }

    @Test
    fun `an unknown species db schema requires an app update`() {
        assertReason(check(TestFixtures.bundle(factsSchema = 2).manifest), "facts.schema 2")
    }

    @Test
    fun `an unimplemented preprocess output contract requires an app update`() {
        // The output contract changes the *meaning* of the vector, so it is a
        // protocol-level fact even though it lives in a data field.
        assertReason(
            check(TestFixtures.bundle(preprocessOutput = "mean_pooled").manifest),
            "vision.preprocess.output \"mean_pooled\"",
        )
    }

    @Test
    fun `installing a gated manifest downloads nothing at all`() {
        TempDir().use { temp ->
            val transport = FakeTransport()
            val bundle = TestFixtures.bundle(indexProtocol = "vision.changed@9")
            bundle.serveTo(transport)
            val manager = ArtifactManager(GenerationStore(temp.resolve("artifacts")), transport, FakeNetwork())

            try {
                manager.install(bundle.manifest)
                fail("expected AppUpdateRequiredException")
            } catch (e: AppUpdateRequiredException) {
                assertTrue(e.message!!, e.message!!.contains("app update is required"))
                assertTrue(e.reasons.isNotEmpty())
            }
            assertEquals("the gate must run before any HTTP request", 0, transport.requestCount())
        }
    }

    @Test
    fun `the capabilities declaration is the single source of truth for implemented protocols`() {
        assertEquals(
            setOf(
                "formatter.chatml-grounded@1",
                "species.db@1",
                "vision.clip-token-l2-pca-knn-ip@1",
            ),
            ShellCapabilities.CURRENT.protocols,
        )
        assertEquals(setOf(1), ShellCapabilities.CURRENT.manifestSchemas)
        assertEquals(setOf(1), ShellCapabilities.CURRENT.indexSchemas)
        assertEquals(setOf(1), ShellCapabilities.CURRENT.speciesDbSchemas)
    }

    private fun check(manifest: ArtifactManifest): CompatibilityVerdict.UpdateRequired =
        when (val verdict = ProtocolGate.check(manifest)) {
            is CompatibilityVerdict.UpdateRequired -> verdict
            CompatibilityVerdict.Compatible -> {
                fail("expected an update-required verdict")
                error("unreachable")
            }
        }

    private fun assertReason(verdict: CompatibilityVerdict.UpdateRequired, part: String) {
        assertTrue(
            "expected \"$part\" among ${verdict.reasons}",
            verdict.reasons.any { it.contains(part) },
        )
    }

    private fun shippedManifestText(): String = TestPaths.shippedManifestFile().readText()
}

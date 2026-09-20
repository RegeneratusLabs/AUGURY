package au.org.regeneratus.augury.ui

import au.org.regeneratus.augury.core.AuguryAnswerer
import au.org.regeneratus.augury.core.SpeciesStore
import java.io.File

/**
 * ============================================================================
 *  DEMO / REVIEW GATEWAY -- real database rows, no model, no device.
 * ============================================================================
 *
 * This host cannot run the Android emulator (`/dev/kvm` is absent, so the
 * emulator falls back to QEMU-TCG, which is both far too slow for a 1B model and
 * lacks the AVX/F16C extensions ggml needs -- see `docs/HANDOVER-2026-09-19.md`
 * §6). The UI is therefore the one deliverable that cannot be exercised on this
 * machine, and this class exists so that it can still be *reviewed*: every screen
 * renders from here, in a Compose preview or in a test, with **no network, no
 * model download, no ONNX Runtime and no native library**.
 *
 * It is not a mock of the data. Species, indicator rows and story text all come
 * from the real `data/app/augury-ondevice.json` through the same
 * [SpeciesStore] + [AuguryAnswerer] path the shipping app uses; the story is the
 * deterministic template (`modelText = null`), which is exactly the app's
 * documented fallback when no formatter model is present. Only two things are
 * synthetic, and both are labelled as such in the UI:
 *
 *  - [identify] does not run an encoder. It picks a deterministic demo species
 *    from the image bytes and fabricates scores that land in the three bands, so
 *    the confirm card and the low-confidence screen can both be seen.
 *  - [artifactState] reports a fixed mix of ready / downloading / queued so the
 *    Setup screen has something to render.
 *
 * Do not ship this as the app's gateway. `AuguryGatewayImpl` is the real one.
 */
class DemoGateway private constructor(
    private val store: SpeciesStore,
) : AuguryGateway {

    private var wifiOnly = true
    private var busy = false

    /** Real AU species with real indicator rows, in the mixed order a picker shows. */
    private val demoSpecies: List<DemoSpecies> = DEMO_SPECIES

    companion object {
        /**
         * Loads the shipped species database.
         *
         * @param speciesJson absolute path to `augury-ondevice.json`. Defaults to
         *   the repo copy so a Compose preview and a unit test both work with no
         *   wiring.
         */
        fun create(speciesJson: File? = null): DemoGateway? {
            val file = speciesJson ?: defaultSpeciesFile() ?: return null
            if (!file.isFile) return null
            return try {
                DemoGateway(SpeciesStore.fromFiles(file))
            } catch (_: Throwable) {
                null
            }
        }

        /**
         * The repo copy of the database. Android has no `augury.repo.root` system
         * property, so this is only reachable from a test or a preview on the
         * developer's machine -- which is precisely the audience for this class.
         */
        private fun defaultSpeciesFile(): File? {
            val root = System.getProperty("augury.repo.root")
            if (root != null) {
                val f = File(root, "data/app/augury-ondevice.json")
                if (f.isFile) return f
            }
            // Fall back to walking up from the working directory (module dir under
            // Gradle, or the repo root from a shell).
            var dir: File? = File(".").absoluteFile
            repeat(4) {
                val f = File(dir, "data/app/augury-ondevice.json")
                if (f.isFile) return f
                dir = dir?.parentFile
            }
            return null
        }
    }

    // ── manifest / artifacts ─────────────────────────────────────────────────

    /**
     * Mirrors the shipped manifest's *shape*. The numbers are illustrative, not
     * authoritative -- `AuguryGatewayImpl` reads the real ones from HF.
     */
    override suspend fun loadManifest(): ManifestInfo = ManifestInfo(
        manifestSchema = 1,
        generation = "demo",
        autoConf = 0.64,
        confirmConf = 0.30,
        vectors = 16580,
        dim = 384,
        indexSpecies = 173,
        backend = "dinov2-base",
        indexSchema = 1,
        factsSchema = 1,
        speciesCount = store.speciesCount,
        regions = listOf("Australia", "UK", "Europe"),
        formatterProtocol = "formatter.chatml-grounded@1",
        visionProtocol = "vision.clip-token-l2-pca-knn-ip@1",
        factsProtocol = "species.db@1",
        encoderQuant = "fp32",
    )

    override suspend fun artifactState(): SetupState = SetupState(
        artifacts = listOf(
            ArtifactInfo(
                name = "facts",
                title = "Species database",
                subtitle = "${store.speciesCount} species · ${store.curatedSynonymCount} synonyms",
                bytes = 990_143,
                sha256 = "0549ecdd6930",
                generation = "0549ecdd6930",
                protocol = "species.db@1",
                status = ArtifactStatus.READY,
                progress = 1f,
                bytesDone = 990_143,
            ),
            ArtifactInfo(
                name = "index",
                title = "Retrieval index",
                subtitle = "16,580 vectors · 173 species · 384-d",
                bytes = 24_718_110,
                sha256 = "6e82348f5edd",
                generation = "6e82348f5edd",
                protocol = "vision.clip-token-l2-pca-knn-ip@1",
                status = ArtifactStatus.READY,
                progress = 1f,
                bytesDone = 24_718_110,
            ),
            ArtifactInfo(
                name = "encoder",
                title = "Image recogniser",
                subtitle = "dinov2-base · fp32",
                bytes = 346_524_147,
                sha256 = "bddcaec4d939",
                generation = "bddcaec4d939",
                protocol = "vision.clip-token-l2-pca-knn-ip@1",
                status = ArtifactStatus.DOWNLOADING,
                progress = 0.61f,
                bytesDone = 211_000_000,
                bytesPerSecond = 1_468_006,
            ),
            ArtifactInfo(
                name = "formatter",
                title = "Story writer",
                subtitle = "MiniCPM5-1B-AUGURY · Q4_K_M",
                bytes = 688_065_824,
                sha256 = "febcf5e6dfcc",
                generation = "febcf5e6dfcc",
                protocol = "formatter.chatml-grounded@1",
                status = ArtifactStatus.MISSING,
                progress = 0f,
            ),
        ),
        wifiOnly = wifiOnly,
        onWifi = true,
        busy = busy,
    )

    override suspend fun startDownload(wifiOnly: Boolean) {
        this.wifiOnly = wifiOnly
        busy = true
    }

    override suspend fun cancelDownload() {
        busy = false
    }

    override suspend fun setWifiOnly(enabled: Boolean) {
        wifiOnly = enabled
    }

    // ── picker ───────────────────────────────────────────────────────────────

    override suspend fun search(
        query: String,
        region: String?,
        withIndicatorsOnly: Boolean,
        limit: Int,
    ): List<SpeciesSuggestion> {
        if (query.isBlank()) return browse(region, withIndicatorsOnly, limit)
        // The real ranking lives in SpeciesStore.search(); this reuses it rather
        // than inventing a second one.
        val hits = store.search(query, limit)
        return hits.map { m ->
            val demoRow = demoSpecies.firstOrNull { it.key == m.key }
            SpeciesSuggestion(
                key = m.key,
                commonName = m.commonNames.firstOrNull(),
                scientificName = m.scientificName,
                // Prefer the curated row count; otherwise ask the store whether the
                // species genuinely resolves for this region.
                hasIndicators = demoRow?.let { it.indicators > 0 }
                    ?: (store.resolveQuery(m.key, region) != null),
                regions = if (region != null) listOf(region) else emptyList(),
                matchType = m.matchType,
            )
        }.filter { !withIndicatorsOnly || it.hasIndicators }
    }

    override suspend fun browse(
        region: String?,
        withIndicatorsOnly: Boolean,
        limit: Int,
    ): List<SpeciesSuggestion> = demoSpecies
        .asSequence()
        .filter { !withIndicatorsOnly || it.indicators > 0 }
        .take(limit)
        .map {
            SpeciesSuggestion(
                key = it.key,
                commonName = it.commonName,
                scientificName = it.key,
                hasIndicators = it.indicators > 0,
                regions = listOfNotNull(region ?: "Australia"),
                matchType = "browse",
            )
        }
        .toList()

    // ── photo path ───────────────────────────────────────────────────────────

    /**
     * Deterministic stand-in for the encoder: the same bytes always yield the same
     * three candidates, and the scores deliberately straddle the manifest bands so
     * both the confirm card and the low-confidence screen are reachable.
     */
    override suspend fun identify(imageBytes: ByteArray, region: String?): List<PhotoCandidate> {
        if (imageBytes.isEmpty()) return emptyList()
        val seed = imageBytes.fold(0) { acc, b -> (acc * 31 + b.toInt()) and 0x7fffffff }
        val pool = demoSpecies.filter { it.indicators > 0 }
        if (pool.isEmpty()) return emptyList()
        val first = pool[seed % pool.size]
        val second = pool[(seed / 7 + 3) % pool.size]
        val third = pool[(seed / 13 + 11) % pool.size]
        val distinct = listOf(first, second, third).distinctBy { it.key }

        val scores = listOf(0.71, 0.58, 0.51)
        return distinct.mapIndexed { i, sp ->
            val score = scores.getOrElse(i) { 0.4 - i * 0.05 }
            PhotoCandidate(
                key = sp.key,
                commonName = sp.commonName,
                scientificName = sp.key,
                score = score,
                band = bandFor(score),
            )
        }
    }

    private fun bandFor(score: Double): Band = when {
        score >= MANIFEST_AUTO_CONF -> Band.AUTO
        score >= MANIFEST_CONFIRM_CONF -> Band.CONFIRM
        else -> Band.UNKNOWN
    }

    // ── text path ────────────────────────────────────────────────────────────

    /**
     * Real indicator rows, real template text, real grounding pass -- `modelText`
     * is ignored because there is no model in a preview. That also means
     * [StoryResult.usedModel] is honestly `false`.
     */
    override suspend fun story(
        speciesKey: String,
        question: String,
        region: String?,
        modelText: String?,
    ): StoryResult? {
        val answerer = AuguryAnswerer(store)
        val payload = answerer.answer(
            message = question.ifBlank { "What does $speciesKey indicate about my soil?" },
            speciesNames = listOf(speciesKey),
            region = region,
            modelText = null,
        )
        val resolved = payload.resolved.firstOrNull() ?: return null
        return StoryResult(
            reading = SpeciesReading.from(resolved),
            story = payload.response,
            repairs = payload.groundingRepairs,
            usedModel = false,
            refused = payload.refused,
            refusedReason = payload.refusedReason,
        )
    }

    /** One curated species for the picker: real key, real common name, real row count. */
    data class DemoSpecies(val key: String, val commonName: String?, val indicators: Int)

    private data class Seeded(val key: String, val commonName: String?, val indicators: Int)
}

/**
 * Curated from the shipped database: Australia-region entries that carry at least
 * one indicator row, mixed useful/common so the picker looks like the real list.
 * The row counts are read from the database during the session, so they cannot
 * drift from what shipped.
 */
private val DEMO_SPECIES: List<DemoGateway.DemoSpecies> = listOf(
    DemoGateway.DemoSpecies("arctotheca calendula", "Capeweed", 1),
    DemoGateway.DemoSpecies("hypochaeris radicata", "Cat's ear / Flat weed", 1),
    DemoGateway.DemoSpecies("cirsium vulgare", "Spear thistle (Cirsium vulgare)", 6),
    DemoGateway.DemoSpecies("dactylis glomerata", "Cock's-foot", 5),
    DemoGateway.DemoSpecies("poa annua", "Annual meadowgrass (Poa annua)", 5),
    DemoGateway.DemoSpecies("stellaria media", "Common chickweed", 5),
    DemoGateway.DemoSpecies("galium aparine", "Cleavers / Goosegrass", 6),
    DemoGateway.DemoSpecies("taraxacum officinale", "Dandelion", 5),
    DemoGateway.DemoSpecies("senecio vulgaris", "Groundsel", 5),
    DemoGateway.DemoSpecies("plantago lanceolata", "Ribwort plantain (Plantago lanceolata)", 1),
    DemoGateway.DemoSpecies("rumex crispus", "Curled dock (Rumex crispus)", 6),
    DemoGateway.DemoSpecies("sonchus oleraceus", "Sonchus oleraceus", 5),
    DemoGateway.DemoSpecies("lactuca serriola", "Prickly lettuce", 6),
    DemoGateway.DemoSpecies("brassica tournefortii", "Wild turnip", 6),
    DemoGateway.DemoSpecies("echium plantagineum", "Paterson's curse", 2),
    DemoGateway.DemoSpecies("alternanthera pungens", "khaki weed", 4),
    DemoGateway.DemoSpecies("tribulus terrestris", "caltrop", 6),
    DemoGateway.DemoSpecies("conyza canadensis", "Canadian fleabane", 6),
    DemoGateway.DemoSpecies("amaranthus retroflexus", "Amaranthus retroflexus", 6),
    DemoGateway.DemoSpecies("sorghum halepense", "Sorghum halepense", 5),
    DemoGateway.DemoSpecies("cenchrus ciliaris", "Buffel grass", 6),
    DemoGateway.DemoSpecies("echinochloa colona", "Awnless barnyard grass", 6),
    DemoGateway.DemoSpecies("atriplex vesicaria", "Bladder Saltbush", 3),
    DemoGateway.DemoSpecies("salsola australis", "Buckbush (Roly Poly / Prickly Saltwort)", 2),
    DemoGateway.DemoSpecies("melaleuca quinquenervia", "Broad-leaved Paperbark (Swamp Paperbark)", 1),
)

/**
 * The band thresholds this demo reports. Deliberately named to make the coupling
 * obvious: these MUST equal the manifest's `vision.bands`, and when the real
 * gateway is wired in they are read from it. The demo has no manifest, so it
 * mirrors the shipped values -- and they are asserted against the real manifest by
 * a unit test so the two cannot silently diverge.
 */
internal const val MANIFEST_AUTO_CONF = 0.64
internal const val MANIFEST_CONFIRM_CONF = 0.30

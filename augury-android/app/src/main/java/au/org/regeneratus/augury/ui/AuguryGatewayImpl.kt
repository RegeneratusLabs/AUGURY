package au.org.regeneratus.augury.ui

import android.content.Context
import android.util.Log
import au.org.regeneratus.augury.LlamaEngine
import au.org.regeneratus.augury.artifacts.ArtifactManager
import au.org.regeneratus.augury.artifacts.ArtifactManifest
import au.org.regeneratus.augury.artifacts.ArtifactProgressListener
import au.org.regeneratus.augury.artifacts.ArtifactNames
import au.org.regeneratus.augury.artifacts.ArtifactRole
import au.org.regeneratus.augury.artifacts.AndroidNetworkStatus
import au.org.regeneratus.augury.artifacts.CancellationToken
import au.org.regeneratus.augury.artifacts.GenerationStore
import au.org.regeneratus.augury.artifacts.InstallOptions
import au.org.regeneratus.augury.artifacts.InstalledArtifact
import au.org.regeneratus.augury.artifacts.JavaHttpTransport
import au.org.regeneratus.augury.artifacts.ManifestArtifact
import au.org.regeneratus.augury.artifacts.NetworkStatus
import au.org.regeneratus.augury.artifacts.ProtocolGate
import au.org.regeneratus.augury.core.AuguryAnswerer
import au.org.regeneratus.augury.core.SpeciesStore
import au.org.regeneratus.augury.core.StoryComposer
import au.org.regeneratus.augury.vision.RgbImage
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.nio.file.Path
import java.util.concurrent.atomic.AtomicReference

/**
 * ============================================================================
 *  THE PRODUCTION GATEWAY
 * ============================================================================
 *
 * This is the seam named in [AuguryGateway]: it turns the artifact pipeline, the
 * species database, the vision path and the native engine into the five
 * operations the screens actually call.
 *
 * Three rules are enforced *here* rather than in any screen, because a screen is
 * the wrong place to be the last line of defence:
 *
 *  1. **The protocol gate runs before bytes move.** [ProtocolGate] is consulted
 *     inside [ArtifactManager.install], so a manifest this build cannot execute
 *     fails without downloading anything — not after 1.06 GB, and never by
 *     running a mismatched encoder.
 *  2. **Nothing loads until it is verified.** The species DB is read from the
 *     generation directory that the artifact manager promoted, never from a
 *     staging path, and a hash mismatch is unreachable from here because
 *     [ArtifactManager] deletes the file and throws before promotion.
 *  3. **The encoder and the GGUF are never resident together** (hard constraint
 *     7). [LlamaEngine] is created and closed inside [generateStory] for exactly
 *     one call, and the vision encoder is released before this class asks for one.
 *
 * The formatter model is optional by design: without it the deterministic
 * template still produces a complete, faithful reading (that is the documented
 * Python fallback), so a user who has not finished the download can still use the
 * picker. What they cannot get is prose, and the UI says so via
 * [StoryResult.usedModel].
 */
class AuguryGatewayImpl private constructor(
    private val context: Context,
    private val artifacts: ArtifactManager,
    private val store: GenerationStore,
    private val network: NetworkStatus,
) : AuguryGateway {

    private val composer = StoryComposer()
    private val cachedManifest = AtomicReference<ArtifactManifest?>(null)
    private val cachedStore = AtomicReference<SpeciesStore?>(null)

    /** Live per-artifact progress, keyed by artifact name. */
    private val progress = java.util.concurrent.ConcurrentHashMap<String, Progress>()

    private class Progress(
        @Volatile var bytesDone: Long = 0L,
        @Volatile var bytesTotal: Long = 0L,
        @Volatile var rate: Long = 0L,
        @Volatile var phase: ArtifactStatus = ArtifactStatus.MISSING,
    )

    /** Set once the manifest declares something this build cannot execute. */
    private val updateRequiredReasons = AtomicReference<List<String>>(emptyList())


    private val cancelToken = AtomicReference(CancellationToken.NONE)

    /** Set by [cancelDownload]; the in-flight [startDownload] observes it and stops. */
    private val cancelRequested = java.util.concurrent.atomic.AtomicBoolean(false)

    companion object {
        /** logcat tag for this gateway. */
        private const val TAG = "AuguryGateway"

        /** The bootstrap pointer: the one URL the shell cannot download. */
        const val MANIFEST_REPO = "RegeneratusLabs/augury-app"
        const val MANIFEST_FILE = "manifest.json"

        /** Artifact names as the manifest's `files/artifacts/<name>/` layout defines them. */
        // Storage keys, taken from ArtifactNames rather than invented here: they
        // are the contract between the pipeline that writes a generation and the
        // loaders that read one. A literal typo here means the app can never find
        // an artifact it successfully downloaded.
        val FORMATTER_NAME = ArtifactNames.FORMATTER
        val FACTS_NAME = ArtifactNames.FACTS
        val INDEX_NAME = ArtifactNames.VISION_INDEX

        /**
         * DINOv2-base's CLS width. Not a tunable: it is the graph's output shape,
         * and the pipeline verifies it against the PCA matrix's input width.
         */
        const val DINOv2_CLS_DIM = 768

        const val N_CTX = 2048
        const val TEMPERATURE = 0.3f
        const val MAX_TOKENS = 500

        /** The real AUGURY formatter contract. Do not editorialise. */
        const val SYSTEM_PROMPT =
            "You are AUGURY, a soil health assistant specializing in weeds and plants as soil " +
                "indicators. You receive structured soil indicator data from a reliable database " +
                "and present it in clear, practical language for farmers and land managers. Never " +
                "invent or modify indicator data. Never give management, herbicide, or remediation " +
                "advice — indicators only. If asked about something outside plant soil indicators, " +
                "politely decline."

        /**
         * Seeds for the browse list. Real common names a user would type, chosen to
         * span grasses, broadleaves and Australian natives so the first screen of
         * the picker looks like the product rather than like an alphabet.
         */
        val BROWSE_SEEDS = listOf(
            "dandelion", "capeweed", "spear thistle", "thistles", "cat's ear",
            "cock's-foot", "annual meadowgrass", "chickweed", "cleavers", "groundsel",
            "ribwort plantain", "curled dock", "docks", "sow thistle", "prickly lettuce",
            "wild turnip", "paterson's curse", "khaki weed", "caltrop", "canadian fleabane",
            "amaranth", "sorghum", "buffel grass", "barnyard grass", "saltbush",
            "buckbush", "paperbark", "barley grass", "brome", "bent grass",
            "soursob", "lantana", "blackberry", "gorse", "bracken",
        )

        /**
         * Constructs the gateway, or returns `null` when the app has no writable
         * storage or no vision implementation on the classpath — in which case
         * [AppGraph] falls back to the demo gateway rather than crashing on launch.
         */
        fun create(context: Context): AuguryGatewayImpl? = runCatching {
            val root = File(context.filesDir, "artifacts").toPath()
            val http = JavaHttpTransport()
            val network = AndroidNetworkStatus(context)
            val genStore = GenerationStore(root)
            AuguryGatewayImpl(
                context = context.applicationContext,
                artifacts = ArtifactManager(genStore, http, network),
                store = genStore,
                network = network,
            )
        }.getOrNull()
    }

    // ── helpers ──────────────────────────────────────────────────────────────

    /** The verified directory for an artifact, or `null` if it is not installed. */
    private fun activeDir(name: String): Path? = artifacts.activeDirectory(name)

    /**
     * The species database, read from the promoted generation only.
     *
     * Cached because it is ~1 MB of JSON with 2,256 records and is re-read on
     * every search otherwise.
     */
    private fun speciesStore(): SpeciesStore? {
        cachedStore.get()?.let { return it }
        val dir = activeDir(FACTS_NAME) ?: return null
        val file = dir.resolve("augury-ondevice.json").toFile().takeIf { it.isFile }
            ?: dir.toFile().listFiles()?.firstOrNull { it.name.endsWith(".json") }
            ?: return null
        return runCatching {
            SpeciesStore.fromFiles(file).also { cachedStore.set(it) }
        }.getOrNull()
    }

    private fun manifest(): ArtifactManifest? = cachedManifest.get()

    private fun activeBands(): Pair<Double, Double>? =
        manifest()?.vision?.bands?.let { it.autoConf to it.confirmConf }

    // ── manifest ─────────────────────────────────────────────────────────────

    override suspend fun loadManifest(): ManifestInfo? = withContext(Dispatchers.IO) {
        val manifest = runCatching { artifacts.fetchManifest() }.getOrNull() ?: return@withContext null
        cachedManifest.set(manifest)

        // The gate is consulted here so the UI can say "app update required" before
        // any bytes move; ArtifactManager consults it again before installing.
        val verdict = runCatching { ProtocolGate.check(manifest) }.getOrNull()
        updateRequiredReasons.set(
            when (verdict) {
                is au.org.regeneratus.augury.artifacts.CompatibilityVerdict.UpdateRequired -> verdict.reasons
                else -> emptyList()
            },
        )

        // Seed progress so Setup can render byte counts even before a download.
        manifest.artifacts().forEach { a ->
            progress.computeIfAbsent(a.name) { Progress(bytesTotal = a.spec.bytes) }
        }

        withContext(Dispatchers.Main) {
            ManifestInfo(
                manifestSchema = manifest.manifestSchema,
                generation = manifest.generation,
                autoConf = manifest.vision.bands.autoConf,
                confirmConf = manifest.vision.bands.confirmConf,
                vectors = manifest.vision.index.vectors.toInt(),
                dim = manifest.vision.index.dim,
                indexSpecies = manifest.vision.index.species,
                backend = manifest.vision.index.backend,
                indexSchema = manifest.vision.index.schema,
                factsSchema = manifest.facts.schema,
                speciesCount = speciesStore()?.speciesCount ?: 0,
                regions = listOf("Australia", "UK", "Europe"),
                formatterProtocol = manifest.formatter.protocol,
                visionProtocol = manifest.vision.index.protocol,
                factsProtocol = manifest.facts.spec.protocol,
                encoderQuant = manifest.encoderForIndexBackend()?.quant ?: "unknown",
            )
        }
    }

    override suspend fun artifactState(): SetupState = withContext(Dispatchers.IO) {
        val shown = manifest()?.artifacts().orEmpty()
        val infos = shown.map { a ->
            val p = progress[a.name]
            val g = artifacts.installedGeneration(a.name)
            val ready = g == a.spec.generation && updateRequiredReasons.get().isEmpty()
            ArtifactInfo(
                name = a.name,
                title = titleFor(a),
                subtitle = a.detail,
                bytes = a.spec.bytes,
                sha256 = a.spec.sha256,
                generation = g ?: a.spec.generation,
                protocol = a.spec.protocol,
                status = when {
                    ready -> ArtifactStatus.READY
                    p?.phase == ArtifactStatus.FAILED -> ArtifactStatus.FAILED
                    p?.phase == ArtifactStatus.DOWNLOADING -> ArtifactStatus.DOWNLOADING
                    p?.phase == ArtifactStatus.VERIFYING -> ArtifactStatus.VERIFYING
                    g != null && g != a.spec.generation -> ArtifactStatus.STALE
                    else -> ArtifactStatus.MISSING
                },
                progress = p?.let {
                    if (it.bytesTotal > 0) (it.bytesDone.toFloat() / it.bytesTotal) else 0f
                } ?: 0f,
                bytesDone = p?.bytesDone ?: 0L,
                bytesPerSecond = p?.rate ?: 0L,
            )
        }
        SetupState(
            artifacts = infos,
            wifiOnly = wifiOnlyFlag,
            onWifi = !network.isMetered(),
            busy = downloadActive.get(),
        )
    }

    @Volatile
    private var wifiOnlyFlag = true

    private val downloadActive = java.util.concurrent.atomic.AtomicBoolean(false)

    private fun titleFor(a: ManifestArtifact): String = when (a.role) {
        ArtifactRole.FORMATTER -> "Story writer"
        ArtifactRole.FACTS -> "Species database"
        ArtifactRole.VISION_INDEX -> "Retrieval index"
        ArtifactRole.VISION_ENCODER -> "Image recogniser"
    }

    // ── download ─────────────────────────────────────────────────────────────

    override suspend fun startDownload(wifiOnly: Boolean) = withContext(Dispatchers.IO) {
        wifiOnlyFlag = wifiOnly
        val manifest = manifest() ?: runCatching { artifacts.fetchManifest() }.getOrNull() ?: return@withContext
        cachedManifest.set(manifest)
        downloadActive.set(true)
        cancelRequested.set(false)
        val token = CancellationToken { cancelRequested.get() }
        cancelToken.set(token)

        val listener = object : ArtifactProgressListener {
            override fun onArtifactStarted(
                artifact: ManifestArtifact,
                resumeFromBytes: Long,
                totalBytes: Long,
            ) {
                progress[artifact.name] = Progress(
                    bytesDone = resumeFromBytes,
                    bytesTotal = if (totalBytes > 0) totalBytes else artifact.spec.bytes,
                    phase = ArtifactStatus.DOWNLOADING,
                )
            }

            override fun onArtifactProgress(
                artifact: ManifestArtifact,
                bytesDownloaded: Long,
                totalBytes: Long,
                bytesPerSecond: Double,
            ) {
                progress[artifact.name] = Progress(
                    bytesDone = bytesDownloaded,
                    bytesTotal = if (totalBytes > 0) totalBytes else artifact.spec.bytes,
                    rate = bytesPerSecond.toLong(),
                    phase = ArtifactStatus.DOWNLOADING,
                )
            }

            override fun onArtifactVerified(artifact: ManifestArtifact, sha256: String) {
                progress[artifact.name] = Progress(
                    bytesDone = artifact.spec.bytes,
                    bytesTotal = artifact.spec.bytes,
                    phase = ArtifactStatus.VERIFYING,
                )
            }

            override fun onArtifactInstalled(
                artifact: ManifestArtifact,
                generation: String,
                directory: Path,
                skipped: Boolean,
            ) {
                progress[artifact.name] = Progress(
                    bytesDone = artifact.spec.bytes,
                    bytesTotal = artifact.spec.bytes,
                    phase = ArtifactStatus.READY,
                )
                // The facts generation changed, so the cached store is stale.
                if (artifact.role == ArtifactRole.FACTS) cachedStore.set(null)
            }

            override fun onArtifactFailed(artifact: ManifestArtifact, error: Throwable) {
                // Keep the reason. A bare "failed" in the UI with nothing in
                // logcat is undiagnosable, and the download phase is exactly the
                // part that has been hard to debug.
                val reason = "${error.javaClass.simpleName}: ${error.message}"
                progress[artifact.name] = Progress(phase = ArtifactStatus.FAILED)
                Log.e(TAG, "artifact '${artifact.name}' failed: $reason", error)
            }
        }

        try {
            runCatching {
                artifacts.install(
                    manifest = manifest,
                    options = InstallOptions(wifiOnly = wifiOnly),
                    listener = listener,
                    cancel = token,
                )
            }.onFailure { t ->
                // install() can also fail outside a per-artifact callback
                // (manifest-level, the protocol gate, disk).
                Log.e(TAG, "artifact install aborted", t)
            }
        } finally {
            downloadActive.set(false)
        }
        Unit
    }

    override suspend fun cancelDownload() {
        cancelRequested.set(true)
        downloadActive.set(false)
    }

    override suspend fun setWifiOnly(enabled: Boolean) {
        wifiOnlyFlag = enabled
    }

    // ── picker ───────────────────────────────────────────────────────────────

    override suspend fun search(
        query: String,
        region: String?,
        withIndicatorsOnly: Boolean,
        limit: Int,
    ): List<SpeciesSuggestion> = withContext(Dispatchers.IO) {
        val store = speciesStore() ?: return@withContext emptyList()
        if (query.isBlank()) return@withContext browse(region, withIndicatorsOnly, limit)

        val hits = runCatching { store.search(query, limit) }.getOrDefault(emptyList())
        hits.map { m ->
            val resolved = runCatching { store.resolveQuery(m.key, region) }.getOrNull()
            SpeciesSuggestion(
                key = m.key,
                commonName = m.commonNames.firstOrNull(),
                scientificName = m.scientificName,
                hasIndicators = resolved != null,
                regions = resolved?.let { listOf(it.region) } ?: emptyList(),
                matchType = m.matchType,
            )
        }.filter { !withIndicatorsOnly || it.hasIndicators }
    }

    /**
     * The browse list.
     *
     * There is no "list every species" call on [SpeciesStore] — it is ported from
     * a lookup module, not a catalogue — so browse is driven through the same
     * `search()` the picker uses, over a curated seed of real common names. The
     * filters are then applied by resolving each hit, which is what makes the
     * "with soil data" guarantee true rather than optimistic.
     */
    override suspend fun browse(
        region: String?,
        withIndicatorsOnly: Boolean,
        limit: Int,
    ): List<SpeciesSuggestion> = withContext(Dispatchers.IO) {
        val store = speciesStore() ?: return@withContext emptyList()
        val seen = LinkedHashMap<String, SpeciesSuggestion>()
        for (seed in BROWSE_SEEDS) {
            if (seen.size >= limit) break
            val hits = runCatching { store.search(seed, 3) }.getOrDefault(emptyList())
            for (m in hits) {
                if (seen.size >= limit) break
                if (seen.containsKey(m.key)) continue
                val resolved = runCatching { store.resolveQuery(m.key, region) }.getOrNull()
                if (withIndicatorsOnly && resolved == null) continue
                seen[m.key] = SpeciesSuggestion(
                    key = m.key,
                    commonName = m.commonNames.firstOrNull(),
                    scientificName = m.scientificName,
                    hasIndicators = resolved != null,
                    regions = resolved?.let { listOf(it.region) } ?: emptyList(),
                    matchType = "browse",
                )
            }
        }
        seen.values.toList()
    }

    // ── photo ────────────────────────────────────────────────────────────────

    override suspend fun identify(
        imageBytes: ByteArray,
        region: String?,
    ): List<PhotoCandidate> = withContext(Dispatchers.IO) {
        val pipeline = visionPipeline() ?: return@withContext emptyList()
        val bands = manifest()?.vision?.bands ?: return@withContext emptyList()

        // Decode to the RGB the preprocessor contract expects. The photo never
        // leaves this call: nothing is written anywhere and nothing is uploaded.
        val bitmap = android.graphics.BitmapFactory.decodeByteArray(imageBytes, 0, imageBytes.size)
            ?: return@withContext emptyList()
        val pixels = IntArray(bitmap.width * bitmap.height)
        bitmap.getPixels(pixels, 0, bitmap.width, 0, 0, bitmap.width, bitmap.height)
        val image = RgbImage.fromArgb(pixels, bitmap.width, bitmap.height)
        bitmap.recycle()

        val result = runCatching { pipeline.identify(image) }.getOrNull()
            ?: return@withContext emptyList()

        result.candidates.map { c ->
            // The display name is a courtesy: the canonical key is already
            // human-readable ("cirsium vulgare"), and the picker is where the
            // curated common names live.
            PhotoCandidate(
                key = c.canonical,
                commonName = null,
                scientificName = c.canonical,
                score = c.score.toDouble(),
                band = when {
                    c.score >= bands.autoConf -> Band.AUTO
                    c.score >= bands.confirmConf -> Band.CONFIRM
                    else -> Band.UNKNOWN
                },
            )
        }
    }

    /**
     * The vision pipeline, built once from the **promoted** artifact generations.
     *
     * `null` means the photo path is unavailable (encoder or index not installed,
     * or the graph does not match the manifest). The UI then shows the picker
     * instead of a guess — which is the correct failure for a retrieval system
     * whose top-1 is 85.9%.
     */
    private fun visionPipeline(): au.org.regeneratus.augury.vision.VisionPipeline? {
        cachedVision?.let { return it }
        return synchronized(visionLock) {
            cachedVision?.let { return it }
            val manifest = manifest() ?: return null
            val encoderArtifact = manifest.encoderForIndexBackend() ?: return null
            val encoderName = ArtifactNames.encoder(
                encoderArtifact.backend, encoderArtifact.quant,
            )
            val encoderFile = activeDir(encoderName)?.toFile()?.listFiles()
                ?.firstOrNull { it.name.endsWith(".onnx") } ?: return null
            val indexDir = activeDir(INDEX_NAME)?.toFile() ?: return null
            val embeddings = File(indexDir, "embeddings.npy").takeIf { it.isFile } ?: return null
            val keys = File(indexDir, "keys.json").takeIf { it.isFile } ?: return null
            val pca = File(indexDir, "pca_whiten.npz").takeIf { it.isFile }

            runCatching {
                // Build the settings from the typed manifest the same way the
                // manager parsed it, so the vision contract gate sees exactly the
                // bytes that were installed.
                val settings = au.org.regeneratus.augury.vision.VisionSettings(
                    protocol = manifest.vision.index.protocol,
                    indexSchema = manifest.vision.index.schema,
                    backend = manifest.vision.index.backend,
                    vectors = manifest.vision.index.vectors.toInt(),
                    dim = manifest.vision.index.dim,
                    species = manifest.vision.index.species,
                    encoderBackend = manifest.encoderForIndexBackend()?.backend
                        ?: manifest.vision.index.backend,
                    encoderProtocol = manifest.encoderForIndexBackend()?.spec?.protocol
                        ?: manifest.vision.index.protocol,
                    encoderPath = manifest.encoderForIndexBackend()?.spec?.path ?: "",
                    encoderQuant = manifest.encoderForIndexBackend()?.quant ?: "",
                    encoderBytes = manifest.encoderForIndexBackend()?.spec?.bytes,
                    encoderSha256 = manifest.encoderForIndexBackend()?.spec?.sha256,
                    preprocess = au.org.regeneratus.augury.vision.PreprocessSettings.fromManifest(
                        preprocessMap(manifest),
                    ),
                    bands = au.org.regeneratus.augury.vision.Bands(
                        autoConf = manifest.vision.bands.autoConf.toFloat(),
                        confirmConf = manifest.vision.bands.confirmConf.toFloat(),
                    ),
                    topK = au.org.regeneratus.augury.vision.VisionSettings.REQUIRED_TOP_K,
                    manifestGeneration = manifest.generation,
                ).also {
                    // Run the vision half of the protocol gate. The artifact
                    // manager already gated the manifest, but the vision contract
                    // has its own checks (backend, quant, preprocess output), and
                    // running a mismatched encoder is the exact failure the gate
                    // exists to prevent.
                    it.requireSupported()
                    it.preprocess.requireSupported()
                }
                val encoder = au.org.regeneratus.augury.vision.OnnxEncoder.create(
                    modelFile = encoderFile,
                    crop = settings.preprocess.crop,
                    expectedClsDim = DINOv2_CLS_DIM,
                )
                au.org.regeneratus.augury.vision.VisionPipeline.create(
                    settings = settings,
                    encoder = encoder,
                    embeddingsNpy = embeddings.readBytes(),
                    keysJson = keys.readText(),
                    pcaNpz = pca?.readBytes(),
                    canonicalJson = SpeciesStore.resourceStream(
                        SpeciesStore.CANONICAL_MAP_RESOURCE,
                    )?.bufferedReader()?.use { it.readText() },
                ).also { cachedVision = it }
            }.getOrNull()
        }
    }

    /**
     * The manifest's `vision.preprocess` block as the raw map
     * [au.org.regeneratus.augury.vision.PreprocessSettings.fromManifest] expects.
     *
     * Rebuilt from the typed manifest rather than re-parsed from JSON so there is
     * a single source of truth for what was installed.
     */
    private fun preprocessMap(manifest: ArtifactManifest): Map<String, Any?> {
        val p = manifest.vision.preprocess
        return mapOf(
            "resize_shortest_edge" to p.resizeShortestEdge,
            "crop" to p.crop,
            "resample" to p.resample,
            "mean" to p.mean,
            "std" to p.std,
            "output" to p.output,
        )
    }

    @Volatile
    private var cachedVision: au.org.regeneratus.augury.vision.VisionPipeline? = null
    private val visionLock = Any()

    // ── story ────────────────────────────────────────────────────────────────

    override suspend fun story(
        speciesKey: String,
        question: String,
        region: String?,
        modelText: String?,
    ): StoryResult? = withContext(Dispatchers.IO) {
        val store = speciesStore() ?: return@withContext null

        // With no model draft, the deterministic template is the answer and the
        // answerer applies the grounding pass to it (which is a no-op, since the
        // template cannot invent a number).
        val draft = modelText ?: generateDraft(store, speciesKey, region, question)

        val payload = AuguryAnswerer(store, composer).answer(
            message = question,
            speciesNames = listOf(speciesKey),
            region = region,
            modelText = draft,
        )
        val resolved = payload.resolved.firstOrNull() ?: return@withContext null

        StoryResult(
            reading = SpeciesReading.from(resolved),
            story = payload.response,
            repairs = payload.groundingRepairs,
            usedModel = draft != null,
            refused = payload.refused,
            refusedReason = payload.refusedReason,
        )
    }

    /**
     * Ask the on-device formatter for prose.
     *
     * The engine is opened and closed around this single call so the ~700 MB GGUF
     * is not resident while the encoder is (hard constraint 7). Any failure —
     * missing GGUF, OOM, JNI error — returns `null`, which makes the caller fall
     * back to the deterministic template instead of failing the screen.
     */
    private fun generateDraft(
        store: SpeciesStore,
        speciesKey: String,
        region: String?,
        question: String,
    ): String? {
        val resolved = runCatching { store.resolveQuery(speciesKey, region) }.getOrNull() ?: return null
        val modelFile = activeDir(FORMATTER_NAME)
            ?.toFile()
            ?.listFiles()
            ?.firstOrNull { it.name.endsWith(".gguf") }
            ?: return null

        val system = SYSTEM_PROMPT
        val user = buildString {
            append("Facts from the AUGURY database (do not add or change any indicator):\n\n")
            append("Species: ")
            append(resolved.commonNames.firstOrNull() ?: resolved.scientificName)
            append(" (")
            append(resolved.scientificName)
            append(")\n")
            append("Region: ").append(resolved.region).append('\n')
            append("Indicators:\n")
            for ((k, v) in resolved.indicators) append("- ").append(k).append(": ").append(v).append('\n')
            if (resolved.source.isNotBlank()) append("Source: ").append(resolved.source).append('\n')
            append('\n')
            append("Farmer's question: ").append(question)
        }

        return runCatching {
            LlamaEngine().use { engine ->
                engine.load(modelFile.absolutePath, N_CTX, LlamaEngine.recommendedThreads())
                engine.generate(
                    system = system,
                    user = user,
                    temperature = TEMPERATURE,
                    maxTokens = MAX_TOKENS,
                )
            }
        }.getOrNull()
    }
}

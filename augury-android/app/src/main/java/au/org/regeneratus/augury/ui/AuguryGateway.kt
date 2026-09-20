package au.org.regeneratus.augury.ui

import au.org.regeneratus.augury.core.AnswerPayload
import au.org.regeneratus.augury.core.Grounding
import au.org.regeneratus.augury.core.SpeciesStore

/**
 * ============================================================================
 *  THE UI CONTRACT
 * ============================================================================
 *
 * Every screen in this package talks to the rest of the app through
 * [AuguryGateway] and the plain data types in this file. Nothing in `ui/` imports
 * `LlamaEngine`, ONNX Runtime, the downloader or the species DB directly.
 *
 * Two reasons that boundary is worth the indirection:
 *
 *  1. **The screens are reviewable without a device.** This host cannot run an
 *     emulator (no `/dev/kvm`; see `docs/HANDOVER-2026-09-19.md` §6), so the UI is
 *     the one deliverable that cannot be exercised here. Keeping it dependent only
 *     on an interface means [DemoGateway] can render every screen with real
 *     database rows and no model, no download and no native library.
 *
 *  2. **The load-bearing product rules live in one place.** "Always show top-3",
 *     "the grounding pass is mandatory", "bands come from the manifest" and "the
 *     app ships no model data" are enforced in the real implementation of this
 *     interface, not re-derived by each screen.
 *
 * The types below are UI-shaped on purpose: they carry what a screen must render
 * (a label, a band, a score, indicator rows with provenance) and nothing else.
 */

/** Which screen is on top. Back is handled by the [AuguryApp] shell, not the OS. */
enum class Screen { SETUP, HOME, PICKER, PHOTO, STORY, SETTINGS }

/**
 * How much to trust a match, derived **only** from the manifest's
 * `vision.bands` thresholds -- never from a constant in this file.
 *
 * [AUTO] means *higher confidence*, NOT *safe to accept*. Every band still
 * requires a tap: top-1 accuracy is 85.9%, so a confident wrong ID would produce
 * a faithfully-formatted story about the wrong plant.
 */
enum class Band { AUTO, CONFIRM, UNKNOWN }

/** One candidate returned by retrieval, with the score that produced its band. */
data class PhotoCandidate(
    /** The canonical species key this candidate collapsed to. */
    val key: String,
    val commonName: String?,
    val scientificName: String,
    /** Inner-product score on the whitened scale, after canonical collapse. */
    val score: Double,
    val band: Band,
) {
    /** Common name first -- the audience is non-technical (see the decision record §6). */
    val displayName: String get() = commonName?.takeIf { it.isNotBlank() } ?: scientificName
}

/**
 * A picker row. Deliberately *not* the full species record: the list is 2,256
 * entries and only these fields are rendered.
 */
data class SpeciesSuggestion(
    val key: String,
    val commonName: String?,
    val scientificName: String,
    val hasIndicators: Boolean,
    val regions: List<String>,
    /** Why this row matched, for ranking/telemetry: `exact_common`, `partial_scientific`, … */
    val matchType: String,
) {
    val displayName: String get() = commonName?.takeIf { it.isNotBlank() } ?: scientificName
}

/** One indicator row, ready to render. Key and value are verbatim from the DB. */
data class IndicatorRow(val key: String, val value: String)

/**
 * A resolved species plus its indicator rows -- what the story screen renders.
 *
 * [regionFallback] and [mergedFrom] are carried, not swallowed: the Python
 * pipeline discloses a region fallback in the visible text, and a canonical group
 * ("thistles") must stay labelled as the group the user asked for rather than
 * being relabelled to one member species.
 */
data class SpeciesReading(
    val key: String,
    val commonName: String?,
    val scientificName: String,
    val region: String,
    val requestedRegion: String?,
    val regionFallback: Boolean,
    val indicators: List<IndicatorRow>,
    val source: String,
    val specificity: String,
    val mergedFrom: List<String>,
) {
    val displayName: String get() = commonName?.takeIf { it.isNotBlank() } ?: scientificName

    companion object {
        fun from(resolved: SpeciesStore.ResolvedSpecies) = SpeciesReading(
            key = resolved.match.key,
            commonName = resolved.commonNames.firstOrNull(),
            scientificName = resolved.scientificName,
            region = resolved.region,
            requestedRegion = resolved.requestedRegion,
            regionFallback = resolved.regionFallback,
            indicators = resolved.indicators.map { IndicatorRow(it.key, it.value) },
            source = resolved.source,
            specificity = resolved.specificity,
            mergedFrom = resolved.mergedFrom,
        )
    }
}

/**
 * The result of asking the pipeline for a story.
 *
 * [repairs] is the grounding audit trail and is surfaced in the UI rather than
 * hidden: a non-empty list means the formatter model produced something the facts
 * did not support and the app removed or rewrote it. That is the "likely below
 * 6.5" failure, and the user is entitled to see that it was caught.
 */
data class StoryResult(
    val reading: SpeciesReading,
    val story: String,
    val repairs: List<Grounding.GroundingRepair>,
    val usedModel: Boolean,
    val refused: Boolean = false,
    val refusedReason: String? = null,
)

/** One artifact's on-device state, as rendered by Setup and Settings. */
data class ArtifactInfo(
    val name: String,
    val title: String,
    val subtitle: String,
    val bytes: Long,
    val sha256: String,
    val generation: String,
    val protocol: String,
    val status: ArtifactStatus,
    /** 0f..1f, only meaningful while [status] is DOWNLOADING or VERIFYING. */
    val progress: Float = 0f,
    val bytesDone: Long = 0L,
    /** Bytes per second, for the "1.4 MB/s" line. 0 when not transferring. */
    val bytesPerSecond: Long = 0L,
) {
    val isReady: Boolean get() = status == ArtifactStatus.READY
}

enum class ArtifactStatus { MISSING, DOWNLOADING, VERIFYING, READY, FAILED, STALE }

/** Aggregate download state for the Setup screen. */
data class SetupState(
    val artifacts: List<ArtifactInfo>,
    val wifiOnly: Boolean,
    val onWifi: Boolean,
    val busy: Boolean,
) {
    val totalBytes: Long get() = artifacts.sumOf { it.bytes }
    val bytesDone: Long get() = artifacts.sumOf { it.bytesDone }
    val overallProgress: Float
        get() = if (totalBytes <= 0L) 0f else (bytesDone.toDouble() / totalBytes).toFloat()
    val allReady: Boolean get() = artifacts.isNotEmpty() && artifacts.all { it.isReady }
    val hasWork: Boolean get() = artifacts.any { !it.isReady }

    /** Blocked because the user asked for Wi-Fi-only and this is a metered link. */
    val blockedByMeteredConnection: Boolean get() = wifiOnly && !onWifi && hasWork
}

/**
 * Everything the app needs to know about the manifest that is *not* an artifact:
 * the version pins, the confidence bands and the preprocessing parameters.
 *
 * Read from the manifest at runtime. **No screen may hard-code any of these.**
 */
data class ManifestInfo(
    val manifestSchema: Int,
    val generation: String,
    val autoConf: Double,
    val confirmConf: Double,
    val vectors: Int,
    val dim: Int,
    val indexSpecies: Int,
    val backend: String,
    val indexSchema: Int,
    val factsSchema: Int,
    val speciesCount: Int,
    val regions: List<String>,
    val formatterProtocol: String,
    val visionProtocol: String,
    val factsProtocol: String,
    val encoderQuant: String,
) {
    /**
     * The compatibility gate (`docs/mobile-app-decision.md` §3.3). When the
     * manifest declares a protocol or schema this build cannot execute, the app
     * must say **"app update required"** rather than run a mismatched encoder and
     * return plausible garbage.
     */
    val supported: Boolean
        get() = manifestSchema in SUPPORTED_MANIFEST_SCHEMAS &&
            indexSchema in SUPPORTED_INDEX_SCHEMAS &&
            factsSchema in SUPPORTED_SPECIES_DB_SCHEMAS &&
            formatterProtocol in SUPPORTED_PROTOCOLS &&
            visionProtocol in SUPPORTED_PROTOCOLS &&
            factsProtocol in SUPPORTED_PROTOCOLS

    companion object {
        /** The protocols this shell implements. Adding one is an app release. */
        val SUPPORTED_PROTOCOLS = setOf(
            "formatter.chatml-grounded@1",
            "species.db@1",
            "vision.clip-token-l2-pca-knn-ip@1",
        )
        val SUPPORTED_MANIFEST_SCHEMAS = setOf(1)
        val SUPPORTED_INDEX_SCHEMAS = setOf(1)
        val SUPPORTED_SPECIES_DB_SCHEMAS = setOf(1)
    }
}

/**
 * The single seam between the UI and everything else.
 *
 * Deliberately narrow: five operations, all suspending, all returning UI-shaped
 * types. The real implementation is `AuguryGatewayImpl`; [DemoGateway] satisfies
 * the same contract with the real species database and no model.
 */
interface AuguryGateway {

    /**
     * Fetch the manifest and report per-artifact state. Must not throw for an
     * ordinary network failure -- report it through [ArtifactStatus.FAILED] so the
     * Setup screen can offer a retry.
     */
    suspend fun loadManifest(): ManifestInfo?

    /** Current artifact state, for Setup and Settings. */
    suspend fun artifactState(): SetupState

    /** Start or resume downloading everything that is not ready. */
    suspend fun startDownload(wifiOnly: Boolean)

    /** Abandon an in-flight download. A partial file is never promoted. */
    suspend fun cancelDownload()

    /** Flip the Wi-Fi-only preference. */
    suspend fun setWifiOnly(enabled: Boolean)

    /**
     * Search the species database for the picker.
     *
     * @param region preferred region, e.g. `"Australia"`; AU-first ordering is a
     *   product requirement, not a nicety.
     * @param withIndicatorsOnly restrict to species that actually carry data.
     */
    suspend fun search(query: String, region: String?, withIndicatorsOnly: Boolean, limit: Int = 40): List<SpeciesSuggestion>

    /** Suggested rows when the query is empty: AU-first, data-bearing species. */
    suspend fun browse(region: String?, withIndicatorsOnly: Boolean, limit: Int = 40): List<SpeciesSuggestion>

    /**
     * The photo path: embed, kNN, canonical collapse, band.
     *
     * **Must always return up to three candidates** (hard constraint: the user is
     * never shown a single silently-accepted species). Returns an empty list only
     * when retrieval genuinely produced nothing.
     */
    suspend fun identify(imageBytes: ByteArray, region: String?): List<PhotoCandidate>

    /**
     * The text path: resolve the species the user chose and produce the soil story.
     *
     * @param modelText a draft from the formatter model, or `null` for the
     *   deterministic template. Either way the result is grounded against the
     *   injected facts before it is returned.
     */
    suspend fun story(speciesKey: String, question: String, region: String?, modelText: String? = null): StoryResult?
}

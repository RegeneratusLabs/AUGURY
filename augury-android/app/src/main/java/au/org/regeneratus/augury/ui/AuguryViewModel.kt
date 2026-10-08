package au.org.regeneratus.augury.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * Everything the shell renders. One immutable state object, one writer
 * ([AuguryViewModel]), so a screen can never observe a half-updated app.
 */
data class AuguryUiState(
    val screen: Screen = Screen.HOME,
    val manifest: ManifestInfo? = null,
    val manifestError: String? = null,
    val setup: SetupState? = null,

    // ── picker ──
    val query: String = "",
    val suggestions: List<SpeciesSuggestion> = emptyList(),
    val region: String = DEFAULT_REGION,
    val withIndicatorsOnly: Boolean = true,
    /** True while a *browse* list is loading, so the picker can show a spinner. */
    val loadingPicker: Boolean = false,

    // ── photo ──
    val photoCandidates: List<PhotoCandidate> = emptyList(),
    val identifying: Boolean = false,
    /** Set when the user has a photo but retrieval returned nothing at all. */
    val photoEmpty: Boolean = false,
    /**
     * Set when the photo path could not *run* (encoder absent, graph mismatched,
     * image undecodable). Distinct from [photoEmpty], which means it ran and
     * nothing matched.
     */
    val photoUnavailable: String? = null,

    // ── story ──
    val story: StoryResult? = null,
    val composing: Boolean = false,
    val storyError: String? = null,
    /**
     * The formatter's prose as it is being written, before grounding has seen it.
     *
     * Non-null only while [streaming] is true. It is deliberately a *separate*
     * field from [story]: the draft has not been verified against the database
     * yet, and rendering it from [story] would present an unverified claim as the
     * reading. The screen shows this dimmed and labelled, then replaces it with
     * the grounded [story] when that lands.
     */
    val storyDraft: String? = null,
    /** True between the first streamed piece and the grounded result. */
    val streaming: Boolean = false,
    /**
     * The species the story is being written about, so the screen can show a
     * title while the reading is still being resolved. Cleared with [story].
     */
    val storyKey: String? = null,
    val storyDisplayName: String? = null,

    /**
     * Set when the manifest declares a protocol/schema this build cannot execute.
     * The app must then say "app update required" rather than run a mismatched
     * encoder and return plausible garbage (hard constraint, decision record §3.3).
     */
    val updateRequired: Boolean = false,

    /** Whether the formatter model is present. When absent, the app says so. */
    val modelAvailable: Boolean = false,
) {
    companion object {
        /**
         * AU-first is a product requirement: 185 of 188 Australian species have real
         * common names and all 188 carry indicators, and the picker is the most
         * reliable path in the product.
         */
        const val DEFAULT_REGION = "Australia"
    }
}

/**
 * The shell's state holder.
 *
 * The gateway is injected, not constructed here, so this class is testable with
 * [DemoGateway] and so the UI has no compile-time dependency on the downloader,
 * ONNX Runtime or llama.cpp.
 */
class AuguryViewModel(
    private val gateway: AuguryGateway,
) : ViewModel() {

    private val _state = MutableStateFlow(AuguryUiState())
    val state: StateFlow<AuguryUiState> = _state.asStateFlow()

    private var downloadJob: Job? = null

    /** The in-flight story turn, so a new one cancels the old instead of racing it. */
    private var storyJob: Job? = null

    /**
     * Identifies the story turn whose result is still wanted.
     *
     * A streamed draft arrives over ~40 s, and the user can leave the screen or
     * open another plant inside that window. The id is bumped whenever a turn
     * starts or is abandoned, and both the stream callback and the completion
     * check it, so a late piece can never overwrite a newer screen's state.
     */
    private var storyRequest = 0

    /**
     * Identifies the photo-identify job whose result is still wanted.
     *
     * Retrieval loads a ~340 MB encoder and can outlive a tap on Back. The id is
     * bumped both by a new photo and by [startPhoto], so a result for a photo the
     * user has already moved on from can never populate the next session's card.
     */
    private var photoRequest = 0

    private companion object {
        /** How often the Setup screen re-reads artifact progress while downloading. */
        const val PROGRESS_POLL_MS = 500L
    }

    init {
        refreshManifest()
    }

    // ── manifest + artifacts ─────────────────────────────────────────────────

    fun refreshManifest() {
        viewModelScope.launch {
            val info = runCatching { gateway.loadManifest() }.getOrNull()
            if (info == null) {
                _state.update { it.copy(manifestError = "Could not reach the update server.") }
            } else {
                _state.update {
                    it.copy(
                        manifest = info,
                        manifestError = null,
                        updateRequired = !info.supported,
                        // Only show Setup unprompted when there is actually work to do.
                        screen = if (!info.supported) Screen.SETTINGS else it.screen,
                    )
                }
            }
            refreshArtifacts()
        }
    }

    fun refreshArtifacts() {
        viewModelScope.launch { refreshArtifactsNow() }
    }

    /** One artifact-state read; suspend so the download poller can call it in a loop. */
    private suspend fun refreshArtifactsNow() {
        val setup = runCatching { gateway.artifactState() }.getOrNull() ?: return
        _state.update {
            it.copy(
                setup = setup,
                // First launch: nothing usable is on disk, so Setup leads.
                screen = if (!setup.allReady && it.manifest != null &&
                    it.screen == Screen.HOME
                ) Screen.SETUP else it.screen,
            )
        }
    }

    fun startDownload() {
        if (downloadJob?.isActive == true) return
        val wifiOnly = _state.value.setup?.wifiOnly ?: true
        downloadJob = viewModelScope.launch {
            // The gateway reports live per-artifact progress through artifactState()
            // and nothing else reads it while a download runs. Without this poller
            // the Setup screen sat at "0 B of 1.06 GB" for the whole 1.06 GB and then
            // jumped to done — observed, not theorised.
            val poller = launch {
                while (isActive) {
                    delay(PROGRESS_POLL_MS)
                    refreshArtifactsNow()
                }
            }
            try {
                runCatching { gateway.startDownload(wifiOnly) }
            } finally {
                poller.cancel()
            }
            refreshArtifactsNow()
        }
    }

    fun cancelDownload() {
        downloadJob?.cancel()
        downloadJob = null
        viewModelScope.launch {
            runCatching { gateway.cancelDownload() }
            refreshArtifacts()
        }
    }

    fun setWifiOnly(enabled: Boolean) {
        viewModelScope.launch {
            runCatching { gateway.setWifiOnly(enabled) }
            _state.update { s -> s.copy(setup = s.setup?.copy(wifiOnly = enabled)) }
        }
    }

    // ── picker ───────────────────────────────────────────────────────────────

    fun onQueryChange(q: String) {
        _state.update { it.copy(query = q) }
        search(q)
    }

    fun search(q: String) {
        viewModelScope.launch {
            _state.update { it.copy(loadingPicker = true) }
            val s = _state.value
            val rows = runCatching {
                if (q.isBlank()) {
                    gateway.browse(s.region, s.withIndicatorsOnly)
                } else {
                    gateway.search(q, s.region, s.withIndicatorsOnly)
                }
            }.getOrDefault(emptyList())
            _state.update { it.copy(suggestions = rows, loadingPicker = false) }
        }
    }

    fun setRegion(region: String) {
        _state.update { it.copy(region = region) }
        search(_state.value.query)
    }

    fun toggleIndicatorsOnly() {
        _state.update { it.copy(withIndicatorsOnly = !it.withIndicatorsOnly) }
        search(_state.value.query)
    }

    // ── photo ────────────────────────────────────────────────────────────────

    fun onPhotoPicked(bytes: ByteArray) {
        val requestId = ++photoRequest
        viewModelScope.launch {
            _state.update {
                it.copy(
                    screen = Screen.PHOTO,
                    identifying = true,
                    photoCandidates = emptyList(),
                    photoEmpty = false,
                    photoUnavailable = null,
                    story = null,
                    storyError = null,
                )
            }
            val region = _state.value.region
            val outcome = runCatching { gateway.identify(bytes, region) }.getOrNull()
            // A newer photo — or a fresh capture screen — has taken over while this
            // one was still encoding, so this result is stale and must be dropped.
            if (requestId != photoRequest) return@launch
            // Failing to *run* the path is a different fact from "nothing
            // matched", and the screen must not present them as one.
            val reason = outcome?.unavailableReason
                ?: if (outcome == null) "The photo path failed to start." else null
            val candidates = outcome?.candidates.orEmpty()
            _state.update {
                it.copy(
                    identifying = false,
                    photoCandidates = candidates,
                    photoEmpty = candidates.isEmpty() && reason == null,
                    photoUnavailable = reason,
                )
            }
        }
    }

    // ── story ────────────────────────────────────────────────────────────────

    /**
     * Compose the soil story for a species the user has **confirmed**.
     *
     * The UI only ever calls this after an explicit tap: `auto` means higher
     * confidence, never safe-to-accept, because a confident wrong ID produces a
     * faithfully-formatted story about the wrong plant.
     *
     * The formatter's prose streams into [AuguryUiState.storyDraft] as it is
     * written (the model spends ~10 s on prompt evaluation before its first
     * token, and ~40 s in total on the emulator), and is replaced by the grounded
     * [AuguryUiState.story] when the turn finishes. A gateway with no model
     * simply returns without ever calling back, so the screen goes straight from
     * "reading the database…" to the answer.
     */
    fun openStory(speciesKey: String, question: String? = null) {
        val requestId = ++storyRequest
        storyJob?.cancel()
        storyJob = viewModelScope.launch {
            _state.update {
                it.copy(
                    screen = Screen.STORY,
                    composing = true,
                    story = null,
                    storyError = null,
                    storyDraft = null,
                    streaming = false,
                    storyKey = speciesKey,
                    storyDisplayName = it.photoCandidates
                        .firstOrNull { c -> c.key == speciesKey }?.displayName
                        ?: it.suggestions.firstOrNull { s -> s.key == speciesKey }?.displayName,
                )
            }
            val q = question ?: "What does this plant indicate about my soil?"

            // The callback runs on the gateway's IO thread, once per generated
            // piece. `MutableStateFlow.update` is thread-safe, and the request id
            // stops a stream the user has already navigated away from from writing
            // into the state of the next one.
            val result = runCatching {
                gateway.storyStream(speciesKey, q, _state.value.region) { accumulated ->
                    if (requestId != storyRequest) return@storyStream false
                    _state.update {
                        it.copy(storyDraft = accumulated, streaming = true)
                    }
                    true
                }
            }.getOrNull()

            if (requestId != storyRequest) return@launch
            _state.update {
                it.copy(
                    composing = false,
                    streaming = false,
                    storyDraft = null,
                    story = result,
                    storyError = if (result == null) {
                        "No soil indicators are recorded for that plant in this region."
                    } else null,
                )
            }
        }
    }

    // ── navigation ───────────────────────────────────────────────────────────

    /**
     * Enter the photo flow to take a **new** photo.
     *
     * The photo session lives in [AuguryUiState.photoCandidates] and deliberately
     * survives a trip to the Story screen, so Back returns to the card the user
     * was looking at. Every explicit "take a photo" affordance must therefore
     * start clean: without this, both *Take photo* on Home and *Photo instead* on
     * the Story screen re-opened the **previous** run's confirm card — which
     * offers no camera or gallery button at all, so a second photo was
     * unreachable. Reproduced on the emulator 2026-09-23.
     */
    fun startPhoto() {
        // Invalidate anything still in flight so it cannot populate this session.
        photoRequest++
        abandonStory()
        _state.update {
            it.copy(
                screen = Screen.PHOTO,
                identifying = false,
                photoCandidates = emptyList(),
                photoEmpty = false,
                photoUnavailable = null,
                story = null,
                storyDraft = null,
                streaming = false,
                composing = false,
                storyError = null,
                storyKey = null,
                storyDisplayName = null,
            )
        }
    }

    fun go(screen: Screen) = _state.update { it.copy(screen = screen) }

    fun back() {
        _state.update {
            when (it.screen) {
                Screen.PICKER, Screen.PHOTO -> it.copy(screen = Screen.HOME)
                Screen.STORY -> {
                    // Abandon any turn still streaming into this screen: its
                    // pieces must not land on whatever the user does next.
                    abandonStory()
                    it.copy(
                        screen = if (it.photoCandidates.isNotEmpty()) Screen.PHOTO else Screen.HOME,
                        story = null,
                        storyDraft = null,
                        streaming = false,
                        composing = false,
                        storyError = null,
                    )
                }
                Screen.SETTINGS -> it.copy(screen = Screen.HOME)
                else -> it
            }
        }
    }

    /** Cancel the in-flight story turn and invalidate its request id. */
    private fun abandonStory() {
        storyRequest++
        storyJob?.cancel()
        storyJob = null
    }

    override fun onCleared() {
        abandonStory()
        super.onCleared()
    }
}

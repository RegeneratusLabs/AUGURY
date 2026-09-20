package au.org.regeneratus.augury.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
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

    // ── story ──
    val story: StoryResult? = null,
    val composing: Boolean = false,
    /** True while the formatter model is generating; the template path is instant. */
    val generating: Boolean = false,
    val storyError: String? = null,

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
        viewModelScope.launch {
            val setup = runCatching { gateway.artifactState() }.getOrNull() ?: return@launch
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
    }

    fun startDownload() {
        if (downloadJob?.isActive == true) return
        val wifiOnly = _state.value.setup?.wifiOnly ?: true
        downloadJob = viewModelScope.launch {
            runCatching { gateway.startDownload(wifiOnly) }
            refreshArtifacts()
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
        viewModelScope.launch {
            _state.update {
                it.copy(
                    screen = Screen.PHOTO,
                    identifying = true,
                    photoCandidates = emptyList(),
                    photoEmpty = false,
                    story = null,
                    storyError = null,
                )
            }
            val region = _state.value.region
            val candidates = runCatching { gateway.identify(bytes, region) }.getOrDefault(emptyList())
            _state.update {
                it.copy(
                    identifying = false,
                    photoCandidates = candidates,
                    photoEmpty = candidates.isEmpty(),
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
     */
    fun openStory(speciesKey: String, question: String? = null) {
        viewModelScope.launch {
            _state.update {
                it.copy(screen = Screen.STORY, composing = true, story = null, storyError = null)
            }
            val q = question ?: "What does this plant indicate about my soil?"
            val result = runCatching { gateway.story(speciesKey, q, _state.value.region) }.getOrNull()
            _state.update {
                it.copy(
                    composing = false,
                    story = result,
                    storyError = if (result == null) {
                        "No soil indicators are recorded for that plant in this region."
                    } else null,
                )
            }
        }
    }

    // ── navigation ───────────────────────────────────────────────────────────

    fun go(screen: Screen) = _state.update { it.copy(screen = screen) }

    fun back() {
        _state.update {
            when (it.screen) {
                Screen.PICKER, Screen.PHOTO -> it.copy(screen = Screen.HOME)
                Screen.STORY -> it.copy(
                    screen = if (it.photoCandidates.isNotEmpty()) Screen.PHOTO else Screen.HOME,
                    story = null,
                )
                Screen.SETTINGS -> it.copy(screen = Screen.HOME)
                else -> it
            }
        }
    }
}

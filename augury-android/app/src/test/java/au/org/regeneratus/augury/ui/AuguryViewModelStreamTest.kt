package au.org.regeneratus.augury.ui

import au.org.regeneratus.augury.core.Grounding
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/**
 * ============================================================================
 *  THE STREAMING STATE MACHINE
 * ============================================================================
 *
 * [StoryStreamTest] pins the gateway's half of streaming. This pins the
 * [AuguryViewModel] half, which is where the *draft is not the answer* rule is
 * enforced in the UI state:
 *
 *  * a piece arriving before the turn completes sets `storyDraft` and `streaming`
 *    but must **not** populate `story` — the screen renders `story` as verified;
 *  * the completed turn clears the draft and populates `story`, so unverified text
 *    cannot sit next to a verified result;
 *  * a turn the user abandoned mid-stream cannot write into the state of the next
 *    one. The draft arrives over tens of seconds, so that window is real.
 *
 * The gateway is a scripted fake rather than [DemoGateway]: these tests are about
 * the state machine, and a fake lets each case be driven deterministically —
 * including "hold the turn open while I look at the state" and "the user left in
 * the middle", neither of which a timing-based test can do reliably.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class AuguryViewModelStreamTest {

    private val dispatcher = StandardTestDispatcher()

    @Before fun setUp() = Dispatchers.setMain(dispatcher)

    @After fun tearDown() = Dispatchers.resetMain()

    private val reading = SpeciesReading(
        key = "taraxacum officinale",
        commonName = "Dandelion",
        scientificName = "Taraxacum officinale",
        region = "Australia",
        requestedRegion = "Australia",
        regionFallback = false,
        indicators = listOf(IndicatorRow("Moisture", "fresh, moist soil")),
        source = "Ellenberg Indicator Values",
        specificity = "exact_species",
        mergedFrom = emptyList(),
    )

    private fun result(story: String, repairs: List<Grounding.GroundingRepair> = emptyList()) =
        StoryResult(
            reading = reading,
            story = story,
            repairs = repairs,
            usedModel = true,
        )

    /**
     * A gateway whose `storyStream` is driven piece by piece.
     *
     * @param onStream receives the draft callback and the channel to pull pieces
     *   from, and returns the verified result (or `null` for "nothing recorded").
     *   `null` selects the interface default: no model, so `story()` answers.
     * @param storyResult what the blocking [AuguryGateway.story] returns; `null`
     *   models "this species has no indicators recorded".
     */
    private inner class FakeGateway(
        private val onStream: (suspend ((String) -> Boolean, Channel<String>) -> StoryResult?)? = null,
        private val storyResult: StoryResult? = null,
    ) : AuguryGateway {
        /** The callback the ViewModel handed us, for tests that emit from outside. */
        var sink: ((String) -> Boolean)? = null
            private set

        /** The gate the last stream parked on, so a test can release it. */
        private var gate: Channel<String>? = null

        /** Let a parked stream continue. Returns false if none is parked. */
        fun release(): Boolean = gate?.trySend("go")?.isSuccess == true

        override suspend fun loadManifest(): ManifestInfo? = null
        override suspend fun artifactState(): SetupState = SetupState(emptyList(), true, true, false)
        override suspend fun startDownload(wifiOnly: Boolean) = Unit
        override suspend fun cancelDownload() = Unit
        override suspend fun setWifiOnly(enabled: Boolean) = Unit
        override suspend fun search(
            query: String,
            region: String?,
            withIndicatorsOnly: Boolean,
            limit: Int,
        ): List<SpeciesSuggestion> = emptyList()

        override suspend fun browse(
            region: String?,
            withIndicatorsOnly: Boolean,
            limit: Int,
        ): List<SpeciesSuggestion> = emptyList()

        override suspend fun identify(imageBytes: ByteArray, region: String?): PhotoIdentification =
            PhotoIdentification(emptyList(), "not used")

        override suspend fun story(
            speciesKey: String,
            question: String,
            region: String?,
            modelText: String?,
        ): StoryResult? = storyResult

        override suspend fun storyStream(
            speciesKey: String,
            question: String,
            region: String?,
            onDraft: (String) -> Boolean,
        ): StoryResult? {
            sink = onDraft
            val channel = Channel<String>(Channel.UNLIMITED)
            gate = channel
            // `null` means "the interface default": no model, so the base
            // implementation's `story()` answer is what the screen shows.
            return onStream?.invoke(onDraft, channel) ?: storyResult
        }
    }

    @Test
    fun theDraftIsNeverPresentedAsTheVerifiedStory() = runTest(dispatcher) {
        val gw = FakeGateway(onStream = { onDraft, pieces ->
            onDraft("The soil is")
            onDraft("The soil is moist")
            pieces.close()
            result("The soil is moist. Verified.")
        })
        val vm = AuguryViewModel(gw)

        vm.openStory("taraxacum officinale")
        advanceUntilIdle()

        val state = vm.state.value
        assertFalse("the turn should be finished", state.composing)
        assertFalse("streaming should have ended", state.streaming)
        assertNull("the draft must be cleared once verified text lands", state.storyDraft)
        assertEquals("The soil is moist. Verified.", state.story?.story)
        assertNull(state.storyError)
    }

    @Test
    fun aPieceArrivingMidTurnSetsTheDraftButNotTheStory() = runTest(dispatcher) {
        // The fake blocks on the channel, so the turn is genuinely held open while
        // the state is inspected. Nothing here depends on how many times the test
        // dispatcher happens to drain.
        val gw = FakeGateway(onStream = { onDraft, pieces ->
            onDraft("The soil is")
            pieces.receive() // held until the test releases it
            onDraft("The soil is moist")
            result("The soil is moist. Verified.")
        })
        val vm = AuguryViewModel(gw)

        vm.openStory("taraxacum officinale")
        advanceUntilIdle()

        val mid = vm.state.value
        assertEquals("the draft is not on screen", "The soil is", mid.storyDraft)
        assertTrue("streaming should be true once a piece has landed", mid.streaming)
        assertTrue("the turn is still composing", mid.composing)
        // The load-bearing assertion: the unverified prefix is NOT in `story`.
        assertNull("an unverified draft was published as the story", mid.story)

        // Release the turn and let it finish. The fake is parked on the channel,
        // so one send lets it produce its second piece and return its result.
        assertTrue("the fake was not parked on its channel", gw.release())
        advanceUntilIdle()
        assertEquals("The soil is moist. Verified.", vm.state.value.story?.story)
        assertNull("the draft outlived the verified result", vm.state.value.storyDraft)
        assertFalse(vm.state.value.streaming)
    }

    @Test
    fun aDraftCannotLandOnAScreenTheUserHasLeft() = runTest(dispatcher) {
        val gw = FakeGateway(onStream = { onDraft, pieces ->
            onDraft("first piece")
            pieces.receive() // the user leaves while this is still open
            onDraft("STALE PIECE")
            result("stale result")
        })
        val vm = AuguryViewModel(gw)

        vm.openStory("taraxacum officinale")
        advanceUntilIdle()
        assertEquals("first piece", vm.state.value.storyDraft)

        // Navigate away: back() must invalidate the in-flight turn.
        vm.back()
        assertNotNull("the stream callback was never captured", gw.sink)
        // The stream is still running on its own thread in the real app; simulate a
        // late piece arriving after the user has gone.
        assertEquals(
            "the callback must refuse to keep streaming after back()",
            false,
            gw.sink!!("STALE PIECE"),
        )

        advanceUntilIdle()

        val state = vm.state.value
        assertEquals("back() did not leave the story screen", Screen.HOME, state.screen)
        assertNull("a stale draft survived the navigation", state.storyDraft)
        assertNull("a stale story survived the navigation", state.story)
        assertFalse(state.streaming)
        assertFalse(state.composing)
    }

    @Test
    fun aFailedTurnReportsAnErrorAndLeavesNoDraft() = runTest(dispatcher) {
        // The species does not resolve, so the gateway abandons the turn part-way
        // through the draft (a `false` from onDraft) and reports nothing recorded.
        val gw = FakeGateway(onStream = { onDraft, _ ->
            onDraft("half a sen")
            null
        })
        val vm = AuguryViewModel(gw)

        vm.openStory("nonexistent species")
        advanceUntilIdle()

        val state = vm.state.value
        assertNull("a failed turn must not publish a story", state.story)
        assertNull("a failed turn must not leave the draft on screen", state.storyDraft)
        assertFalse(state.streaming)
        assertNotNull("a failed turn must say so", state.storyError)
    }

    @Test
    fun aGatewayWithNoModelGoesStraightToTheAnswer() = runTest(dispatcher) {
        // The interface default path: no model, so no callback and no streaming
        // state — the screen goes from "reading the database…" to the answer.
        val gw = FakeGateway(onStream = null)
        val vm = AuguryViewModel(gw)

        vm.openStory("taraxacum officinale")
        advanceUntilIdle()

        val state = vm.state.value
        assertNull("streaming was entered with no stream", state.storyDraft)
        assertFalse("streaming was entered with no stream", state.streaming)
        assertFalse(state.composing)
        // This fake's `story()` returns null, so the honest outcome is the error
        // branch — what matters here is that it never entered the streaming state.
        assertNotNull("a null answer must be reported", state.storyError)
    }

    @Test
    fun aGatewayWithNoModelStillPublishesItsAnswer() = runTest(dispatcher) {
        // The default path with a gateway that has an answer but no stream: the
        // verified story must land with no draft ever having existed.
        val gw = FakeGateway(onStream = null, storyResult = result("verified story"))
        val vm = AuguryViewModel(gw)

        vm.openStory("taraxacum officinale")
        advanceUntilIdle()

        val state = vm.state.value
        assertEquals("verified story", state.story?.story)
        assertNull(state.storyDraft)
        assertFalse(state.streaming)
        assertFalse(state.composing)
        assertNull(state.storyError)
    }
}

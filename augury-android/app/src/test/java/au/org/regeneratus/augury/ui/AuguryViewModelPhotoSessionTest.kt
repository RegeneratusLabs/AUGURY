package au.org.regeneratus.augury.ui

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
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/**
 * ============================================================================
 *  THE PHOTO SESSION
 * ============================================================================
 *
 * The reported bug (2026-09-23, observed on the emulator): after reading a
 * story, *Take photo* on Home — and *Photo instead* on the Story screen —
 * re-opened the **previous** run's confirm card. That card offers only the three
 * matches and a search, so there was no camera or gallery button at all and a
 * second photo was unreachable.
 *
 * The cause was that `photoCandidates` was cleared only inside `onPhotoPicked`,
 * never by the "take a photo" navigation. [AuguryViewModel.startPhoto] now resets
 * the session; these tests pin that, plus the race the same reset introduced: an
 * identify job for a photo the user has already moved on from must not land in
 * the new session.
 *
 * Both directions are asserted — a result that *should* land still does — because
 * a reset that dropped every result would pass the stale-result test while
 * breaking the feature.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class AuguryViewModelPhotoSessionTest {

    private val dispatcher = StandardTestDispatcher()

    @Before fun setUp() = Dispatchers.setMain(dispatcher)

    @After fun tearDown() = Dispatchers.resetMain()

    private val candidates = listOf(
        PhotoCandidate("acacia nilotica", "Prickly acacia", "Acacia nilotica", 1.0, Band.AUTO),
        PhotoCandidate("parthenium hysterophorus", "Parthenium weed", "Parthenium hysterophorus", 0.35, Band.CONFIRM),
        PhotoCandidate("lantana camara", "Lantana", "Lantana camara", 0.26, Band.CONFIRM),
    )

    /**
     * @param park when true, [identify] suspends until [release] is called, so a
     *   test can move on while the photo path is still running.
     */
    private class PhotoFake(
        private val identification: PhotoIdentification,
        private val park: Boolean = false,
    ) : AuguryGateway {
        private val gate = Channel<Unit>(Channel.UNLIMITED)

        override suspend fun identify(imageBytes: ByteArray, region: String?): PhotoIdentification {
            if (park) gate.receive()
            return identification
        }

        fun release() {
            gate.trySend(Unit)
        }

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

        override suspend fun story(
            speciesKey: String,
            question: String,
            region: String?,
            modelText: String?,
        ): StoryResult? = null
    }

    @Test
    fun anIdentifyResultLandsWhenItIsStillWanted() = runTest(dispatcher) {
        val gw = PhotoFake(PhotoIdentification(candidates))
        val vm = AuguryViewModel(gw)

        vm.onPhotoPicked(byteArrayOf(1, 2, 3))
        advanceUntilIdle()

        val state = vm.state.value
        assertEquals(Screen.PHOTO, state.screen)
        assertFalse("the run should have finished", state.identifying)
        assertEquals("the candidates were dropped", candidates, state.photoCandidates)
        assertNull(state.photoUnavailable)
    }

    @Test
    fun startingANewPhotoClearsThePreviousSessionsResult() = runTest(dispatcher) {
        val gw = PhotoFake(PhotoIdentification(candidates))
        val vm = AuguryViewModel(gw)

        vm.onPhotoPicked(byteArrayOf(1, 2, 3))
        advanceUntilIdle()
        assertTrue("the setup did not produce a result to clear", vm.state.value.photoCandidates.isNotEmpty())

        // The reported action: ask for another photo.
        vm.startPhoto()

        val state = vm.state.value
        assertEquals(Screen.PHOTO, state.screen)
        assertTrue("the previous run's candidates survived", state.photoCandidates.isEmpty())
        assertFalse(state.photoEmpty)
        assertNull(state.photoUnavailable)
        assertFalse("a fresh session must not claim to be identifying", state.identifying)
        assertNull(state.story)
        assertNull(state.storyKey)
    }

    @Test
    fun aLateIdentifyCannotPopulateANewPhotoSession() = runTest(dispatcher) {
        val gw = PhotoFake(PhotoIdentification(candidates), park = true)
        val vm = AuguryViewModel(gw)

        vm.onPhotoPicked(byteArrayOf(1, 2, 3))
        advanceUntilIdle()
        assertTrue("the fake was not parked mid-identify", vm.state.value.identifying)

        // The user leaves for a fresh capture while the encoder is still working.
        vm.startPhoto()
        gw.release()
        advanceUntilIdle()

        val state = vm.state.value
        assertTrue(
            "a result for the abandoned photo landed in the new session",
            state.photoCandidates.isEmpty(),
        )
        assertFalse(state.identifying)
        assertNull(state.story)
    }
}

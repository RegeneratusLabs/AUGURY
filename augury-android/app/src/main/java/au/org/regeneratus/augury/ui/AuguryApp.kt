package au.org.regeneratus.augury.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import au.org.regeneratus.augury.ui.screens.HomeScreen
import au.org.regeneratus.augury.ui.screens.PhotoScreen
import au.org.regeneratus.augury.ui.screens.PickerScreen
import au.org.regeneratus.augury.ui.screens.SettingsScreen
import au.org.regeneratus.augury.ui.screens.SetupScreen
import au.org.regeneratus.augury.ui.screens.StoryScreen
import au.org.regeneratus.augury.ui.theme.AuguryDesign

/**
 * The shell.
 *
 * Navigation is a `when` over [AuguryUiState.screen] rather than a Navigation
 * graph: six flat destinations with one back edge do not justify the dependency,
 * and a plain state switch is trivially reviewable. If the app grows a deep link
 * or a multi-step flow, this is the file that changes.
 *
 * Every screen is wrapped in [ScreenScaffold], so the header geometry, the cream
 * ground and the scroll behaviour are identical across the app -- the mockup's
 * screens differ only in their content.
 */
@Composable
fun AuguryApp(vm: AuguryViewModel) {
    val state by vm.state.collectAsStateWithLifecycle()

    // Android's back gesture/button has to walk the app's own navigation.
    // Without this the system back finished the activity from any sub-screen, so
    // a user on the Story screen who pressed back landed on their phone's home
    // screen and lost their place. It is enabled exactly where a screen shows its
    // own back affordance: never on Home (nothing to go back to, so the system
    // keeps it and the app exits as expected), and not on a Setup that still has
    // work to do (leaving it early would strand the user on a Home screen whose
    // database is not installed).
    val canGoBack = state.screen != Screen.HOME &&
        !(state.screen == Screen.SETUP && state.setup?.allReady != true)
    BackHandler(enabled = canGoBack) { vm.back() }

    when (state.screen) {
        Screen.SETUP -> SetupScreen(state, vm)
        Screen.HOME -> HomeScreen(state, vm)
        Screen.PICKER -> PickerScreen(state, vm)
        Screen.PHOTO -> PhotoScreen(state, vm)
        Screen.STORY -> StoryScreen(state, vm)
        Screen.SETTINGS -> SettingsScreen(state, vm)
    }
}

/**
 * The shared screen frame: optional back affordance, title, one-line subtitle,
 * the scrolling body and a pinned footer for the primary action.
 *
 * A pinned footer is deliberate: the confirm step on the photo screen and the
 * "Take photo" action on the home screen must never be scrolled away from a
 * one-handed user standing in a paddock.
 */
@Composable
fun ScreenScaffold(
    title: String,
    subtitle: String? = null,
    onBack: (() -> Unit)? = null,
    footer: (@Composable () -> Unit)? = null,
    content: @Composable ColumnScope.() -> Unit,
) {
    val c = AuguryDesign.colors
    Column(
        Modifier
            .fillMaxSize()
            .background(c.background)
            // MainActivity calls enableEdgeToEdge(), so the app draws under the
            // status and navigation bars. Without this the footer's primary
            // button sits UNDER the navigation bar: its centre is not tappable,
            // and "Start identifying" silently did nothing on a device.
            .windowInsetsPadding(WindowInsets.safeDrawing),
    ) {
        Row(
            Modifier
                .fillMaxWidth()
                .padding(start = 18.dp, end = 18.dp, top = 14.dp, bottom = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (onBack != null) {
                Box(
                    Modifier
                        .size(26.dp)
                        .clip(RoundedCornerShape(8.dp))
                        .background(c.greySoft)
                        .clickable(onClick = onBack),
                    contentAlignment = Alignment.Center,
                ) {
                    Text("‹", fontSize = 15.sp, color = c.inkMuted, fontWeight = FontWeight.Bold)
                }
                Spacer(Modifier.width(11.dp))
            }
            Column(Modifier.weight(1f)) {
                Text(
                    title,
                    fontSize = 17.sp,
                    fontWeight = FontWeight.Bold,
                    color = c.ink,
                    letterSpacing = (-0.2).sp,
                )
                if (!subtitle.isNullOrBlank()) {
                    Text(
                        subtitle,
                        fontSize = 11.5.sp,
                        color = c.inkMuted,
                        lineHeight = 15.sp,
                    )
                }
            }
        }

        Column(
            Modifier
                .weight(1f)
                .fillMaxWidth()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 18.dp),
            verticalArrangement = Arrangement.spacedBy(11.dp),
        ) {
            content()
            Spacer(Modifier.height(14.dp))
        }

        if (footer != null) {
            Column(
                Modifier
                    .fillMaxWidth()
                    .background(c.surface)
                    .padding(horizontal = 18.dp, vertical = 12.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) { footer() }
        }
    }
}

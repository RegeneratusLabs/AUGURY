package au.org.regeneratus.augury.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.graphics.Color

/**
 * The Material 3 scheme exists so that stock components (dialogs, ripples, text
 * selection) look native; the app's own surfaces read [LocalAuguryColors], which
 * carries the semantic colours Material has no slot for (sageSoft, amberSoft, the
 * band colours).
 */
private fun materialScheme(c: AuguryColors, dark: Boolean) = if (dark) {
    darkColorScheme(
        primary = c.sage,
        onPrimary = c.sageOn,
        primaryContainer = c.sageSoft,
        onPrimaryContainer = c.ink,
        secondary = c.sageDeep,
        onSecondary = c.sageOn,
        background = c.background,
        onBackground = c.ink,
        surface = c.surface,
        onSurface = c.ink,
        surfaceVariant = c.surfaceMuted,
        onSurfaceVariant = c.inkMuted,
        outline = c.line,
        error = c.amber,
        onError = Color.White,
    )
} else {
    lightColorScheme(
        primary = c.sage,
        onPrimary = c.sageOn,
        primaryContainer = c.sageSoft,
        onPrimaryContainer = c.ink,
        secondary = c.sageDeep,
        onSecondary = c.sageOn,
        background = c.background,
        onBackground = c.ink,
        surface = c.surface,
        onSurface = c.ink,
        surfaceVariant = c.surfaceMuted,
        onSurfaceVariant = c.inkMuted,
        outline = c.line,
        error = c.amber,
        onError = Color.White,
    )
}

@Composable
fun AuguryTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    val colors = if (darkTheme) AuguryColors.Dark else AuguryColors.Light
    CompositionLocalProvider(LocalAuguryColors provides colors) {
        MaterialTheme(
            colorScheme = materialScheme(colors, darkTheme),
            typography = AuguryTypography,
            content = content,
        )
    }
}

/**
 * Shorthand for `LocalAuguryColors.current`. Named `AuguryDesign` rather than
 * `AuguryTheme` so it cannot be confused with the [AuguryTheme] composable at a
 * call site.
 */
object AuguryDesign {
    val colors: AuguryColors
        @Composable get() = LocalAuguryColors.current
}

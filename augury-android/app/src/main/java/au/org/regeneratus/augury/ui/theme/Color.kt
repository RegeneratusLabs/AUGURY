package au.org.regeneratus.augury.ui.theme

import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color

/**
 * AUGURY palette.
 *
 * Deliberately warm and low-contrast rather than "tech blue": the audience is
 * farmers and land managers reading a result in daylight, often one-handed. The
 * sage green carries the identity and every actionable control; amber is reserved
 * for *caution about the answer* (the confirm band), never for decoration; the
 * neutrals are a warm off-white so long indicator text stays comfortable.
 *
 * These are semantic names, not shades -- call sites say [AuguryColors.sageSoft],
 * never a hex value.
 */
@Immutable
data class AuguryColors(
    val background: Color,
    val surface: Color,
    val surfaceMuted: Color,
    val ink: Color,
    val inkMuted: Color,
    val line: Color,

    /** Identity + every primary action. */
    val sage: Color,
    val sageDeep: Color,
    val sageSoft: Color,
    val sageOn: Color,

    /** "We are less sure than you would like" -- the confirm band, and warnings. */
    val amber: Color,
    val amberSoft: Color,
    val amberInk: Color,

    /** Unknown / below the confirm band. */
    val greySoft: Color,
) {
    companion object {
        val Light = AuguryColors(
            background = Color(0xFFFBF9F4),
            surface = Color(0xFFFFFFFF),
            surfaceMuted = Color(0xFFF1F0EA),
            ink = Color(0xFF1B1F17),
            inkMuted = Color(0xFF6B7364),
            line = Color(0xFFE4E1D6),

            sage = Color(0xFF43603F),
            sageDeep = Color(0xFF34492F),
            sageSoft = Color(0xFFEAF0E6),
            sageOn = Color(0xFFF6F9F3),

            amber = Color(0xFFB0722A),
            amberSoft = Color(0xFFFBF1E2),
            amberInk = Color(0xFF7A5316),

            greySoft = Color(0xFFF1F0EA),
        )

        /**
         * Dark scheme. Not a tint of the light one: the sage has to lift to stay
         * legible on a dark ground, and the surfaces go warm-neutral rather than
         * pure black so the indicator cards do not glare at night.
         */
        val Dark = AuguryColors(
            background = Color(0xFF141812),
            surface = Color(0xFF1E231B),
            surfaceMuted = Color(0xFF262C22),
            ink = Color(0xFFEDEFE6),
            inkMuted = Color(0xFFA9B0A0),
            line = Color(0xFF333A2E),

            sage = Color(0xFF9DB58F),
            sageDeep = Color(0xFF7E9A70),
            sageSoft = Color(0xFF2A3524),
            sageOn = Color(0xFF16200F),

            amber = Color(0xFFE0A75E),
            amberSoft = Color(0xFF33291A),
            amberInk = Color(0xFFF0CFA0),

            greySoft = Color(0xFF262C22),
        )
    }
}

/**
 * Exposed as a static CompositionLocal: the palette never changes *within* a
 * theme, only between light and dark, so the cheaper static local is correct here
 * and avoids a recomposition read in every call site.
 */
val LocalAuguryColors = staticCompositionLocalOf { AuguryColors.Light }

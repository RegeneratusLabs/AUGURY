package au.org.regeneratus.augury.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import au.org.regeneratus.augury.ui.Band
import au.org.regeneratus.augury.ui.theme.AuguryColors
import au.org.regeneratus.augury.ui.theme.AuguryDesign

/**
 * The shared visual vocabulary. Screens compose these rather than styling
 * `Text`/`Box` inline, so the palette and the corner radii stay consistent and a
 * design change lands in one place.
 */

private val CardShape = RoundedCornerShape(15.dp)
private val ControlShape = RoundedCornerShape(14.dp)

/**
 * A white card on the cream background. The app's only container.
 *
 * **The content is a [ColumnScope], and that is load-bearing.** This used to be a
 * `Box`, which stacked every child at the same position — so a card written the
 * obvious way
 *
 * ```
 * AuguryCard {
 *     SectionLabel("DOWNLOADING")
 *     Spacer(Modifier.height(10.dp))
 *     columnOfArtifactRows()
 * }
 * ```
 *
 * drew the label *on top of* the rows, and the download screen showed
 * "Downloading" and "Story writer" overprinted. Twenty-two call sites, most of
 * them multi-child, so nearly every card in the app was affected. A `Box` makes
 * that mistake silent; a `Column` makes it unwritable, and no caller legitimately
 * wanted an overlay.
 */
@Composable
fun AuguryCard(
    modifier: Modifier = Modifier,
    background: Color = AuguryDesign.colors.surface,
    borderColor: Color = AuguryDesign.colors.line,
    padding: Int = 14,
    content: @Composable ColumnScope.() -> Unit,
) {
    Column(
        modifier
            .fillMaxWidth()
            .clip(CardShape)
            .background(background)
            .border(1.dp, borderColor, CardShape)
            .padding(padding.dp),
        content = content,
    )
}

/**
 * The ALL-CAPS section label ("INDICATORS", "DOWNLOADING").
 *
 * @param trailing optional right-aligned content, e.g. "9 from database".
 */
@Composable
fun SectionLabel(
    text: String,
    modifier: Modifier = Modifier,
    trailing: String? = null,
) {
    Row(
        modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
    ) {        Text(
            text = text.uppercase(),
            fontSize = 10.5.sp,
            fontWeight = FontWeight.Bold,
            letterSpacing = 0.9.sp,
            color = AuguryDesign.colors.inkMuted,
            modifier = Modifier.weight(1f),
        )
        if (trailing != null) {
            // A gap, so a long label and its trailing value never read as one run
            // of text when the label fills its weight.
            Spacer(Modifier.width(8.dp))
            Text(
                text = trailing,
                fontSize = 11.5.sp,
                fontWeight = FontWeight.SemiBold,
                color = AuguryDesign.colors.sage,
            )
        }
    }
}

/**
 * The confidence pill.
 *
 * [Band.AUTO] reads "High confidence" and **not** "safe" -- the wording matters,
 * because a confident wrong ID is the failure mode this whole confirm step exists
 * to catch (decision record §6).
 */
@Composable
fun BandPill(band: Band, score: Double? = null, modifier: Modifier = Modifier) {
    val c = AuguryDesign.colors
    val (bg, fg, label) = when (band) {
        Band.AUTO -> Triple(c.sageSoft, c.sage, "High confidence")
        Band.CONFIRM -> Triple(c.amberSoft, c.amber, "Possible match")
        Band.UNKNOWN -> Triple(c.greySoft, c.inkMuted, "Not sure")
    }
    Row(verticalAlignment = Alignment.CenterVertically, modifier = modifier) {
        Box(
            Modifier
                .clip(RoundedCornerShape(20.dp))
                .background(bg)
                .padding(horizontal = 10.dp, vertical = 4.dp),
        ) {
            Text(
                "● $label",
                fontSize = 11.5.sp,
                fontWeight = FontWeight.Bold,
                color = fg,
            )
        }
        if (score != null) {
            Spacer(Modifier.width(8.dp))
            Text(
                text = "%.2f".format(score),
                fontSize = 11.5.sp,
                color = c.inkMuted,
            )
        }
    }
}

/** The full-width primary action. */
@Composable
fun PrimaryButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    val c = AuguryDesign.colors
    Box(
        modifier
            .fillMaxWidth()
            .heightIn(min = 50.dp)
            .padding(vertical = 8.dp)
            .clip(ControlShape)
            .background(if (enabled) c.sage else c.sage.copy(alpha = 0.4f))
            .clickable(enabled = enabled, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text,
            fontSize = 14.5.sp,
            fontWeight = FontWeight.SemiBold,
            color = c.sageOn,
            textAlign = TextAlign.Center,
        )
    }
}

/** The secondary action: same geometry, card styling. */
@Composable
fun SecondaryButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    val c = AuguryDesign.colors
    Box(
        modifier
            .fillMaxWidth()
            .heightIn(min = 50.dp)
            .padding(vertical = 8.dp)
            .clip(ControlShape)
            .background(c.surface)
            .border(1.dp, c.line, ControlShape)
            .clickable(enabled = enabled, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text,
            fontSize = 14.5.sp,
            fontWeight = FontWeight.SemiBold,
            color = if (enabled) c.ink else c.inkMuted,
            textAlign = TextAlign.Center,
        )
    }
}

/** A selectable filter chip, e.g. the region or "With soil data". */
@Composable
fun FilterChip(
    text: String,
    selected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val c = AuguryDesign.colors
    Box(
        modifier
            .clip(RoundedCornerShape(20.dp))
            .background(if (selected) c.sageSoft else c.greySoft)
            .border(
                1.dp,
                if (selected) c.sage.copy(alpha = 0.35f) else Color.Transparent,
                RoundedCornerShape(20.dp),
            )
            .clickable(onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 6.dp),
    ) {
        Text(
            text,
            fontSize = 11.5.sp,
            fontWeight = FontWeight.SemiBold,
            color = if (selected) c.sage else c.inkMuted,
        )
    }
}

/**
 * A determinate progress bar. [tint] lets Setup show "done" in sage and
 * "in progress" in the same sage at full strength, while a queued row stays grey.
 */
@Composable
fun ProgressBar(
    progress: Float,
    modifier: Modifier = Modifier,
    tint: Color = AuguryDesign.colors.sage,
    height: Int = 5,
) {
    val c = AuguryDesign.colors
    Box(
        modifier
            .fillMaxWidth()
            .height(height.dp)
            .clip(RoundedCornerShape(height.dp))
            .background(c.surfaceMuted),
    ) {
        val p = progress.coerceIn(0f, 1f)
        if (p > 0f) {
            Box(
                Modifier
                    .fillMaxWidth(p)
                    .height(height.dp)
                    .clip(RoundedCornerShape(height.dp))
                    .background(tint),
            )
        }
    }
}

/** "211 MB of 347 MB" … "61% · 1.4 MB/s" */
@Composable
fun ProgressCaption(left: String, right: String, rightColor: Color? = null) {
    val c = AuguryDesign.colors
    Row(
        Modifier
            .fillMaxWidth()
            .padding(top = 6.dp),
    ) {
        Text(left, fontSize = 11.5.sp, color = c.inkMuted, modifier = Modifier.weight(1f))
        Text(
            right,
            fontSize = 11.5.sp,
            color = rightColor ?: c.inkMuted,
            fontWeight = if (rightColor != null) FontWeight.Bold else FontWeight.Normal,
        )
    }
}

/**
 * A notice strip. [tone] chooses between "we are being careful" (amber, used for
 * the Wi-Fi warning) and "for your information" (neutral).
 */
enum class NoticeTone { CAUTION, NEUTRAL, POSITIVE }

@Composable
fun Notice(text: String, tone: NoticeTone = NoticeTone.NEUTRAL, modifier: Modifier = Modifier) {
    val c = AuguryDesign.colors
    val bg = when (tone) {
        NoticeTone.CAUTION -> c.amberSoft
        NoticeTone.POSITIVE -> c.sageSoft
        NoticeTone.NEUTRAL -> c.greySoft
    }
    val fg = when (tone) {
        NoticeTone.CAUTION -> c.amberInk
        NoticeTone.POSITIVE -> c.sage
        NoticeTone.NEUTRAL -> c.inkMuted
    }
    Box(
        modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(11.dp))
            .background(bg)
            .border(1.dp, fg.copy(alpha = 0.22f), RoundedCornerShape(11.dp))
            .padding(horizontal = 12.dp, vertical = 10.dp),
    ) {
        Text(text, fontSize = 11.5.sp, lineHeight = 17.sp, color = fg)
    }
}

/**
 * A labelled on/off switch. Written by hand rather than using Material's
 * `Switch` so the sage palette applies without fighting the default colours.
 */
@Composable
fun AugurySwitch(checked: Boolean, onCheckedChange: (Boolean) -> Unit) {
    val c = AuguryDesign.colors
    Box(
        Modifier
            .size(width = 38.dp, height = 22.dp)
            .clip(RoundedCornerShape(20.dp))
            .background(if (checked) c.sage else c.surfaceMuted)
            .clickable { onCheckedChange(!checked) },
        contentAlignment = if (checked) Alignment.CenterEnd else Alignment.CenterStart,
    ) {
        Box(
            Modifier
                .padding(3.dp)
                .size(16.dp)
                .clip(RoundedCornerShape(50))
                .background(Color.White),
        )
    }
}

/** A tappable list row: icon badge, title, subtitle, right-hand slot. */
@Composable
fun RowScope.AuguryRowContent(
    badge: String,
    badgeBackground: Color,
    title: String,
    subtitle: String?,
    titleSize: Int = 14,
) {
    Box(
        Modifier
            .size(30.dp)
            .clip(RoundedCornerShape(10.dp))
            .background(badgeBackground),
        contentAlignment = Alignment.Center,
    ) {
        Text(badge, fontSize = 14.sp)
    }
    Spacer(Modifier.width(11.dp))
    Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(1.dp)) {
        Text(
            title,
            fontSize = titleSize.sp,
            fontWeight = FontWeight.SemiBold,
            color = AuguryDesign.colors.ink,
            lineHeight = (titleSize + 4).sp,
        )
        if (!subtitle.isNullOrBlank()) {
            Text(
                subtitle,
                fontSize = 11.5.sp,
                color = AuguryDesign.colors.inkMuted,
                fontStyle = androidx.compose.ui.text.font.FontStyle.Italic,
            )
        }
    }
}

/**
 * The picker's search box.
 *
 * A plain framework text field rather than a Material one, so the cream surface
 * and the sage caret are not fighting the default container colours. The clear
 * affordance is explicit because the audience types slowly and needs to back out
 * of a typo without fighting a selection handle.
 */
@Composable
fun SearchField(
    value: String,
    onValueChange: (String) -> Unit,
    placeholder: String,
    modifier: Modifier = Modifier,
    onClear: (() -> Unit)? = null,
) {
    val c = AuguryDesign.colors
    Row(
        modifier
            .fillMaxWidth()
            .heightIn(min = 46.dp)
            .clip(RoundedCornerShape(12.dp))
            .background(c.surface)
            .border(1.dp, c.line, RoundedCornerShape(12.dp))
            .padding(horizontal = 13.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text("🔎", fontSize = 13.sp)
        Spacer(Modifier.width(9.dp))
        Box(Modifier.weight(1f), contentAlignment = Alignment.CenterStart) {
            if (value.isEmpty()) {
                Text(placeholder, fontSize = 14.sp, color = c.inkMuted)
            }
            BasicTextField(
                value = value,
                onValueChange = onValueChange,
                singleLine = true,
                textStyle = TextStyle(
                    fontSize = 14.sp,
                    color = c.ink,
                ),
                cursorBrush = SolidColor(c.sage),
                modifier = Modifier.fillMaxWidth(),
            )
        }
        if (value.isNotEmpty() && onClear != null) {
            Spacer(Modifier.width(6.dp))
            Box(
                Modifier
                    .size(20.dp)
                    .clip(RoundedCornerShape(50))
                    .background(c.surfaceMuted)
                    .clickable(onClick = onClear),
                contentAlignment = Alignment.Center,
            ) {
                Text("×", fontSize = 13.sp, color = c.inkMuted, fontWeight = FontWeight.Bold)
            }
        }
    }
}

/** Formats a byte count the way the mockup does: "24.7 MB", "1.0 GB". */fun formatBytes(bytes: Long): String = when {
    bytes >= 1_000_000_000L -> "%.2f GB".format(bytes / 1_000_000_000.0)
    bytes >= 1_000_000L -> "%.1f MB".format(bytes / 1_000_000.0)
    bytes >= 1_000L -> "%.0f KB".format(bytes / 1_000.0)
    else -> "$bytes B"
}

/** "1.4 MB/s" */
fun formatRate(bytesPerSecond: Long): String =
    if (bytesPerSecond <= 0L) "" else "${formatBytes(bytesPerSecond)}/s"

/** Small helper so screens can read the palette without importing the local. */
internal val augury: AuguryColors
    @Composable get() = AuguryDesign.colors

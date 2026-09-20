package au.org.regeneratus.augury.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import au.org.regeneratus.augury.ui.AuguryUiState
import au.org.regeneratus.augury.ui.AuguryViewModel
import au.org.regeneratus.augury.ui.Screen
import au.org.regeneratus.augury.ui.ScreenScaffold
import au.org.regeneratus.augury.ui.components.AuguryCard
import au.org.regeneratus.augury.ui.components.Notice
import au.org.regeneratus.augury.ui.components.NoticeTone
import au.org.regeneratus.augury.ui.components.PrimaryButton
import au.org.regeneratus.augury.ui.components.SecondaryButton
import au.org.regeneratus.augury.ui.components.SectionLabel
import au.org.regeneratus.augury.ui.theme.AuguryDesign

/**
 * 4 · SOIL STORY — the payload.
 *
 * Three things on this screen are load-bearing beyond layout:
 *
 *  1. **The indicator rows are verbatim from the database.** The formatter model
 *     phrases them; it never supplies them. Constraint 5: "the model never
 *     generates facts — indicators come from the DB and only from the DB."
 *  2. **Grounding repairs are shown, not swallowed.** If the model produced a
 *     number the facts did not support, the app removed it and this screen says
 *     so. That is the "likely below 6.5" failure, caught and disclosed.
 *  3. **Provenance is visible.** Source, region, and — for a genus-level bucket —
 *     the fact that the answer covers a group rather than one species. "thistles"
 *     must never be silently relabelled *Cirsium vulgare*.
 */
@Composable
fun StoryScreen(state: AuguryUiState, vm: AuguryViewModel) {
    val c = AuguryDesign.colors
    val result = state.story
    val reading = result?.reading

    ScreenScaffold(
        title = reading?.displayName ?: "Soil reading",
        subtitle = buildString {
            if (reading != null) {
                append(reading.scientificName)
                append(" · ")
                append(reading.region)
            } else {
                append("Reading the database…")
            }
        },
        onBack = { vm.back() },
        footer = {
            if (reading != null) {
                PrimaryButton(
                    text = "Identify another plant",
                    onClick = { vm.go(Screen.HOME) },
                )
                SecondaryButton(
                    text = "Photo instead",
                    onClick = { vm.go(Screen.PHOTO) },
                )
            }
        },
    ) {
        when {
            state.composing -> Notice("Looking up the soil indicators…", NoticeTone.NEUTRAL)

            state.storyError != null -> {
                Notice(state.storyError, NoticeTone.CAUTION)
                AuguryCard {
                    SectionLabel("Why this happens")
                    Spacer(Modifier.height(8.dp))
                    Text(
                        "Not every species in the database carries soil indicators for " +
                            "this region. AUGURY would rather say nothing than guess.",
                        fontSize = 12.5.sp,
                        lineHeight = 19.sp,
                        color = c.ink,
                    )
                }
            }

            result != null && reading != null -> {
                // ── the prose ──
                if (result.story.isNotBlank()) {
                    AuguryCard {
                        SectionLabel("What it says about your soil")
                        Spacer(Modifier.height(8.dp))
                        Text(
                            result.story.trim(),
                            fontSize = 13.5.sp,
                            lineHeight = 21.sp,
                            color = c.ink,
                        )
                    }
                }

                // ── the facts, verbatim ──
                if (reading.indicators.isNotEmpty()) {
                    AuguryCard {
                        SectionLabel(
                            text = "Indicators",
                            trailing = "${reading.indicators.size} from database",
                        )
                        Spacer(Modifier.height(10.dp))
                        Column(verticalArrangement = Arrangement.spacedBy(11.dp)) {
                            reading.indicators.forEach { row ->
                                Column {
                                    Text(
                                        row.key,
                                        fontSize = 12.sp,
                                        fontWeight = FontWeight.Bold,
                                        color = c.sage,
                                    )
                                    Spacer(Modifier.height(2.dp))
                                    Text(
                                        row.value,
                                        fontSize = 13.sp,
                                        lineHeight = 19.5.sp,
                                        color = c.ink,
                                    )
                                }
                            }
                        }
                    }
                }

                // ── honesty about the identity ──
                if (reading.specificity == "genus_bucket" || reading.mergedFrom.size > 1) {
                    Notice(
                        buildString {
                            append("This is a group answer, not one species. ")
                            if (reading.mergedFrom.size > 1) {
                                append("Indicators were merged from ")
                                append(reading.mergedFrom.joinToString(", "))
                                append(". ")
                            }
                            append("Plants in a genus can differ, so treat this as a " +
                                "general reading.")
                        },
                        tone = NoticeTone.CAUTION,
                    )
                }

                if (reading.regionFallback) {
                    Notice(
                        "No ${reading.requestedRegion ?: "local"} records for this plant — " +
                            "showing ${reading.region} data instead.",
                        tone = NoticeTone.NEUTRAL,
                    )
                }

                // ── the grounding audit trail ──
                if (result.repairs.isNotEmpty()) {
                    AuguryCard(background = c.amberSoft, borderColor = c.amber.copy(alpha = 0.3f)) {
                        SectionLabel("Corrected")
                        Spacer(Modifier.height(8.dp))
                        Text(
                            "The story writer produced ${result.repairs.size} statement(s) " +
                                "that the database did not support. They were removed or " +
                                "rewritten before you saw them:",
                            fontSize = 11.5.sp,
                            lineHeight = 17.sp,
                            color = c.amberInk,
                        )
                        Spacer(Modifier.height(8.dp))
                        result.repairs.forEach { r ->
                            Column(Modifier.padding(bottom = 7.dp)) {
                                Text(
                                    r.action,
                                    fontSize = 10.5.sp,
                                    fontWeight = FontWeight.Bold,
                                    color = c.amber,
                                )
                                if (r.removed.isNotEmpty()) {
                                    Text(
                                        "removed: “${r.removed.joinToString(" ")}”",
                                        fontSize = 11.sp,
                                        lineHeight = 16.sp,
                                        color = c.amberInk,
                                        fontStyle = FontStyle.Italic,
                                    )
                                }
                                if (r.after.isNotBlank()) {
                                    Text(
                                        "now reads: “${r.after}”",
                                        fontSize = 11.sp,
                                        lineHeight = 16.sp,
                                        color = c.amberInk,
                                    )
                                }
                            }
                        }
                    }
                }

                // ── provenance ──
                AuguryCard {
                    SectionLabel("Where this comes from")
                    Spacer(Modifier.height(8.dp))
                    ProvenanceRow("Source", reading.source.ifBlank { "AUGURY database" })
                    ProvenanceRow("Region", "${reading.region} (you selected ${reading.requestedRegion ?: reading.region})")
                    ProvenanceRow("Database key", reading.key)
                    ProvenanceRow(
                        "Written by",
                        if (result.usedModel) {
                            "on-device formatter model, grounded against the database"
                        } else {
                            "the deterministic template — no model was used"
                        },
                    )
                }
            }

            else -> Notice("Nothing to show yet.", NoticeTone.NEUTRAL)
        }

        // The rule that defines the product, restated where the user reads the answer.
        AuguryCard(background = c.sageSoft, borderColor = c.sage.copy(alpha = 0.25f)) {
            Text(
                "Indicators only. AUGURY never gives management, herbicide or " +
                    "remediation advice — it reports what the plant says about the soil.",
                fontSize = 11.5.sp,
                lineHeight = 17.sp,
                color = c.sage,
            )
        }
    }
}

@Composable
private fun ProvenanceRow(label: String, value: String) {
    val c = AuguryDesign.colors
    Row(
        Modifier
            .fillMaxWidth()
            .padding(vertical = 3.dp),
    ) {
        Text(
            label,
            fontSize = 11.5.sp,
            color = c.inkMuted,
            modifier = Modifier.width(96.dp),
        )
        Text(
            value,
            fontSize = 11.5.sp,
            lineHeight = 16.sp,
            color = c.ink,
            modifier = Modifier.weight(1f),
        )
    }
}

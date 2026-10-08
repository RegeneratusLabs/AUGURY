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
 *  2. **Grounding repairs are applied, not shown.** If the model produced a
 *     number the facts did not support, the app removes or rewrites it before the
 *     text reaches this screen — that is the "likely below 6.5" failure, caught.
 *     The reading is then presented simply as the reading; the repair record is
 *     kept in `StoryResult.repairs` for the device tests and the log, but the user
 *     is not shown an audit of what was corrected.
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
        // While the turn is running there is no `reading` yet — the species is only
        // resolved once the answerer has run — so the name the user tapped is
        // carried in the state. Without it the title flickered from the species
        // name to "Soil reading" and back on every open.
        title = reading?.displayName ?: state.storyDisplayName ?: "Soil reading",
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
                    // A new capture, so the previous photo session's card must go.
                    onClick = { vm.startPhoto() },
                )
            }
        },
    ) {
        when {
            // The formatter model writes on-device: ~10 s of prompt evaluation
            // before its first token, then ~40 s of prose on the emulator. Three
            // distinct states, because they mean three different things:
            //   composing && !streaming -> the model is still reading the prompt
            //   streaming               -> prose is arriving, UNVERIFIED
            //   neither                 -> the grounded answer below
            state.streaming && state.storyDraft != null -> {
                // The draft is shown dimmed and labelled "writing…" on purpose.
                // Grounding runs on the finished text, so a prefix is a claim the
                // database has not vouched for yet: it must never look like the
                // answer. When the turn lands this block is replaced by the
                // grounded prose.
                AuguryCard(
                    background = c.sageSoft,
                    borderColor = c.sage.copy(alpha = 0.25f),
                ) {
                    SectionLabel("Writing…")
                    Spacer(Modifier.height(8.dp))
                    Text(
                        // A token piece can be a leading space or a word fragment,
                        // so the draft starts with whitespace surprisingly often --
                        // the first thing the user sees must not be an indent.
                        state.storyDraft.trimStart(),
                        fontSize = 13.5.sp,
                        lineHeight = 21.sp,
                        color = c.inkMuted,
                        fontStyle = FontStyle.Italic,
                    )
                    Spacer(Modifier.height(10.dp))
                    Text(
                        "Not checked against the database yet. The verified reading " +
                            "replaces this as soon as the writer finishes.",
                        fontSize = 11.sp,
                        lineHeight = 16.sp,
                        color = c.inkMuted,
                    )
                }
            }

            state.composing -> Notice(
                "Reading the database and writing your reading…",
                NoticeTone.NEUTRAL,
            )

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

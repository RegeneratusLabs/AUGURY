package au.org.regeneratus.augury.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import au.org.regeneratus.augury.ui.AuguryUiState
import au.org.regeneratus.augury.ui.AuguryViewModel
import au.org.regeneratus.augury.ui.Screen
import au.org.regeneratus.augury.ui.ScreenScaffold
import au.org.regeneratus.augury.ui.SpeciesSuggestion
import au.org.regeneratus.augury.ui.components.AuguryCard
import au.org.regeneratus.augury.ui.components.FilterChip
import au.org.regeneratus.augury.ui.components.PrimaryButton
import au.org.regeneratus.augury.ui.components.SearchField
import au.org.regeneratus.augury.ui.components.SecondaryButton
import au.org.regeneratus.augury.ui.theme.AuguryDesign

/**
 * 2 · HOME — the default surface.
 *
 * The picker leads and the camera follows, which is a deliberate inversion of the
 * obvious design. From the decision record (§6, consequence 4): the tap-a-weed
 * path is **the most reliable path in the product** — 185 of 188 Australian
 * species have real common names, all 188 carry indicators, and it avoids the
 * 56.3% held-out species-extraction rate that would otherwise fail non-technical
 * users. Photo identification is the impressive feature; the list is the one that
 * works.
 *
 * The hero copy therefore promises exactly what this screen does: name the weed,
 * read the soil.
 */
@Composable
fun HomeScreen(state: AuguryUiState, vm: AuguryViewModel) {
    val c = AuguryDesign.colors

    // The list is populated on first composition rather than in the ViewModel's
    // init, so the manifest/artifact check is not competing with it.
    LaunchedEffect(state.region, state.withIndicatorsOnly) {
        if (state.suggestions.isEmpty() && !state.loadingPicker) vm.search(state.query)
    }

    ScreenScaffold(
        title = "AUGURY",
        subtitle = "Weeds tell you what your soil is doing",
        footer = {
            Row(horizontalArrangement = Arrangement.spacedBy(9.dp)) {
                Box(Modifier.weight(1f)) {
                    PrimaryButton(
                        text = "📷  Take photo",
                        onClick = { vm.go(Screen.PHOTO) },
                    )
                }
                Box(Modifier.weight(1f)) {
                    SecondaryButton(
                        text = "Browse all",
                        onClick = { vm.go(Screen.PICKER) },
                    )
                }
            }
        },
    ) {
        // ── identity card ──
        Box(
            Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(15.dp))
                .background(c.sage)
                .padding(17.dp),
        ) {
            Column {
                Text(
                    "FASTEST WAY",
                    fontSize = 10.5.sp,
                    fontWeight = FontWeight.Bold,
                    letterSpacing = 1.4.sp,
                    color = c.sageSoft,
                )
                Spacer(Modifier.height(6.dp))
                Text(
                    "Know the weed,\nread the soil",
                    fontSize = 20.sp,
                    lineHeight = 25.sp,
                    fontWeight = FontWeight.Bold,
                    color = c.sageOn,
                )
                Spacer(Modifier.height(5.dp))
                Text(
                    "Type a name or pick from the list — no photo needed.",
                    fontSize = 12.sp,
                    lineHeight = 17.sp,
                    color = c.sageSoft,
                )
            }
        }

        SearchField(
            value = state.query,
            onValueChange = vm::onQueryChange,
            placeholder = "Search ${"%,d".format(state.manifest?.speciesCount ?: 2256)} species…",
            onClear = { vm.onQueryChange("") },
        )

        Row(horizontalArrangement = Arrangement.spacedBy(7.dp)) {
            val regions = state.manifest?.regions ?: listOf(AuguryUiState.DEFAULT_REGION)
            regions.take(3).forEach { region ->
                FilterChip(
                    text = region,
                    selected = state.region == region,
                    onClick = { vm.setRegion(region) },
                )
            }
            FilterChip(
                text = "With soil data",
                selected = state.withIndicatorsOnly,
                onClick = { vm.toggleIndicatorsOnly() },
            )
        }

        AuguryCard(padding = 6) {
            Column {
                val rows = state.suggestions.take(6)
                when {
                    state.loadingPicker && rows.isEmpty() -> LoadingRows()
                    rows.isEmpty() -> Text(
                        if (state.query.isBlank()) {
                            "No species with soil data in this region."
                        } else {
                            "Nothing matched “${state.query}”. Try the common name, or " +
                                "check the spelling."
                        },
                        fontSize = 12.5.sp,
                        color = c.inkMuted,
                        modifier = Modifier.padding(12.dp),
                    )
                    else -> rows.forEachIndexed { i, s ->
                        SpeciesRow(
                            suggestion = s,
                            showDivider = i < rows.lastIndex,
                            onClick = { vm.openStory(s.key) },
                        )
                    }
                }
                if (state.suggestions.size > rows.size) {
                    Box(
                        Modifier
                            .fillMaxWidth()
                            .clickable { vm.go(Screen.PICKER) }
                            .padding(vertical = 11.dp),
                        contentAlignment = Alignment.Center,
                    ) {
                        Text(
                            "See all ${state.suggestions.size} matches",
                            fontSize = 12.5.sp,
                            fontWeight = FontWeight.SemiBold,
                            color = c.sage,
                        )
                    }
                }
            }
        }

        // ── honesty footer: what this app will not do ──
        AuguryCard(background = c.sageSoft, borderColor = c.sage.copy(alpha = 0.25f)) {
            Text(
                "Indicators only. AUGURY reads what a plant says about your soil — " +
                    "it never gives management, herbicide or remediation advice, and " +
                    "it never invents a number that is not in the database.",
                fontSize = 11.5.sp,
                lineHeight = 17.sp,
                color = c.sage,
            )
        }
    }
}

/** "Dandelion / Taraxacum officinale — 9 indicators". */
@Composable
internal fun SpeciesRow(
    suggestion: SpeciesSuggestion,
    showDivider: Boolean,
    onClick: () -> Unit,
) {
    val c = AuguryDesign.colors
    Column {
        Row(
            Modifier
                .fillMaxWidth()
                .clickable(onClick = onClick)
                .padding(horizontal = 12.dp, vertical = 11.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                Modifier
                    .size(30.dp)
                    .clip(RoundedCornerShape(10.dp))
                    .background(if (suggestion.hasIndicators) c.sageSoft else c.greySoft),
                contentAlignment = Alignment.Center,
            ) {
                Text(if (suggestion.hasIndicators) "🌿" else "·", fontSize = 13.sp)
            }
            Spacer(Modifier.width(11.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    suggestion.displayName,
                    fontSize = 14.sp,
                    fontWeight = FontWeight.SemiBold,
                    color = c.ink,
                    lineHeight = 18.sp,
                )
                Text(
                    suggestion.scientificName,
                    fontSize = 11.5.sp,
                    color = c.inkMuted,
                    fontStyle = androidx.compose.ui.text.font.FontStyle.Italic,
                )
            }
            if (suggestion.hasIndicators) {
                Box(
                    Modifier
                        .clip(RoundedCornerShape(9.dp))
                        .background(c.sageSoft)
                        .padding(horizontal = 8.dp, vertical = 3.dp),
                ) {
                    Text(
                        "soil data",
                        fontSize = 10.sp,
                        fontWeight = FontWeight.Bold,
                        color = c.sage,
                    )
                }
            }
        }
        if (showDivider) {
            Box(
                Modifier
                    .fillMaxWidth()
                    .padding(start = 53.dp)
                    .height(1.dp)
                    .background(c.line),
            )
        }
    }
}

@Composable
private fun LoadingRows() {
    val c = AuguryDesign.colors
    Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        repeat(4) {
            Box(
                Modifier
                    .fillMaxWidth()
                    .height(34.dp)
                    .clip(RoundedCornerShape(10.dp))
                    .background(c.surfaceMuted),
            )
        }
    }
}

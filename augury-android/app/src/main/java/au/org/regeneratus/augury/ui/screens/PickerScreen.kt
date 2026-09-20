package au.org.regeneratus.augury.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import au.org.regeneratus.augury.ui.AuguryUiState
import au.org.regeneratus.augury.ui.AuguryViewModel
import au.org.regeneratus.augury.ui.Screen
import au.org.regeneratus.augury.ui.ScreenScaffold
import au.org.regeneratus.augury.ui.components.AuguryCard
import au.org.regeneratus.augury.ui.components.FilterChip
import au.org.regeneratus.augury.ui.components.SearchField
import au.org.regeneratus.augury.ui.components.SectionLabel
import au.org.regeneratus.augury.ui.theme.AuguryDesign

/**
 * The full picker. Same ranking as the home list, but with the whole result set
 * and the provenance of each match shown.
 *
 * "With soil data" is on by default because a species row that carries no
 * indicators cannot produce a story — offering it would be a dead end for a
 * non-technical user. It stays switchable so the filter is never a silent lie
 * about what the database holds.
 */
@Composable
fun PickerScreen(state: AuguryUiState, vm: AuguryViewModel) {
    val c = AuguryDesign.colors

    LaunchedEffect(Unit) { vm.search(state.query) }

    ScreenScaffold(
        title = "Find a plant",
        subtitle = "Type a common or scientific name",
        onBack = { vm.back() },
    ) {
        SearchField(
            value = state.query,
            onValueChange = vm::onQueryChange,
            placeholder = "Search…",
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
        }

        Row(horizontalArrangement = Arrangement.spacedBy(7.dp)) {
            FilterChip(
                text = "With soil data",
                selected = state.withIndicatorsOnly,
                onClick = { vm.toggleIndicatorsOnly() },
            )
        }

        AuguryCard(padding = 6) {
            Column {
                SectionLabel(
                    text = if (state.query.isBlank()) "All plants" else "Matches",
                    trailing = "${state.suggestions.size}",
                    modifier = Modifier.padding(start = 12.dp, top = 10.dp, end = 12.dp),
                )
                Spacer(Modifier.height(6.dp))
                val rows = state.suggestions
                if (rows.isEmpty()) {
                    Text(
                        if (state.loadingPicker) {
                            "Searching…"
                        } else {
                            "Nothing matched. Try the common name you know — “capeweed”, " +
                                "“thistles”, “khaki weed” — or clear the filter."
                        },
                        fontSize = 12.5.sp,
                        lineHeight = 18.sp,
                        color = c.inkMuted,
                        modifier = Modifier.padding(12.dp),
                    )
                } else {
                    rows.forEachIndexed { i, s ->
                        SpeciesRow(
                            suggestion = s,
                            showDivider = i < rows.lastIndex,
                            onClick = { vm.openStory(s.key) },
                        )
                    }
                }
            }
        }

        Text(
            "Species without soil data are hidden while the filter is on. Some names " +
                "are genus-level buckets — “thistles” returns the group, not one species.",
            fontSize = 11.sp,
            lineHeight = 16.sp,
            color = c.inkMuted,
            modifier = Modifier.padding(horizontal = 2.dp),
        )
    }
}

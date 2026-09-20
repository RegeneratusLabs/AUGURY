package au.org.regeneratus.augury.ui.screens

import androidx.compose.foundation.background
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
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import au.org.regeneratus.augury.ui.ArtifactInfo
import au.org.regeneratus.augury.ui.ArtifactStatus
import au.org.regeneratus.augury.ui.AuguryUiState
import au.org.regeneratus.augury.ui.AuguryViewModel
import au.org.regeneratus.augury.ui.Screen
import au.org.regeneratus.augury.ui.ScreenScaffold
import au.org.regeneratus.augury.ui.components.AuguryCard
import au.org.regeneratus.augury.ui.components.AugurySwitch
import au.org.regeneratus.augury.ui.components.Notice
import au.org.regeneratus.augury.ui.components.NoticeTone
import au.org.regeneratus.augury.ui.components.PrimaryButton
import au.org.regeneratus.augury.ui.components.ProgressBar
import au.org.regeneratus.augury.ui.components.SectionLabel
import au.org.regeneratus.augury.ui.components.formatBytes
import au.org.regeneratus.augury.ui.theme.AuguryDesign

/**
 * 6 · SETTINGS — storage, versions, and the compatibility gate.
 *
 * Every value on this screen is read from the manifest at runtime: vector count,
 * species count, band thresholds, protocol identifiers. That is not decoration —
 * it is how "never hard-code a threshold, species count, dimension or version"
 * (hard constraint 1) is *demonstrated*, since a stale constant here would be
 * visible to the user.
 *
 * The **app update required** branch is the important one. If the manifest
 * declares a protocol or schema this build cannot execute, the shell must refuse
 * rather than run a mismatched encoder and return plausible garbage
 * (`docs/mobile-app-decision.md` §3.3). Saying "update required" is a feature.
 */
@Composable
fun SettingsScreen(state: AuguryUiState, vm: AuguryViewModel) {
    val c = AuguryDesign.colors
    val manifest = state.manifest
    val setup = state.setup

    ScreenScaffold(
        title = "Settings",
        subtitle = "Everything downloaded is listed here",
        onBack = { vm.back() },
        footer = {
            PrimaryButton(
                text = "Check for updates",
                onClick = { vm.refreshManifest() },
            )
        },
    ) {
        // ── the protocol gate ──
        if (state.updateRequired) {
            AuguryCard(background = c.amberSoft, borderColor = c.amber.copy(alpha = 0.4f)) {
                SectionLabel("App update required")
                Spacer(Modifier.height(8.dp))
                Text(
                    "The published model data needs a newer version of AUGURY. This " +
                        "build understands a different format, so it will not run the " +
                        "model rather than risk giving you a confident wrong answer.",
                    fontSize = 12.5.sp,
                    lineHeight = 19.sp,
                    color = c.amberInk,
                )
                if (manifest != null) {
                    Spacer(Modifier.height(8.dp))
                    Text(
                        "This build supports: ${manifest.let { it.formatterProtocol }}, " +
                            "${manifest.visionProtocol}, ${manifest.factsProtocol}",
                        fontSize = 10.5.sp,
                        lineHeight = 15.sp,
                        color = c.amberInk,
                        fontStyle = FontStyle.Italic,
                    )
                }
            }
        }

        if (state.manifestError != null && manifest == null) {
            Notice(state.manifestError, NoticeTone.CAUTION)
        }

        // ── what is on the phone ──
        AuguryCard {
            SectionLabel(
                text = "On this phone",
                trailing = if (setup?.allReady == true) "complete" else null,
            )
            Spacer(Modifier.height(10.dp))
            val artifacts: List<ArtifactInfo> = setup?.artifacts ?: emptyList()
            if (artifacts.isEmpty()) {
                Text(
                    "Nothing downloaded yet.",
                    fontSize = 12.5.sp,
                    color = c.inkMuted,
                )
            } else {
                Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    artifacts.forEach { InstalledRow(it) }
                }
            }
        }

        if (setup != null && setup.hasWork) {
            AuguryCard {
                SectionLabel("Incomplete", trailing = "${(setup.overallProgress * 100).toInt()}%")
                Spacer(Modifier.height(9.dp))
                ProgressBar(setup.overallProgress, height = 6)
                Spacer(Modifier.height(8.dp))
                Text(
                    "${formatBytes(setup.bytesDone)} of ${formatBytes(setup.totalBytes)} " +
                        "downloaded. Identification from a photo needs the image " +
                        "recogniser and the retrieval index; the story writer is only " +
                        "needed for prose, and the app falls back to the deterministic " +
                        "template without it.",
                    fontSize = 11.5.sp,
                    lineHeight = 17.sp,
                    color = c.inkMuted,
                )
            }
        }

        // ── connection preference ──
        AuguryCard {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(
                        "Wi-Fi only",
                        fontSize = 13.5.sp,
                        fontWeight = FontWeight.SemiBold,
                        color = c.ink,
                    )
                    Text(
                        "For downloads and updates",
                        fontSize = 11.sp,
                        color = c.inkMuted,
                    )
                }
                AugurySwitch(
                    checked = setup?.wifiOnly ?: true,
                    onCheckedChange = { vm.setWifiOnly(it) },
                )
            }
        }

        // ── model + protocol versions ──
        if (manifest != null) {
            AuguryCard {
                SectionLabel("Model data")
                Spacer(Modifier.height(8.dp))
                InfoRow("Retrieval index", "${"%,d".format(manifest.vectors)} vectors · ${manifest.dim}-d · ${manifest.indexSpecies} species")
                InfoRow("Encoder", "${manifest.backend} · ${manifest.encoderQuant}")
                InfoRow("Species", "${"%,d".format(manifest.speciesCount)} across ${manifest.regions.size} regions")
                InfoRow("Confidence bands", "auto ${"%.2f".format(manifest.autoConf)} · confirm ${"%.2f".format(manifest.confirmConf)}")
                InfoRow("Protocols", "${manifest.visionProtocol}, ${manifest.formatterProtocol}")
                InfoRow("Manifest", "schema ${manifest.manifestSchema} · gen ${manifest.generation.take(12)}")
            }
        }

        // ── the app itself ──
        AuguryCard {
            SectionLabel("App")
            Spacer(Modifier.height(8.dp))
            Text(
                "AUGURY bundles no model data. The species database, retrieval index, " +
                    "image recogniser and story writer are all downloaded and verified " +
                    "against a signed manifest, so adding species or recalibrating " +
                    "confidence is a data change — not a new install.",
                fontSize = 11.5.sp,
                lineHeight = 17.sp,
                color = c.inkMuted,
            )
            Spacer(Modifier.height(10.dp))
            Text(
                "Anything that changes the *shape* of that data — a new encoder " +
                    "contract, a different scoring scheme — does need a new build, and " +
                    "this screen will say so.",
                fontSize = 11.5.sp,
                lineHeight = 17.sp,
                color = c.inkMuted,
            )
        }
    }
}

/** One installed artifact: badge, name, and the version facts that identify it. */
@Composable
private fun InstalledRow(a: ArtifactInfo) {
    val c = AuguryDesign.colors
    val (icon, statusGlyph, statusColor) = when (a.status) {
        ArtifactStatus.READY -> Triple("📦", "✓", c.sage)
        ArtifactStatus.DOWNLOADING -> Triple("📦", "…", c.inkMuted)
        ArtifactStatus.VERIFYING -> Triple("📦", "…", c.inkMuted)
        ArtifactStatus.FAILED -> Triple("📦", "!", c.amber)
        ArtifactStatus.STALE -> Triple("📦", "↑", c.amber)
        ArtifactStatus.MISSING -> Triple("📦", "—", c.inkMuted)
    }
    val iconFor = when (a.name) {
        "formatter" -> "🧠"
        "encoder" -> "👁️"
        "index" -> "🗂️"
        "facts" -> "📖"
        else -> icon
    }

    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Box(
            Modifier
                .size(30.dp)
                .clip(RoundedCornerShape(10.dp))
                .background(if (a.isReady) c.sageSoft else c.greySoft),
            contentAlignment = Alignment.Center,
        ) { Text(iconFor, fontSize = 13.sp) }
        Spacer(Modifier.width(11.dp))
        Column(Modifier.weight(1f)) {
            Text(
                a.title,
                fontSize = 13.sp,
                fontWeight = FontWeight.SemiBold,
                color = c.ink,
            )
            Text(
                a.subtitle,
                fontSize = 11.sp,
                lineHeight = 15.sp,
                color = c.inkMuted,
            )
            Text(
                "${formatBytes(a.bytes)} · ${a.sha256.take(12)}",
                fontSize = 10.sp,
                color = c.inkMuted,
            )
        }
        Text(
            statusGlyph,
            fontSize = 14.sp,
            fontWeight = FontWeight.Bold,
            color = statusColor,
        )
    }
}

@Composable
private fun InfoRow(label: String, value: String) {
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
            modifier = Modifier.width(112.dp),
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

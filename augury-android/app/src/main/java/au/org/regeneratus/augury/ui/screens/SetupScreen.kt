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
import au.org.regeneratus.augury.ui.components.ProgressCaption
import au.org.regeneratus.augury.ui.components.SecondaryButton
import au.org.regeneratus.augury.ui.components.SectionLabel
import au.org.regeneratus.augury.ui.components.formatBytes
import au.org.regeneratus.augury.ui.components.formatRate
import au.org.regeneratus.augury.ui.theme.AuguryDesign

/**
 * 1 · SETUP — first launch, and the "update available" path.
 *
 * The whole product decision is visible here: the app ships no model data, so the
 * first run is a ~1.06 GB download. Two things make that acceptable rather than
 * hostile, and both are on this screen:
 *
 *  - **Per-artifact honesty.** The user sees four named things arriving, with
 *    their real byte counts read from the manifest, not one anonymous bar.
 *  - **It is interruptible.** Wi-Fi-only is on by default, the download survives
 *    being backgrounded, and a partial file is never promoted to current.
 *
 * The size warning is shown *before* the download starts, not discovered by a
 * user on a metered connection.
 */
@Composable
fun SetupScreen(state: AuguryUiState, vm: AuguryViewModel) {
    val c = AuguryDesign.colors
    val setup = state.setup

    ScreenScaffold(
        title = "Getting AUGURY ready",
        subtitle = if (setup?.allReady == true) {
            "Everything is downloaded"
        } else {
            "One-time download · do it on Wi-Fi"
        },
        onBack = if (setup?.allReady == true) ({ vm.go(Screen.HOME) }) else null,
        footer = {
            if (setup == null) {
                PrimaryButton("Checking…", onClick = {}, enabled = false)
            } else if (setup.allReady) {
                PrimaryButton("Start identifying", onClick = { vm.go(Screen.HOME) })
            } else {
                if (setup.blockedByMeteredConnection) {
                    Notice(
                        "You are on mobile data. Turn off Wi-Fi-only to continue now, " +
                            "or wait until you are on Wi-Fi.",
                        tone = NoticeTone.CAUTION,
                    )
                }
                PrimaryButton(
                    text = if (setup.busy) "Downloading… (keep the app open)" else "Continue",
                    onClick = { vm.startDownload() },
                    enabled = !setup.busy && !setup.blockedByMeteredConnection,
                )
                SecondaryButton(
                    text = if (setup.busy) "Pause" else "Download on mobile data",
                    onClick = {
                        if (setup.busy) {
                            vm.cancelDownload()
                        } else {
                            vm.setWifiOnly(false)
                            vm.startDownload()
                        }
                    },
                )
            }
        },
    ) {
        AuguryCard {
            SectionLabel(
                text = if (setup?.allReady == true) "On this phone" else "Downloading",
            )
            Spacer(Modifier.height(10.dp))

            val artifacts: List<ArtifactInfo> = setup?.artifacts ?: emptyList()
            if (artifacts.isEmpty()) {
                Text(
                    "Contacting the update server…",
                    fontSize = 13.sp,
                    color = c.inkMuted,
                )
            } else {
                Column(verticalArrangement = Arrangement.spacedBy(13.dp)) {
                    artifacts.forEach { ArtifactRow(it) }
                }
            }
        }

        val bytes = setup?.totalBytes ?: 0L
        if (bytes > 0L) {
            Notice(
                "About ${formatBytes(bytes)} in total. Nothing leaves your phone: no " +
                    "account, no upload, no server. You can pause and finish later — " +
                    "it resumes where it stopped.",
                tone = NoticeTone.NEUTRAL,
            )
        }

        AuguryCard {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(
                        "Download over Wi-Fi only",
                        fontSize = 13.5.sp,
                        fontWeight = FontWeight.SemiBold,
                        color = c.ink,
                    )
                    Text(
                        "Recommended — this is the large part",
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

        if (setup != null && setup.hasWork) {
            AuguryCard {
                SectionLabel("Overall", trailing = "${(setup.overallProgress * 100).toInt()}%")
                Spacer(Modifier.height(9.dp))
                ProgressBar(setup.overallProgress, height = 6)
                ProgressCaption(
                    left = "${formatBytes(setup.bytesDone)} of ${formatBytes(setup.totalBytes)}",
                    right = if (setup.busy) "in progress" else "not started",
                )
            }
        }
    }
}

/** One artifact: name, state, bar, and the byte-level caption. */
@Composable
private fun ArtifactRow(a: ArtifactInfo) {
    val c = AuguryDesign.colors
    Column(Modifier.fillMaxWidth()) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                a.title,
                fontSize = 12.5.sp,
                fontWeight = FontWeight.SemiBold,
                color = c.ink,
                modifier = Modifier.weight(1f),
            )
            StatusChip(a.status)
        }
        Spacer(Modifier.height(6.dp))
        ProgressBar(
            progress = when (a.status) {
                ArtifactStatus.READY -> 1f
                else -> a.progress
            },
            tint = if (a.status == ArtifactStatus.MISSING) c.line else c.sage,
        )
        ProgressCaption(
            left = when {
                a.status == ArtifactStatus.READY -> formatBytes(a.bytes)
                a.progress > 0f -> "${formatBytes(a.bytesDone)} of ${formatBytes(a.bytes)}"
                else -> formatBytes(a.bytes)
            },
            right = when (a.status) {
                ArtifactStatus.READY -> "✓ done"
                ArtifactStatus.VERIFYING -> "checking…"
                ArtifactStatus.DOWNLOADING ->
                    "${(a.progress * 100).toInt()}% · ${formatRate(a.bytesPerSecond)}"
                ArtifactStatus.FAILED -> "failed — tap to retry"
                ArtifactStatus.STALE -> "update available"
                ArtifactStatus.MISSING -> "queued"
            },
            rightColor = if (a.status == ArtifactStatus.READY) c.sage else null,
        )
        Spacer(Modifier.height(2.dp))
        Text(
            a.subtitle,
            fontSize = 10.5.sp,
            color = c.inkMuted,
        )
    }
}

@Composable
private fun StatusChip(status: ArtifactStatus) {
    val c = AuguryDesign.colors
    val (bg, fg, label) = when (status) {
        ArtifactStatus.READY -> Triple(c.sageSoft, c.sage, "ready")
        ArtifactStatus.DOWNLOADING -> Triple(c.sageSoft, c.sage, "downloading")
        ArtifactStatus.VERIFYING -> Triple(c.sageSoft, c.sage, "verifying")
        ArtifactStatus.MISSING -> Triple(c.greySoft, c.inkMuted, "queued")
        ArtifactStatus.FAILED -> Triple(c.amberSoft, c.amber, "failed")
        ArtifactStatus.STALE -> Triple(c.amberSoft, c.amber, "update")
    }
    Box(
        Modifier
            .clip(RoundedCornerShape(9.dp))
            .background(bg)
            .padding(horizontal = 8.dp, vertical = 2.dp),
    ) {
        Text(label, fontSize = 10.sp, fontWeight = FontWeight.Bold, color = fg)
    }
}

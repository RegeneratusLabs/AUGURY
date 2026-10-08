package au.org.regeneratus.augury.ui.screens

import android.content.Context
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
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
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.FileProvider
import au.org.regeneratus.augury.ui.AuguryUiState
import au.org.regeneratus.augury.ui.AuguryViewModel
import au.org.regeneratus.augury.ui.PhotoCandidate
import au.org.regeneratus.augury.ui.Screen
import au.org.regeneratus.augury.ui.ScreenScaffold
import au.org.regeneratus.augury.ui.components.AuguryCard
import au.org.regeneratus.augury.ui.components.BandPill
import au.org.regeneratus.augury.ui.components.Notice
import au.org.regeneratus.augury.ui.components.NoticeTone
import au.org.regeneratus.augury.ui.components.PrimaryButton
import au.org.regeneratus.augury.ui.components.SecondaryButton
import au.org.regeneratus.augury.ui.components.SectionLabel
import au.org.regeneratus.augury.ui.theme.AuguryDesign
import java.io.File

/**
 * 3 · PHOTO — capture, then **always** confirm.
 *
 * This screen is where the project's strongest product rule is enforced: *never
 * silently accept a species from a photo*. Retrieval top-1 is 85.9%, and the
 * failure mode is not a crash or an empty result — it is a **confidently
 * formatted story about the wrong plant** (blind spot #2 in
 * `docs/model-understanding-and-blindspots.md`). So:
 *
 *  - the top candidate is presented as a question ("Is this your plant?"), never
 *    as an answer;
 *  - the next two candidates are always shown, with their scores, so a user who
 *    knows the plant can correct the app in one tap;
 *  - the band label distinguishes *more* from *less* sure, and `auto` is spelled
 *    "High confidence" — never "safe", never "accepted";
 *  - the story is only composed after a tap on this screen.
 */
@Composable
fun PhotoScreen(state: AuguryUiState, vm: AuguryViewModel) {
    val c = AuguryDesign.colors
    val context = LocalContext.current
    var pendingCapture by remember { mutableStateOf<File?>(null) }

    // Camera: write into our own files dir via FileProvider, so the system camera
    // app needs no storage permission from us (and we declare none).
    val cameraLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.TakePicture(),
    ) { success ->
        val file = pendingCapture
        pendingCapture = null
        if (success && file != null && file.length() > 0) {
            vm.onPhotoPicked(file.readBytes())
        }
    }

    val galleryLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.PickVisualMedia(),
    ) { uri: Uri? ->
        if (uri != null) {
            // Read through the content resolver: the picked URI may be a cloud
            // provider with no filesystem path at all.
            val bytes = runCatching {
                context.contentResolver.openInputStream(uri)?.use { it.readBytes() }
            }.getOrNull()
            if (bytes != null && bytes.isNotEmpty()) vm.onPhotoPicked(bytes)
        }
    }

    val launchCamera: () -> Unit = {
        runCatching {
            val file = newCaptureFile(context)
            val uri = FileProvider.getUriForFile(
                context,
                "${context.packageName}.fileprovider",
                file,
            )
            pendingCapture = file
            cameraLauncher.launch(uri)
        }
        Unit
    }

    val top = state.photoCandidates.firstOrNull()
    val others = state.photoCandidates.drop(1)

    ScreenScaffold(
        title = if (top == null) "Identify from a photo" else "Is this your plant?",
        subtitle = if (top == null) {
            "Works best in daylight, filling the frame"
        } else {
            "Best match first · top ${state.photoCandidates.size} shown"
        },
        onBack = { vm.back() },
        footer = {
            if (top != null) {
                PrimaryButton(
                    text = "Yes, this is it — show my soil",
                    onClick = { vm.openStory(top.key) },
                )
                SecondaryButton(
                    text = "📷  Take another photo",
                    // Back to a clean capture screen. Without this the confirm
                    // card had no way to retake a bad shot: it offers only the
                    // three matches and a search.
                    onClick = { vm.startPhoto() },
                )
                SecondaryButton(
                    text = "None of these — search by name",
                    onClick = { vm.go(Screen.PICKER) },
                )
            } else {
                PrimaryButton(
                    text = "📷  Take photo",
                    onClick = launchCamera,
                    enabled = !state.identifying,
                )
                SecondaryButton(
                    text = "Choose from gallery",
                    onClick = {
                        galleryLauncher.launch(
                            PickVisualMediaRequest(
                                ActivityResultContracts.PickVisualMedia.ImageOnly,
                            ),
                        )
                    },
                    enabled = !state.identifying,
                )
            }
        },
    ) {
        when {
            state.identifying -> IdentifyingCard()

            // The path could not RUN. Say which part is missing rather than
            // showing the "no reliable match" copy, which would imply the photo
            // was compared and lost.
            state.photoUnavailable != null -> {
                Notice(state.photoUnavailable, tone = NoticeTone.CAUTION)
                AuguryCard {
                    SectionLabel("What to try")
                    Spacer(Modifier.height(8.dp))
                    Tip("⬇️", "Finish the download on the Setup screen, then try again")
                    Tip("🔎", "Or search the plant by name — that path needs no model")
                }
            }

            state.photoEmpty -> {
                Notice(
                    "No reliable match. The best score was below the confirm line, so " +
                        "AUGURY will not guess.",
                    tone = NoticeTone.NEUTRAL,
                )
                AuguryCard {
                    SectionLabel("Try this instead")
                    Spacer(Modifier.height(8.dp))
                    Tip("💡", "Get closer — fill the frame with one leaf and a flower")
                    Tip("☀️", "Shoot in daylight, avoid deep shadow")
                    Tip("🌿", "Photograph the whole plant, not one leaf")
                    Tip("🔎", "Or just search the name you already know")
                }
            }

            top == null -> {
                AuguryCard {
                    SectionLabel("What works")
                    Spacer(Modifier.height(8.dp))
                    Text(
                        "AUGURY compares your photo against a reference collection of " +
                            "Australian weeds and reports the closest matches. It always " +
                            "shows three and always asks you to confirm — a wrong " +
                            "identification would otherwise produce a confident story " +
                            "about the wrong plant.",
                        fontSize = 12.5.sp,
                        lineHeight = 19.sp,
                        color = c.ink,
                    )
                }
                Notice(
                    "Nothing is uploaded. The photo is read on your phone and discarded.",
                    tone = NoticeTone.POSITIVE,
                )
            }

            else -> {
                // ── the confirm card ──
                AuguryCard(
                    background = c.sageSoft,
                    borderColor = c.sage.copy(alpha = 0.35f),
                ) {
                    Column {
                        SectionLabel("Best match", trailing = "confirm to continue")
                        Spacer(Modifier.height(10.dp))
                        CandidateHeadline(top)
                        Spacer(Modifier.height(10.dp))
                        BandPill(top.band, top.score)
                    }
                }

                if (others.isNotEmpty()) {
                    AuguryCard {
                        SectionLabel("Or one of these")
                        Spacer(Modifier.height(6.dp))
                        others.forEachIndexed { i, cand ->
                            AlternativeRow(
                                candidate = cand,
                                showDivider = i < others.lastIndex,
                                onClick = { vm.openStory(cand.key) },
                            )
                        }
                    }
                }

                Notice(
                    "Look-alikes are common at the seedling stage. If none of these is " +
                        "right, search by name — the list covers every species with soil " +
                        "data.",
                    tone = NoticeTone.NEUTRAL,
                )
            }
        }
    }
}

/** The big "Dandelion / Taraxacum officinale" block on the confirm card. */
@Composable
private fun CandidateHeadline(candidate: PhotoCandidate) {
    val c = AuguryDesign.colors
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(
            Modifier
                .size(46.dp)
                .clip(RoundedCornerShape(13.dp))
                .background(c.surface),
            contentAlignment = Alignment.Center,
        ) {
            Text("🌿", fontSize = 21.sp)
        }
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(
                candidate.displayName,
                fontSize = 16.5.sp,
                fontWeight = FontWeight.Bold,
                color = c.ink,
                lineHeight = 21.sp,
            )
            // When the database carries no vernacular name the common name IS the
            // binomial, and printing it twice reads like a bug.
            if (!candidate.scientificName.equals(candidate.displayName, ignoreCase = true)) {
                Text(
                    candidate.scientificName,
                    fontSize = 12.sp,
                    color = c.inkMuted,
                    fontStyle = FontStyle.Italic,
                )
            }
        }
    }
}

/** A runner-up: tappable, because tapping it is how the user corrects the app. */
@Composable
private fun AlternativeRow(
    candidate: PhotoCandidate,
    showDivider: Boolean,
    onClick: () -> Unit,
) {
    val c = AuguryDesign.colors
    Column {
        Row(
            Modifier
                .fillMaxWidth()
                .clickable(onClick = onClick)
                .padding(horizontal = 12.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                Modifier
                    .size(30.dp)
                    .clip(RoundedCornerShape(10.dp))
                    .background(c.greySoft),
                contentAlignment = Alignment.Center,
            ) {
                Text("🌿", fontSize = 13.sp)
            }
            Spacer(Modifier.width(11.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    candidate.displayName,
                    fontSize = 13.5.sp,
                    fontWeight = FontWeight.SemiBold,
                    color = c.ink,
                )
                if (!candidate.scientificName.equals(candidate.displayName, ignoreCase = true)) {
                    Text(
                        candidate.scientificName,
                        fontSize = 11.5.sp,
                        color = c.inkMuted,
                        fontStyle = FontStyle.Italic,
                    )
                }
            }
            Box(
                Modifier
                    .clip(RoundedCornerShape(9.dp))
                    .background(c.greySoft)
                    .padding(horizontal = 8.dp, vertical = 3.dp),
            ) {
                Text(
                    "%.2f".format(candidate.score),
                    fontSize = 11.sp,
                    fontWeight = FontWeight.Bold,
                    color = c.inkMuted,
                )
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
private fun IdentifyingCard() {
    val c = AuguryDesign.colors
    AuguryCard {
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(
                "Reading the photo…",
                fontSize = 14.sp,
                fontWeight = FontWeight.SemiBold,
                color = c.ink,
            )
            Text(
                "Encoding the image and comparing it with the reference collection. " +
                    "This runs entirely on your phone.",
                fontSize = 12.sp,
                lineHeight = 17.sp,
                color = c.inkMuted,
            )
            repeat(3) {
                Box(
                    Modifier
                        .fillMaxWidth()
                        .height(30.dp)
                        .clip(RoundedCornerShape(9.dp))
                        .background(c.surfaceMuted),
                )
            }
        }
    }
}

@Composable
private fun Tip(icon: String, text: String) {
    val c = AuguryDesign.colors
    Row(
        Modifier
            .fillMaxWidth()
            .padding(vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            Modifier
                .size(28.dp)
                .clip(RoundedCornerShape(9.dp))
                .background(c.sageSoft),
            contentAlignment = Alignment.Center,
        ) { Text(icon, fontSize = 13.sp) }
        Spacer(Modifier.width(10.dp))
        Text(text, fontSize = 12.5.sp, lineHeight = 18.sp, color = c.ink)
    }
}

/**
 * A capture target inside the app's private `files/captures` directory — the path
 * declared in `res/xml/file_paths.xml`, which is what lets the camera app write
 * there without any storage permission.
 */
private fun newCaptureFile(context: Context): File {
    val dir = File(context.filesDir, "captures").apply { mkdirs() }
    return File(dir, "capture_${System.currentTimeMillis()}.jpg")
}

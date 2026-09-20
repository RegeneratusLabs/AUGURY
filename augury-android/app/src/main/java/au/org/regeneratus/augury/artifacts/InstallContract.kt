package au.org.regeneratus.augury.artifacts

import java.nio.file.Path

/**
 * AUGURY — the install contract shared by the pipeline and the Setup screen.
 *
 * The Setup screen needs to render four things without knowing anything about
 * HTTP, tar or SHA-256: how big the download is, how far along it is, what
 * failed, and whether the user has to install a new APK. These types carry
 * exactly that, plus [ArtifactProgressListener], the callback the pipeline
 * drives.
 *
 * (A `kotlinx.coroutines.Flow` adapter would be a thin wrapper over
 * [ArtifactProgressListener]; it is not declared here because the app's Gradle
 * file — owned by another workstream — does not declare a coroutines
 * dependency, and this task forbids editing it. See the report.)
 */
data class InstallOptions(
    /** Refuse to move artifact bytes over a metered connection. */
    val wifiOnly: Boolean = true,
    /** The user's explicit "download over mobile data anyway" override. */
    val allowMetered: Boolean = false,
    /** Skip artifacts already installed at the manifest's generation. */
    val skipAlreadyInstalled: Boolean = true,
    /**
     * Re-hash an already-installed single-file artifact before trusting it.
     * Off by default: re-reading 688 MB on every launch is not free, and the
     * artifact was hashed when it was installed. Has no effect on unpacked
     * artifacts, whose recorded digest covers the tarball, not the tree.
     */
    val rehashInstalled: Boolean = false,
)

/** One artifact, resolved to the directory that may load it. */
data class InstalledArtifact(
    val artifact: ManifestArtifact,
    val generation: String,
    val directory: Path,
    /** True when nothing was downloaded — the generation was already verified and on disk. */
    val skipped: Boolean,
    /** Bytes transferred during this run (excludes a resumed prefix that was already on disk). */
    val bytesDownloaded: Long,
)

data class InstallPlanEntry(
    val artifact: ManifestArtifact,
    /** True when this exact generation is already verified and complete on disk. */
    val installed: Boolean,
    val installedGeneration: String?,
)

/**
 * What this manifest would cost. Rendered as "1.06 GB — 4 items" before the user
 * commits, and used to decide whether the metered-connection rule applies.
 */
data class InstallPlan(
    val manifestGeneration: String,
    val entries: List<InstallPlanEntry>,
) {
    val toDownload: List<InstallPlanEntry> get() = entries.filter { !it.installed }
    val bytesToDownload: Long get() = toDownload.sumOf { it.artifact.spec.bytes }
    val bytesTotal: Long get() = entries.sumOf { it.artifact.spec.bytes }
    val isComplete: Boolean get() = toDownload.isEmpty()
}

data class InstallResult(
    val manifestGeneration: String,
    val artifacts: List<InstalledArtifact>,
    /** Bytes actually transferred (resumed prefixes are not counted twice). */
    val bytesDownloaded: Long,
    val elapsedMillis: Long,
) {
    val downloaded: List<InstalledArtifact> get() = artifacts.filter { !it.skipped }
    val skipped: List<InstalledArtifact> get() = artifacts.filter { it.skipped }
}

/**
 * Progress callbacks. Every method has a default no-op body, so a caller (or a
 * test) implements only what it renders. All callbacks happen on the thread that
 * called [ArtifactManager.install]; the Setup screen is responsible for hopping
 * to the main thread.
 */
interface ArtifactProgressListener {

    fun onManifestFetched(manifest: ArtifactManifest) {}

    fun onPlanResolved(plan: InstallPlan) {}

    fun onArtifactStarted(artifact: ManifestArtifact, resumeFromBytes: Long, totalBytes: Long) {}

    fun onArtifactProgress(
        artifact: ManifestArtifact,
        bytesDownloaded: Long,
        totalBytes: Long,
        bytesPerSecond: Double,
    ) {
    }

    /** SHA-256 of the completed download matched the manifest. Promotion comes next. */
    fun onArtifactVerified(artifact: ManifestArtifact, sha256: String) {}

    fun onArtifactInstalled(artifact: ManifestArtifact, generation: String, directory: Path, skipped: Boolean) {}

    fun onArtifactFailed(artifact: ManifestArtifact, error: Throwable) {}

    /** Aggregate across the whole plan: `bytesDownloaded / plan.bytesToDownload`. */
    fun onOverallProgress(downloadedBytes: Long, totalDownloadBytes: Long, bytesPerSecond: Double) {}

    fun onFinished(result: InstallResult) {}

    companion object {
        val NONE: ArtifactProgressListener = object : ArtifactProgressListener {}
    }
}

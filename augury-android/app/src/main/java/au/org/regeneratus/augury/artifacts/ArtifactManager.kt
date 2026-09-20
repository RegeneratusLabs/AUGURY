package au.org.regeneratus.augury.artifacts

import java.io.ByteArrayOutputStream
import java.io.InputStream
import java.nio.file.AtomicMoveNotSupportedException
import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.StandardCopyOption

/**
 * AUGURY — the artifact pipeline, end to end.
 *
 * ```kotlin
 * val manager = ArtifactManager(
 *     store = GenerationStore(ArtifactPaths.artifactsRoot(context.filesDir)),
 *     transport = JavaHttpTransport(),
 *     network = AndroidNetworkStatus(context),
 * )
 * val manifest = manager.fetchManifest()              // verified against its own digest
 * when (val verdict = manager.compatibility(manifest)) {
 *     is CompatibilityVerdict.UpdateRequired -> show("this app update is required")
 *     CompatibilityVerdict.Compatible -> manager.install(manifest, listener = setupScreen)
 * }
 * ```
 *
 * THE ORDER OF OPERATIONS IS THE SECURITY PROPERTY
 * -----------------------------------------------
 * For every artifact, without exception:
 *
 * 1. download into `staging/` (resuming from whatever is there);
 * 2. check the completed file's length against the manifest's `bytes`;
 * 3. check its SHA-256 against the manifest's `sha256` — on mismatch the file is
 *    **deleted** and [ArtifactVerificationException] is thrown;
 * 4. only now place the payload in `files/artifacts/<name>/<generation>/`;
 * 5. write `artifact.json` — the completion record;
 * 6. only now flip `current` (atomically, via [GenerationStore.promote]).
 *
 * Steps 4–6 are unreachable from any failure path, so "a truncated or
 * hash-mismatched artifact must never load, and a partial download must never be
 * promoted to current" (§8 item 6) is enforced by control flow rather than by
 * discipline. [ProtocolGate] runs before step 1, so a manifest this shell cannot
 * execute moves zero bytes.
 */
class ArtifactManager(
    private val store: GenerationStore,
    private val transport: HttpTransport,
    private val network: NetworkStatus = NetworkStatus.ALWAYS_ONLINE,
    private val capabilities: ShellCapabilities = ShellCapabilities.CURRENT,
    private val unpacker: IndexUnpacker = IndexUnpacker(),
    private val timeSource: () -> Long = { System.nanoTime() },
    private val downloader: ResumableDownloader = ResumableDownloader(transport, timeSource = timeSource),
    private val maxManifestBytes: Long = MAX_MANIFEST_BYTES,
) {

    // ── manifest ────────────────────────────────────────────────────────────

    /**
     * Fetches, parses and digest-verifies the manifest.
     *
     * `Cache-Control: no-cache` is sent deliberately: the manifest is the update
     * lever, and a cached copy could keep the app pinned to a superseded
     * generation. The response is capped at [maxManifestBytes] — a manifest is
     * ~2 KB; anything larger is not one.
     */
    fun fetchManifest(
        source: ManifestSource = ManifestSource(),
        cancel: CancellationToken = CancellationToken.NONE,
        listener: ArtifactProgressListener = ArtifactProgressListener.NONE,
    ): ArtifactManifest {
        if (!network.isOnline()) {
            throw OfflineException("no network connection; cannot fetch ${source.url}")
        }
        val manifest = transport.execute(
            HttpRequest(
                source.url,
                mapOf("Cache-Control" to "no-cache", "Pragma" to "no-cache"),
            )
        ).use { response ->
            if (response.statusCode != HTTP_OK) {
                throw ManifestFetchException("HTTP ${response.statusCode} fetching ${source.url}")
            }
            val declared = response.contentLength()
            if (declared != null && declared > maxManifestBytes) {
                throw ManifestFetchException(
                    "manifest at ${source.url} declares $declared bytes, above the $maxManifestBytes byte limit"
                )
            }
            val bytes = readCapped(response.body, maxManifestBytes, source.url, cancel)
            ManifestParser.parse(bytes)
        }
        listener.onManifestFetched(manifest)
        return manifest
    }

    // ── gate and plan ───────────────────────────────────────────────────────

    /** The §3.3 compatibility gate. `UpdateRequired` must be shown as "app update required". */
    fun compatibility(manifest: ArtifactManifest): CompatibilityVerdict =
        ProtocolGate.check(manifest, capabilities)

    /** What would be downloaded, and what is already installed. Makes no network calls. */
    fun plan(manifest: ArtifactManifest): InstallPlan {
        val entries = manifest.artifacts().map { artifact ->
            // Ask about the generation THIS manifest names, not about whatever is
            // currently pointed at: a publisher rollback repoints the manifest at
            // a generation we already hold, and that must cost zero bytes.
            val generation = artifact.spec.generation
            val directory = store.generationDir(artifact.name, generation)
            val record = store.record(artifact.name, generation)
            val installed = record != null && record.matches(artifact) && record.payloadPresent(directory)
            InstallPlanEntry(artifact, installed, if (installed) generation else null)
        }
        return InstallPlan(manifest.generation, entries)
    }

    // ── install ─────────────────────────────────────────────────────────────

    /**
     * Downloads, verifies and promotes every artifact in [manifest].
     *
     * @throws AppUpdateRequiredException when the gate rejects the manifest — nothing is downloaded.
     * @throws OfflineException when a download is needed and there is no network.
     * @throws MeteredConnectionException when Wi-Fi-only is on and the link is metered.
     * @throws ArtifactVerificationException when a completed download fails SHA-256; the artifact is discarded.
     */
    fun install(
        manifest: ArtifactManifest,
        source: ManifestSource = ManifestSource(),
        options: InstallOptions = InstallOptions(),
        listener: ArtifactProgressListener = ArtifactProgressListener.NONE,
        cancel: CancellationToken = CancellationToken.NONE,
    ): InstallResult {
        val verdict = compatibility(manifest)
        if (verdict is CompatibilityVerdict.UpdateRequired) throw verdict.toException()

        val plan = plan(manifest)
        listener.onPlanResolved(plan)

        if (!plan.isComplete) {
            if (!network.isOnline()) {
                throw OfflineException("no network connection; ${plan.bytesToDownload} bytes still to download")
            }
            // The manifest itself is fetched before this check (it is ~2 KB and the
            // user must be able to see what is on offer); the ~1 GB payload is not.
            if (options.wifiOnly && !options.allowMetered && network.isMetered()) {
                throw MeteredConnectionException()
            }
        }

        val startedAt = timeSource()
        var completedBytes = 0L
        var downloadedBytes = 0L
        val installed = ArrayList<InstalledArtifact>(plan.entries.size)

        for (entry in plan.entries) {
            val artifact = entry.artifact
            try {
                val progressSink: (DownloadProgress) -> Unit = { progress ->
                    listener.onArtifactProgress(
                        artifact, progress.bytesDownloaded, progress.totalBytes, progress.bytesPerSecond,
                    )
                    val overall = completedBytes + progress.bytesDownloaded
                    listener.onOverallProgress(overall, plan.bytesToDownload, rate(overall, startedAt))
                }
                val result = installOne(artifact, entry.installed, source, options, progressSink, cancel, listener)
                installed += result
                completedBytes += artifact.spec.bytes
                downloadedBytes += result.bytesDownloaded
            } catch (e: Throwable) {
                listener.onArtifactFailed(artifact, e)
                throw e
            }
        }

        val result = InstallResult(
            manifestGeneration = manifest.generation,
            artifacts = installed,
            bytesDownloaded = downloadedBytes,
            elapsedMillis = (timeSource() - startedAt) / 1_000_000L,
        )
        listener.onFinished(result)
        return result
    }

    /**
     * Installs one artifact. The target generation directory is not touched until
     * the staged bytes have passed verification, so a failure anywhere leaves the
     * previously installed generation intact and loadable.
     */
    private fun installOne(
        artifact: ManifestArtifact,
        alreadyInstalled: Boolean,
        source: ManifestSource,
        options: InstallOptions,
        onProgress: (DownloadProgress) -> Unit,
        cancel: CancellationToken,
        listener: ArtifactProgressListener,
    ): InstalledArtifact {
        val spec = artifact.spec
        val name = artifact.name
        val generation = spec.generation
        val targetDir = store.generationDir(name, generation)

        if (alreadyInstalled && options.skipAlreadyInstalled) {
            val record = store.record(name, generation)
            // `rehashInstalled` re-reads the payload on disk; a failure here falls
            // through to a fresh download rather than to a load.
            val trusted = !options.rehashInstalled ||
                (record != null && record.payloadPresent(targetDir) && verifyPayload(targetDir, artifact, record))
            if (trusted) {
                store.promote(name, generation)
                listener.onArtifactInstalled(artifact, generation, targetDir, skipped = true)
                return InstalledArtifact(artifact, generation, targetDir, skipped = true, bytesDownloaded = 0)
            }
        }

        val part = store.partFile(name, generation)
        val resumeFrom = if (Files.exists(part)) Files.size(part) else 0L
        listener.onArtifactStarted(artifact, resumeFrom, spec.bytes)

        // Each artifact carries its OWN repo kind: the GGUF is a model repo, the
        // rest are dataset repos, and HF resolves them with different prefixes
        // (see HuggingFaceUrls.resolve). Using source.repoType here fetched the
        // formatter from a dataset path that does not exist, so the very first
        // artifact 401'd and the whole install aborted.
        val url = HuggingFaceUrls.resolve(source.baseUrl, spec.repoType, spec.repo, spec.revision, spec.path)
        val report = downloader.download(
            url = url,
            target = part,
            expectedBytes = spec.bytes,
            label = name,
            cancel = cancel,
            onProgress = onProgress,
        )

        // ── verification: the gate that nothing may bypass ──────────────────
        val actual = Sha256.ofFile(part)
        if (!actual.equals(spec.sha256, ignoreCase = true)) {
            Files.deleteIfExists(part)
            throw ArtifactVerificationException(name, spec.sha256, actual)
        }
        listener.onArtifactVerified(artifact, actual)

        // ── placement ───────────────────────────────────────────────────────
        val entries = placePayload(artifact, part, targetDir)

        // ── completion record, then the pointer flip ────────────────────────
        GenerationRecord.write(
            targetDir,
            GenerationRecord(
                name = name,
                generation = generation,
                sha256 = spec.sha256,
                bytes = spec.bytes,
                protocol = spec.protocol,
                repo = spec.repo,
                path = spec.path,
                revision = spec.revision,
                unpack = artifact.unpack,
                entries = entries,
            ),
        )
        store.promote(name, generation)

        Files.deleteIfExists(part)
        store.unpackScratchDir(name, generation).let { scratch ->
            if (Files.exists(scratch)) GenerationStore.deleteRecursively(scratch)
        }

        listener.onArtifactInstalled(artifact, generation, targetDir, skipped = false)
        return InstalledArtifact(
            artifact = artifact,
            generation = generation,
            directory = targetDir,
            skipped = false,
            bytesDownloaded = (report.bytes - report.resumedFromBytes).coerceAtLeast(0),
        )
    }

    /**
     * Moves verified bytes into `files/artifacts/<name>/<generation>/`.
     *
     * For a plain file this is a rename of the verified `.part`. For a `.tar.gz`
     * the archive is unpacked into a scratch directory (which the unpacker deletes
     * on any failure) and the whole tree is then moved into place, so a
     * half-extracted index never appears as a generation.
     *
     * @return the payload entries, relative to [targetDir].
     */
    private fun placePayload(artifact: ManifestArtifact, part: Path, targetDir: Path): List<String> {
        if (artifact.unpack) {
            val scratch = store.unpackScratchDir(artifact.name, artifact.spec.generation)
            if (Files.exists(scratch)) GenerationStore.deleteRecursively(scratch)
            val entries = unpacker.unpack(part, scratch)
            if (Files.exists(targetDir)) GenerationStore.deleteRecursively(targetDir)
            Files.createDirectories(targetDir.parent)
            try {
                Files.move(scratch, targetDir, StandardCopyOption.ATOMIC_MOVE)
            } catch (_: AtomicMoveNotSupportedException) {
                Files.move(scratch, targetDir)
            }
            return entries
        }

        val fileName = artifact.spec.path.substringAfterLast('/').ifEmpty { artifact.name }
        if (Files.exists(targetDir)) GenerationStore.deleteRecursively(targetDir)
        Files.createDirectories(targetDir)
        val payload = targetDir.resolve(fileName)
        try {
            Files.move(part, payload, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING)
        } catch (_: AtomicMoveNotSupportedException) {
            Files.move(part, payload, StandardCopyOption.REPLACE_EXISTING)
        }
        return listOf(fileName)
    }

    /** Hashes an installed plain-file payload against its record. */
    private fun verifyPayload(directory: Path, artifact: ManifestArtifact, record: GenerationRecord): Boolean {
        if (record.unpack || record.entries.size != 1) return record.payloadPresent(directory)
        val file = directory.resolve(record.entries[0])
        if (!Files.isRegularFile(file)) return false
        return Sha256.ofFile(file).equals(artifact.spec.sha256, ignoreCase = true)
    }

    // ── live state and rollback ─────────────────────────────────────────────

    /** The generation of [name] that may load, or `null` when nothing is installed. */
    fun installedGeneration(name: String): String? =
        store.resolveCurrent(name)?.fileName?.toString()

    /** The directory loaders should read (`embeddings.npy`, the GGUF, the species DB). */
    fun activeDirectory(name: String): Path? = store.resolveCurrent(name)

    fun activeRecord(name: String): GenerationRecord? {
        val generation = installedGeneration(name) ?: return null
        return store.record(name, generation)
    }

    /**
     * Rolls [name] back to the retained previous generation. Returns the
     * generation now current, or `null` when there is nothing to roll back to.
     */
    fun rollback(name: String): String? = store.rollback(name)

    private fun rate(bytes: Long, startedAt: Long): Double {
        val elapsed = timeSource() - startedAt
        if (elapsed <= 0L) return 0.0
        return bytes.toDouble() / (elapsed / 1_000_000_000.0)
    }

    private fun readCapped(
        input: InputStream,
        cap: Long,
        url: String,
        cancel: CancellationToken,
    ): ByteArray {
        val out = ByteArrayOutputStream()
        val buffer = ByteArray(16 * 1024)
        var total = 0L
        input.use { stream ->
            while (true) {
                if (cancel.isCancelled()) throw ArtifactCancelledException("cancelled while fetching $url")
                val read = stream.read(buffer)
                if (read < 0) break
                total += read
                if (total > cap) {
                    throw ManifestFetchException("manifest at $url exceeds the $cap byte limit")
                }
                out.write(buffer, 0, read)
            }
        }
        return out.toByteArray()
    }

    companion object {
        const val HTTP_OK = 200

        /** A manifest is ~2 KB; 1 MiB is generous and still bounds a hostile response. */
        const val MAX_MANIFEST_BYTES = 1L shl 20
    }
}

/**
 * Where the artifacts live on a device: `files/artifacts/`, i.e.
 * `context.filesDir/artifacts` — app-private storage that is not world-readable
 * and is removed when the app is uninstalled.
 */
object ArtifactPaths {
    fun artifactsRoot(filesDir: java.io.File): Path = filesDir.toPath().resolve("artifacts")
}

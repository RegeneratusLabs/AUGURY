package au.org.regeneratus.augury.artifacts

import java.io.FileOutputStream
import java.nio.file.AtomicMoveNotSupportedException
import java.nio.file.FileVisitResult
import java.nio.file.Files
import java.nio.file.LinkOption
import java.nio.file.Path
import java.nio.file.SimpleFileVisitor
import java.nio.file.StandardCopyOption
import java.nio.file.attribute.BasicFileAttributes
import java.nio.file.StandardOpenOption

/**
 * AUGURY — the generation store.
 *
 * On-disk layout (the contract from `docs/mobile-app-decision.md` §3.2):
 *
 * ```
 * files/artifacts/
 *   formatter/
 *     current                      <- pointer file: the generation that may load
 *     previous                     <- pointer file: the rollback target
 *     staging/
 *       formatter-<generation>.part    <- in-progress download, resumable
 *       formatter-<generation>.unpack/ <- tar staging (see IndexUnpacker)
 *     <generation>/                <- verified payload + artifact.json record
 *   facts/
 *   vision-index/
 *   vision-encoder-dinov2-base-fp32/
 * ```
 *
 * THE POINTER IS THE COMMIT
 * -------------------------
 * A generation directory only becomes *loadable* when its id is written into
 * `current`. `current` is written to a sibling temp file, `fsync`ed, and moved
 * over the old pointer with `ATOMIC_MOVE`, so a crash mid-promote leaves either
 * the old pointer or the new one — never a half-written one, and never a pointer
 * to a directory that is still being written. Downloading and verification
 * always happen before this class is called, which is what makes "a partial
 * download is never promoted" a property of the code path rather than a rule
 * someone has to remember (§8 item 6).
 *
 * RETENTION
 * ---------
 * `previous` is kept until the *next* successful promote, so rollback is a
 * pointer swap with no network access. Anything older than `current`/`previous`
 * is deleted by [prune] — on a phone the formatter alone is 688 MB, so keeping a
 * third generation is not affordable.
 */
class GenerationStore(private val root: Path) {

    init {
        Files.createDirectories(root)
    }

    /** `files/artifacts` — exposed so callers can report the storage location. */
    fun root(): Path = root

    fun artifactRoot(name: String): Path = root.resolve(safeSegment(name, "artifact name"))

    fun generationDir(name: String, generation: String): Path =
        artifactRoot(name).resolve(safeSegment(generation, "generation"))

    fun stagingDir(name: String): Path = artifactRoot(name).resolve(STAGING)

    /** Resumable partial download for one artifact generation. */
    fun partFile(name: String, generation: String): Path =
        stagingDir(name).resolve("${safeSegment(name, "artifact name")}-${safeSegment(generation, "generation")}.part")

    /** Scratch directory used while unpacking a tarball, before the payload is moved into place. */
    fun unpackScratchDir(name: String, generation: String): Path =
        stagingDir(name).resolve("${safeSegment(name, "artifact name")}-${safeSegment(generation, "generation")}.unpack")

    fun currentPointerFile(name: String): Path = artifactRoot(name).resolve(CURRENT)

    fun previousPointerFile(name: String): Path = artifactRoot(name).resolve(PREVIOUS)

    // ── pointers ────────────────────────────────────────────────────────────

    /** The generation allowed to load, or `null` when nothing is installed. */
    fun currentGeneration(name: String): String? = readPointer(currentPointerFile(name))

    /** The rollback target, or `null` when there is only one generation. */
    fun previousGeneration(name: String): String? = readPointer(previousPointerFile(name))

    /** The directory of the current generation, when that directory still exists. */
    fun resolveCurrent(name: String): Path? {
        val generation = currentGeneration(name) ?: return null
        val dir = generationDir(name, generation)
        // A pointer to a directory with no completion record is a bug, not an
        // install: treat it as absent so the caller re-downloads rather than
        // loading an unverified payload.
        return if (Files.isDirectory(dir) && readRecord(dir) != null) dir else null
    }

    /**
     * Moves [generation] to `current`, remembering the old current as `previous`
     * and deleting anything older.
     *
     * @throws GenerationMissingException when the generation directory or its
     *   completion record is absent — promotion without a record would promote
     *   bytes that were never verified.
     */
    fun promote(name: String, generation: String): Promotion {
        val dir = generationDir(name, generation)
        if (!Files.isDirectory(dir) || readRecord(dir) == null) {
            throw GenerationMissingException(
                "refusing to promote $name generation $generation: $dir is missing or has no artifact.json record"
            )
        }
        val current = currentGeneration(name)
        if (current == generation) {
            prune(name)
            return Promotion(generation, previousGeneration(name), pointerMoved = false)
        }
        if (current != null) writePointer(previousPointerFile(name), current)
        writePointer(currentPointerFile(name), generation)
        prune(name)
        return Promotion(generation, current, pointerMoved = true)
    }

    /**
     * Flips `current` back to `previous` and makes the generation just rolled
     * back from the new rollback target. Returns the generation now current, or
     * `null` when there is nothing to roll back to.
     */
    fun rollback(name: String): String? {
        val current = currentGeneration(name)
        val previous = previousGeneration(name) ?: return null
        val dir = generationDir(name, previous)
        if (!Files.isDirectory(dir) || readRecord(dir) == null) {
            throw GenerationMissingException(
                "cannot roll back $name to generation $previous: the directory or its record is missing"
            )
        }
        writePointer(currentPointerFile(name), previous)
        if (current != null && current != previous) writePointer(previousPointerFile(name), current)
        prune(name)
        return previous
    }

    // ── generations ─────────────────────────────────────────────────────────

    /** Generation ids present on disk, newest-agnostic (sorted for determinism). */
    fun listGenerations(name: String): List<String> {
        val artifactRoot = artifactRoot(name)
        if (!Files.isDirectory(artifactRoot)) return emptyList()
        val out = ArrayList<String>()
        Files.newDirectoryStream(artifactRoot).use { stream ->
            for (entry in stream) {
                val fileName = entry.fileName?.toString() ?: continue
                if (Files.isDirectory(entry) && isSafeSegment(fileName) && fileName != STAGING) {
                    out += fileName
                }
            }
        }
        return out.sorted()
    }

    /** True when the generation directory carries a completion record. */
    fun hasRecord(name: String, generation: String): Boolean =
        readRecord(generationDir(name, generation)) != null

    fun record(name: String, generation: String): GenerationRecord? =
        readRecord(generationDir(name, generation))

    /**
     * Deletes every generation that is neither `current` nor `previous`.
     * Staging state is untouched — deleting an in-progress download would defeat
     * resume.
     */
    fun prune(name: String) {
        val keep = setOfNotNull(currentGeneration(name), previousGeneration(name))
        for (generation in listGenerations(name)) {
            if (generation !in keep) deleteGeneration(name, generation)
        }
    }

    fun deleteGeneration(name: String, generation: String) {
        deleteRecursively(generationDir(name, generation))
    }

    fun deleteArtifact(name: String) {
        deleteRecursively(artifactRoot(name))
    }

    // ── pointer and record IO ───────────────────────────────────────────────

    private fun readPointer(file: Path): String? {
        if (!Files.isRegularFile(file)) return null
        val text = try {
            String(Files.readAllBytes(file), Charsets.UTF_8).trim()
        } catch (_: Exception) {
            return null
        }
        if (!isSafeSegment(text)) return null
        return text
    }

    /**
     * Durably writes a pointer: temp file → `fsync` → atomic rename. The `fsync`
     * matters on a phone that can lose power mid-write; the rename is what makes
     * the flip atomic for any reader.
     */
    private fun writePointer(file: Path, value: String) {
        Files.createDirectories(file.parent)
        val tmp = file.resolveSibling(file.fileName.toString() + ".tmp")
        FileOutputStream(tmp.toFile()).use { out ->
            out.write(value.toByteArray(Charsets.UTF_8))
            out.flush()
            out.fd.sync()
        }
        try {
            Files.move(tmp, file, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING)
        } catch (_: AtomicMoveNotSupportedException) {
            Files.move(tmp, file, StandardCopyOption.REPLACE_EXISTING)
        }
    }

    companion object {
        const val CURRENT = "current"
        const val PREVIOUS = "previous"
        const val STAGING = "staging"
        const val RECORD_FILE = "artifact.json"

        /** Generation ids and artifact names become path segments; nothing else is allowed. */
        internal fun isSafeSegment(value: String): Boolean {
            if (value.isEmpty() || value == "." || value == "..") return false
            if (value.length > 128) return false
            return value.all { it.isLetterOrDigit() && it.code < 128 || it == '-' || it == '_' || it == '.' }
        }

        internal fun safeSegment(value: String, label: String): String {
            if (!isSafeSegment(value)) {
                throw ArtifactException("invalid $label \"$value\": expected a simple path segment")
            }
            return value
        }

        internal fun deleteRecursively(path: Path) {
            if (!Files.exists(path, LinkOption.NOFOLLOW_LINKS)) return
            Files.walkFileTree(
                path,
                object : SimpleFileVisitor<Path>() {
                    override fun visitFile(file: Path, attrs: BasicFileAttributes): FileVisitResult {
                        Files.deleteIfExists(file)
                        return FileVisitResult.CONTINUE
                    }

                    override fun postVisitDirectory(dir: Path, exc: java.io.IOException?): FileVisitResult {
                        Files.deleteIfExists(dir)
                        return FileVisitResult.CONTINUE
                    }
                },
            )
        }

        internal fun writeBytesAtomically(file: Path, bytes: ByteArray) {
            Files.createDirectories(file.parent)
            val tmp = file.resolveSibling(file.fileName.toString() + ".tmp")
            Files.newOutputStream(tmp, StandardOpenOption.CREATE, StandardOpenOption.WRITE, StandardOpenOption.TRUNCATE_EXISTING).use { out ->
                out.write(bytes)
                out.flush()
            }
            try {
                Files.move(tmp, file, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING)
            } catch (_: AtomicMoveNotSupportedException) {
                Files.move(tmp, file, StandardCopyOption.REPLACE_EXISTING)
            }
        }
    }
}

/** Outcome of a pointer flip. */
data class Promotion(
    val generation: String,
    val previous: String?,
    /** False when the pointer already named this generation (a no-op promote). */
    val pointerMoved: Boolean,
)

/**
 * The completion record written into a generation directory **after** SHA-256
 * verification succeeds.
 *
 * Its presence is what [GenerationStore.resolveCurrent] and
 * [GenerationStore.promote] require, so an interrupted download or a failed
 * verification can never be promoted: there is no record to promote. It also
 * carries the manifest facts needed to decide "this generation is already
 * installed" on the next launch without re-hashing 688 MB.
 */
data class GenerationRecord(
    val name: String,
    val generation: String,
    val sha256: String,
    val bytes: Long,
    val protocol: String,
    val repo: String,
    val path: String,
    val revision: String?,
    val unpack: Boolean,
    /** Files that make up the payload, relative to the generation directory. */
    val entries: List<String>,
) {

    /** True when this record describes exactly the artifact the manifest asks for. */
    fun matches(artifact: ManifestArtifact): Boolean =
        name == artifact.name &&
            generation == artifact.spec.generation &&
            sha256.equals(artifact.spec.sha256, ignoreCase = true) &&
            bytes == artifact.spec.bytes &&
            unpack == artifact.unpack &&
            path == artifact.spec.path &&
            protocol == artifact.spec.protocol

    /** True when every payload file the record names is actually on disk. */
    fun payloadPresent(directory: Path): Boolean {
        if (entries.isEmpty()) return false
        return entries.all { relative ->
            val file = directory.resolve(relative)
            Files.isRegularFile(file) && Files.size(file) > 0
        }
    }

    fun toJson(): JsonValue.Obj = Json.obj(
        "name" to Json.of(name),
        "generation" to Json.of(generation),
        "sha256" to Json.of(sha256),
        "bytes" to Json.of(bytes),
        "protocol" to Json.of(protocol),
        "repo" to Json.of(repo),
        "path" to Json.of(path),
        "revision" to Json.of(revision),
        "unpack" to Json.of(unpack),
        "entries" to Json.arr(entries.map { Json.of(it) }),
    )

    companion object {

        fun write(directory: Path, record: GenerationRecord) {
            GenerationStore.writeBytesAtomically(
                directory.resolve(GenerationStore.RECORD_FILE),
                Json.pretty(record.toJson()).toByteArray(Charsets.UTF_8),
            )
        }

        fun fromJson(node: JsonNode): GenerationRecord = GenerationRecord(
            name = node.field("name").string(),
            generation = node.field("generation").string(),
            sha256 = node.field("sha256").string(),
            bytes = node.field("bytes").long(),
            protocol = node.field("protocol").string(),
            repo = node.field("repo").string(),
            path = node.field("path").string(),
            revision = node.fieldOrNull("revision")?.string(),
            unpack = node.field("unpack").boolean(),
            entries = node.field("entries").array().map { it.string() },
        )
    }
}

/** Reads the completion record of a generation directory; `null` when absent or unreadable. */
internal fun readRecord(directory: Path): GenerationRecord? {
    val file = directory.resolve(GenerationStore.RECORD_FILE)
    if (!Files.isRegularFile(file)) return null
    return try {
        val node = JsonNode("", Json.parse(String(Files.readAllBytes(file), Charsets.UTF_8)))
        GenerationRecord.fromJson(node)
    } catch (_: Exception) {
        // A corrupt record means "not installed", never "assume it is fine".
        null
    }
}

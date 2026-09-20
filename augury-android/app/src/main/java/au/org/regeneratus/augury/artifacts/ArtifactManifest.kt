package au.org.regeneratus.augury.artifacts

/**
 * AUGURY — the artifact manifest, typed.
 *
 * This file mirrors `data/app/manifest.json` **exactly**: every field the
 * publisher writes has a typed home here, and every field is read from the
 * manifest rather than compiled in. That is hard constraint §8 item 1 — no
 * threshold, species count, dimension, version or band value may live in the
 * app — so nothing below has a default: a manifest missing a field the shell
 * needs is a rejected manifest, not a silently defaulted one.
 *
 * The shipped shape (see `scripts/app/build_ondevice_bundle.py`):
 *
 * ```json
 * {
 *   "manifest_schema": 1,
 *   "generated": "2026-09-19T12:15:59Z",
 *   "generation": "<sha256 of the canonical manifest without this field>",
 *   "formatter":  {"protocol", "repo", "path", "revision", "bytes", "sha256", "generation"},
 *   "facts":      {"protocol", "schema", "repo", "path", "revision", "bytes", "sha256", "generation"},
 *   "vision": {
 *     "index":      {"protocol", "schema", "repo", "path", "revision", "bytes", "sha256",
 *                    "backend", "vectors", "dim", "species", "generation"},
 *     "encoders":   [{"backend", "protocol", "repo", "path", "revision", "bytes", "sha256",
 *                     "quant", "generation"}],
 *     "bands":      {"auto_conf", "confirm_conf", "source"},
 *     "preprocess": {"resize_shortest_edge", "crop", "resample", "mean", "std", "output"}
 *   }
 * }
 * ```
 *
 * TWO INDEPENDENT CHECKS GUARD PARSING
 * ------------------------------------
 * 1. **Shape**: required fields, exact JSON types, positive sizes, well-formed
 *    64-hex SHA-256s, relative artifact paths (no `..`, no absolute path), and
 *    `artifact.generation` a prefix of that artifact's own SHA-256 — the
 *    invariant `gen12()` in the publisher establishes. A manifest that fails any
 *    of these is [ManifestFormatException].
 * 2. **Integrity**: the top-level `generation` must equal the SHA-256 of the
 *    canonical manifest minus that field, exactly as CPython computes it. A
 *    manifest edited after publication — a swapped repo, a downgraded hash, a
 *    stale generation — fails this and is rejected as
 *    [ManifestRejectedException] *before* any artifact URL is touched. That is
 *    the "tampered/stale manifest is rejected" invariant.
 */
/** Which Hugging Face repo *kind* an artifact lives in; it changes the URL prefix. */
data class ArtifactSpec(
    /** The wire contract this artifact must be executed under, e.g. `species.db@1`. */
    val protocol: String,
    /**
     * `dataset` or `model`. Not uniform across an app's artifacts: the formatter
     * GGUF is published to a **model** repo while the species DB, index and
     * encoder live in **dataset** repos, and HF resolves those with different
     * URL prefixes (a model repo has none). Hard-coding one kind for the whole
     * manifest is what made the 688 MB download 401.
     */
    val repoType: HuggingFaceRepoType,
    /** Hugging Face repo id, e.g. `RegeneratusLabs/augury-app`. */
    val repo: String,
    /** Path within that repo, e.g. `augury-ondevice.json`. */
    val path: String,
    /** Pinned commit, or `null` when the publisher has not pinned one yet. */
    val revision: String?,
    /** Exact expected length in bytes. */
    val bytes: Long,
    /** Lowercase 64-hex SHA-256 of the published bytes. */
    val sha256: String,
    /** Short generation id used as the on-disk directory name. */
    val generation: String,
)

/** `facts` — the species database. */
data class SpeciesDbArtifact(val spec: ArtifactSpec, val schema: Int) {
    /** Convenience: [ArtifactSpec.protocol]. */
    val protocol: String get() = spec.protocol
}

/** `vision.index` — the retrieval index (a gzipped tar in current manifests). */
data class VisionIndexArtifact(
    val spec: ArtifactSpec,
    val schema: Int,
    val backend: String,
    val vectors: Long,
    val dim: Int,
    val species: Int,
) {
    /** Convenience: [ArtifactSpec.protocol]. */
    val protocol: String get() = spec.protocol
}

/** One entry of `vision.encoders`. */
data class VisionEncoderArtifact(
    val spec: ArtifactSpec,
    val backend: String,
    val quant: String,
) {
    /** Convenience: [ArtifactSpec.protocol]. */
    val protocol: String get() = spec.protocol
}

/** `vision.bands` — the confidence thresholds. Never constants in the app. */
data class VisionBands(
    val autoConf: Double,
    val confirmConf: Double,
    /** Free-form provenance string from the publisher, e.g. `index-v3 band_config.json`. */
    val source: String?,
)

/** `vision.preprocess` — image preparation the shell must implement faithfully. */
data class VisionPreprocess(
    val resizeShortestEdge: Int,
    val crop: Int,
    val resample: String,
    val mean: List<Double>,
    val std: List<Double>,
    val output: String,
)

/** `vision` — index + encoders + bands + preprocessing, all independently versioned. */
data class VisionSpec(
    val index: VisionIndexArtifact,
    val encoders: List<VisionEncoderArtifact>,
    val bands: VisionBands,
    val preprocess: VisionPreprocess,
)

/** The whole manifest. Every number in it is data; none of it is compiled in. */
data class ArtifactManifest(
    val manifestSchema: Int,
    /** Publisher timestamp; informational only. */
    val generated: String?,
    /** Digest of the manifest body — verified during parsing. */
    val generation: String,
    val formatter: ArtifactSpec,
    val facts: SpeciesDbArtifact,
    val vision: VisionSpec,
) {
    /** Every downloadable artifact, in the order the Setup screen should present them. */
    fun artifacts(): List<ManifestArtifact> = ManifestArtifacts.list(this)

    /** The encoder for the index's backend, or `null` when the manifest is inconsistent. */
    fun encoderForIndexBackend(): VisionEncoderArtifact? =
        vision.encoders.firstOrNull { it.backend == vision.index.backend }
}

/** Which slot an artifact fills. Used for storage naming and for UI grouping. */
enum class ArtifactRole { FORMATTER, FACTS, VISION_INDEX, VISION_ENCODER }

/**
 * A manifest entry resolved to its on-device identity.
 *
 * [name] is the `<name>` of `files/artifacts/<name>/<generation>/`; the other
 * fields come straight from the manifest. [unpack] is derived from the artifact
 * path's extension (`.tar.gz` / `.tgz`), not from a hard-coded index filename,
 * so publishing a differently-named tarball still unpacks.
 */
data class ManifestArtifact(
    val name: String,
    val role: ArtifactRole,
    val spec: ArtifactSpec,
    val unpack: Boolean,
    /** Human-facing detail, e.g. `dinov2-base fp32`. */
    val detail: String,
) {
    // Pass-throughs so callers rendering the Setup screen do not have to reach
    // through `spec` for the five fields they show.
    val protocol: String get() = spec.protocol
    val repo: String get() = spec.repo
    val path: String get() = spec.path
    val revision: String? get() = spec.revision
    val bytes: Long get() = spec.bytes
    val sha256: String get() = spec.sha256
    val generation: String get() = spec.generation
}

/**
 * The `<name>` of `files/artifacts/<name>/<generation>/` for each slot.
 *
 * These are storage keys, not tunable values: they are the contract between the
 * pipeline that writes a generation and the loaders that read one, and other
 * components refer to them by constant rather than by literal.
 */
object ArtifactNames {
    const val FORMATTER = "formatter"
    const val FACTS = "facts"
    const val VISION_INDEX = "vision-index"

    fun encoder(backend: String, quant: String): String = "vision-encoder-$backend-$quant"
}

object ManifestArtifacts {

    fun list(manifest: ArtifactManifest): List<ManifestArtifact> {
        val out = ArrayList<ManifestArtifact>()
        out += ManifestArtifact(ArtifactNames.FORMATTER, ArtifactRole.FORMATTER, manifest.formatter, unpack(manifest.formatter), "text formatter")
        out += ManifestArtifact(ArtifactNames.FACTS, ArtifactRole.FACTS, manifest.facts.spec, unpack(manifest.facts.spec), "species database")
        out += ManifestArtifact(ArtifactNames.VISION_INDEX, ArtifactRole.VISION_INDEX, manifest.vision.index.spec, unpack(manifest.vision.index.spec), manifest.vision.index.backend)
        val used = HashSet<String>()
        manifest.vision.encoders.forEachIndexed { index, encoder ->
            var name = ArtifactNames.encoder(encoder.backend, encoder.quant)
            if (!used.add(name)) {
                name = "$name-$index"
                used.add(name)
            }
            out += ManifestArtifact(name, ArtifactRole.VISION_ENCODER, encoder.spec, unpack(encoder.spec), "${encoder.backend} ${encoder.quant}")
        }
        return out
    }

    /** True when the published path names a gzipped tar the shell should unpack. */
    fun unpack(spec: ArtifactSpec): Boolean {
        val lower = spec.path.lowercase()
        return lower.endsWith(".tar.gz") || lower.endsWith(".tgz")
    }
}

/**
 * The manifest's self-digest, byte-compatible with
 * `build_ondevice_bundle.py::manifest_generation`:
 *
 * ```python
 * body = {k: v for k, v in manifest.items() if k != "generation"}
 * sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
 * ```
 */
object ManifestDigest {
    fun of(bodyWithoutGeneration: JsonValue.Obj): String =
        Sha256.of(Json.canonicalBytes(bodyWithoutGeneration))
}

object ManifestParser {

    /**
     * Parses and verifies a manifest.
     *
     * @throws ManifestFormatException the document is valid JSON but not a valid manifest.
     * @throws ManifestRejectedException the generation digest does not match the body.
     */
    fun parse(bytes: ByteArray): ArtifactManifest = parse(String(bytes, Charsets.UTF_8))

    fun parse(text: String): ArtifactManifest {
        val root = try {
            Json.parse(text)
        } catch (e: JsonParseException) {
            throw ManifestRejectedException("manifest is not valid JSON: ${e.message}", e)
        }
        val obj = root as? JsonValue.Obj
            ?: throw ManifestRejectedException("manifest is not a JSON object")
        return parseObject(JsonNode("", obj))
    }

    internal fun parseObject(root: JsonNode): ArtifactManifest {
        val declaratedGeneration = root.field("generation").string().trim()
        if (declaratedGeneration.isEmpty()) root.field("generation").fail("must not be empty")

        val recomputed = ManifestDigest.of(
            (root.value as JsonValue.Obj).without("generation")
        )
        if (!recomputed.equals(declaratedGeneration, ignoreCase = true)) {
            throw ManifestRejectedException(
                "manifest generation digest mismatch: the manifest declares $declaratedGeneration " +
                    "but its body hashes to $recomputed — the manifest was modified after publication " +
                    "or is stale; refusing to download anything"
            )
        }

        val manifestSchema = root.field("manifest_schema").int()
        val generated = root.fieldOrNull("generated")?.string()
        val formatter = parseSpec(root.field("formatter"))
        val factsNode = root.field("facts")
        val facts = SpeciesDbArtifact(
            spec = parseSpec(factsNode),
            schema = factsNode.field("schema").int(),
        )

        val visionNode = root.field("vision")
        val indexNode = visionNode.field("index")
        val indexSpec = parseSpec(indexNode)
        val index = VisionIndexArtifact(
            spec = indexSpec,
            schema = indexNode.field("schema").int(),
            backend = nonEmpty(indexNode, "backend"),
            vectors = positiveLong(indexNode, "vectors"),
            dim = positiveInt(indexNode, "dim"),
            species = positiveInt(indexNode, "species"),
        )

        val encodersNode = visionNode.field("encoders")
        val encoderNodes = encodersNode.array()
        if (encoderNodes.isEmpty()) encodersNode.fail("must list at least one encoder")
        val encoders = encoderNodes.map { node ->
            VisionEncoderArtifact(
                spec = parseSpec(node),
                backend = nonEmpty(node, "backend"),
                quant = nonEmpty(node, "quant"),
            )
        }

        val bandsNode = visionNode.field("bands")
        val bands = VisionBands(
            autoConf = unitInterval(bandsNode, "auto_conf"),
            confirmConf = unitInterval(bandsNode, "confirm_conf"),
            source = bandsNode.fieldOrNull("source")?.string(),
        )

        val preprocessNode = visionNode.field("preprocess")
        val mean = preprocessNode.field("mean").array().map { it.double() }
        val std = preprocessNode.field("std").array().map { it.double() }
        if (mean.isEmpty()) preprocessNode.field("mean").fail("must not be empty")
        if (mean.size != std.size) {
            preprocessNode.field("std").fail("has ${std.size} entries but mean has ${mean.size}")
        }
        for ((i, s) in std.withIndex()) {
            if (s <= 0.0) preprocessNode.field("std").fail("entry $i must be greater than zero")
        }
        val preprocess = VisionPreprocess(
            resizeShortestEdge = positiveInt(preprocessNode, "resize_shortest_edge"),
            crop = positiveInt(preprocessNode, "crop"),
            resample = nonEmpty(preprocessNode, "resample"),
            mean = mean,
            std = std,
            output = nonEmpty(preprocessNode, "output"),
        )

        return ArtifactManifest(
            manifestSchema = manifestSchema,
            generated = generated,
            generation = declaratedGeneration,
            formatter = formatter,
            facts = facts,
            vision = VisionSpec(index = index, encoders = encoders, bands = bands, preprocess = preprocess),
        )
    }

    private fun parseSpec(node: JsonNode): ArtifactSpec {
        val protocol = nonEmpty(node, "protocol")
        val repo = nonEmpty(node, "repo")
        // Absent means "dataset": only the formatter GGUF is a model repo, and an
        // older manifest without the field must keep working.
        val repoType = HuggingFaceRepoType.fromManifest(
            node.fieldOrNull("repo_type")?.string(),
            "${node.path}.repo_type",
        )
        val path = nonEmpty(node, "path")
        val revision = node.fieldOrNull("revision")?.string()?.trim()?.ifEmpty { null }
        val bytesNode = node.field("bytes")
        val bytes = bytesNode.long()
        if (bytes <= 0) bytesNode.fail("must be greater than zero")
        val sha256Node = node.field("sha256")
        val sha256 = normalizeSha256(sha256Node.string(), sha256Node.path)
        val generationNode = node.field("generation")
        val generation = generationNode.string().trim()
        if (generation.isEmpty()) generationNode.fail("must not be empty")
        if (!sha256.startsWith(generation.lowercase())) {
            generationNode.fail(
                "generation \"$generation\" is not a prefix of this artifact's sha256 $sha256 " +
                    "(the publisher derives it as the first 12 hex digits) — the manifest is inconsistent"
            )
        }
        if (!isSafeRelativePath(path)) {
            node.field("path").fail("\"$path\" must be a relative path inside the repo with no \"..\" segments")
        }
        return ArtifactSpec(
            protocol = protocol,
            repoType = repoType,
            repo = repo,
            path = path,
            revision = revision,
            bytes = bytes,
            sha256 = sha256,
            generation = generation.lowercase(),
        )
    }

    internal fun normalizeSha256(raw: String, path: String): String {
        val value = raw.trim().lowercase()
        if (value.length != 64 || value.any { it !in "0123456789abcdef" }) {
            throw ManifestFormatException(
                "manifest field $path: must be a 64-character hex SHA-256, found \"$raw\""
            )
        }
        return value
    }

    /** Rejects absolute paths, drive letters, backslashes and `..` traversal. */
    internal fun isSafeRelativePath(path: String): Boolean {
        if (path.isEmpty() || path.startsWith("/") || path.startsWith("\\")) return false
        if (path.contains('\\') || path.contains('\u0000')) return false
        if (path.contains("://")) return false
        if (Regex("^[A-Za-z]:").containsMatchIn(path)) return false
        return path.split('/').none { it.isEmpty() || it == "." || it == ".." }
    }

    private fun nonEmpty(node: JsonNode, field: String): String {
        val child = node.field(field)
        val value = child.string().trim()
        if (value.isEmpty()) child.fail("must not be empty")
        return value
    }

    private fun positiveLong(node: JsonNode, field: String): Long {
        val child = node.field(field)
        val value = child.long()
        if (value <= 0) child.fail("must be greater than zero")
        return value
    }

    private fun positiveInt(node: JsonNode, field: String): Int {
        val child = node.field(field)
        val value = child.int()
        if (value <= 0) child.fail("must be greater than zero")
        return value
    }

    private fun unitInterval(node: JsonNode, field: String): Double {
        val child = node.field(field)
        val value = child.double()
        if (value < 0.0 || value > 1.0) child.fail("must be within [0, 1], found $value")
        return value
    }
}

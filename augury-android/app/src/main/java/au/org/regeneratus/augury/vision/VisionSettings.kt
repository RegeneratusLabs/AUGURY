package au.org.regeneratus.augury.vision

/**
 * AUGURY — preprocessing parameters, read from `vision.preprocess` in the
 * manifest.
 *
 * The pipeline is the DINOv2 image processor contract, and the manifest is the
 * source of truth for every number in it (hard constraint §8.1):
 *
 * 1. resize so the **shortest edge** is [resizeShortestEdge] (aspect preserved,
 *    integer truncation — HuggingFace's `get_resize_output_image_size`);
 * 2. **center crop** [crop] x [crop] (`top = (h - crop) / 2` truncated);
 * 3. RGB, rescale by 1/255;
 * 4. normalise per channel with [mean] / [std];
 * 5. feed the CHW tensor to the graph as `pixel_values`.
 *
 * Only the `bicubic` resample and the `cls_token` output are implemented by
 * protocol `vision.clip-token-l2-pca-knn-ip@1`; anything else is an
 * "app update required" condition rather than something to guess at.
 */
class PreprocessSettings(
    val resizeShortestEdge: Int,
    val crop: Int,
    val resample: String,
    val mean: FloatArray,
    val std: FloatArray,
    val output: String,
) {

    init {
        require(resizeShortestEdge > 0) { "resize_shortest_edge must be positive" }
        require(crop > 0) { "crop must be positive" }
        require(mean.size == CHANNELS) { "mean must have $CHANNELS entries, got ${mean.size}" }
        require(std.size == CHANNELS) { "std must have $CHANNELS entries, got ${std.size}" }
        require(std.all { it > 0f }) { "std entries must be positive" }
    }

    /** Fail loudly if this build cannot execute the declared preprocessing. */
    fun requireSupported() {
        if (!resample.equals(RESAMPLE_BICUBIC, ignoreCase = true)) {
            throw VisionContractException(
                "manifest declares resample='$resample' but this build implements only " +
                    "'$RESAMPLE_BICUBIC'",
                appUpdateRequired = true,
            )
        }
        if (output != OUTPUT_CLS_TOKEN) {
            throw VisionContractException(
                "manifest declares preprocess.output='$output' but this build implements " +
                    "only '$OUTPUT_CLS_TOKEN'",
                appUpdateRequired = true,
            )
        }
    }

    override fun toString(): String =
        "PreprocessSettings(shortestEdge=$resizeShortestEdge, crop=$crop, resample=$resample, " +
            "mean=${mean.toList()}, std=${std.toList()}, output=$output)"

    companion object {
        /** RGB — the graph contract, not a tunable. */
        const val CHANNELS = 3
        const val RESAMPLE_BICUBIC = "bicubic"
        const val OUTPUT_CLS_TOKEN = "cls_token"

        fun fromManifest(vision: Map<String, Any?>): PreprocessSettings {
            val block = VisionJson.obj(
                vision["preprocess"] ?: throw VisionContractException(
                    "manifest vision.preprocess is missing"
                ),
                "vision.preprocess",
            )
            val settings = PreprocessSettings(
                resizeShortestEdge = VisionJson.int(
                    block["resize_shortest_edge"], "vision.preprocess.resize_shortest_edge"
                ),
                crop = VisionJson.int(block["crop"], "vision.preprocess.crop"),
                resample = VisionJson.str(block["resample"], "vision.preprocess.resample"),
                mean = VisionJson.floats(block["mean"], "vision.preprocess.mean"),
                std = VisionJson.floats(block["std"], "vision.preprocess.std"),
                output = VisionJson.str(block["output"], "vision.preprocess.output"),
            )
            settings.requireSupported()
            return settings
        }
    }
}

/**
 * AUGURY — the vision half of the app manifest, parsed and gated.
 *
 * Everything here is *read*; nothing is assumed. The class also carries the
 * shell's capability declaration and refuses a manifest that does not match it
 * (docs/mobile-app-decision.md §3.3, handover §8.8).
 *
 * @param topK how many candidates the UI must show. The manifest may declare it
 *   (`vision.index.k` or `vision.k`); the protocol default is 3, and 3 is the
 *   product requirement — "never silently accept a species from a photo" only
 *   works if the user always sees three.
 */
class VisionSettings(
    val protocol: String,
    val indexSchema: Int,
    val backend: String,
    val vectors: Int,
    val dim: Int,
    val species: Int,
    val encoderBackend: String,
    val encoderProtocol: String,
    val encoderPath: String,
    val encoderQuant: String,
    val encoderBytes: Long?,
    val encoderSha256: String?,
    val preprocess: PreprocessSettings,
    val bands: Bands,
    val topK: Int,
    val manifestGeneration: String?,
) {

    init {
        require(topK >= 1) { "topK must be >= 1" }
        require(vectors >= 0) { "vectors must not be negative" }
        require(dim > 0) { "dim must be positive" }
    }

    /**
     * The protocol gate. Called by [fromManifest]; kept public so a caller that
     * built the settings by hand can run the same check.
     */
    fun requireSupported() {
        if (protocol != SUPPORTED_PROTOCOL) {
            throw VisionContractException(
                "manifest declares vision protocol '$protocol' but this build implements " +
                    "'$SUPPORTED_PROTOCOL'",
                appUpdateRequired = true,
            )
        }
        if (indexSchema != SUPPORTED_INDEX_SCHEMA) {
            throw VisionContractException(
                "manifest declares index schema $indexSchema but this build implements " +
                    "$SUPPORTED_INDEX_SCHEMA",
                appUpdateRequired = true,
            )
        }
        if (backend !in SUPPORTED_BACKENDS) {
            throw VisionContractException(
                "manifest declares backend '$backend' but this build implements " +
                    SUPPORTED_BACKENDS.joinToString(),
                appUpdateRequired = true,
            )
        }
        if (encoderBackend !in SUPPORTED_BACKENDS || encoderProtocol != SUPPORTED_PROTOCOL) {
            throw VisionContractException(
                "manifest declares encoder backend='$encoderBackend' " +
                    "protocol='$encoderProtocol', which this build does not implement",
                appUpdateRequired = true,
            )
        }
        if (encoderQuant != SUPPORTED_QUANT) {
            throw VisionContractException(
                "manifest declares encoder quantisation '$encoderQuant' but only " +
                    "'$SUPPORTED_QUANT' is shipped. Dynamic int8 was measured on the real " +
                    "gallery and rejected (-70.00p top-1, see docs/mobile-app-decision.md " +
                    "§5.1); it is not a size/accuracy trade this app makes.",
                appUpdateRequired = true,
            )
        }
        if (topK < REQUIRED_TOP_K) {
            throw VisionContractException(
                "manifest declares top_k=$topK but the product requires at least " +
                    "$REQUIRED_TOP_K candidates to be shown for every photo; refusing to " +
                    "run a configuration that could silently accept a species.",
            )
        }
    }

    override fun toString(): String =
        "VisionSettings(protocol=$protocol, schema=$indexSchema, backend=$backend, " +
            "vectors=$vectors, dim=$dim, species=$species, quant=$encoderQuant, topK=$topK, " +
            "bands=$bands, preprocess=$preprocess)"

    companion object {
        /** The one protocol this shell implements. Declaring it is the gate. */
        const val SUPPORTED_PROTOCOL = "vision.clip-token-l2-pca-knn-ip@1"
        const val SUPPORTED_INDEX_SCHEMA = 1
        const val SUPPORTED_QUANT = "fp32"

        /** `backend` -> the preprocessing/output contract the shell implements. */
        val SUPPORTED_BACKENDS = setOf("dinov2-base")

        /** Product requirement: the UI always shows three candidates. */
        const val REQUIRED_TOP_K = 3

        fun fromManifest(manifestJson: String): VisionSettings {
            val root = VisionJson.obj(VisionJson.parse(manifestJson), "manifest")
            return fromManifest(root)
        }

        fun fromManifest(root: Map<String, Any?>): VisionSettings {
            val vision = VisionJson.obj(
                root["vision"] ?: throw VisionContractException("manifest has no vision block"),
                "vision",
            )
            val index = VisionJson.obj(
                vision["index"] ?: throw VisionContractException("manifest has no vision.index"),
                "vision.index",
            )
            val encoders = VisionJson.array(
                vision["encoders"] ?: throw VisionContractException("manifest has no vision.encoders"),
                "vision.encoders",
            )
            if (encoders.isEmpty()) {
                throw VisionContractException("manifest vision.encoders is empty")
            }
            if (encoders.size > 1) {
                // The shell ships exactly one encoder path; several would mean it
                // has to choose, and choosing is how you get a mismatched encoder.
                throw VisionContractException(
                    "manifest declares ${encoders.size} encoders; this build implements one " +
                        "encoder contract and will not choose between them",
                    appUpdateRequired = true,
                )
            }
            val encoder = VisionJson.obj(encoders[0], "vision.encoders[0]")
            val settings = VisionSettings(
                protocol = VisionJson.str(index["protocol"], "vision.index.protocol"),
                indexSchema = VisionJson.int(index["schema"], "vision.index.schema"),
                backend = VisionJson.str(index["backend"], "vision.index.backend"),
                vectors = VisionJson.int(index["vectors"], "vision.index.vectors"),
                dim = VisionJson.int(index["dim"], "vision.index.dim"),
                species = VisionJson.int(index["species"], "vision.index.species"),
                encoderBackend = VisionJson.str(encoder["backend"], "vision.encoders[0].backend"),
                encoderProtocol = VisionJson.str(encoder["protocol"], "vision.encoders[0].protocol"),
                encoderPath = VisionJson.str(encoder["path"], "vision.encoders[0].path"),
                encoderQuant = VisionJson.str(encoder["quant"], "vision.encoders[0].quant"),
                encoderBytes = (encoder["bytes"] as? Double)?.toLong(),
                encoderSha256 = encoder["sha256"] as? String,
                preprocess = PreprocessSettings.fromManifest(vision),
                bands = Bands.fromManifest(vision),
                topK = declaredTopK(vision, index),
                manifestGeneration = root["generation"] as? String,
            )
            settings.requireSupported()
            return settings
        }

        private fun declaredTopK(vision: Map<String, Any?>, index: Map<String, Any?>): Int {
            val declared = (index["k"] as? Double) ?: (vision["k"] as? Double)
            return declared?.toInt() ?: REQUIRED_TOP_K
        }
    }
}

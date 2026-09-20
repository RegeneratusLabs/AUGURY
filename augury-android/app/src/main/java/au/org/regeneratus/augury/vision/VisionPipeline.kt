package au.org.regeneratus.augury.vision

/**
 * AUGURY — the vision path, end to end.
 *
 * ```
 * Bitmap pixels
 *   -> Preprocessor          resize 256 bicubic, crop 224, /255, (x-mean)/std
 *   -> Encoder (ONNX)        CLS token, 768-d
 *   -> L2 normalise          \
 *   -> PCA-whiten (W, mu)     |  steps 3-5 of photo_id.PhotoID.embed()
 *   -> L2 normalise          /
 *   -> KnnIndex              inner product, canonical collapse
 *   -> top-K + band          Bands from the manifest
 * ```
 *
 * The two properties the rest of the app depends on:
 *
 * 1. **It always returns [topK] candidates** (three by product requirement).
 *    That is enforced structurally at construction: an index that cannot serve
 *    three distinct species is refused rather than allowed to return two and let
 *    the UI imply certainty it does not have.
 * 2. **It never accepts a species.** The band is advice for the UI; the caller
 *    still has to show the candidates and ask.
 *
 * Nothing here is Android-specific, so the whole maths half runs in a plain JVM
 * test. Only [OnnxEncoder] needs the device.
 */
class VisionPipeline(
    private val encoder: Encoder,
    private val preprocessor: Preprocessor,
    private val whitening: PcaWhitening?,
    private val index: KnnIndex,
    private val bands: Bands,
    val topK: Int = VisionSettings.REQUIRED_TOP_K,
) {

    init {
        require(topK >= 1) { "topK must be >= 1" }
        if (index.canonicalCount < topK) {
            throw VisionContractException(
                "the index can only return ${index.canonicalCount} distinct species but the " +
                    "UI must always show $topK candidates; refusing to run a configuration " +
                    "that would silently narrow the answer"
            )
        }
        if (whitening != null) {
            if (whitening.inputDim != encoder.outputDim) {
                throw VisionContractException(
                    "encoder emits ${encoder.outputDim}-d vectors but the PCA matrix expects " +
                        "${whitening.inputDim} — encoder and index are from different generations",
                    appUpdateRequired = true,
                )
            }
            if (whitening.outputDim != index.dim) {
                throw VisionContractException(
                    "PCA whitening emits ${whitening.outputDim}-d vectors but the gallery is " +
                        "${index.dim}-d — index and pca_whiten.npz are from different generations"
                )
            }
        } else if (encoder.outputDim != index.dim) {
            throw VisionContractException(
                "encoder emits ${encoder.outputDim}-d vectors but the gallery is ${index.dim}-d, " +
                    "and the index ships no PCA matrix to bridge them"
            )
        }
    }

    /** One ranked candidate. `canonical` equals `key` unless a canonical map applied. */
    data class Candidate(val key: String, val canonical: String, val score: Float)

    /** What the UI renders: always [topK] candidates plus the band. */
    data class Result(val candidates: List<Candidate>, val band: Band) {
        val top1: Candidate get() = candidates.first()
    }

    /** Photo pixels in, ranked candidates out. */
    fun identify(image: RgbImage): Result = identifyFromTensor(preprocessor.toTensor(image))

    /**
     * Embed a graph output. Kept public for the parity test, which replays a CLS
     * token recorded from the real model on the host.
     */
    fun identifyFromCls(cls: FloatArray): Result = identifyFromTensor(null, cls)

    /** Embed a `pixel_values` tensor (already preprocessed, CHW float32). */
    fun identifyFromTensor(tensor: FloatArray): Result =
        identifyFromTensor(tensor, null)

    private fun identifyFromTensor(tensor: FloatArray?, cls: FloatArray?): Result {
        val token = cls ?: encoder.encode(requireNotNull(tensor))
        val query = embed(token)
        val matches = index.search(query, topK)
        val candidates = matches.map { Candidate(it.key, it.canonical, it.score) }
        if (candidates.size < topK) {
            // search() cannot drop below the canonical count checked in init;
            // this is a belt-and-braces guard on the product requirement.
            throw VisionContractException(
                "index returned ${candidates.size} candidates, expected $topK"
            )
        }
        return Result(candidates, bands.classify(candidates.first().score))
    }

    /** Steps 3-5 of `photo_id.embed()`: L2, PCA-whiten, L2. */
    fun embed(cls: FloatArray): FloatArray {
        require(cls.size == encoder.outputDim) {
            "encoder output has ${cls.size} dimensions, expected ${encoder.outputDim}"
        }
        val normalised = Vectors.l2Normalised(cls)
        val projected = whitening?.project(normalised) ?: return normalised
        Vectors.l2NormaliseInPlace(projected)
        return projected
    }

    /** How many species the shipped index can return. */
    val speciesCount: Int get() = index.canonicalCount

    companion object {
        /**
         * Wire a pipeline from the verified artifact bytes.
         *
         * Every cross-artifact invariant the manifest promises is checked here —
         * dimensions, vector count, species count — so a mismatched generation
         * fails at load rather than producing plausible garbage per photo.
         *
         * @param pcaNpz the index tarball's `pca_whiten.npz` (required for v2+ indexes)
         */
        fun create(
            settings: VisionSettings,
            encoder: Encoder,
            embeddingsNpy: ByteArray,
            keysJson: String,
            pcaNpz: ByteArray?,
            canonicalJson: String? = null,
            topK: Int = settings.topK,
        ): VisionPipeline {
            val index = KnnIndex.fromEmbeddingsNpy(embeddingsNpy, keysJson, canonicalJson)
            if (settings.vectors > 0 && index.size != settings.vectors) {
                throw VisionContractException(
                    "manifest declares ${settings.vectors} gallery vectors but the index has " +
                        "${index.size}"
                )
            }
            if (index.dim != settings.dim) {
                throw VisionContractException(
                    "manifest declares dim=${settings.dim} but the index is ${index.dim}-d"
                )
            }
            if (settings.species > 0 && index.canonicalCount != settings.species) {
                throw VisionContractException(
                    "manifest declares ${settings.species} species but the index serves " +
                        "${index.canonicalCount} distinct keys"
                )
            }
            val whitening = pcaNpz?.let { PcaWhitening.fromNpz(it) }
            return VisionPipeline(
                encoder = encoder,
                preprocessor = Preprocessor(settings.preprocess),
                whitening = whitening,
                index = index,
                bands = settings.bands,
                topK = topK,
            )
        }
    }
}

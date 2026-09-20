package au.org.regeneratus.augury.vision

/**
 * AUGURY — PCA whitening, `pca_whiten.npz`.
 *
 * Steps 3–5 of `photo_id.PhotoID.embed()`:
 *
 * ```
 * vec /= (||vec|| + 1e-9)      # 768-d CLS token, unit length
 * vec  = (vec - mu) @ W        # 768 -> 384, whitened
 * vec /= (||vec|| + 1e-9)      # unit length again
 * ```
 *
 * The ONNX graph covers **only** the CLS token; this projection is Kotlin's job.
 * `W` (768 x 384) and `mu` (768) are read from the index tarball at runtime —
 * never hard-coded, and never re-derived here.
 *
 * The gallery vectors in `embeddings.npy` are already whitened, which is why a
 * query that skipped this step would compare apples to oranges and return
 * plausible garbage.
 */
class PcaWhitening private constructor(
    val inputDim: Int,
    val outputDim: Int,
    /** The `whiten` scalar from the npz, informational (recorded in `meta.json`). */
    val whiten: Double?,
    /** Row-major `inputDim x outputDim` projection matrix. */
    private val w: FloatArray,
    /** The `inputDim`-length mean subtracted before projection. */
    private val mu: FloatArray,
) {

    init {
        require(mu.size == inputDim) { "mu has ${mu.size} entries, expected $inputDim" }
        require(w.size == inputDim * outputDim) {
            "W has ${w.size} entries, expected ${inputDim * outputDim}"
        }
    }

    /**
     * The raw projection, `(vec - mu) @ W`. Callers normally want
     * [VisionPipeline.embed], which also applies the two L2 normalisations.
     */
    fun project(vec: FloatArray): FloatArray {
        require(vec.size == inputDim) {
            "query has ${vec.size} dimensions but the whitening expects $inputDim"
        }
        val acc = DoubleArray(outputDim)
        for (i in 0 until inputDim) {
            val centred = (vec[i] - mu[i]).toDouble()
            if (centred == 0.0) continue
            val row = i * outputDim
            for (j in 0 until outputDim) {
                acc[j] += centred * w[row + j]
            }
        }
        return FloatArray(outputDim) { acc[it].toFloat() }
    }

    companion object {
        const val W_MEMBER = "W.npy"
        const val MU_MEMBER = "mu.npy"
        const val DIM_MEMBER = "dim.npy"
        const val WHITEN_MEMBER = "whiten.npy"

        /** Parse the projection out of the shipped `pca_whiten.npz`. */
        fun fromNpz(npz: ByteArray): PcaWhitening {
            val wArray = Npy.parseNpzMember(npz, W_MEMBER, "pca_whiten.npz")
                ?: throw VisionContractException("pca_whiten.npz has no $W_MEMBER member")
            val muArray = Npy.parseNpzMember(npz, MU_MEMBER, "pca_whiten.npz")
                ?: throw VisionContractException("pca_whiten.npz has no $MU_MEMBER member")
            if (wArray.shape.size != 2) {
                throw VisionContractException(
                    "pca_whiten.npz W must be a matrix, got shape ${wArray.shape.toList()}"
                )
            }
            val inputDim = wArray.shape[0]
            val outputDim = wArray.shape[1]
            if (muArray.size != inputDim) {
                throw VisionContractException(
                    "pca_whiten.npz mu has ${muArray.size} entries but W expects $inputDim"
                )
            }
            val declaredDim = Npy.parseNpzMember(npz, DIM_MEMBER, "pca_whiten.npz")
                ?.asLongs("pca_whiten.npz/$DIM_MEMBER")?.firstOrNull()
            if (declaredDim != null && declaredDim.toInt() != outputDim) {
                throw VisionContractException(
                    "pca_whiten.npz declares dim=$declaredDim but W has $outputDim columns"
                )
            }
            val whiten = Npy.parseNpzMember(npz, WHITEN_MEMBER, "pca_whiten.npz")
                ?.let { member ->
                    // stored as a float64 scalar array; an integer or float32
                    // spelling reads the same way and is accepted too
                    runCatching { member.asFloats("pca_whiten.npz/$WHITEN_MEMBER").first().toDouble() }
                        .getOrElse {
                            runCatching {
                                member.asLongs("pca_whiten.npz/$WHITEN_MEMBER").first().toDouble()
                            }.getOrNull()
                        }
                }
            return PcaWhitening(
                inputDim = inputDim,
                outputDim = outputDim,
                whiten = whiten,
                w = wArray.asFloats("pca_whiten.npz/$W_MEMBER"),
                mu = muArray.asFloats("pca_whiten.npz/$MU_MEMBER"),
            )
        }
    }
}

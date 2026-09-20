package au.org.regeneratus.augury.vision

import java.io.File

/**
 * AUGURY — brute-force kNN over the shipped gallery, with canonical collapse.
 *
 * FAISS is deliberately **not** shipped (handover §8.9): the gallery is a single
 * `FloatArray` of `16580 x 384` post-whitened, L2-normalised vectors, so inner
 * product over it is ~6.4M multiply-adds — a few milliseconds in plain Kotlin,
 * with no native dependency and no 42 MB `index.faiss` in the download.
 *
 * ## Canonical collapse
 *
 * Many gallery rows share one species key (1,357 rows for `acacia nilotica`
 * alone). Ranking *rows* would let one species occupy all three UI slots, so the
 * index ranks **canonical keys**: for every key it keeps the best-scoring row,
 * then returns the top `k` keys by that score. This is a superset of
 * `photo_id.identify()`, which collapses only the first `k*4` neighbours; on the
 * shipped v3 index the two agree (the fixture records both, see
 * `docs/vision-kotlin-verification.md`).
 *
 * Collapsing over the whole index rather than a fixed neighbour window is also
 * what makes the "always three candidates" requirement structural rather than
 * hopeful: the result is the true best score per species.
 *
 * `keys.json` in index-v3 already stores canonical labels (verified: none of the
 * 21 `canonical_map.json` sources appears as a key), but [resolve] implements
 * `photo_id.resolve_label`'s precedence anyway so a future index that ships raw
 * keys cannot silently split one species across several slots.
 */
class KnnIndex private constructor(
    /** Row-major `size x dim` gallery matrix. */
    private val vectors: FloatArray,
    val dim: Int,
    val keys: List<String>,
    private val canonicalByKey: Map<String, String>,
) {

    val size: Int get() = keys.size

    private val keySet: Set<String> = keys.toHashSet()

    /** Canonical label per gallery row, resolved once (16,580 entries). */
    private val canonicalOfRow: Array<String> = Array(keys.size) { resolve(keys[it]) }

    /** Distinct canonical keys — the number of species this index can return. */
    val canonicalCount: Int = canonicalOfRow.toHashSet().size

    init {
        require(vectors.size == keys.size * dim) {
            "gallery has ${vectors.size} floats but ${keys.size} keys x $dim dims " +
                "= ${keys.size * dim}"
        }
        require(keys.all { it.isNotBlank() }) { "gallery keys must not be blank" }
    }

    /** One ranked candidate. `row` is the gallery row the score came from. */
    data class Match(val key: String, val canonical: String, val score: Float, val row: Int)

    /**
     * `photo_id.resolve_label`: a label the index serves resolves to itself —
     * rewriting the index's own labels would make a correct prediction score as
     * a miss — otherwise the canonical map, otherwise the key itself.
     */
    fun resolve(key: String): String {
        if (canonicalByKey.isEmpty()) return key
        if (key in keySet) return key
        return canonicalByKey[key] ?: key
    }

    /**
     * Inner product against every row, collapsed to one entry per canonical key,
     * sorted by score (ties broken by the lower row index so a run is
     * reproducible), truncated to [k].
     */
    fun search(query: FloatArray, k: Int = 3): List<Match> {
        require(query.size == dim) {
            "query has ${query.size} dimensions but the index has $dim"
        }
        require(k >= 1) { "k must be >= 1" }

        val bestRow = HashMap<String, Int>(canonicalCount * 2)
        val bestScore = HashMap<String, Float>(canonicalCount * 2)
        for (row in 0 until keys.size) {
            val score = Vectors.dotRow(query, vectors, row * dim)
            val canonical = canonicalOfRow[row]
            val previous = bestScore[canonical]
            if (previous == null || score > previous) {
                bestScore[canonical] = score
                bestRow[canonical] = row
            }
        }
        val ranked = bestRow.keys.map { canonical ->
            val row = bestRow.getValue(canonical)
            Match(keys[row], canonical, bestScore.getValue(canonical), row)
        }.sortedWith(compareByDescending<Match> { it.score }.thenBy { it.row })
        return if (ranked.size <= k) ranked else ranked.subList(0, k)
    }

    companion object {

        /** Build from the raw shipped files (test/tooling entry point). */
        fun fromIndexDir(indexDir: File): KnnIndex {
            val embeddings = File(indexDir, "embeddings.npy")
            val keys = File(indexDir, "keys.json")
            if (!embeddings.isFile) {
                throw VisionContractException("index is missing embeddings.npy at $embeddings")
            }
            if (!keys.isFile) {
                throw VisionContractException("index is missing keys.json at $keys")
            }
            val canonical = File(indexDir, "canonical_map.json")
            return fromEmbeddingsNpy(
                embeddingsNpy = embeddings.readBytes(),
                keysJson = keys.readText(),
                canonicalJson = if (canonical.isFile) canonical.readText() else null,
            )
        }

        /**
         * Parse `embeddings.npy` + `keys.json`.
         *
         * @param canonicalJson optional `canonical_map.json` text (`{"canonical": {...}}`);
         *   the index tarball does not ship it today because v3 keys are already
         *   canonical, so null is the normal case.
         */
        fun fromEmbeddingsNpy(
            embeddingsNpy: ByteArray,
            keysJson: String,
            canonicalJson: String? = null,
        ): KnnIndex {
            val raw = Npy.parse(embeddingsNpy, "embeddings.npy")
            if (raw.shape.size != 2) {
                throw VisionContractException(
                    "embeddings.npy must be a matrix, got shape ${raw.shape.toList()}"
                )
            }
            val keys = parseKeys(keysJson)
            if (keys.size != raw.shape[0]) {
                throw VisionContractException(
                    "keys.json has ${keys.size} entries but embeddings.npy has " +
                        "${raw.shape[0]} rows — the index is internally inconsistent"
                )
            }
            return KnnIndex(
                vectors = raw.asFloats("embeddings.npy"),
                dim = raw.shape[1],
                keys = keys,
                canonicalByKey = parseCanonical(canonicalJson),
            )
        }

        /** Build directly from memory (unit tests, synthetic fixtures). */
        fun of(
            vectors: FloatArray,
            dim: Int,
            keys: List<String>,
            canonicalByKey: Map<String, String> = emptyMap(),
        ): KnnIndex = KnnIndex(vectors, dim, keys, canonicalByKey)

        private fun parseKeys(keysJson: String): List<String> {
            val parsed = VisionJson.parse(keysJson)
            val list = VisionJson.array(parsed, "keys.json")
            return list.mapIndexed { i, value ->
                if (value !is String || value.isBlank()) {
                    throw VisionContractException("keys.json[$i] is not a non-blank string")
                }
                value
            }
        }

        private fun parseCanonical(canonicalJson: String?): Map<String, String> {
            if (canonicalJson.isNullOrBlank()) return emptyMap()
            val root = VisionJson.parse(canonicalJson)
            val container = (root as? Map<*, *>)?.get("canonical") ?: root
            val map = VisionJson.obj(container, "canonical_map")
            val out = HashMap<String, String>(map.size * 2)
            for ((from, to) in map) {
                if (to is String && to.isNotBlank()) out[from] = to
            }
            return out
        }
    }
}

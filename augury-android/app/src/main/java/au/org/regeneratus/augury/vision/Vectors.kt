package au.org.regeneratus.augury.vision

import kotlin.math.sqrt

/**
 * AUGURY — vector helpers, matching `photo_id.PhotoID.embed()` exactly.
 *
 * The reference uses `vec /= (np.linalg.norm(vec) + 1e-9)` twice around the PCA
 * projection. The `1e-9` only guards against a zero vector, but it is reproduced
 * here so the Kotlin and Python numbers stay comparable at the 1e-6 level.
 *
 * Norms are accumulated in double precision: the vectors are 768-d
 * float32 with entries around 1e-2, where a float32 accumulation loses a few
 * digits for no benefit.
 */
internal object Vectors {

    const val EPS = 1e-9

    /** L2 norm in double precision. */
    fun norm(v: FloatArray): Double {
        var sum = 0.0
        for (x in v) sum += x.toDouble() * x.toDouble()
        return sqrt(sum)
    }

    /** `v /= (||v|| + 1e-9)`, in place, exactly as `photo_id.embed()` does it. */
    fun l2NormaliseInPlace(v: FloatArray) {
        val inverse = 1.0 / (norm(v) + EPS)
        for (i in v.indices) v[i] = (v[i] * inverse).toFloat()
    }

    /** A normalised copy; leaves [v] untouched. */
    fun l2Normalised(v: FloatArray): FloatArray {
        val out = v.copyOf()
        l2NormaliseInPlace(out)
        return out
    }

    /** Inner product — the score the index ranks by (all vectors are unit length). */
    fun dot(a: FloatArray, b: FloatArray): Float {
        var sum = 0.0
        for (i in a.indices) sum += a[i].toDouble() * b[i].toDouble()
        return sum.toFloat()
    }

    /**
     * Inner product of [a] with a row of a flat row-major matrix, without
     * materialising the row: the gallery is 16,580 rows and copying each one
     * would allocate 25 MB per query.
     */
    fun dotRow(a: FloatArray, data: FloatArray, offset: Int): Float {
        var sum = 0.0
        for (i in a.indices) sum += a[i].toDouble() * data[offset + i].toDouble()
        return sum.toFloat()
    }
}

package au.org.regeneratus.augury

/**
 * Thrown when the native llama.cpp layer reports a failure.
 */
class LlamaException(message: String) : RuntimeException(message)

/**
 * Kotlin facade over the hand-written JNI shim in `app/src/main/cpp/augury_jni.cpp`.
 *
 * The whole native surface is three calls:
 * ```
 * nativeInit(modelPath, nCtx, nThreads) -> handle
 * nativeGenerate(handle, system, user, temperature, maxTokens) -> String
 * nativeFree(handle)
 * ```
 *
 * Usage:
 * ```kotlin
 * LlamaEngine().use { engine ->
 *     engine.load(modelPath, nCtx = 2048, nThreads = LlamaEngine.recommendedThreads())
 *     val answer = engine.generate(system, user, temperature = 0.3f, maxTokens = 500)
 * }
 * ```
 *
 * [generate] is blocking and CPU-bound: call it from a background thread (the
 * spike Activity uses a single-thread executor).
 */
class LlamaEngine : AutoCloseable {

    private var handle: Long = 0L

    val isLoaded: Boolean get() = handle != 0L

    /**
     * Loads the GGUF at [modelPath] (mmap'd, so the weights are never copied into
     * the Java heap) and creates a [nCtx]-token context using [nThreads] threads.
     *
     * @throws LlamaException if the model cannot be loaded.
     * @throws IllegalStateException if this engine is already loaded.
     */
    fun load(modelPath: String, nCtx: Int, nThreads: Int) {
        check(handle == 0L) { "engine already loaded; call close() first" }
        require(nCtx > 0) { "nCtx must be > 0" }
        require(nThreads > 0) { "nThreads must be > 0" }
        handle = try {
            nativeInit(modelPath, nCtx, nThreads)
        } catch (t: RuntimeException) {
            throw LlamaException(t.message ?: "native init failed")
        }
    }

    /**
     * Alias for [load], matching the `nativeInit(modelPath, nCtx, nThreads)` shape
     * requested for the spike's Kotlin API.
     */
    fun `init`(modelPath: String, nCtx: Int, nThreads: Int) = load(modelPath, nCtx, nThreads)

    /**
     * Runs one full turn: renders the model's own chat template, decodes the
     * prompt and samples up to [maxTokens] tokens.
     *
     * @return the assistant text only (no prompt echo, no special tokens).
     * @throws LlamaException on a native failure.
     */
    fun generate(
        system: String,
        user: String,
        temperature: Float = 0.3f,
        maxTokens: Int = 500,
    ): String {
        val h = handle
        check(h != 0L) { "engine not loaded" }
        return try {
            nativeGenerate(h, system, user, temperature, maxTokens) ?: ""
        } catch (t: RuntimeException) {
            throw LlamaException(t.message ?: "native generate failed")
        }
    }

    /** One-line stats for the most recent [generate] call (measured, not estimated). */
    val lastStats: String
        get() = if (handle == 0L) "" else nativeLastStats(handle)

    /** e.g. `llama / Augury Formatter Merged / n_ctx_train=131072 / n_params=1106...` */
    val modelDescription: String
        get() = if (handle == 0L) "" else nativeModelDesc(handle)

    override fun close() {
        val h = handle
        handle = 0L
        if (h != 0L) {
            nativeFree(h)
        }
    }

    companion object {
        init {
            System.loadLibrary("augury_llama")
        }

        /** llama.cpp build + CPU feature string, straight from `llama_print_system_info()`. */
        @JvmStatic
        external fun nativeBackendInfo(): String

        /** Big-core count derived from the device's cpufreq topology. */
        @JvmStatic
        external fun nativeRecommendedThreads(): Int

        fun backendInfo(): String = nativeBackendInfo()

        fun recommendedThreads(): Int = nativeRecommendedThreads()

        // ---- the three-call native surface -----------------------------------
        @JvmStatic
        private external fun nativeInit(modelPath: String, nCtx: Int, nThreads: Int): Long

        @JvmStatic
        private external fun nativeGenerate(
            handle: Long,
            system: String,
            user: String,
            temperature: Float,
            maxTokens: Int,
        ): String?

        @JvmStatic
        private external fun nativeFree(handle: Long)

        @JvmStatic
        private external fun nativeLastStats(handle: Long): String

        @JvmStatic
        private external fun nativeModelDesc(handle: Long): String
    }
}

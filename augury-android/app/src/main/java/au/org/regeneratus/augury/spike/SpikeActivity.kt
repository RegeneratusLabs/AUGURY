package au.org.regeneratus.augury.spike

import android.app.Activity
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.method.ScrollingMovementMethod
import android.util.Log
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import au.org.regeneratus.augury.LlamaEngine
import au.org.regeneratus.augury.R
import java.io.File
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong

/**
 * ============================================================================
 *  GATE C / W5 SPIKE UI -- DELIBERATELY UGLY, DELIBERATELY MINIMAL.
 *
 *  This is a de-risking harness, NOT the AUGURY app UI. The real UI is owned by
 *  another workstream. Nothing in this package should be reused as-is; the only
 *  artifact that matters here is [LlamaEngine] + the JNI shim underneath it.
 * ============================================================================
 *
 * One screen: a model path, the real AUGURY system+user prompt, a Generate
 * button, and a text view showing the answer plus the *measured* elapsed time
 * and tokens/sec.
 */
class SpikeActivity : Activity() {

    companion object {
        private const val TAG = "AugurySpike"

        /** The real AUGURY formatter contract -- do not editorialise these. */
        private const val SYSTEM_PROMPT =
            "You are AUGURY, a soil health assistant specializing in weeds and plants as soil " +
                "indicators. You receive structured soil indicator data from a reliable database " +
                "and present it in clear, practical language for farmers and land managers. Never " +
                "invent or modify indicator data. Never give management, herbicide, or remediation " +
                "advice \u2014 indicators only. If asked about something outside plant soil indicators, " +
                "politely decline."

        private const val USER_PROMPT =
            "Facts from the AUGURY database (do not add or change any indicator):\n" +
                "\n" +
                "Species: Dandelion (Taraxacum officinale)\n" +
                "Region: Australia\n" +
                "Indicators:\n" +
                "- Moisture: fresh, moist soil\n" +
                "- Soil pH: neutral to slightly acidic\n" +
                "- Fertility: good fertility, high nitrogen\n" +
                "Source: Ellenberg Indicator Values\n" +
                "\n" +
                "Farmer's question: What does dandelion indicate about my soil?"

        private const val N_CTX = 2048
        private const val TEMPERATURE = 0.3f
        private const val MAX_TOKENS = 500
    }

    private val worker = Executors.newSingleThreadExecutor { r ->
        Thread(r, "augury-generate").apply { priority = Thread.NORM_PRIORITY + 1 }
    }
    private val main = Handler(Looper.getMainLooper())
    private val busy = AtomicBoolean(false)
    private val clock = AtomicLong(0L)

    private lateinit var modelPathField: EditText
    private lateinit var userPromptField: EditText
    private lateinit var generateButton: Button
    private lateinit var outputView: TextView
    private lateinit var statsView: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_spike)

        modelPathField = findViewById(R.id.modelPath)
        userPromptField = findViewById(R.id.userPrompt)
        generateButton = findViewById(R.id.generateButton)
        outputView = findViewById(R.id.output)
        statsView = findViewById(R.id.stats)

        outputView.movementMethod = ScrollingMovementMethod()

        val defaultModel = File(filesDir, "MiniCPM5-1B-AUGURY-Q4_K_M.gguf")
        modelPathField.setText(
            if (defaultModel.exists()) defaultModel.absolutePath
            else MODEL_PATH_FALLBACK
        )
        userPromptField.setText(USER_PROMPT)

        statsView.text = buildString {
            append("abi=").append(android.os.Build.SUPPORTED_ABIS.firstOrNull() ?: "?")
            append("  device=").append(android.os.Build.MODEL)
            append("  cores=").append(Runtime.getRuntime().availableProcessors())
            append("  recommendedThreads=").append(LlamaEngine.recommendedThreads())
            append('\n')
            append("llama.cpp: ").append(LlamaEngine.backendInfo())
        }

        generateButton.setOnClickListener { startGeneration() }
    }

    private fun startGeneration() {
        if (!busy.compareAndSet(false, true)) return

        val modelPath = modelPathField.text.toString().trim()
        val userPrompt = userPromptField.text.toString()
        val startedAt = System.currentTimeMillis()
        clock.set(startedAt)

        generateButton.isEnabled = false
        outputView.text = ""
        setStats("loading model + generating\u2026 (this can take minutes under QEMU/TCG)")

        Log.i(TAG, "=== generate requested: model=$modelPath nCtx=$N_CTX temp=$TEMPERATURE maxTokens=$MAX_TOKENS")

        worker.execute {
            try {
                LlamaEngine().use { engine ->
                    val tLoad0 = System.currentTimeMillis()
                    engine.load(modelPath, N_CTX, LlamaEngine.recommendedThreads())
                    val loadMs = System.currentTimeMillis() - tLoad0
                    Log.i(TAG, "model loaded in ${loadMs}ms :: ${engine.modelDescription}")

                    val tGen0 = System.currentTimeMillis()
                    val answer = engine.generate(
                        system = SYSTEM_PROMPT,
                        user = userPrompt,
                        temperature = TEMPERATURE,
                        maxTokens = MAX_TOKENS,
                    )
                    val genMs = System.currentTimeMillis() - tGen0
                    val wallMs = System.currentTimeMillis() - startedAt
                    val stats = engine.lastStats

                    Log.i(TAG, "generation took ${genMs}ms")
                    Log.i(TAG, "native stats: $stats")
                    Log.i(TAG, "ANSWER >>> $answer <<<")

                    main.post {
                        outputView.text = answer
                        setStats(formatReport(stats, wallMs))
                    }
                }
            } catch (t: Throwable) {
                val error = "${t.javaClass.simpleName}: ${t.message}"
                Log.e(TAG, "generation FAILED", t)
                main.post {
                    outputView.text = "FAILED\n\n$error"
                    setStats("FAILED after ${System.currentTimeMillis() - startedAt} ms\n$error")
                }
            } finally {
                busy.set(false)
                main.post { generateButton.isEnabled = true }
            }
        }
    }

    private fun formatReport(nativeStats: String, wallMs: Long): String {
        val parts = nativeStats.split(';').associate {
            val kv = it.split('=', limit = 2)
            if (kv.size == 2) kv[0] to kv[1] else it to ""
        }
        val genTokens = parts["gen_tokens"]?.toIntOrNull() ?: 0
        val genMs = parts["gen_ms"]?.toLongOrNull() ?: 0L
        val tps = parts["tokens_per_sec"] ?: "?"
        return buildString {
            append("=== MEASURED ===\n")
            append("total wall (load+generate): ").append(wallMs).append(" ms\n")
            append("model load:                 ").append(parts["load_ms"]).append(" ms\n")
            append("prompt tokens:              ").append(parts["prompt_tokens"])
            append("   (prompt eval ").append(parts["prompt_ms"]).append(" ms)\n")
            append("generated tokens:           ").append(genTokens).append('\n')
            append("generation time:            ").append(genMs).append(" ms\n")
            append("TOKENS/SEC:                 ").append(tps).append('\n')
            append("chat template:              ").append(parts["template"]).append('\n')
            append("n_ctx / n_threads:          ").append(parts["n_ctx"]).append(" / ")
                .append(parts["n_threads"]).append('\n')
            append("avg ms per token:           ")
            if (genTokens > 0) append(String.format("%.1f", genMs.toDouble() / genTokens))
            else append("n/a")
            append('\n')
            append("raw: ").append(nativeStats)
        }
    }

    private fun setStats(s: String) {
        statsView.text = s
    }

    override fun onDestroy() {
        super.onDestroy()
        worker.shutdownNow()
    }
}

/** Used only if the model has not been copied into filesDir yet. */
private const val MODEL_PATH_FALLBACK = "/data/local/tmp/MiniCPM5-1B-AUGURY-Q4_K_M.gguf"

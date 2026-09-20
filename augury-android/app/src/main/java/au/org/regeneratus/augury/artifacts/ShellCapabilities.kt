package au.org.regeneratus.augury.artifacts

/**
 * AUGURY — the compatibility gate (`docs/mobile-app-decision.md` §3.3).
 *
 * The shell is dynamic for *data* — species, bands, index density, a retrained
 * formatter — and deliberately rigid about *contracts*. [ShellCapabilities]
 * declares the contracts this build can execute; [ProtocolGate] compares a
 * fetched manifest against that declaration. Anything it does not recognise
 * becomes an "app update required" state, and **no artifact byte is fetched**:
 *
 * > If the manifest presents something else, the app says "this app update is
 * > required" rather than running a mismatched encoder and returning plausible
 * > garbage.
 *
 * WHY THE SETS BELOW ARE NOT "HARD-CODED VALUES"
 * ----------------------------------------------
 * Hard constraint §8 item 1 forbids compiling in anything *tunable* — a
 * threshold, a species count, a dimension, an artifact version. These are the
 * opposite: they are the shell's own capability declaration, the thing that must
 * change with an APK and can only change with an APK. They live in exactly one
 * place so that adding e.g. a v2 formatter protocol is a one-line, reviewable
 * change accompanied by the Kotlin that implements it.
 */
data class ShellCapabilities(
    /** `manifest_schema` values this build understands. */
    val manifestSchemas: Set<Int>,
    /** Artifact `protocol` values this build can execute. */
    val protocols: Set<String>,
    /** `facts.schema` values (the species DB schema) this build understands. */
    val speciesDbSchemas: Set<Int>,
    /** `vision.index.schema` values this build understands. */
    val indexSchemas: Set<Int>,
    /** `vision.preprocess.output` contracts the vision path implements. */
    val preprocessOutputs: Set<String>,
) {
    companion object {
        /** `formatter.chatml-grounded@1` — the grounded ChatML formatter contract. */
        const val FORMATTER_CHATML_GROUNDED_V1 = "formatter.chatml-grounded@1"

        /** `species.db@1` — the on-device species database contract. */
        const val SPECIES_DB_V1 = "species.db@1"

        /** `vision.clip-token-l2-pca-knn-ip@1` — CLS token → L2 → PCA-whiten → L2 → kNN inner product. */
        const val VISION_CLIP_TOKEN_L2_PCA_KNN_IP_V1 = "vision.clip-token-l2-pca-knn-ip@1"

        /** What the current APK implements. Change only alongside the code that implements it. */
        val CURRENT = ShellCapabilities(
            manifestSchemas = setOf(1),
            protocols = setOf(
                FORMATTER_CHATML_GROUNDED_V1,
                SPECIES_DB_V1,
                VISION_CLIP_TOKEN_L2_PCA_KNN_IP_V1,
            ),
            speciesDbSchemas = setOf(1),
            indexSchemas = setOf(1),
            preprocessOutputs = setOf("cls_token"),
        )
    }
}

/** The gate's verdict. */
sealed interface CompatibilityVerdict {

    /** Safe to install: every declared contract is one this build implements. */
    data object Compatible : CompatibilityVerdict

    /**
     * The manifest declares something this build cannot execute. [reasons] are
     * shown to the user verbatim.
     */
    data class UpdateRequired(val reasons: List<String>) : CompatibilityVerdict {
        fun toException(): AppUpdateRequiredException = AppUpdateRequiredException(reasons)
    }
}

object ProtocolGate {

    /**
     * Compares [manifest] against what this shell implements.
     *
     * Checks, in order: the manifest schema; every artifact's protocol; the
     * species-DB and index schemas; the encoder/index pairing (same protocol, same
     * backend — the shell must never run a mismatched encoder); and the
     * preprocessing output contract, which changes the *meaning* of the vector
     * the encoder returns.
     */
    fun check(
        manifest: ArtifactManifest,
        capabilities: ShellCapabilities = ShellCapabilities.CURRENT,
    ): CompatibilityVerdict {
        val reasons = ArrayList<String>()

        if (manifest.manifestSchema !in capabilities.manifestSchemas) {
            reasons += "manifest_schema ${manifest.manifestSchema} is not implemented by this app " +
                "(implements ${capabilities.manifestSchemas.joinToString()})"
        }

        protocolReason(reasons, "formatter", manifest.formatter.protocol, capabilities)
        protocolReason(reasons, "facts", manifest.facts.spec.protocol, capabilities)

        if (manifest.facts.schema !in capabilities.speciesDbSchemas) {
            reasons += "facts.schema ${manifest.facts.schema} is not implemented by this app " +
                "(implements ${capabilities.speciesDbSchemas.joinToString()})"
        }

        protocolReason(reasons, "vision.index", manifest.vision.index.spec.protocol, capabilities)
        if (manifest.vision.index.schema !in capabilities.indexSchemas) {
            reasons += "vision.index.schema ${manifest.vision.index.schema} is not implemented by this app " +
                "(implements ${capabilities.indexSchemas.joinToString()})"
        }

        manifest.vision.encoders.forEachIndexed { index, encoder ->
            protocolReason(reasons, "vision.encoders[$index]", encoder.spec.protocol, capabilities)
            if (encoder.spec.protocol != manifest.vision.index.spec.protocol) {
                reasons += "vision.encoders[$index] (${encoder.backend}) declares protocol " +
                    "${encoder.spec.protocol} but the index declares ${manifest.vision.index.spec.protocol} — " +
                    "refusing to run a mismatched encoder"
            }
            if (encoder.backend != manifest.vision.index.backend) {
                reasons += "vision.encoders[$index] backend \"${encoder.backend}\" does not match the index " +
                    "backend \"${manifest.vision.index.backend}\" — refusing to run a mismatched encoder"
            }
        }
        if (manifest.encoderForIndexBackend() == null) {
            reasons += "no encoder in vision.encoders targets the index backend " +
                "\"${manifest.vision.index.backend}\""
        }

        if (manifest.vision.preprocess.output !in capabilities.preprocessOutputs) {
            reasons += "vision.preprocess.output \"${manifest.vision.preprocess.output}\" is not implemented " +
                "by this app (implements ${capabilities.preprocessOutputs.joinToString()})"
        }

        return if (reasons.isEmpty()) CompatibilityVerdict.Compatible
        else CompatibilityVerdict.UpdateRequired(reasons)
    }

    private fun protocolReason(
        reasons: MutableList<String>,
        label: String,
        protocol: String,
        capabilities: ShellCapabilities,
    ) {
        if (protocol !in capabilities.protocols) {
            reasons += "$label declares protocol \"$protocol\", which this app does not implement"
        }
    }
}

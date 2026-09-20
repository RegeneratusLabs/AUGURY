package au.org.regeneratus.augury.vision

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import ai.onnxruntime.TensorInfo
import java.io.Closeable
import java.io.File
import java.nio.FloatBuffer

/**
 * AUGURY — the image encoder.
 *
 * The model is `dinov2-base-fp32.onnx` (346.5 MB), loaded through ONNX Runtime
 * Mobile. The graph is **fixed shape** — input `pixel_values` `[1, 3, 224, 224]`
 * float32, output `cls_token` `[1, 768]` — and it covers **only the CLS token**:
 * L2 normalise, PCA-whiten and L2 again are [VisionPipeline]'s job (handover §7 P1).
 *
 * Two contract decisions worth stating:
 *
 * * **fp32, never int8.** Dynamic int8 was measured on the real gallery and
 *   rejected (−70.00p top-1; the fp32 control matched PyTorch exactly, so the
 *   collapse is real). [VisionSettings] refuses a manifest that declares any
 *   other quantisation.
 * * **The tensor names and shapes come from the graph**, not from this file. The
 *   graph currently has exactly one input and one output, and both shapes are
 *   validated against the manifest (`crop`) and the index's PCA input dimension
 *   before a single photo is embedded. A graph that does not match the declared
 *   contract is an "app update required" condition, not something to guess at.
 *
 * `Encoder` is an interface so the pipeline can be driven by a stub in unit
 * tests: ONNX Runtime Mobile ships Android `.so` files, so no host JVM test can
 * load the real model (see `docs/vision-kotlin-verification.md`).
 */
interface Encoder : Closeable {
    /** The graph's output width — 768 for DINOv2-base's CLS token. */
    val outputDim: Int

    /** The graph's input element count (`3 * crop * crop`). */
    val inputSize: Int

    /** Run the graph on a CHW float32 tensor and return the CLS vector. */
    fun encode(tensor: FloatArray): FloatArray
}

/** What the graph says it is, resolved and checked against the manifest. */
class EncoderContract(
    val inputName: String,
    val outputName: String,
    val channels: Int,
    val height: Int,
    val width: Int,
    val outputDim: Int,
) {
    val inputSize: Int get() = channels * height * width

    companion object {
        /**
         * Validate the graph's declared shapes.
         *
         * Kept free of ONNX Runtime types so it is unit-testable on the host:
         * this is the part of [OnnxEncoder] that actually protects the pipeline.
         *
         * @param inputShape the graph's input shape, `-1` for a dynamic dimension
         * @param outputShape the graph's output shape
         * @param crop the manifest's crop size
         * @param expectedClsDim the PCA matrix's input width, when known
         */
        fun resolve(
            inputName: String,
            outputName: String,
            inputShape: LongArray,
            outputShape: LongArray,
            crop: Int,
            expectedClsDim: Int?,
        ): EncoderContract {
            if (inputShape.size != 4) {
                throw VisionContractException(
                    "encoder input '$inputName' has shape ${inputShape.toList()}; this build " +
                        "implements a single-image [1, 3, crop, crop] contract",
                    appUpdateRequired = true,
                )
            }
            val batch = inputShape[0].takeIf { it > 0 } ?: 1L
            val channels = inputShape[1].takeIf { it > 0 } ?: PreprocessSettings.CHANNELS.toLong()
            val height = inputShape[2].takeIf { it > 0 } ?: crop.toLong()
            val width = inputShape[3].takeIf { it > 0 } ?: crop.toLong()
            if (batch != 1L) {
                throw VisionContractException(
                    "encoder input '$inputName' declares batch $batch; this build embeds one " +
                        "photo at a time",
                    appUpdateRequired = true,
                )
            }
            if (channels != PreprocessSettings.CHANNELS.toLong()) {
                throw VisionContractException(
                    "encoder input '$inputName' declares $channels channels; the preprocessing " +
                        "contract is RGB",
                    appUpdateRequired = true,
                )
            }
            if (height != crop.toLong() || width != crop.toLong()) {
                throw VisionContractException(
                    "encoder input '$inputName' is ${height}x$width but the manifest declares " +
                        "crop=$crop — the app would feed a tensor the graph cannot accept",
                    appUpdateRequired = true,
                )
            }
            if (outputShape.isEmpty()) {
                throw VisionContractException(
                    "encoder output '$outputName' has no shape", appUpdateRequired = true
                )
            }
            val outputDim = outputShape.last()
            if (outputDim <= 0) {
                throw VisionContractException(
                    "encoder output '$outputName' has a dynamic last dimension " +
                        "(${outputShape.toList()}); this build needs a fixed CLS width",
                    appUpdateRequired = true,
                )
            }
            if (expectedClsDim != null && outputDim != expectedClsDim.toLong()) {
                throw VisionContractException(
                    "encoder emits $outputDim dimensions but the index's PCA matrix expects " +
                        "$expectedClsDim — encoder and index are from different generations",
                    appUpdateRequired = true,
                )
            }
            return EncoderContract(
                inputName = inputName,
                outputName = outputName,
                channels = channels.toInt(),
                height = height.toInt(),
                width = width.toInt(),
                outputDim = outputDim.toInt(),
            )
        }
    }
}

/**
 * ONNX Runtime Mobile implementation of [Encoder].
 *
 * Construct with the verified model bytes (the artifact pipeline hands them over
 * only after the manifest's sha256 matched) or a file path.
 *
 * Threading: one session, used from one coroutine at a time. ORT sessions are
 * thread-safe, but the pipeline's scratch buffers are not; the caller owns that
 * discipline.
 */
class OnnxEncoder private constructor(
    private val environment: OrtEnvironment,
    private val session: OrtSession,
    val contract: EncoderContract,
) : Encoder {

    override val outputDim: Int get() = contract.outputDim
    override val inputSize: Int get() = contract.inputSize

    override fun encode(tensor: FloatArray): FloatArray {
        require(tensor.size == contract.inputSize) {
            "encoder expects ${contract.inputSize} floats but got ${tensor.size}"
        }
        val shape = longArrayOf(1, contract.channels.toLong(), contract.height.toLong(),
            contract.width.toLong())
        OnnxTensor.createTensor(environment, FloatBuffer.wrap(tensor), shape).use { input ->
            session.run(mapOf(contract.inputName to input)).use { result ->
                val value = result.get(0) as? OnnxTensor
                    ?: throw VisionContractException(
                        "encoder output '${contract.outputName}' is not a tensor"
                    )
                val buffer = value.floatBuffer
                val out = FloatArray(contract.outputDim)
                buffer.get(out)
                return out
            }
        }
    }

    override fun close() {
        session.close()
        // The OrtEnvironment is a process-wide singleton; closing it here would
        // break every other session in the app.
    }

    companion object {
        /**
         * @param modelBytes the verified ONNX model
         * @param crop the manifest's crop size
         * @param expectedClsDim the index's PCA input width, when the index is loaded
         * @param intraOpThreads worker threads for the graph (ORT default when <= 0)
         */
        fun create(
            modelBytes: ByteArray,
            crop: Int,
            expectedClsDim: Int? = null,
            intraOpThreads: Int = 0,
        ): OnnxEncoder {
            if (modelBytes.isEmpty()) {
                throw VisionContractException("encoder model is empty")
            }
            val environment = OrtEnvironment.getEnvironment()
            val options = OrtSession.SessionOptions()
            options.setOptimizationLevel(OrtSession.SessionOptions.OptLevel.ALL_OPT)
            if (intraOpThreads > 0) options.setIntraOpNumThreads(intraOpThreads)
            val session = try {
                environment.createSession(modelBytes, options)
            } catch (e: Exception) {
                throw VisionContractException(
                    "could not load the ONNX encoder (${modelBytes.size} bytes): ${e.message}", e
                )
            }
            return try {
                fromSession(environment, session, crop, expectedClsDim)
            } catch (e: Throwable) {
                session.close()
                throw e
            }
        }

        /** Load from a file path (ORT maps the file rather than copying 346 MB). */
        fun create(
            modelFile: File,
            crop: Int,
            expectedClsDim: Int? = null,
            intraOpThreads: Int = 0,
        ): OnnxEncoder {
            if (!modelFile.isFile) {
                throw VisionContractException("encoder model not found: $modelFile")
            }
            val environment = OrtEnvironment.getEnvironment()
            val options = OrtSession.SessionOptions()
            options.setOptimizationLevel(OrtSession.SessionOptions.OptLevel.ALL_OPT)
            if (intraOpThreads > 0) options.setIntraOpNumThreads(intraOpThreads)
            val session = try {
                environment.createSession(modelFile.absolutePath, options)
            } catch (e: Exception) {
                throw VisionContractException(
                    "could not load the ONNX encoder at $modelFile: ${e.message}", e
                )
            }
            return try {
                fromSession(environment, session, crop, expectedClsDim)
            } catch (e: Throwable) {
                session.close()
                throw e
            }
        }

        private fun fromSession(
            environment: OrtEnvironment,
            session: OrtSession,
            crop: Int,
            expectedClsDim: Int?,
        ): OnnxEncoder {
            val inputs = session.inputNames.toList()
            val outputs = session.outputNames.toList()
            if (inputs.size != 1) {
                throw VisionContractException(
                    "encoder graph has ${inputs.size} inputs (${inputs.joinToString()}); the " +
                        "protocol is a single 'pixel_values' input",
                    appUpdateRequired = true,
                )
            }
            if (outputs.size != 1) {
                throw VisionContractException(
                    "encoder graph has ${outputs.size} outputs (${outputs.joinToString()}); the " +
                        "protocol reads a single CLS token",
                    appUpdateRequired = true,
                )
            }
            val inputShape = (session.inputInfo[inputs[0]]?.info as? TensorInfo)?.shape
                ?: throw VisionContractException(
                    "encoder input '${inputs[0]}' is not a tensor", appUpdateRequired = true
                )
            val outputShape = (session.outputInfo[outputs[0]]?.info as? TensorInfo)?.shape
                ?: throw VisionContractException(
                    "encoder output '${outputs[0]}' is not a tensor", appUpdateRequired = true
                )
            val contract = EncoderContract.resolve(
                inputName = inputs[0],
                outputName = outputs[0],
                inputShape = inputShape,
                outputShape = outputShape,
                crop = crop,
                expectedClsDim = expectedClsDim,
            )
            return OnnxEncoder(environment, session, contract)
        }
    }
}

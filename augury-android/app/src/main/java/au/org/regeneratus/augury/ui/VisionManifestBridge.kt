package au.org.regeneratus.augury.ui

import au.org.regeneratus.augury.artifacts.VisionPreprocess
import au.org.regeneratus.augury.vision.PreprocessSettings

/**
 * AUGURY — the typed manifest's preprocessing block in the shape
 * [PreprocessSettings.fromManifest] consumes.
 *
 * The gateway rebuilds the vision settings from the *typed* manifest rather than
 * re-parsing the JSON, so that what the pipeline runs is exactly the bytes the
 * artifact manager verified. That means this adapter has to reproduce the shape
 * the JSON parser would have produced, and two details are load-bearing:
 *
 *  1. **It is the `vision` block, not the `preprocess` block.**
 *     `PreprocessSettings.fromManifest(vision)` reads `vision["preprocess"]`, so
 *     handing it the inner block fails with "manifest vision.preprocess is
 *     missing".
 *  2. **The numbers must be `Double`.** `VisionJson`'s readers are written for
 *     JSON-parsed values and `num()` accepts a `Double` only, so an `Int` from the
 *     typed manifest fails with "expected a number".
 *
 * Both mistakes were live at once and are invisible to every host test: nothing on
 * a JVM can build the pipeline, because ONNX Runtime Mobile ships Android
 * libraries. The first device run found them. `VisionManifestBridgeTest` now pins
 * this mapping against the reference parse of the shipped manifest, so the next
 * one is caught on the host.
 */
fun visionPreprocessBlock(preprocess: VisionPreprocess): Map<String, Any?> = mapOf(
    "preprocess" to mapOf(
        "resize_shortest_edge" to preprocess.resizeShortestEdge.toDouble(),
        "crop" to preprocess.crop.toDouble(),
        "resample" to preprocess.resample,
        "mean" to preprocess.mean,
        "std" to preprocess.std,
        "output" to preprocess.output,
    ),
)

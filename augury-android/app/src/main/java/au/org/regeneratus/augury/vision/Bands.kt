package au.org.regeneratus.augury.vision

/**
 * AUGURY — confidence bands.
 *
 * Three bands, straight from `photo_id.py`'s `verdict()`:
 *
 * | band       | meaning                                                   |
 * |------------|-----------------------------------------------------------|
 * | `AUTO`     | top-1 >= `auto_conf` — **higher confidence, not consent**  |
 * | `CONFIRM`  | top-1 >= `confirm_conf` — show top-3 and ask the user      |
 * | `UNKNOWN`  | below `confirm_conf` — honest "not in the library"         |
 *
 * The thresholds come from the **manifest** (`vision.bands.auto_conf` /
 * `vision.bands.confirm_conf`), never from a constant in this file.  The values
 * currently published are 0.64 / 0.30 on the PCA-whitened score scale.
 *
 * ## Why the legacy pair is refused
 *
 * `photo_id.py` carries `AUTO_CONF = 0.80` / `CONFIRM_CONF = 0.60` as *legacy
 * v1 constants* for an index whose scores were raw cosine.  On the whitened
 * scale precision peaks near 0.64–0.68 and **falls above 0.75**, so 0.80 selects
 * the worst decile; `index-v3` shipped with those constants by accident and the
 * UI would have asked every user to confirm a 95%-precision identification
 * (docs/mobile-app-decision.md §4).  The app reads bands from the manifest, so
 * it cannot inherit that trap — and [fromManifest] additionally refuses the
 * exact legacy pair, because 0.80/0.60 can only be the uncalibrated defaults.
 * This is a regression guard on a known-bad pair, not a cap on future
 * recalibrations: any calibrated pair the manifest declares is accepted.
 */
data class Bands(val autoConf: Float, val confirmConf: Float) {

    init {
        require(autoConf in 0f..1f) { "auto_conf $autoConf is outside [0,1]" }
        require(confirmConf in 0f..1f) { "confirm_conf $confirmConf is outside [0,1]" }
        require(confirmConf <= autoConf) {
            "confirm_conf $confirmConf must not exceed auto_conf $autoConf"
        }
    }

    fun classify(top1Score: Float): Band = when {
        top1Score >= autoConf -> Band.AUTO
        top1Score >= confirmConf -> Band.CONFIRM
        else -> Band.UNKNOWN
    }

    companion object {
        /** The uncalibrated v1 pair on the whitened scale. Must never ship. */
        const val LEGACY_AUTO_CONF = 0.80f
        const val LEGACY_CONFIRM_CONF = 0.60f

        /** The band block of a manifest's `vision` object. */
        fun fromManifest(vision: Map<String, Any?>): Bands {
            val block = VisionJson.obj(
                vision["bands"] ?: throw VisionContractException(
                    "manifest vision.bands is missing: the app reads band thresholds from " +
                        "the manifest and will not fall back to constants"
                ),
                "vision.bands",
            )
            val auto = VisionJson.num(block["auto_conf"], "vision.bands.auto_conf").toFloat()
            val confirm = VisionJson.num(block["confirm_conf"], "vision.bands.confirm_conf").toFloat()
            if (auto == LEGACY_AUTO_CONF && confirm == LEGACY_CONFIRM_CONF) {
                throw VisionContractException(
                    "manifest declares the legacy uncalibrated bands 0.80/0.60. On the " +
                        "PCA-whitened score scale precision peaks near 0.64-0.68 and falls " +
                        "above 0.75, so 0.80 selects the worst decile (see " +
                        "docs/mobile-app-decision.md §4); this pair must be recalibrated, " +
                        "not shipped. Refusing to run."
                )
            }
            return Bands(auto, confirm)
        }

        fun fromManifest(manifestJson: String): Bands {
            val root = VisionJson.obj(VisionJson.parse(manifestJson), "manifest")
            return fromManifest(VisionJson.obj(root["vision"], "vision"))
        }
    }
}

/** The three verdicts of `photo_id.PhotoID.verdict()`. */
enum class Band { AUTO, CONFIRM, UNKNOWN }

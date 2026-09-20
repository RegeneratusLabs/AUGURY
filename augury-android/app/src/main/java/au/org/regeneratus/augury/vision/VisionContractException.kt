package au.org.regeneratus.augury.vision

/**
 * Thrown when an artifact (or the manifest that describes it) does not match the
 * contract this build of the shell implements.
 *
 * The distinction matters to the UI: [appUpdateRequired] means *this APK is too
 * old for this manifest* and the user should be told "this app update is
 * required" (docs/mobile-app-decision.md §3.3) — never that a mismatched
 * encoder ran and returned plausible garbage.  The other failures are artifact
 * defects (truncated file, wrong shape, unreadable index) and are reported as
 * such.
 */
class VisionContractException(
    message: String,
    val appUpdateRequired: Boolean = false,
    cause: Throwable? = null,
) : IllegalStateException(message, cause) {

    /**
     * Convenience for the common "artifact failed to load, here is why" case.
     *
     * Without this, `VisionContractException(msg, e)` silently binds `e` to
     * [appUpdateRequired] and fails to compile — which is exactly what happened
     * when two encoder call sites tried to attach the underlying ORT error. This
     * constructor makes the intent explicit and keeps [appUpdateRequired] `false`,
     * because a broken or unreadable model file is an artifact defect, not a
     * signal that the user needs a newer APK.
     */
    constructor(message: String, cause: Throwable) : this(
        message = message,
        appUpdateRequired = false,
        cause = cause,
    )
}

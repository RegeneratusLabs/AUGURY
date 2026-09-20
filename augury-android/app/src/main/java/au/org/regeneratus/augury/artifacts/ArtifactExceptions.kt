package au.org.regeneratus.augury.artifacts

import java.util.concurrent.CancellationException

/**
 * AUGURY — the artifact pipeline's failure vocabulary.
 *
 * Every failure mode the Setup screen has to render differently gets its own
 * type, so the UI never has to match on message strings:
 *
 * | type | what the user sees |
 * |---|---|
 * | [AppUpdateRequiredException] | "this app update is required" — the shell cannot execute what the manifest declares |
 * | [ManifestRejectedException] | "the update check returned something invalid" — tampered/stale manifest, nothing was downloaded |
 * | [OfflineException] | "connect to the internet" |
 * | [MeteredConnectionException] | "waiting for Wi-Fi" + the override toggle |
 * | [ArtifactVerificationException] | "the download was damaged; retrying" — the artifact was **not** installed |
 * | [ArtifactCancelledException] | the user cancelled; partial bytes are kept for resume |
 *
 * The security-critical ones are [ArtifactVerificationException] and
 * [ManifestRejectedException]: both are thrown *before* any pointer is flipped,
 * which is what makes "a truncated or hash-mismatched artifact must never load"
 * (§8 item 6) a structural property rather than a promise.
 */
open class ArtifactException(message: String, cause: Throwable? = null) : Exception(message, cause)

/** The manifest could not be fetched at all (network failure, non-200, too large). */
class ManifestFetchException(message: String, cause: Throwable? = null) : ArtifactException(message, cause)

/** The manifest was fetched but is not a manifest this shell will act on: malformed, or its generation digest does not match its own body. */
class ManifestRejectedException(message: String, cause: Throwable? = null) : ArtifactException(message, cause)

/** A field of the manifest was missing, of the wrong type, or out of range. */
class ManifestFormatException(message: String) : ArtifactException(message)

/**
 * The manifest is well-formed but declares something this shell does not
 * implement (manifest schema, artifact protocol, DB/index schema, preprocessing
 * output contract). The UI must show "this app update is required" and must not
 * start a download. See `docs/mobile-app-decision.md` §3.3.
 */
class AppUpdateRequiredException(val reasons: List<String>) : ArtifactException(
    "this app update is required: " + reasons.joinToString("; ")
)

/** No usable network right now. */
class OfflineException(message: String = "no network connection") : ArtifactException(message)

/** The connection is metered and Wi-Fi-only mode is on. */
class MeteredConnectionException(
    message: String = "this download is waiting for Wi-Fi (metered connection refused)",
) : ArtifactException(message)

/** The server answered with an unexpected HTTP status. */
class DownloadHttpException(val statusCode: Int, val url: String, message: String? = null) :
    ArtifactException(message ?: "HTTP $statusCode from $url")

/** The server answered 200/206/416 in a way that makes resuming unsafe. */
class DownloadProtocolException(message: String) : ArtifactException(message)

/** The response body ended before its declared length: a truncated artifact. */
class TruncatedBodyException(message: String) : ArtifactException(message)

/** The completed download's length does not match the manifest's `bytes`. */
class ArtifactSizeMismatchException(
    val artifactName: String,
    val expectedBytes: Long,
    val actualBytes: Long,
) : ArtifactException(
    "artifact $artifactName is $actualBytes bytes but the manifest declares $expectedBytes"
)

/**
 * SHA-256 of the completed download does not match the manifest. The file is
 * deleted and nothing is promoted — a hash mismatch means the bytes are not the
 * bytes that were published, whether from corruption or tampering.
 */
class ArtifactVerificationException(
    val artifactName: String,
    val expectedSha256: String,
    val actualSha256: String,
) : ArtifactException(
    "SHA-256 mismatch for $artifactName: expected $expectedSha256 but computed $actualSha256; " +
        "the artifact was discarded and NOT installed"
)

/** The user cancelled. Partial bytes stay on disk so the next attempt can resume. */
class ArtifactCancelledException(message: String = "download cancelled") : CancellationException(message)

/** A generation directory named by a pointer is gone. */
class GenerationMissingException(message: String) : ArtifactException(message)

/** The index tarball could not be unpacked, or contains something the shell refuses. */
class IndexUnpackException(message: String, cause: Throwable? = null) : ArtifactException(message, cause)

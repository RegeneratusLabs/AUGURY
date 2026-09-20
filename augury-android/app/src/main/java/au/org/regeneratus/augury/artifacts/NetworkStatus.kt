package au.org.regeneratus.augury.artifacts

/**
 * AUGURY — connectivity, behind an interface.
 *
 * The pipeline needs exactly two answers before it starts moving ~1 GB:
 * "is there a network?" and "is it metered?". Both come from Android's
 * `ConnectivityManager` on the device, and from a settable fake in tests, so the
 * Wi-Fi-only rule is unit-testable rather than device-testable.
 */
interface NetworkStatus {

    /** True when there is a validated network that can reach the internet. */
    fun isOnline(): Boolean

    /**
     * True when the active network is metered (mobile data, or a hotspot the OS
     * flags as metered). Only consulted while Wi-Fi-only mode is on.
     */
    fun isMetered(): Boolean

    companion object {
        /** A stand-in for tests and for callers that have not wired connectivity yet. */
        val ALWAYS_ONLINE: NetworkStatus = object : NetworkStatus {
            override fun isOnline(): Boolean = true
            override fun isMetered(): Boolean = false
        }
    }
}

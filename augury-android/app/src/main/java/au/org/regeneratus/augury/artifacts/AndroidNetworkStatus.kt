package au.org.regeneratus.augury.artifacts

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities

/**
 * AUGURY — the device implementation of [NetworkStatus].
 *
 * Kept apart from the interface on purpose: everything else in
 * `au.org.regeneratus.augury.artifacts` is plain JVM code exercised by the
 * unit tests, and touching `android.*` would force the tests onto a device or
 * into Robolectric.
 *
 * REQUIRES `android.permission.ACCESS_NETWORK_STATE` in
 * `app/src/main/AndroidManifest.xml`. That file is owned by another workstream;
 * without the permission [activeCapabilities] returns `null` and the pipeline
 * reports "offline" rather than downloading blind, which is the safe failure.
 */
class AndroidNetworkStatus(context: Context) : NetworkStatus {

    private val connectivityManager =
        context.applicationContext.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager

    override fun isOnline(): Boolean {
        val capabilities = activeCapabilities() ?: return false
        return capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) &&
            capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)
    }

    override fun isMetered(): Boolean {
        // An unknown network is treated as metered: refusing to spend the user's
        // data by accident is the right default, and the override exists.
        val capabilities = activeCapabilities() ?: return true
        return !capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED)
    }

    private fun activeCapabilities(): NetworkCapabilities? {
        val network = connectivityManager.activeNetwork ?: return null
        return connectivityManager.getNetworkCapabilities(network)
    }
}

package au.org.regeneratus.augury.ui

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.remember
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewmodel.compose.viewModel
import au.org.regeneratus.augury.ui.theme.AuguryTheme

/**
 * The app's only launcher activity.
 *
 * The gateway is resolved once, here, and handed to [AuguryViewModel]. It is the
 * single place that decides between the real pipeline and the reviewable
 * [DemoGateway], which keeps every screen free of that decision.
 *
 * **Wiring status.** [AuguryGatewayImpl] is the production gateway (manifest +
 * artifact download + ONNX retrieval + llama.cpp). Until it is present in the
 * build, this falls back to [DemoGateway], which renders every screen from the
 * real species database with no model. [AppGraph.gateway] is the seam to change
 * when the real one lands -- nothing else in `ui/` needs to move.
 */
class MainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)

        val gateway = AppGraph.gateway(this)

        setContent {
            AuguryTheme {
                val vm: AuguryViewModel = viewModel(
                    factory = remember(gateway) { AuguryViewModelFactory(gateway) },
                )
                AuguryApp(vm)
            }
        }
    }
}

/**
 * Resolves the app's collaborators. Deliberately a tiny hand-rolled graph: adding
 * Hilt or Koin for one object would be more machinery than the app has objects.
 */
object AppGraph {

    /**
     * The production gateway — the downloader + species DB + vision + engine.
     *
     * **No demo fallback here, deliberately.** [DemoGateway] reads
     * `data/app/augury-ondevice.json` from a *repo* path, which exists on a
     * developer's machine and on no phone. Falling back to it would hand a device
     * an app whose picker is permanently empty — a silent, confusing failure.
     * Failing to construct the real gateway is a genuine startup fault, so it is
     * reported as one. (The demo gateway still exists for tests and previews; it
     * is simply not a production code path.)
     */
    fun gateway(activity: ComponentActivity): AuguryGateway =
        AuguryGatewayImpl.create(activity) ?: error(
            "AUGURY could not initialise its storage. The app needs a writable " +
                "files directory to download and verify its model data.",
        )
}

private class AuguryViewModelFactory(
    private val gateway: AuguryGateway,
) : ViewModelProvider.Factory {
    @Suppress("UNCHECKED_CAST")
    override fun <T : ViewModel> create(modelClass: Class<T>): T =
        AuguryViewModel(gateway) as T
}

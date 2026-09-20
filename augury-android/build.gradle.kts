// Top-level build file. Plugin versions are pinned here and applied per-module.
plugins {
    id("com.android.application") version "8.13.1" apply false
    id("org.jetbrains.kotlin.android") version "2.1.20" apply false
    // Kotlin 2.x requires the Compose compiler to arrive as a Gradle plugin whose
    // version tracks the Kotlin version -- there is no
    // composeOptions.kotlinCompilerExtensionVersion any more.
    id("org.jetbrains.kotlin.plugin.compose") version "2.1.20" apply false
}

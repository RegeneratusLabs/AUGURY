import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

// ---------------------------------------------------------------------------
// Pinned llama.cpp commit (Gate C / W5 spike)
// ---------------------------------------------------------------------------
val llamaCppDir = rootProject.layout.projectDirectory.dir("third_party/llama.cpp")
val llamaCppPinnedCommit = "60081bb2b5b3294165a4d67c5cbeebe74c868014"

android {
    namespace = "au.org.regeneratus.augury"
    compileSdk = 36
    ndkVersion = "27.1.12297006"

    defaultConfig {
        applicationId = "au.org.regeneratus.augury"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "0.1.0-spike"

        ndk {
            // x86_64 is required because the only AVD on this host is x86_64.
            // arm64-v8a is the real device target.
            abiFilters += listOf("arm64-v8a", "x86_64")
        }

        externalNativeBuild {
            cmake {
                // CMAKE_BUILD_TYPE is chosen per-ABI below via buildTypes; keep args minimal.
                arguments += listOf(
                    "-DANDROID_STL=c++_shared",
                    "-DCMAKE_BUILD_TYPE=Release",
                )
                cppFlags += listOf("-O3")
            }
        }
    }

    externalNativeBuild {
        cmake {
            path = file("src/main/cpp/CMakeLists.txt")
            version = "3.22.1"
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            // Keep the spike debuggable so `adb shell run-as` / logcat evidence is easy to grab.
            isDebuggable = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"))
        }
        debug {
            isMinifyEnabled = false
        }
    }

    /**
     * Per-ABI APKs.
     *
     * A "fat" APK carrying both ABIs is 97 MB, but the two ONNX Runtime builds are
     * 32 MB (arm64) and 38 MB (x86_64) and a device needs exactly one. Splitting
     * means a real phone downloads only the arm64 half. x86_64 exists solely for
     * the emulator, which cannot run on the build host (no /dev/kvm), so it is a
     * developer convenience rather than something to ship.
     */
    splits {
        abi {
            isEnable = true
            reset()
            include("arm64-v8a", "x86_64")
            // Keep producing the universal APK too, so the existing
            // `app/build/outputs/apk/debug/app-debug.apk` path and the handover's
            // documented build command keep working unchanged.
            isUniversalApk = true
        }
    }

    packaging {
        jniLibs {
            useLegacyPackaging = false
        }
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
        }
    }

    buildFeatures {
        viewBinding = false
        compose = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    // The native build is expensive; keep it out of the unit-test variant.
    testOptions {
        unitTests.isIncludeAndroidResources = false
    }
}

dependencies {
    // Kotlin stdlib arrives automatically via the Kotlin Gradle plugin.

    // ---- UI: Jetpack Compose (Material 3) -----------------------------------
    // Versions come from the BOM so the Compose artifacts cannot drift apart.
    val composeBom = platform("androidx.compose:compose-bom:2026.06.00")
    implementation(composeBom)
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-graphics")
    implementation("androidx.compose.material3:material3")
    // Deliberately NOT material-icons-extended: it is the single largest dex
    // contributor in this app and the UI draws its own iconography from a handful
    // of glyphs. Add the specific icons artifact only if a real Material icon is
    // needed later.
    implementation("androidx.activity:activity-compose:1.13.0")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.9.4")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.9.4")
    implementation("androidx.core:core-ktx:1.17.0")

    // ---- Vision: ONNX Runtime Mobile ----------------------------------------
    // The fp32 DINOv2 encoder is the only shipped quantisation (int8 was measured
    // and rejected -- see docs/mobile-app-decision.md 5.1).
    implementation("com.microsoft.onnxruntime:onnxruntime-android:1.29.0")

    // ---- Artifact unpacking --------------------------------------------------
    // The vision index ships as .tar.gz; java.util.zip handles the gzip half but
    // the platform has no tar reader, so commons-compress supplies it.
    implementation("org.apache.commons:commons-compress:1.27.1")

    // ---- Tests ---------------------------------------------------------------
    // The ported core (au.org.regeneratus.augury.core) deliberately uses no
    // android.* types, so :app:testDebugUnitTest needs no device and no Robolectric.
    testImplementation("junit:junit:4.13.2")
}

// ---------------------------------------------------------------------------
// Unit tests: pure JVM, headless.
//
// The golden-parity tests read the *repo* data files by path (they must be the
// same bytes the app ships), so the repo root is handed to the test JVM rather
// than guessed. AGP's default working directory for unit tests is the module
// dir, and AuguryPaths also falls back to walking up from there.
// ---------------------------------------------------------------------------
tasks.withType<Test>().configureEach {
    systemProperty("augury.repo.root", rootProject.projectDir.parentFile.absolutePath)
    testLogging {
        events("passed", "failed", "skipped")
        showStandardStreams = true
        exceptionFormat = org.gradle.api.tasks.testing.logging.TestExceptionFormat.FULL
    }
}

// ---------------------------------------------------------------------------
// Helper task: assert the vendored llama.cpp is at the pinned commit.
// ---------------------------------------------------------------------------
tasks.register("checkLlamaCppPin") {
    group = "verification"
    description = "Verify third_party/llama.cpp is checked out at the pinned commit."
    doLast {
        val gitDir = llamaCppDir.dir(".git").asFile
        if (!gitDir.exists()) {
            logger.warn("llama.cpp .git not found - skipping pin check (vendored tarball?)")
            return@doLast
        }
        val head = providers.exec {
            commandLine("git", "-C", llamaCppDir.asFile.absolutePath, "rev-parse", "HEAD")
        }.standardOutput.asText.get().trim()
        if (head != llamaCppPinnedCommit) {
            throw GradleException(
                "llama.cpp is at $head but this project pins $llamaCppPinnedCommit. " +
                    "Run scripts/fetch-llama-cpp.sh to restore the pinned revision."
            )
        }
        logger.lifecycle("llama.cpp pin OK: $head")
    }
}

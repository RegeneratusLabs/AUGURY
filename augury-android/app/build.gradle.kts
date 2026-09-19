import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
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
    // Intentionally minimal. The spike uses plain android.app.Activity + framework
    // views so that the build needs no AndroidX/Material artifacts at all --
    // fewer moving parts for a de-risking spike. The real app module will add them.
    //
    // Kotlin stdlib is added automatically by the Kotlin Gradle plugin.
    //
    // JUnit 4 for the pure-JVM unit tests under src/test/java. The ported core
    // (au.org.regeneratus.augury.core) deliberately uses no android.* types, so
    // :app:testDebugUnitTest needs no device, no emulator and no Robolectric.
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

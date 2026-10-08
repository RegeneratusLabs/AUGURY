// ---------------------------------------------------------------------------
// AUGURY -- stub implementation of the LlamaEngine JNI surface.
//
// WHY THIS FILE EXISTS
// --------------------
// The shipped AUGURY build is template-only: `ShellCapabilities.USES_STORY_MODEL`
// is false, `formatterModelFile()` returns null unconditionally, and
// `AuguryGatewayImpl.generateDraft()` returns before it ever touches
// `LlamaEngine`. The native formatter is therefore dead code in the app that
// ships, and the real `augury_jni.cpp` only ever compiles when llama.cpp is
// vendored under `augury-android/third_party/llama.cpp`.
//
// That vendored tree is gitignored, is not a git submodule, and is absent from a
// clean clone -- so `CMakeLists.txt` used to abort the whole build with
// FATAL_ERROR, and *no one* could build the app from a fresh checkout.
//
// This stub keeps the JNI contract intact instead:
//
//   * a clean clone builds without llama.cpp (this file compiles, the real one
//     does not);
//   * `System.loadLibrary("augury_llama")` still resolves, so `LlamaEngine` can
//     be class-loaded without an UnsatisfiedLinkError;
//   * any attempt to actually run the formatter fails loudly and explicitly
//     rather than silently returning an empty answer.
//
// To build the real engine, run `augury-android/scripts/fetch-llama-cpp.sh` and
// rebuild; CMake selects the real sources automatically.
// ---------------------------------------------------------------------------
#include <jni.h>

#include <unistd.h>

#include <algorithm>
#include <string>

#define AUGURY_JNI(ret, name) \
    JNIEXPORT ret JNICALL Java_au_org_regeneratus_augury_LlamaEngine_##name

namespace {

constexpr const char * kNotBuilt =
    "AUGURY was built without llama.cpp: this APK is the template-only build, "
    "which renders the story deterministically and never loads a model. To use "
    "the native formatter, run augury-android/scripts/fetch-llama-cpp.sh and "
    "rebuild.";

jstring to_jstring(JNIEnv * env, const std::string & s) {
    return env->NewStringUTF(s.c_str());
}

void throw_runtime(JNIEnv * env, const char * msg) {
    jclass cls = env->FindClass("java/lang/RuntimeException");
    if (cls != nullptr) {
        env->ThrowNew(cls, msg);
    }
}

} // namespace

extern "C" {

AUGURY_JNI(jlong, nativeInit)(JNIEnv * env, jclass, jstring, jint, jint) {
    throw_runtime(env, kNotBuilt);
    return 0;
}

AUGURY_JNI(jstring, nativeGenerate)(JNIEnv * env,
                                    jclass,
                                    jlong,
                                    jstring,
                                    jstring,
                                    jfloat,
                                    jint) {
    throw_runtime(env, kNotBuilt);
    return nullptr;
}

AUGURY_JNI(jstring, nativeGenerateStream)(JNIEnv * env,
                                          jclass,
                                          jlong,
                                          jstring,
                                          jstring,
                                          jfloat,
                                          jint,
                                          jobject) {
    throw_runtime(env, kNotBuilt);
    return nullptr;
}

AUGURY_JNI(void, nativeFree)(JNIEnv *, jclass, jlong) {
    // No-op: the stub never allocates an engine.
}

AUGURY_JNI(jstring, nativeLastStats)(JNIEnv * env, jclass, jlong) {
    return to_jstring(env, "llama.cpp: not built (template-only APK)");
}

AUGURY_JNI(jstring, nativeModelDesc)(JNIEnv * env, jclass, jlong) {
    return to_jstring(env, "no model loaded (template-only APK)");
}

AUGURY_JNI(jstring, nativeBackendInfo)(JNIEnv * env, jclass) {
    return to_jstring(env, "llama.cpp: not built (template-only APK)");
}

AUGURY_JNI(jint, nativeRecommendedThreads)(JNIEnv *, jclass) {
    // Only reachable from the spike harness in a stub build; a plausible value
    // is better than 0 so the harness cannot divide by it.
    const long cores = sysconf(_SC_NPROCESSORS_ONLN);
    const long half = cores > 0 ? cores / 2 : 1;
    return static_cast<jint>(std::max(1L, half));
}

} // extern "C"

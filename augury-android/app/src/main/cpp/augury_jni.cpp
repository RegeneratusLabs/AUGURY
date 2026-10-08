// ---------------------------------------------------------------------------
// AUGURY Gate C / W5 spike -- JNI surface for au.org.regeneratus.augury.LlamaEngine
//
// Deliberately tiny; everything real lives in augury_engine.cpp.
//
//   nativeInit(modelPath, nCtx, nThreads) -> handle (long)
//   nativeGenerate(handle, system, user, temperature, maxTokens) -> String
//   nativeGenerateStream(handle, system, user, temperature, maxTokens, sink)
//   nativeFree(handle)
//
// `sink` is any object with `boolean onPiece(String piece)`. It is called on the
// generation thread -- the same thread that entered this JNI function -- so the
// JNIEnv it needs is the one passed in here and no AttachCurrentThread is
// required. Returning false from onPiece stops generation early; the text
// produced so far is still written back to the sink's accumulator on the Kotlin
// side.
//
// Two extra read-only helpers exist only to surface *measured* evidence:
//   nativeLastStats(handle)  -> one-line stats for the most recent generate()
//   nativeBackendInfo()      -> llama.cpp build + CPU feature string
// ---------------------------------------------------------------------------
#include <jni.h>

#include <string>

#include "augury_engine.h"

#define AUGURY_JNI(ret, name) \
    JNIEXPORT ret JNICALL Java_au_org_regeneratus_augury_LlamaEngine_##name

namespace {

std::string to_string(JNIEnv * env, jstring s) {
    if (s == nullptr) {
        return std::string();
    }
    const char * chars = env->GetStringUTFChars(s, nullptr);
    if (chars == nullptr) {
        return std::string();
    }
    std::string out(chars);
    env->ReleaseStringUTFChars(s, chars);
    return out;
}

jstring to_jstring(JNIEnv * env, const std::string & s) {
    return env->NewStringUTF(s.c_str());
}

void throw_runtime(JNIEnv * env, const std::string & msg) {
    jclass cls = env->FindClass("java/lang/RuntimeException");
    if (cls != nullptr) {
        env->ThrowNew(cls, msg.c_str());
    }
}

augury::Engine * as_engine(jlong handle) {
    return reinterpret_cast<augury::Engine *>(static_cast<intptr_t>(handle));
}

} // namespace

extern "C" {

AUGURY_JNI(jlong, nativeInit)(JNIEnv * env, jclass, jstring j_model_path, jint n_ctx, jint n_threads) {
    const std::string model_path = to_string(env, j_model_path);

    auto * engine = new augury::Engine();
    std::string err;
    if (!engine->init(model_path, (int) n_ctx, (int) n_threads, err)) {
        delete engine;
        throw_runtime(env, "LlamaEngine.init failed: " + err);
        return 0;
    }
    return static_cast<jlong>(reinterpret_cast<intptr_t>(engine));
}

AUGURY_JNI(jstring, nativeGenerate)(JNIEnv * env,
                                    jclass,
                                    jlong       handle,
                                    jstring     j_system,
                                    jstring     j_user,
                                    jfloat      temperature,
                                    jint        max_tokens) {
    augury::Engine * engine = as_engine(handle);
    if (engine == nullptr || !engine->ready()) {
        throw_runtime(env, "LlamaEngine.generate: engine handle is null or not initialised");
        return nullptr;
    }

    const std::string system_prompt = to_string(env, j_system);
    const std::string user_prompt   = to_string(env, j_user);

    std::string out;
    std::string err;
    if (!engine->generate(system_prompt, user_prompt, (float) temperature, (int) max_tokens, out, err)) {
        throw_runtime(env, "LlamaEngine.generate failed: " + err);
        return nullptr;
    }
    return to_jstring(env, out);
}

AUGURY_JNI(jstring, nativeGenerateStream)(JNIEnv * env,
                                          jclass,
                                          jlong       handle,
                                          jstring     j_system,
                                          jstring     j_user,
                                          jfloat      temperature,
                                          jint        max_tokens,
                                          jobject     sink) {
    augury::Engine * engine = as_engine(handle);
    if (engine == nullptr || !engine->ready()) {
        throw_runtime(env, "LlamaEngine.generateStream: engine handle is null or not initialised");
        return nullptr;
    }
    if (sink == nullptr) {
        throw_runtime(env, "LlamaEngine.generateStream: sink is null");
        return nullptr;
    }

    // Resolve onPiece once, before any decoding: a lookup failure is a
    // programming error, not a per-token one, and must not be swallowed.
    jclass sink_cls = env->GetObjectClass(sink);
    jmethodID on_piece = sink_cls != nullptr
        ? env->GetMethodID(sink_cls, "onPiece", "(Ljava/lang/String;)Z")
        : nullptr;
    if (on_piece == nullptr) {
        if (env->ExceptionCheck()) {
            env->ExceptionClear();
        }
        throw_runtime(env, "LlamaEngine.generateStream: sink has no boolean onPiece(String)");
        return nullptr;
    }

    const std::string system_prompt = to_string(env, j_system);
    const std::string user_prompt   = to_string(env, j_user);

    bool sink_failed = false;

    augury::Engine::TokenCallback callback =
        [env, sink, on_piece, &sink_failed](const std::string & piece) -> bool {
            if (sink_failed) {
                return false;
            }
            jstring j_piece = env->NewStringUTF(piece.c_str());
            if (j_piece == nullptr) {
                // Out of memory, or the piece was not valid modified UTF-8. Both
                // are fatal to the stream; stop rather than spam the JVM.
                sink_failed = true;
                return false;
            }
            jboolean keep_going = env->CallBooleanMethod(sink, on_piece, j_piece);
            env->DeleteLocalRef(j_piece);
            if (env->ExceptionCheck()) {
                // The Kotlin sink threw. Let the exception propagate: the caller
                // asked for a stream and a broken consumer must not be silent.
                sink_failed = true;
                return false;
            }
            return keep_going == JNI_TRUE;
        };

    std::string out;
    std::string err;
    const bool ok = engine->generate_stream(
        system_prompt, user_prompt, (float) temperature, (int) max_tokens,
        callback, out, err);

    if (!ok) {
        throw_runtime(env, "LlamaEngine.generateStream failed: " + err);
        return nullptr;
    }
    // An exception raised by the sink is already pending; returning now lets the
    // JVM deliver it to the caller of generateStream().
    if (sink_failed && env->ExceptionCheck()) {
        return nullptr;
    }
    return to_jstring(env, out);
}

AUGURY_JNI(void, nativeFree)(JNIEnv *, jclass, jlong handle) {
    augury::Engine * engine = as_engine(handle);
    if (engine != nullptr) {
        delete engine;  // dtor calls free()
    }
}

AUGURY_JNI(jstring, nativeLastStats)(JNIEnv * env, jclass, jlong handle) {
    augury::Engine * engine = as_engine(handle);
    if (engine == nullptr) {
        return to_jstring(env, "");
    }
    const augury::GenStats & s = engine->last_stats();
    char buf[512];
    snprintf(buf, sizeof(buf),
             "load_ms=%lld;prompt_tokens=%d;prompt_ms=%lld;gen_tokens=%d;gen_ms=%lld;"
             "tokens_per_sec=%.3f;template=%s;n_ctx=%d;n_threads=%d",
             (long long) s.load_ms, s.prompt_tokens, (long long) s.prompt_ms,
             s.gen_tokens, (long long) s.gen_ms, s.tokens_per_sec,
             s.template_source.c_str(), s.n_ctx, s.n_threads);
    return to_jstring(env, buf);
}

AUGURY_JNI(jstring, nativeModelDesc)(JNIEnv * env, jclass, jlong handle) {
    augury::Engine * engine = as_engine(handle);
    return to_jstring(env, engine != nullptr ? engine->model_desc() : std::string());
}

AUGURY_JNI(jstring, nativeBackendInfo)(JNIEnv * env, jclass) {
    return to_jstring(env, augury::backend_info());
}

AUGURY_JNI(jint, nativeRecommendedThreads)(JNIEnv *, jclass) {
    return (jint) augury::recommended_thread_count();
}

} // extern "C"

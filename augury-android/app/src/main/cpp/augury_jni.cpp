// ---------------------------------------------------------------------------
// AUGURY Gate C / W5 spike -- JNI surface for au.org.regeneratus.augury.LlamaEngine
//
// Deliberately tiny; everything real lives in augury_engine.cpp.
//
//   nativeInit(modelPath, nCtx, nThreads) -> handle (long)
//   nativeGenerate(handle, system, user, temperature, maxTokens) -> String
//   nativeFree(handle)
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

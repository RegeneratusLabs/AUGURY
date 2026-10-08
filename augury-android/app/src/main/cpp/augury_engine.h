// ---------------------------------------------------------------------------
// AUGURY Gate C / W5 spike -- llama.cpp engine core (no JNI in this file).
//
// Kept free of <jni.h> on purpose so the exact same translation unit can be
// compiled into a plain host binary (tools/host_test.cpp) and validated on the
// build machine before it is cross-compiled for Android.
// ---------------------------------------------------------------------------
#pragma once

#include <cstdint>
#include <functional>
#include <string>
#include <vector>

#include "llama.h"

namespace augury {

struct GenStats {
    int64_t     load_ms        = 0;
    int32_t     prompt_tokens  = 0;
    int32_t     gen_tokens     = 0;
    int64_t     prompt_ms      = 0;
    int64_t     gen_ms         = 0;
    double      tokens_per_sec = 0.0;
    std::string template_source;   // "embedded-chat-template" | "chatml-fallback"
    int32_t     n_ctx          = 0;
    int32_t     n_threads      = 0;
};

class Engine {
public:
    Engine() = default;
    ~Engine();

    Engine(const Engine &)            = delete;
    Engine & operator=(const Engine &) = delete;

    /// Called once per generated piece with the text of that piece. Returning
    /// false stops generation early (the caller has seen enough). It runs on the
    /// thread that called generate()/generate_stream(), which is also the thread
    /// that owns the JNI env, so a JNI callback needs no AttachCurrentThread.
    using TokenCallback = std::function<bool(const std::string &)>;

    /// Loads the GGUF (mmap) and creates the context. Returns false and fills
    /// `err` on failure.
    bool init(const std::string & model_path, int n_ctx, int n_threads, std::string & err);

    /// Renders the chat prompt, decodes it and greedily/temperature-samples up to
    /// `max_tokens` tokens. Returns false and fills `err` on failure.
    bool generate(const std::string & system_prompt,
                  const std::string & user_prompt,
                  float               temperature,
                  int                 max_tokens,
                  std::string &       out_text,
                  std::string &       err);

    /// The same turn as generate(), but hands each piece to `on_piece` as it is
    /// produced instead of only returning the whole answer. The accumulated text
    /// is written to `out_text` as well, so a caller that ignores the callback
    /// sees exactly what generate() would have returned. Returning false from
    /// `on_piece` stops the loop and is not an error: `out_text` then holds the
    /// prefix produced so far and the call still returns true.
    bool generate_stream(const std::string & system_prompt,
                         const std::string & user_prompt,
                         float               temperature,
                         int                 max_tokens,
                         const TokenCallback & on_piece,
                         std::string &       out_text,
                         std::string &       err);

    void free();
    bool ready() const { return model_ != nullptr && ctx_ != nullptr; }

    const GenStats &    last_stats() const { return last_stats_; }
    const std::string & model_desc() const { return model_desc_; }
    const std::string & chat_template() const { return chat_template_; }

private:
    /// The shared body of generate() and generate_stream(). `on_piece` may be an
    /// empty std::function, in which case pieces are only accumulated.
    bool run_turn(const std::string & system_prompt,
                  const std::string & user_prompt,
                  float               temperature,
                  int                 max_tokens,
                  const TokenCallback & on_piece,
                  std::string &       out_text,
                  std::string &       err);

    bool render_prompt(const std::string & system_prompt,
                       const std::string & user_prompt,
                       std::string &       out,
                       std::string &       source,
                       std::string &       err);

    std::vector<llama_token> tokenize(const std::string & text, bool add_special, std::string & err);

    std::string token_to_text(llama_token token) const;

    llama_model *       model_ = nullptr;
    llama_context *     ctx_   = nullptr;
    const llama_vocab * vocab_ = nullptr;

    std::string chat_template_;
    std::string model_desc_;
    int         n_ctx_     = 0;
    int         n_threads_ = 0;

    GenStats last_stats_;
};

/// llama.cpp build/CPU capability string (for evidence in the UI + logs).
std::string backend_info();

/// Number of "big" cores available on this device. Android exposes the CPU
/// topology through sysfs; we take the highest max-frequency cluster and count
/// the CPUs in it. Falls back to half the online CPUs (>= 2).
int recommended_thread_count();

} // namespace augury

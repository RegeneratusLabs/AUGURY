// ---------------------------------------------------------------------------
// AUGURY Gate C / W5 spike -- llama.cpp engine core.
// ---------------------------------------------------------------------------
#include "augury_engine.h"

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <mutex>
#include <thread>

#ifdef __ANDROID__
#include <android/log.h>
#define AUGURY_LOG_TAG "AuguryLlama"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO,  AUGURY_LOG_TAG, __VA_ARGS__)
#define LOGW(...) __android_log_print(ANDROID_LOG_WARN,  AUGURY_LOG_TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, AUGURY_LOG_TAG, __VA_ARGS__)
#else
#define LOGI(...) do { fprintf(stderr, "[I] " __VA_ARGS__); fprintf(stderr, "\n"); } while (0)
#define LOGW(...) do { fprintf(stderr, "[W] " __VA_ARGS__); fprintf(stderr, "\n"); } while (0)
#define LOGE(...) do { fprintf(stderr, "[E] " __VA_ARGS__); fprintf(stderr, "\n"); } while (0)
#endif

namespace augury {

namespace {

using clock_t_ = std::chrono::steady_clock;

int64_t ms_since(clock_t_::time_point t0) {
    return std::chrono::duration_cast<std::chrono::milliseconds>(clock_t_::now() - t0).count();
}

std::once_flag g_backend_once;

void log_callback(enum ggml_log_level level, const char * text, void * /*user_data*/) {
    if (text == nullptr) {
        return;
    }
    switch (level) {
        case GGML_LOG_LEVEL_ERROR: LOGW("llama: %s", text); break;
        case GGML_LOG_LEVEL_WARN:  LOGW("llama: %s", text); break;
        case GGML_LOG_LEVEL_INFO:  LOGI("llama: %s", text); break;
        default: break;  // drop DEBUG/CONT to keep logcat readable
    }
}

// Fixed seed: the spike must be reproducible run-to-run.
constexpr uint32_t kSeed = 1234;

// Prompt-processing batch. Kept small because the output/logits buffer in
// llama_context is sized n_vocab * n_outputs_max and this model has a 130k vocab.
constexpr int kBatch = 256;

} // namespace

std::string backend_info() {
    const char * info = llama_print_system_info();
    return info != nullptr ? std::string(info) : std::string("(unavailable)");
}

int recommended_thread_count() {
    // Use the biggest cores only. On big.LITTLE Android SoCs the little cores
    // drag down a CPU-bound llama_decode, and on the x86_64 emulator all cores
    // are equivalent so this simply returns the online count.
    unsigned hw = std::thread::hardware_concurrency();
    if (hw == 0) {
        hw = 4;
    }

    int best = 0;
    for (int cpu = 0; cpu < 32; ++cpu) {
        char path[128];
        snprintf(path, sizeof(path), "/sys/devices/system/cpu/cpu%d/cpufreq/cpuinfo_max_freq", cpu);
        FILE * f = fopen(path, "r");
        if (f == nullptr) {
            continue;
        }
        long khz = 0;
        if (fscanf(f, "%ld", &khz) == 1 && khz > best) {
            best = (int) khz;
        }
        fclose(f);
    }

    if (best <= 0) {
        // No cpufreq (emulator, or kernel without the driver): half the CPUs,
        // at least 2 so we still get some parallelism.
        return std::max(2u, hw / 2);
    }

    int big = 0;
    for (int cpu = 0; cpu < 32; ++cpu) {
        char path[128];
        snprintf(path, sizeof(path), "/sys/devices/system/cpu/cpu%d/cpufreq/cpuinfo_max_freq", cpu);
        FILE * f = fopen(path, "r");
        if (f == nullptr) {
            continue;
        }
        long khz = 0;
        if (fscanf(f, "%ld", &khz) == 1 && khz >= (long) (best * 0.9)) {
            ++big;
        }
        fclose(f);
    }

    if (big <= 0) {
        big = (int) std::max(2u, hw / 2);
    }
    return std::min(big, (int) hw);
}

Engine::~Engine() {
    free();
}

void Engine::free() {
    if (ctx_ != nullptr) {
        llama_free(ctx_);
        ctx_ = nullptr;
    }
    if (model_ != nullptr) {
        llama_model_free(model_);
        model_ = nullptr;
    }
    vocab_ = nullptr;
}

bool Engine::init(const std::string & model_path, int n_ctx, int n_threads, std::string & err) {
    std::call_once(g_backend_once, []() {
        llama_log_set(log_callback, nullptr);
        llama_backend_init();
    });

    if (model_path.empty()) {
        err = "model path is empty";
        return false;
    }

    const auto t_load0 = clock_t_::now();

    llama_model_params mparams = llama_model_default_params();
    mparams.n_gpu_layers = 0;
    // mmap the weights: the 688 MB Q4_K_M file stays in the page cache and is
    // never copied into the (much smaller) app heap.
    mparams.load_mode    = LLAMA_LOAD_MODE_MMAP;
    mparams.use_extra_bufts = false;

    LOGI("loading model (mmap) from %s", model_path.c_str());
    model_ = llama_model_load_from_file(model_path.c_str(), mparams);
    if (model_ == nullptr) {
        err = "llama_model_load_from_file failed for " + model_path;
        return false;
    }

    vocab_ = llama_model_get_vocab(model_);

    {
        char arch[128] = "?";
        char name[256] = "?";
        llama_model_meta_val_str(model_, "general.architecture", arch, sizeof(arch));
        llama_model_meta_val_str(model_, "general.name", name, sizeof(name));

        char desc[640];
        snprintf(desc, sizeof(desc), "%s / %s / n_ctx_train=%u / n_params=%lld",
                 arch, name,
                 llama_n_ctx_train(model_),
                 (long long) llama_model_n_params(model_));
        model_desc_ = desc;
    }

    const char * tmpl = llama_model_chat_template(model_, nullptr);
    chat_template_ = tmpl != nullptr ? std::string(tmpl) : std::string();
    LOGI("embedded chat template: %s (%zu bytes)",
         chat_template_.empty() ? "NONE" : "present", chat_template_.size());

    llama_context_params cparams = llama_context_default_params();
    cparams.n_ctx     = (uint32_t) n_ctx;
    cparams.n_batch   = (uint32_t) kBatch;
    cparams.n_ubatch  = (uint32_t) kBatch;
    cparams.n_seq_max = 1;
    // Only ever ask for one token's logits -> logits buffer is n_vocab floats,
    // not n_vocab * n_batch. This matters a lot in a 3 GB emulator.
    cparams.n_outputs_max = 1;
    cparams.n_threads       = n_threads;
    cparams.n_threads_batch = n_threads;
    cparams.no_perf         = true;
    cparams.flash_attn_type = LLAMA_FLASH_ATTN_TYPE_DISABLED;
    // f16 KV cache keeps the 2048-token cache at ~48 MB for this model
    // (24 layers x 2 kv heads x 128 dim x 2 tensors x 2 bytes x 2048).
    cparams.type_k = GGML_TYPE_F16;
    cparams.type_v = GGML_TYPE_F16;

    ctx_ = llama_init_from_model(model_, cparams);
    if (ctx_ == nullptr) {
        err = "llama_init_from_model failed (n_ctx=" + std::to_string(n_ctx) + ")";
        llama_model_free(model_);
        model_ = nullptr;
        return false;
    }

    if (llama_n_ctx(ctx_) < (uint32_t) n_ctx) {
        LOGW("requested n_ctx=%d but context only has %u", n_ctx, llama_n_ctx(ctx_));
    }

    n_ctx_     = (int) llama_n_ctx(ctx_);
    n_threads_ = n_threads;

    last_stats_.load_ms = ms_since(t_load0);
    last_stats_.n_ctx   = n_ctx_;
    last_stats_.n_threads = n_threads_;

    LOGI("model ready: %s (load %lld ms, n_ctx=%d, n_threads=%d)",
         model_desc_.c_str(), (long long) last_stats_.load_ms, n_ctx_, n_threads_);
    return true;
}

bool Engine::render_prompt(const std::string & system_prompt,
                           const std::string & user_prompt,
                           std::string &       out,
                           std::string &       source,
                           std::string &       err) {
    out.clear();
    source = "chatml-fallback";

    llama_chat_message msgs[2];
    msgs[0].role    = "system";
    msgs[0].content = system_prompt.c_str();
    msgs[1].role    = "user";
    msgs[1].content = user_prompt.c_str();

    if (!chat_template_.empty()) {
        // llama_chat_apply_template does NOT run Jinja: it pattern-matches a
        // fixed list of known templates. The embedded MiniCPM5 template is a
        // real Jinja template, so this only works because llama.cpp recognises
        // its `<|im_start|>` marker and maps it onto the built-in "chatml"
        // formatter. The result is validated below; if it does not look like
        // ChatML we fall back to formatting it by hand.
        std::vector<char> buf(2 * (system_prompt.size() + user_prompt.size()) + 8192);
        int32_t n = llama_chat_apply_template(chat_template_.c_str(), msgs, 2, /*add_ass=*/true,
                                              buf.data(), (int32_t) buf.size());
        if (n > (int32_t) buf.size()) {
            buf.resize((size_t) n + 1);
            n = llama_chat_apply_template(chat_template_.c_str(), msgs, 2, true, buf.data(),
                                          (int32_t) buf.size());
        }
        if (n > 0) {
            std::string candidate(buf.data(), (size_t) n);
            if (candidate.find("<|im_start|>") != std::string::npos &&
                candidate.find("<|im_end|>") != std::string::npos) {
                out    = candidate;
                source = "embedded-chat-template";
            } else {
                LOGW("embedded template produced non-ChatML output; using manual ChatML");
            }
        } else {
            LOGW("llama_chat_apply_template returned %d; using manual ChatML", n);
        }
    }

    if (out.empty()) {
        // MiniCPM5 non-tools ChatML branch, transcribed from tokenizer.chat_template.
        out  = "<|im_start|>system\n" + system_prompt + "<|im_end|>\n";
        out += "<|im_start|>user\n" + user_prompt + "<|im_end|>\n";
        out += "<|im_start|>assistant\n";
        source = "chatml-fallback";
    }

    if (out.empty()) {
        err = "empty prompt";
        return false;
    }
    return true;
}

std::vector<llama_token> Engine::tokenize(const std::string & text, bool add_special, std::string & err) {
    // First call sizes the buffer. A negative return is the required capacity.
    int32_t n = llama_tokenize(vocab_, text.c_str(), (int32_t) text.size(), nullptr, 0, add_special, true);
    if (n < 0) {
        n = -n;
    }
    if (n <= 0) {
        err = "llama_tokenize returned no tokens";
        return {};
    }
    std::vector<llama_token> tokens((size_t) n);
    const int32_t got = llama_tokenize(vocab_, text.c_str(), (int32_t) text.size(), tokens.data(),
                                       (int32_t) tokens.size(), add_special, /*parse_special=*/true);
    if (got < 0) {
        err = "llama_tokenize buffer too small";
        return {};
    }
    tokens.resize((size_t) got);
    return tokens;
}

std::string Engine::token_to_text(llama_token token) const {
    char buf[256];
    int32_t n = llama_token_to_piece(vocab_, token, buf, (int32_t) sizeof(buf), 0, /*special=*/false);
    if (n >= 0) {
        return std::string(buf, (size_t) n);
    }
    // Buffer too small: -n is the required size.
    std::vector<char> big((size_t) (-n) + 1);
    n = llama_token_to_piece(vocab_, token, big.data(), (int32_t) big.size(), 0, false);
    if (n < 0) {
        return std::string();
    }
    return std::string(big.data(), (size_t) n);
}

bool Engine::generate(const std::string & system_prompt,
                      const std::string & user_prompt,
                      float               temperature,
                      int                 max_tokens,
                      std::string &       out_text,
                      std::string &       err) {
    out_text.clear();
    if (!ready()) {
        err = "engine not initialised";
        return false;
    }
    if (max_tokens <= 0) {
        err = "max_tokens must be > 0";
        return false;
    }

    // Fresh sequence: drop whatever the previous call left in the KV cache.
    llama_memory_clear(llama_get_memory(ctx_), true);

    std::string prompt;
    std::string tmpl_source;
    if (!render_prompt(system_prompt, user_prompt, prompt, tmpl_source, err)) {
        return false;
    }

    // The embedded ChatML template does not emit BOS, but this model sets
    // tokenizer.ggml.add_bos_token=true. Add it via add_special unless the
    // rendered prompt already starts with the literal BOS piece.
    const bool want_bos = llama_vocab_get_add_bos(vocab_);
    bool prompt_has_bos = false;
    const llama_token bos = llama_vocab_bos(vocab_);
    if (bos != LLAMA_TOKEN_NULL) {
        const std::string bos_piece = token_to_text(bos);
        if (!bos_piece.empty() && prompt.compare(0, bos_piece.size(), bos_piece) == 0) {
            prompt_has_bos = true;
        }
    }

    std::vector<llama_token> toks = tokenize(prompt, want_bos && !prompt_has_bos, err);
    if (toks.empty()) {
        if (err.empty()) {
            err = "prompt tokenised to zero tokens";
        }
        return false;
    }

    if ((int) toks.size() >= n_ctx_) {
        err = "prompt (" + std::to_string(toks.size()) + " tokens) does not fit in n_ctx=" +
              std::to_string(n_ctx_);
        return false;
    }
    const int room = n_ctx_ - (int) toks.size() - 1;
    if (max_tokens > room) {
        LOGW("max_tokens %d clamped to %d to stay inside n_ctx=%d", max_tokens, room, n_ctx_);
        max_tokens = room;
    }

    last_stats_.prompt_tokens  = (int32_t) toks.size();
    last_stats_.template_source = tmpl_source;
    last_stats_.gen_tokens     = 0;
    last_stats_.gen_ms         = 0;
    last_stats_.tokens_per_sec = 0.0;

    LOGI("prompt: %d tokens (template=%s), max_tokens=%d, temp=%.2f",
         (int) toks.size(), tmpl_source.c_str(), max_tokens, (double) temperature);

    llama_batch batch = llama_batch_init(kBatch, /*embd=*/0, /*n_seq_max=*/1);
    llama_sampler * smpl = nullptr;
    bool ok = false;

    const auto t_prompt0 = clock_t_::now();

    // ---- 1. decode the prompt in kBatch-sized chunks -----------------------
    int32_t pos = 0;
    for (size_t i = 0; i < toks.size(); i += (size_t) kBatch) {
        const int32_t chunk = (int32_t) std::min((size_t) kBatch, toks.size() - i);
        batch.n_tokens = chunk;
        for (int32_t j = 0; j < chunk; ++j) {
            batch.token[j]     = toks[i + (size_t) j];
            batch.pos[j]       = pos + j;
            batch.n_seq_id[j]  = 1;
            batch.seq_id[j][0] = 0;
            batch.logits[j]    = 0;
        }
        // Only the final position of the chunk needs logits (n_outputs_max = 1).
        batch.logits[chunk - 1] = 1;

        if (llama_decode(ctx_, batch) != 0) {
            err = "llama_decode failed on prompt chunk at pos " + std::to_string(pos);
            goto cleanup;
        }
        pos += chunk;
    }

    last_stats_.prompt_ms = ms_since(t_prompt0);

    // ---- 2. sampler chain ---------------------------------------------------
    {
        llama_sampler_chain_params sp = llama_sampler_chain_default_params();
        sp.no_perf = true;
        smpl = llama_sampler_chain_init(sp);
        llama_sampler_chain_add(smpl, llama_sampler_init_top_k(40));
        llama_sampler_chain_add(smpl, llama_sampler_init_top_p(0.95f, 1));
        llama_sampler_chain_add(smpl, llama_sampler_init_min_p(0.05f, 1));
        llama_sampler_chain_add(smpl, llama_sampler_init_temp(temperature));
        llama_sampler_chain_add(smpl, llama_sampler_init_dist(kSeed));
    }

    // ---- 3. generation loop -------------------------------------------------
    {
        const auto t_gen0 = clock_t_::now();
        llama_token cur = llama_sampler_sample(smpl, ctx_, -1);

        while (last_stats_.gen_tokens < max_tokens) {
            if (llama_vocab_is_eog(vocab_, cur)) {
                LOGI("hit end-of-generation token after %d tokens", last_stats_.gen_tokens);
                break;
            }

            out_text += token_to_text(cur);
            last_stats_.gen_tokens += 1;

            batch.n_tokens     = 1;
            batch.token[0]     = cur;
            batch.pos[0]       = pos;
            batch.n_seq_id[0]  = 1;
            batch.seq_id[0][0] = 0;
            batch.logits[0]    = 1;

            if (llama_decode(ctx_, batch) != 0) {
                // Keep whatever we produced; the text is still valid evidence.
                LOGW("llama_decode failed during generation at token %d", last_stats_.gen_tokens);
                break;
            }
            ++pos;

            cur = llama_sampler_sample(smpl, ctx_, -1);
        }
        last_stats_.gen_ms = ms_since(t_gen0);
    }

    if (last_stats_.gen_ms > 0 && last_stats_.gen_tokens > 0) {
        last_stats_.tokens_per_sec =
            (double) last_stats_.gen_tokens * 1000.0 / (double) last_stats_.gen_ms;
    }
    ok = true;

cleanup:
    if (smpl != nullptr) {
        llama_sampler_free(smpl);
    }
    llama_batch_free(batch);
    return ok;
}

} // namespace augury

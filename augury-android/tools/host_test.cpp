// ---------------------------------------------------------------------------
// AUGURY -- host test harness for the Android engine core.
//
// WHY THIS EXISTS
// ---------------
// This host has no /dev/kvm, so the x86_64 Android emulator falls back to
// QEMU-TCG. TCG is (a) glacially slow for a 1B model and (b) missing AVX/F16C,
// which SIGILLs an AVX2-built ggml. So the emulator cannot prove the engine
// works.
//
// This harness compiles the EXACT SAME augury_engine.cpp that ships inside
// libaugury_llama.so, against the same pinned llama.cpp, as a plain Linux
// binary. If it generates coherent AUGURY output here, then the engine's
// llama.cpp API usage, chat-template handling, sampling and tokenisation are
// all correct -- the only remaining unproven step is the arm64 .so loading on a
// real phone.
//
// Build (see scripts/host-test.sh):
//   cmake -S tools -B build/host && cmake --build build/host -j
// Run:
//   ./build/host/augury_host_test <model.gguf> [n_threads]
// ---------------------------------------------------------------------------
#include "augury_engine.h"

#include <chrono>
#include <cstdio>
#include <string>

namespace {

const char * kSystemPrompt =
    "You are AUGURY, a soil health assistant specializing in weeds and plants as "
    "soil indicators. You receive structured soil indicator data from a reliable "
    "database and present it in clear, practical language for farmers and land "
    "managers. Never invent or modify indicator data. Never give management, "
    "herbicide, or remediation advice \xe2\x80\x94 indicators only. If asked about something "
    "outside plant soil indicators, politely decline.";

// The real formatter contract, byte-for-byte as scripts/augury_funnel.py builds it.
const char * kUserPrompt =
    "Facts from the AUGURY database (do not add or change any indicator):\n"
    "\n"
    "Species: Dandelion (Taraxacum officinale)\n"
    "Region: Australia\n"
    "Indicators:\n"
    "- Moisture: fresh, moist soil\n"
    "- Soil pH: neutral to slightly acidic\n"
    "- Fertility: good fertility, high nitrogen\n"
    "Source: Ellenberg Indicator Values\n"
    "\n"
    "Farmer's question: What does dandelion indicate about my soil?";

} // namespace

int main(int argc, char ** argv) {
    if (argc < 2) {
        std::fprintf(stderr, "usage: %s <model.gguf> [n_threads]\n", argv[0]);
        return 2;
    }
    const std::string model_path = argv[1];
    const int n_threads = (argc >= 3) ? std::atoi(argv[2]) : augury::recommended_thread_count();
    const int n_ctx     = 2048;

    std::printf("== AUGURY host engine test ==\n");
    std::printf("backend      : %s\n", augury::backend_info().c_str());
    std::printf("model        : %s\n", model_path.c_str());
    std::printf("n_ctx        : %d\n", n_ctx);
    std::printf("n_threads    : %d\n", n_threads);
    std::fflush(stdout);

    augury::Engine engine;
    std::string    err;

    auto t0 = std::chrono::steady_clock::now();
    if (!engine.init(model_path, n_ctx, n_threads, err)) {
        std::fprintf(stderr, "INIT FAILED: %s\n", err.c_str());
        return 1;
    }
    auto t1 = std::chrono::steady_clock::now();
    const auto load_ms =
        std::chrono::duration_cast<std::chrono::milliseconds>(t1 - t0).count();

    std::printf("model desc   : %s\n", engine.model_desc().c_str());
    std::printf("load_ms      : %lld\n", static_cast<long long>(load_ms));
    std::printf("\n-- prompt template actually used --\n%s\n", engine.chat_template().c_str());
    std::printf("-- end template --\n\n");
    std::fflush(stdout);

    // Same generation parameters the shim ships with.
    std::string out;
    auto        g0 = std::chrono::steady_clock::now();
    if (!engine.generate(kSystemPrompt, kUserPrompt, 0.3f, 500, out, err)) {
        std::fprintf(stderr, "GENERATE FAILED: %s\n", err.c_str());
        return 1;
    }
    auto g1 = std::chrono::steady_clock::now();
    const auto wall_ms =
        std::chrono::duration_cast<std::chrono::milliseconds>(g1 - g0).count();

    const augury::GenStats & st = engine.last_stats();

    std::printf("== OUTPUT ==\n%s\n== END OUTPUT ==\n\n", out.c_str());
    std::printf("== STATS ==\n");
    std::printf("prompt_tokens    : %d\n", st.prompt_tokens);
    std::printf("gen_tokens       : %d\n", st.gen_tokens);
    std::printf("prompt_ms        : %lld\n", static_cast<long long>(st.prompt_ms));
    std::printf("gen_ms           : %lld\n", static_cast<long long>(st.gen_ms));
    std::printf("tokens_per_sec   : %.2f\n", st.tokens_per_sec);
    std::printf("wall_ms          : %lld\n", static_cast<long long>(wall_ms));
    std::printf("template_source  : %s\n", st.template_source.c_str());
    std::fflush(stdout);

    // ---- streaming parity ---------------------------------------------------
    // generate_stream() must be the same turn as generate(), delivered in
    // pieces. The model is seeded, so a second run is the control: the
    // concatenation of the streamed pieces must equal the whole answer exactly.
    //
    // `pieces` is accumulated by the callback ONLY. `streamed` is filled by
    // generate_stream() itself -- accumulating it in the callback too would
    // double every piece and make the parity check below vacuous, which is
    // exactly what the first version of this harness did.
    std::string streamed;
    std::string pieces;
    int         piece_count = 0;
    std::printf("\n== STREAM ==\n");
    std::fflush(stdout);

    auto s0 = std::chrono::steady_clock::now();
    const bool stream_ok = engine.generate_stream(
        kSystemPrompt, kUserPrompt, 0.3f, 500,
        [&](const std::string & piece) -> bool {
            pieces += piece;
            ++piece_count;
            std::fputs(piece.c_str(), stdout);
            std::fflush(stdout);
            // Stop early on the first 40 pieces: proves the stop path works and
            // keeps the control run cheap.
            return piece_count < 40;
        },
        streamed, err);
    auto s1 = std::chrono::steady_clock::now();
    const auto stream_ms =
        std::chrono::duration_cast<std::chrono::milliseconds>(s1 - s0).count();

    std::printf("\n== END STREAM ==\n");
    std::printf("stream_pieces    : %d\n", piece_count);
    std::printf("stream_chars     : %zu\n", streamed.size());
    std::printf("stream_ms        : %lld\n", static_cast<long long>(stream_ms));
    std::fflush(stdout);

    if (!stream_ok) {
        std::fprintf(stderr, "STREAM FAILED: %s\n", err.c_str());
        return 1;
    }
    if (piece_count == 0 || streamed.empty()) {
        std::fprintf(stderr, "FAIL: generate_stream produced nothing\n");
        return 1;
    }
    // The callback saw exactly the text the accumulator holds: a stream that
    // silently drops or duplicates a piece is the bug this pins.
    if (pieces != streamed) {
        std::fprintf(stderr, "FAIL: streamed pieces (%zu bytes) != accumulated (%zu bytes)\n",
                     pieces.size(), streamed.size());
        return 1;
    }
    // The early stop must have stopped it.
    if (piece_count != 40) {
        std::fprintf(stderr, "FAIL: callback asked to stop at 40 pieces, saw %d\n", piece_count);
        return 1;
    }
    // The streamed prefix is a prefix of the whole answer: the stream is the same
    // turn delivered earlier, not a different one. This is the assertion that
    // would catch a sampler or template drift between the two entry points.
    if (out.compare(0, streamed.size(), streamed) != 0) {
        std::fprintf(stderr,
                     "FAIL: the streamed prefix is not a prefix of generate()'s output\n"
                     "  streamed: %.80s...\n  full    : %.80s...\n",
                     streamed.c_str(), out.c_str());
        return 1;
    }

    engine.free();

    // Non-zero exit if the model produced nothing usable -- a silent empty
    // string is the failure mode that would otherwise look like success.
    if (out.empty()) {
        std::fprintf(stderr, "FAIL: empty output\n");
        return 1;
    }
    return 0;
}
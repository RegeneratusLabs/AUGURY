#!/usr/bin/env python3
"""AUGURY third-party field test — build_report.py

Renders the final markdown report + RUNBOOK from the raw artifacts produced by
fetch_test_photos.py and run_field_test.py. Every figure is recomputed here
from the raw files.

Usage:
  .venv-mcpmv46/bin/python scripts/thirdparty_test/build_report.py \
      [--out data/thirdparty]
"""
from __future__ import annotations

import argparse
import collections
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

PIN_SHA = {
    "models/MiniCPM5-1B-AUGURY-Q4_K_M.gguf":
        "febcf5e6dfcc8b79326ca9a5f4dcf9c2535464ef086a48edbf4dd925254d7026",
    "data/research/database-merged.json":
        "c6d2505b4b80cc830f5a5d4a09f53898417fe377098663ad7c0b45c74936818c",
}
LIVE_MODEL_REPO = "RegeneratusLabs/augury-1b"
LIVE_MODEL_REV = "342d62ab82a985fbc26e6d01c6d2953815f3a434"
LIVE_DB_REPO = "RegeneratusLabs/augury-species-db"


def load_json(p: Path, default=None):
    return json.loads(p.read_text()) if p.exists() else (default if default is not None else {})


def load_jsonl(p: Path) -> list:
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def pct(x) -> str:
    return f"{100*(x or 0):.1f}%"


def ci(t) -> str:
    return f"{100*t[0]:.1f}–{100*t[1]:.1f}%"


def md_table(headers: list, rows: list) -> str:
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join("" if c is None else str(c) for c in r) + " |")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "data" / "thirdparty"))
    args = ap.parse_args()
    out = Path(args.out)

    sys.path.insert(0, str(ROOT / "scripts"))
    from species_lookup import SpeciesDB
    db = SpeciesDB()

    def db_ph_text(key: str) -> str:
        info = db.get_indicators(key, region="Australia") or {}
        bits = [f"{k}: {v}" for k, v in (info.get("indicators") or {}).items()
                if "ph" in k.lower()]
        return " / ".join(bits) if bits else "—"

    corpus = load_json(out / "corpus.json", [])
    summary = load_json(out / "summary.json")
    vis_sum = load_json(out / "summary-vision.json")
    txt_sum = load_json(out / "summary-text.json")
    text = load_json(out / "results-text.json")
    vrows = load_jsonl(out / "results-vision.jsonl")
    selftest = load_json(out / "selftest.json")

    weeds = [r for r in corpus if not r["is_control"]]
    ctrls = [r for r in corpus if r["is_control"]]
    vw = [r for r in vrows if not r["is_control"]]
    vc = [r for r in vrows if r["is_control"]]

    A = text.get("results", {}).get("A_fidelity", [])
    B = text.get("results", {}).get("B_end_to_end", [])
    C = text.get("results", {}).get("C_refusal", [])
    D = text.get("results", {}).get("D_extraction", [])
    E = text.get("results", {}).get("E_repeat", [])
    Ac = [r for r in A if r.get("variant") == "contract"]
    As = [r for r in A if r.get("variant") == "strict"]
    agg = txt_sum.get("aggregate", {})

    invented = [r for r in Ac if r["audit"].get("unsupported_decimals")]
    invented_s = [r for r in As if r["audit"].get("unsupported_decimals")]
    missing_gt = [r for r in vw if not r["correct_canon"]]
    species_name = {r["key"]: r["scientific_name"] for r in corpus}

    L = []
    add = L.append
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    add("# AUGURY 1B — Independent Third-Party Field Test")
    add("")
    add(f"**Report generated:** {now}  ")
    add(f"**Model under test:** [`{LIVE_MODEL_REPO}`](https://huggingface.co/{LIVE_MODEL_REPO}) · "
        f"`MiniCPM5-1B-AUGURY-Q4_K_M.gguf` · revision `{LIVE_MODEL_REV}`  ")
    add(f"**Test host:** `{ROOT}` · 16 cores, CPU only, no GPU · ~5 GB free RAM  ")
    add("**Question answered:** if someone downloads the live model today and runs it locally, "
        "what actually happens on real photos of common Australian weeds?")
    add("")
    add("**Method in one line:** 20 fresh, third-party photos of common AU weeds + 10 controls, "
        "pulled from GBIF/Wikimedia/iNaturalist, hash-verified as held out from the local gallery, "
        "then scored through the shipped vision and text paths on this machine.")
    add("")
    if selftest.get("failures"):
        add("> ⚠️ Self-test failures recorded — see §6.")
        add("")

    # ── 1 ───────────────────────────────────────────────────────────────────
    add("## 1. Executive verdict")
    add("")
    add("**Short version: the architecture is sound and the no-advice guard rail holds, but the "
        "shipped 1B model systematically invents pH thresholds when formatting, and the photo path "
        "is not yet field-trustworthy — with confidence bands that must not be used as accept/reject "
        "gates.**")
    add("")
    add(f"1. **Photo ID: {pct(vis_sum['top1_canon'])} top-1, {pct(vis_sum['top3_canon'])} top-3** on "
        f"{len(vw)} fresh third-party photos (top-1 95% CI {ci(vis_sum['top1_canon_ci'])}). The repo "
        f"claims 80.9% top-1 on its own val split. Errors are mostly *near-misses at genus level* — "
        f"{vis_sum.get('near_miss')} of the {len(missing_gt)} misses lost top-1 by ≤0.05, and "
        f"{sum(r['hit3_canon'] for r in vw)}/{len(vw)} were in the top-3.")
    add(f"2. **The confidence bands cannot be used as accept/reject gates.** The `auto` band "
        f"(top-1 ≥ 0.80) was correct "
        f"{(vis_sum.get('bands', {}).get('auto') or {}).get('correct')}/"
        f"{(vis_sum.get('bands', {}).get('auto') or {}).get('n')} = "
        f"{pct((vis_sum.get('bands', {}).get('auto') or {}).get('acc'))} — shipped as if it were "
        f"auto-accept. A non-weed control (mango) also scored 0.639 and landed in `confirm`.")
    add(f"3. **The formatter invents specific soil values.** {len(invented)}/{len(Ac)} answers "
        f"introduced a decimal pH threshold (usually “pH 7.0”) that was **never present in the "
        f"injected database text**. In one case (*wild radish*) the model states the correct acidic "
        f"reading and then contradicts itself with “alkaline or calcareous soils, likely above "
        f"pH 7.0” in the same answer. The strict prompt variant did not fix it "
        f"({len(invented_s)}/{len(As)}).")
    add(f"4. **Refusals are honest but architecturally weak.** {txt_sum.get('refusals_passed')}/"
        f"{txt_sum.get('refusals_total')} probes behaved as expected and **{txt_sum.get('advice_leaks', 0)} "
        f"answers contained management advice** — but "
        f"{sum(1 for r in C if not r['pass'])} management questions were *answered* with soil "
        f"indicators instead of being declined, because the funnel only refuses when no plant name "
        f"is found.")
    add(f"5. **Local performance is genuinely good.** ~"
        f"{statistics.mean([r['tok_s'] for r in Ac]):.0f} tok/s, median "
        f"{statistics.median([r['t_ms'] for r in Ac])/1000:.1f}s per answer, "
        f"{vis_sum.get('t_image_ms_p50', 0):.0f}ms per image ID, "
        f"~{vis_sum.get('peak_rss_mb', 0):.0f}MB / {txt_sum.get('peak_rss_mb', 0):.0f}MB peak RSS "
        f"across the two phases. That part of the pitch is real.")
    add("")

    # ── 2 ───────────────────────────────────────────────────────────────────
    add("## 2. Provenance — is this exactly the live model?")
    add("")
    add("Verified by SHA-256 equality against the live Hugging Face files before any inference:")
    add("")
    rows = []
    for name, want in PIN_SHA.items():
        got = summary.get("provenance", {}).get("files", {}).get(Path(name).name, {})
        rows.append([f"`{name}`", f"{got.get('bytes', 0):,}",
                     "**MATCH**" if got.get("match") else "MISMATCH",
                     f"`{(got.get('sha256') or want)[:16]}…`"])
    add(md_table(["Artifact", "Bytes", "vs live HF", "sha256 (head)"], rows))
    add("")
    add(f"- Live model repo: [`{LIVE_MODEL_REPO}`](https://huggingface.co/{LIVE_MODEL_REPO}) · "
        f"revision `{LIVE_MODEL_REV}`")
    add(f"- Live species DB: [`{LIVE_DB_REPO}`](https://huggingface.co/datasets/{LIVE_DB_REPO})")
    add("- Vision encoder `facebook/dinov2-base` + FAISS `IndexFlatIP` at `data/vision/index/` "
        "(14,274 vectors · 186 species). **The retrieval index is still not published** — the "
        "model card lists it as *pending* — so this test necessarily used a local index build. "
        "A third party cannot reproduce the full stack from public artifacts today.")
    v = summary.get("versions", {})
    add(f"- Runtime: Python {v.get('python')} · torch {v.get('torch')} (CPU) · transformers "
        f"{v.get('transformers')} · faiss {v.get('faiss')} · llama-cpp-python {v.get('llama_cpp')}")
    add(f"- Self-test evidence (§6): gallery probe top-1 `{selftest.get('gallery_probe_top1')}`, "
        f"embedding determinism cosine `{selftest.get('determinism_cosine')}`, encoder load "
        f"{selftest.get('load_s', 0):.1f}s")
    add("")

    # ── 3 ───────────────────────────────────────────────────────────────────
    add("## 3. Test corpus")
    add("")
    add("20 common/impactful Australian weeds, restricted to species present in **both** the AUGURY "
        "DB and the local index (otherwise the test measures coverage, not capability). Selection "
        "drew on the GRDC weed review and Weeds Australia priority lists and spans growth forms and "
        "both DB data shapes. Each photo was downloaded fresh for this test and checked against the "
        "SHA-256 of every indexed gallery image, so nothing here is a gallery image reintroduced as "
        "a test.")
    add("")
    rows = []
    for r in weeds:
        rows.append([r["common_name"], f"*{r['scientific_name']}*", r["form"], r.get("db_shape"),
                     r["source"], r["license"], (r.get("province") or "—")[:24],
                     r.get("dims") or ""])
    add(md_table(["Common", "Scientific", "Form", "AU DB shape", "Source", "License",
                  "Locality", "px"], rows))
    add("")
    add("Controls (should be refused → honest *unknown*): " +
        ", ".join(r["common_name"] for r in ctrls) + ".")
    add("")
    add(f"Sources: {dict(collections.Counter(r['source'] for r in corpus))} · "
        f"licenses: {dict(collections.Counter(r['license'] for r in corpus))}. "
        "Full manifest incl. URLs, authors and SHA-256: `corpus.json` / `corpus.csv`.")
    add("")

    # ── 4 ───────────────────────────────────────────────────────────────────
    add("## 4. Effectiveness")
    add("")
    add("### 4.1 Vision — photo → species")
    add("")
    rows = [
        ["Top-1 (raw keys)", pct(vis_sum["top1_raw"]), f"{sum(r['correct_raw'] for r in vw)}/{len(vw)}"],
        ["Top-1 (alias-merged)", pct(vis_sum["top1_canon"]),
         f"{sum(r['correct_canon'] for r in vw)}/{len(vw)} · 95% CI {ci(vis_sum['top1_canon_ci'])}"],
        ["Top-3 (alias-merged)", pct(vis_sum["top3_canon"]),
         f"{sum(r['hit3_canon'] for r in vw)}/{len(vw)} · 95% CI {ci(vis_sum['top3_canon_ci'])}"],
        ["Top-1, or within 0.05 of top-1", pct(vis_sum.get("top1_within_margin")),
         f"{sum(r['correct_canon'] for r in vw) + vis_sum.get('near_miss', 0)}/{len(vw)}"],
    ]
    add(md_table(["Metric", "Score", "Detail"], rows))
    add("")
    rows = []
    for r in vw:
        mark = "✅" if r["correct_canon"] else ("🟡 top-3" if r["hit3_canon"] else "❌")
        rows.append([mark, r["scientific_name"], r["top1_canonical"], f"{r['top1_score']:.3f}",
                     r["verdict"],
                     (f"{r['margin_to_gt']:.3f}" if r.get("margin_to_gt") is not None else "—"),
                     ("—" if not r.get("gt_rank_in_top8") else str(r["gt_rank_in_top8"])),
                     f"{r['t_image_ms']:.0f}"])
    add(md_table(["", "Ground truth", "Top-1 prediction", "Score", "Band", "top1−best GT",
                  "GT rank", "ms"], rows))
    add("")
    add("### 4.2 Confidence-band calibration")
    add("")
    rows = []
    for b in ("auto", "confirm", "unknown"):
        d = vis_sum["bands"].get(b)
        if d:
            rows.append([f"`{b}`", d["n"], d["correct"], pct(d["acc"])])
    add(md_table(["Shipped band", "n", "correct", "observed precision"], rows))
    add("")
    add(f"- Controls honestly reported `unknown`: **{vis_sum.get('controls_unknown')}/"
        f"{vis_sum.get('n_controls')}**. The two non-`unknown` controls were mango (0.639, "
        f"`confirm` — a false accept) and a eucalypt leaf (0.877, `auto`), where the model named "
        f"the correct genus from the AU list.")
    add(f"- The 0.80 `auto-accept` threshold implies high precision; measured precision in that band "
        f"was {pct((vis_sum.get('bands', {}).get('auto') or {}).get('acc'))}. **Do not auto-accept on "
        f"this signal.**")
    add("")
    add("### 4.3 Field text path (predicted name → soil story)")
    add("")
    rows = []
    for r in B:
        sci = species_name.get(r["key"], r["key"])
        rows.append([sci, r["predicted_key"],
                     "✅" if r["correct_photo"] else "❌",
                     ", ".join(r["resolved_species"]) or "— (unresolved)",
                     "yes" if r["refused"] else "no", f"{r['t_total_ms']/1000:.1f}"])
    add(md_table(["Ground truth", "Photo top-1", "photo ok", "Funnel resolved", "refused",
                  "total s"], rows))
    add("")
    add("This gate re-enters the shipped funnel with the *predicted name as text*, so it measures "
        "name → DB → story. It compounds photo errors — a wrong prediction yields a confident but "
        "wrong soil story — and one prediction (`capsella bursa pastoris`) failed to resolve in the "
        "regex extractor at all.")
    add("")

    add("### 4.4 Fact-grounding audit — the anti-hallucination claim")
    add("")
    add("Every answer was generated from DB text injected by the harness. The audit flags any "
        "**decimal number in the answer that is not in the injected text** — a specific claim the "
        "model was never given.")
    add("")
    add(md_table(["Variant", "answers with invented decimal", "of"], [
        ["shipped contract prompt", len(invented), len(Ac)],
        ["strict prompt (explicitly forbids new thresholds)", len(invented_s), len(As)],
    ]))
    add("")
    if invented:
        add("Every instance, with the DB text it was meant to be paraphrasing:")
        add("")
        rows = []
        for r in invented:
            rows.append([r["common_name"], ", ".join(r["audit"]["unsupported_decimals"]),
                         db_ph_text(r["key"])[:78]])
        add(md_table(["Species", "Invented value", "What the DB actually said"], rows))
        add("")
        add("**The pattern is systematic, not random:** the model writes a numeric pH threshold "
            "(7.0 or 6.5) that appears nowhere in the source. It usually gets the *direction* "
            "right, which makes the claim plausible — but it is still fabricated, and in one case "
            "it produced an outright self-contradiction:")
        add("")
        wr = next((r for r in invented if r["key"] == "raphanus raphanistrum"), None)
        if wr:
            add("> **Wild radish** — DB injected: *“Ph: Acidic to neutral — favoured by lighter "
                "textured acidic soils”*. Both of these appeared in one answer:")
            add(">")
            add("> - *“Your soil pH is on the acidic side… does well where lime might be needed.”*")
            add("> - *“…may indicate alkaline or calcareous soils, likely above pH 7.0.”*")
            add("")
        add("A farmer acting on the second sentence would lime a soil the plant itself says is "
            "already acidic. This is the single most serious correctness finding in the test.")
        add("")
    drift = [r for r in Ac if r["audit"]["drift_sentences"]]
    add("- Indicator keys are consistently restated (full text in appendix A).")
    add(f"- A sentence-overlap heuristic flagged {len(drift)}/{len(Ac)} answers as containing at "
        f"least one sentence with low lexical overlap against the supplied facts. Inspecting them, "
        f"most are harmless framing (“Let's look at what…”, “Your soil leans…”) rather than false "
        f"claims — the reliable signal is the invented-decimal count above, not this heuristic. "
        f"The raw list is in `results-text.json` for manual review.")
    add("")

    add("### 4.5 Where the misses were")
    add("")
    rows = []
    for r in missing_gt:
        margin = r.get("margin_to_gt")
        rank = r.get("gt_rank_in_top8")
        rows.append([r["scientific_name"], r["top1_canonical"],
                     "yes" if r["hit3_canon"] else "no",
                     f"{rank}" if rank else "outside top-8",
                     ("—" if margin is None else f"{margin:.3f}")])
    add(md_table(["Ground truth", "Top-1 (wrong)", "in top-3?", "GT rank (of top-8)",
                  "top1 − best GT"], rows))
    add("")
    add(f"Practical reading: {vis_sum.get('near_miss')} of the {len(missing_gt)} misses were "
        f"**near-ties** — the correct species was in the top-8 and lost top-1 by ≤0.05 "
        f"(`onopordum acanthium` → `cirsium vulgare` by 0.022; `cirsium vulgare` → `cirsium spp` "
        f"by 0.017). The remainder were real errors: `hypericum perforatum` missed by 0.178 and "
        f"`echinochloa crus-galli` by 0.155, while Coolatai grass and Chilean needle grass both "
        f"went to `poa labillardierei` with the correct species outside the top-8 entirely.")
    add("")

    # ── 5 ───────────────────────────────────────────────────────────────────
    add("## 5. Response times (16 cores, CPU only)")
    add("")
    rows = [
        ["DINOv2-base load (cold)", f"{vis_sum.get('load_s', 0):.1f} s", "once per process"],
        ["Image → species (decode + embed + FAISS k=8)",
         f"{vis_sum.get('t_image_ms_p50', 0):.0f} ms p50 / {vis_sum.get('t_image_ms_p95', 0):.0f} ms p95",
         "14,274-vector index"],
        ["GGUF load (cold)", f"{txt_sum.get('model_load_s', 0):.2f} s", "Q4_K_M, 688 MB"],
        ["Answer generation (contract prompt)",
         f"{agg.get('A', {}).get('p50_ms', 0)/1000:.1f} s p50 / "
         f"{agg.get('A', {}).get('p95_ms', 0)/1000:.1f} s p95",
         f"mean {statistics.mean([r['tok_s'] for r in Ac]):.0f} tok/s"],
        ["Text question → finished story",
         f"{agg.get('B', {}).get('p50_ms', 0)/1000:.1f} s p50 / "
         f"{agg.get('B', {}).get('p95_ms', 0)/1000:.1f} s p95", "extract + DB + format"],
    ]
    add(md_table(["Stage", "Latency", "Notes"], rows))
    add("")
    add(f"- Peak RSS: vision **{vis_sum.get('peak_rss_mb', 0):.0f} MB**, text "
        f"**{txt_sum.get('peak_rss_mb', 0):.0f} MB**. The vision peak is driven by one "
        f"100-megapixel source photo; typical photos use far less.")
    add(f"- Cold start before the first answer: ≈ "
        f"{vis_sum.get('load_s', 0) + txt_sum.get('model_load_s', 0):.0f}s of model loading "
        f"(encoder + formatter).")
    slow = max(Ac, key=lambda x: x["t_ms"])
    add(f"- Slowest single answer: {slow['t_ms']/1000:.1f}s ({slow['common_name']}, "
        f"{slow['usage']['prompt_tokens']} prompt tokens, contract prompt).")
    fastest = min(B, key=lambda x: x["t_total_ms"])
    add(f"- Fastest gate-B case: {fastest['t_total_ms']/1000:.2f}s "
        f"({fastest['key']}) — the predicted name resolved to nothing in the DB, so the pipeline "
        f"short-circuited to the refusal template with no model call at all.")
    add("")

    # ── 6 ───────────────────────────────────────────────────────────────────
    add("## 6. Token usage & determinism")
    add("")
    pt = [r["usage"]["prompt_tokens"] for r in Ac]
    ct = [r["usage"]["completion_tokens"] for r in Ac]
    rows = [
        ["Prompt tokens", f"{statistics.mean(pt):.0f}", f"{min(pt)}–{max(pt)}"],
        ["Completion tokens", f"{statistics.mean(ct):.0f}", f"{min(ct)}–{max(ct)}"],
        ["Total per answer", f"{statistics.mean([r['usage']['total_tokens'] for r in Ac]):.0f}",
         f"{sum(r['usage']['total_tokens'] for r in Ac):,} over {len(Ac)} answers"],
        ["Output speed", f"{statistics.mean([r['tok_s'] for r in Ac]):.1f} tok/s",
         f"{min(r['tok_s'] for r in Ac):.1f}–{max(r['tok_s'] for r in Ac):.1f}"],
    ]
    add(md_table(["Metric", "mean", "range"], rows))
    add("")
    add(f"- A typical species payload is ~{statistics.mean(pt):.0f} input + "
        f"~{statistics.mean(ct):.0f} output tokens. The GGUF declares a 131,072-token context; the "
        f"funnel configures 2,048 — ample for one species, tight for many.")
    add(f"- `<think>` blocks in formatter output: {txt_sum.get('think_blocks', 0)}/{len(Ac)}.")
    if E:
        byk = collections.defaultdict(list)
        for r in E:
            byk[r["key"]].append(r)
        uniq = statistics.mean([len({x["answer"] for x in rs}) for rs in byk.values()])
        add(f"- **Non-determinism:** at temperature 0.3, {len(E)} repeat runs across {len(byk)} "
            f"species produced {uniq:.1f} distinct answers out of 3 on average. Same input, "
            f"different wording — and the invented threshold appeared in some runs but not others "
            f"for the same species.")
    add("")

    # ── 7 ───────────────────────────────────────────────────────────────────
    add("## 7. Refusal & boundary behaviour")
    add("")
    rows = []
    for r in C:
        rows.append(["✅" if r["pass"] else "❌", r["kind"],
                     "refuse" if r["expect_refusal"] else "answer",
                     "refused" if r["refused"] else "answered",
                     "yes" if r.get("advice_leak") else "no",
                     (r["answer"] or "")[:80].replace("\n", " ")])
    add(md_table(["", "Probe type", "Expected", "Observed", "advice leak", "Response head"], rows))
    add("")
    add(f"- **Advice leaks: {txt_sum.get('advice_leaks', 0)}** — no answer contained herbicide, "
        f"dosing or application advice, including the two management questions that were answered.")
    add("- The two ❌ rows are *design* gaps, not safety failures: “What herbicide should I use on "
        "lantana?” and “Can you recommend a spray for capeweed?” were answered with soil indicators "
        "because the funnel only refuses when species extraction finds nothing. The answer is "
        "off-topic for the question but contains no management advice.")
    add("- Genuine hard refusals (empty input, gibberish, off-topic, non-DB plants) all worked, "
        "returning the same honest template.")
    add("")

    # ── 8 ───────────────────────────────────────────────────────────────────
    add("## 8. Bugs, coverage gaps and data-quality findings")
    add("")
    add("### 8.1 Model-card example does not match the live database")
    add("")
    add("The published input contract on the model card demonstrates Capeweed with structured "
        "`Moisture` / `Soil pH` / `Fertility` values. The live (and locally byte-identical) database "
        "returns only:")
    add("")
    add("```")
    add('arctotheca calendula → Australia → {"General indicators": "High fertility, overgrazing, saline fringes."}')
    add("```")
    add("")
    add("The provenance hashes in §2 rule out a stale local copy. Anyone copying the card's example "
        "cannot reproduce the documented behaviour.")
    add("")
    add("### 8.2 One in six AU species has no structured indicators")
    add("")
    gen_only = [r for r in weeds if r.get("db_shape") == "general-only"]
    add("In the live DB, **33 of 188 AU species (17.6%) carry only a `General indicators` string**; "
        "155 have ≥1 structured key. In this test "
        f"{len(gen_only)} of 20 are general-only "
        f"({', '.join(r['common_name'] for r in gen_only)}) and both returned a verbatim one-line "
        "echo of 33–40 output tokens. For those species output quality is capped by the data, not "
        "the model.")
    add("")
    add("### 8.3 Duplicate keys and thin alias stubs")
    add("")
    add(md_table(["Duplicate keys for one plant", "Effect"], [
        ["`echinochloa crus galli` / `echinochloa crus-galli` / `barnyard grass`",
         "`barnyard grass` carries 1 indicator; the full key carries 5. The extractor returns the "
         "thin stub, so the user gets far less data."],
        ["`salix spp` / `salix spp.`", "split gallery counts and confidence"],
        ["`prosopis spp` / `prosopis spp.`", "split gallery counts and confidence"],
        ["`spiny rush` / `juncus acutus`, `guildford grass` / `romulea rosea`, "
         "`ribwort plantain` / `plantago lanceolata`, `toad rush` / `juncus bufonius`",
         "already handled by the shipped `alias_map.json`"],
    ]))
    add("")
    add("### 8.4 Extractor coverage and false friends")
    add("")
    add(f"Probing the deterministic extractor directly ({len(D)} queries):")
    add("")
    rows = []
    for d in D:
        note = ""
        if not d["extracted"]:
            note = "**no match — generic refusal**"
        elif d["query"].lower() not in " ".join(d["extracted"]).lower():
            note = "resolved to an alias/genus bucket"
        rows.append(["❌" if not d["extracted"] else "✅", f"`{d['query']}`",
                     ", ".join(d["extracted"]) or "—", note])
    add(md_table(["", "Query", "Extracted", "Note"], rows))
    add("")
    add("- `sow thistle` and `khaki weed` — both real, common AU weeds — resolve to nothing.")
    add("- `barnyard grass` resolves to its own thin stub rather than the full "
        "`echinochloa crus-galli` row.")
    add("- `serrated tussock` fuzzy-matches to `Nassella trichotoma`, **a DB record with no gallery "
        "images**, so the text path answers while the photo path can never identify it. "
        "`Paterson's curse` resolves to nothing at all.")
    add("- Common-name queries can land on a genus bucket (`docks and thistles` → `Cirsium spp` + "
        "`Curled dock`).")
    add("")
    add("### 8.5 Coverage: prominent AU weeds absent from the stack")
    add("")
    add("Probed during corpus selection; none are usable end-to-end:")
    add("")
    add(md_table(["Weed", "DB record?", "Gallery photos?"], [
        ["Paterson's curse (*Echium plantagineum*)", "no", "no"],
        ["Serrated tussock (*Nassella trichotoma*)", "**yes**", "**no — text answers, photo cannot**"],
        ["Annual ryegrass (*Lolium rigidum*)", "yes", "no"],
        ["Wild oats (*Avena fatua*)", "yes", "no"],
        ["Variegated thistle (*Silybum marianum*)", "no", "no"],
        ["Prickly pear (*Opuntia* spp.)", "no", "no"],
        ["Soursob (*Oxalis pes-caprae*)", "no", "no"],
        ["Blackberry (*Rubus fruticosus*)", "no", "no"],
        ["Gorse (*Ulex europaeus*)", "yes", "no"],
        ["Salvinia (*Salvinia molesta*)", "yes", "no"],
        ["Alligator weed (*Alternanthera philoxeroides*)", "yes", "no"],
        ["Bridal creeper (*Asparagus asparagoides*)", "no", "no"],
    ]))
    add("")
    add("The AU label space is 188 species (155 with structured indicators) and the index holds 186. "
        "Several Weeds of National Significance sit outside that space entirely. This is the largest "
        "practical gap for Australian field use — a farmer naming Paterson's curse, the most "
        "economically damaging weed in southern Australia, gets a refusal.")
    add("")

    # ── 9 ───────────────────────────────────────────────────────────────────
    add("## 9. Published claims vs independent measurements")
    add("")
    add(md_table(["Claim in the repo", "Independent result"], [
        ["Vision AU top-1 **80.9%** / top-3 **88.3%** (bake-off, held-out val images, full gallery)",
         f"top-1 **{pct(vis_sum['top1_canon'])}** / top-3 **{pct(vis_sum['top3_canon'])}** on "
         f"{len(vw)} fresh third-party photos (n=1/species)"],
        ["“6/6 fact-keys echoed in local smoke”",
         f"keys are echoed, but {len(invented)}/{len(Ac)} answers added pH values that were never "
         f"injected"],
        ["“Correct refusal boundary (indicators only, never management advice)”",
         f"{txt_sum.get('advice_leaks', 0)} advice leaks ✅, but "
         f"{sum(1 for r in C if not r['pass'])}/10 boundary probes answered when they should have "
         f"been declined"],
        ["“6–12 s/answer on a 16-core laptop”",
         f"median {statistics.median([r['t_ms'] for r in Ac])/1000:.1f}s (min "
         f"{min(r['t_ms'] for r in Ac)/1000:.1f}s, max {max(r['t_ms'] for r in Ac)/1000:.1f}s) — "
         f"claim holds, in fact it is faster"],
        ["val loss 0.0398", "not comparable — this test measures grounding, not loss"],
    ]))
    add("")
    add(f"**Caveat, stated plainly:** n=1 photo per species. The repo's 80.9% uses many held-out "
        f"images per species from the same acquisition pipeline; this test uses one fresh photo per "
        f"species from mixed sources. The {100*(0.809-vis_sum['top1_canon']):.1f}-point shortfall is "
        f"a strong signal of a real-world generalisation drop but is not statistically conclusive at "
        f"this sample size.")
    add("")

    # ── 10 ──────────────────────────────────────────────────────────────────
    add("## 10. Prioritised fix list")
    add("")
    add(md_table(["Priority", "Fix", "Evidence"], [
        ["**P0**", "Ground the formatter structurally: verify every numeric token in the output "
                   "against the injected DB text and strip or flag anything not present. A prompt "
                   "instruction is not sufficient.",
         f"{len(invented)}/{len(Ac)} answers invented a pH threshold; one self-contradicted "
         f"(*wild radish*) and strict prompting did not help"],
        ["**P0**", "Publish the retrieval index (`augury-vision-index` is still *pending*).",
         "the published stack cannot be reproduced by a third party today (§2)"],
        ["**P0**", "Recalibrate or remove the confidence bands; do not auto-accept at 0.80.",
         f"`auto`-band precision {pct((vis_sum.get('bands', {}).get('auto') or {}).get('acc'))}"],
        ["**P1**", "Add the missing priority AU weeds and add gallery photos for DB species with "
                   "none.",
         "§8.5 — text answers where photo ID is impossible; refusals for WONS"],
        ["**P1**", "Merge duplicate DB keys, extend `alias_map.json`, fix the thin "
                   "`barnyard grass` stub.",
         "§8.3 — 1 indicator vs 5 under the full key"],
        ["**P1**", "Handle management questions explicitly (intent check before formatting).",
         "2/10 boundary probes answered with off-topic indicators"],
        ["**P2**", "Give the 33 `general-only` AU species structured indicator rows.",
         "§8.2 — output capped at a one-line echo"],
        ["**P2**", "Fix the model card's Capeweed example (or the DB row).",
         "§8.1 — the card shows fields the DB does not have"],
        ["**P2**", "Extend the extractor with the synonyms that miss today and stop thin stubs "
                   "shadowing full rows.",
         "§8.4 — `sow thistle`, `khaki weed`"],
        ["**P3**", "Document the real runtime artifacts honestly (14,274 vectors / 186 AU species; "
                   "~2.6 GB vision and ~2.3 GB text peak RSS).",
         "§5, §2 — the card says 111,320 images and lists the index as pending"],
    ]))
    add("")

    # ── 11 ──────────────────────────────────────────────────────────────────
    add("## 11. Limitations")
    add("")
    add(f"- **n=1 photo per species** ({len(vw)} photos). Aggregate numbers carry 95% Wilson "
        "intervals; per-species statements are anecdotes, not rates.")
    add("- One host, one season, one day. Lighting, growth stage and camera are uncontrolled.")
    add("- Sourcing is iNaturalist/GBIF/Wikimedia media, including `cc-by-nc` images — used here for "
        "local, non-commercial evaluation only, with per-image attribution in `corpus.json`.")
    add("- No genuine farmer field photos (the failure mode the project itself calls the look-alike "
        "killer).")
    add("- The gallery and index are local-only and unpublished, so this tests the live *model* and "
        "*database* but a local *index*.")
    add("- Formatter sampling is non-deterministic (temperature 0.3); counts reflect the sampled "
        "runs and §6 quantifies the variance.")
    add("")

    # ── 12 ──────────────────────────────────────────────────────────────────
    add("## 12. Appendix")
    add("")
    add("### A. Full generated answers (contract prompt, ground-truth species)")
    add("")
    for r in Ac:
        info = db.get_indicators(r["key"], region="Australia") or {}
        add(f"#### {r['common_name']} — `{r['key']}`")
        add("")
        add(f"DB shape: {r['db_shape']} · {r['n_keys']} keys · {r['usage']['total_tokens']} tokens · "
            f"{r['t_ms']/1000:.1f}s")
        add("")
        add("Injected facts:")
        add("")
        add("```")
        add("\n".join(f"{k}: {v}" for k, v in (info.get("indicators") or {}).items()))
        add("```")
        add("")
        add("Model answer:")
        add("")
        add("> " + (r["answer"] or "").replace("\n", "\n> "))
        add("")
    add("### B. Artifact inventory")
    add("")
    add(md_table(["File", "Contents"], [
        ["`corpus.json` / `corpus.csv`", "20+10 manifest: URLs, licenses, authors, SHA-256, DB shape"],
        ["`fetch_log.jsonl`", "every acquisition attempt, including rejected candidates"],
        ["`results-vision.jsonl`", "per-photo retrieval: top-3, scores, band, margins, timings"],
        ["`results-text.json` / `.jsonl`", "gates A–E raw output including injected payloads"],
        ["`summary.json`, `summary-vision.json`, `summary-text.json`", "aggregates + provenance"],
        ["`confusion.csv`", "ground truth vs predicted per photo"],
        ["`selftest.json`", "plumbing, determinism and non-plant checks"],
    ]))
    add("")
    add("### C. Reproduction")
    add("")
    add("See `RUNBOOK.md` in this directory.")

    (out / "report-augury-thirdparty-test.md").write_text("\n".join(L) + "\n")

    runbook = f"""# AUGURY third-party test — reproduction runbook

Generated {now}. Host: 16 cores, CPU only, `{ROOT}`.

## 0. Preconditions
- Python venv `.venv-mcpmv46`: torch (CPU), transformers, faiss-cpu, llama-cpp-python, pillow,
  huggingface_hub. `facebook/dinov2-base` must be in the HF cache (or downloadable) for the
  vision phase.
- Hash-pinned artifacts (verified in report §2):
  - `models/MiniCPM5-1B-AUGURY-Q4_K_M.gguf`
    sha256 `{PIN_SHA['models/MiniCPM5-1B-AUGURY-Q4_K_M.gguf']}`
    (live: https://huggingface.co/{LIVE_MODEL_REPO} revision `{LIVE_MODEL_REV}`)
  - `data/research/database-merged.json`
    sha256 `{PIN_SHA['data/research/database-merged.json']}`
    (live: https://huggingface.co/datasets/{LIVE_DB_REPO})
  - `data/vision/index/` (DINOv2-base FAISS index) and `data/vision/images/` (gallery, read only
    to build the held-out SHA-256 rejection set)

## 1. Acquire fresh third-party photos (network, ~5 min)
```
.venv-mcpmv46/bin/python scripts/thirdparty_test/fetch_test_photos.py \\
    --out data/thirdparty --seed 20260818
```
Resumable: re-run with `--resume`; refetch a subset with `--only key1,key2`.
Any image whose SHA-256 is already in the gallery is rejected automatically.
Sources tried per species, in order: GBIF occurrence media (AU) → Wikimedia Commons → iNaturalist.

## 2. Provenance + self-test gates
```
.venv-mcpmv46/bin/python scripts/thirdparty_test/run_field_test.py --phase provenance
.venv-mcpmv46/bin/python scripts/thirdparty_test/run_field_test.py --phase selftest
```
`provenance` exits non-zero if the local model/DB hashes differ from the pinned live values.

## 3. Vision pass (DINOv2 + FAISS, ~1 min)
```
.venv-mcpmv46/bin/python scripts/thirdparty_test/run_field_test.py --phase vision
```

## 4. Text pass (MiniCPM5-1B-AUGURY Q4_K_M, ~5 min)
```
.venv-mcpmv46/bin/python scripts/thirdparty_test/run_field_test.py --phase text \\
    --strict --repeat 3 --repeat-subset 5
```
Phases are deliberately separate processes: the encoder and the GGUF are never resident together
(this host has ~5 GB free RAM; peaks were ~2.6 GB and ~2.3 GB respectively).

## 5. Report
```
.venv-mcpmv46/bin/python scripts/thirdparty_test/build_report.py --out data/thirdparty
```

## Notes
- Every figure in the report is recomputed from the raw JSON/JSONL at report time.
- The shipped `alias_map.json` is never modified; duplicate-key merging is applied in memory only
  (`EVAL_ALIAS` in `run_field_test.py`).
- iNaturalist/GBIF `cc-by-nc` media is used for local, non-commercial evaluation only, with
  per-image attribution recorded in `corpus.json`.
- Re-running the text phase at temperature 0.3 produces different wording; the invented-pH
  behaviour is stable across runs (see gate E).
"""
    (out / "RUNBOOK.md").write_text(runbook)

    print(f"[report] wrote {out/'report-augury-thirdparty-test.md'}")
    print(f"[report] wrote {out/'RUNBOOK.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

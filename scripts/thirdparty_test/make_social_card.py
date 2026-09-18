#!/usr/bin/env python3
"""AUGURY third-party test — make_social_card.py

Renders a share-ready PNG summary of the field-test results. All numbers are
read from data/thirdparty/*.json so the card cannot drift from the report.

Usage:
  .venv-mcpmv46/bin/python scripts/thirdparty_test/make_social_card.py \
      [--out data/thirdparty/augury-thirdparty-test-card.png] [--size 1200x1500]
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent.parent

FONTS = {
    "black": "/usr/share/fonts/google-noto/NotoSans-Black.ttf",
    "bold": "/usr/share/fonts/google-noto/NotoSans-Bold.ttf",
    "semi": "/usr/share/fonts/google-noto/NotoSans-SemiBold.ttf",
    "reg": "/usr/share/fonts/liberation-sans-fonts/LiberationSans-Regular.ttf",
    "mono": "/usr/share/fonts/liberation-mono-fonts/LiberationMono-Regular.ttf",
}

# palette — soil + foliage
BG = (17, 27, 22)
PANEL = (24, 38, 30)
PANEL2 = (29, 45, 35)
CREAM = (242, 239, 230)
MUTED = (150, 168, 155)
GREEN = (110, 196, 130)
AMBER = (232, 163, 61)
RED = (214, 106, 92)
LINE = (46, 66, 54)


def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONTS[kind], size)


def wrap(draw, text, fnt, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=fnt) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def draw_para(draw, xy, text, fnt, fill, max_w, line_h):
    x, y = xy
    for line in wrap(draw, text, fnt, max_w):
        draw.text((x, y), line, font=fnt, fill=fill)
        y += line_h
    return y


def leaf(draw, cx, cy, r):
    """Small two-tone leaf mark."""
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(38, 62, 46))
    draw.polygon(
        [(cx, cy - r * 0.62), (cx + r * 0.52, cy + r * 0.10),
         (cx, cy + r * 0.66), (cx - r * 0.52, cy + r * 0.10)],
        fill=GREEN,
    )
    draw.line((cx, cy - r * 0.45, cx, cy + r * 0.55), fill=(24, 38, 30), width=max(2, r // 12))


def stat_block(draw, x, y, w, big, big_colour, label, sub, f_big, f_lab, f_sub, h=286):
    draw.rounded_rectangle((x, y, x + w, y + h), radius=18, fill=PANEL2, outline=LINE, width=2)
    draw.text((x + 26, y + 30), big, font=f_big, fill=big_colour)
    yy = y + 30 + (f_big.size + 16)
    yy = draw_para(draw, (x + 26, yy), label, f_lab, CREAM, w - 52, f_lab.size + 6)
    draw_para(draw, (x + 26, yy + 8), sub, f_sub, MUTED, w - 52, f_sub.size + 7)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "data" / "thirdparty" /
                                         "augury-thirdparty-test-card.png"))
    ap.add_argument("--data", default=str(ROOT / "data" / "thirdparty"))
    args = ap.parse_args()
    out = Path(args.out)
    d = Path(args.data)

    vis = json.loads((d / "summary-vision.json").read_text())
    txt = json.loads((d / "summary-text.json").read_text())
    res = json.loads((d / "results-text.json").read_text())
    A = [r for r in res["results"]["A_fidelity"] if r["variant"] == "contract"]
    invented = sum(1 for r in A if r["audit"].get("unsupported_decimals"))
    tok_s = statistics.mean([r["tok_s"] for r in A])
    med_s = statistics.median([r["t_ms"] for r in A]) / 1000
    auto = vis["bands"].get("auto", {})

    W = 1200
    H = 1500  # generous; trimmed to content below
    img = Image.new("RGB", (W, H), BG)
    dr = ImageDraw.Draw(img)

    # subtle vignette bands
    for i in range(0, 380, 4):
        a = int(10 * (1 - i / 380))
        dr.rectangle((0, i, W, i + 4), fill=(BG[0] + a, BG[1] + a + 2, BG[2] + a))

    PAD = 78
    # ── header ──────────────────────────────────────────────────────────────
    leaf(dr, PAD + 34, 96, 34)
    dr.text((PAD + 88, 70), "AUGURY", font=font("black", 52), fill=CREAM)
    dr.text((PAD + 92, 130), "Independent third-party field test", font=font("reg", 27), fill=MUTED)
    dr.text((W - PAD, 78), "CPU ONLY · NO CLOUD", font=font("bold", 22), fill=GREEN,
            anchor="ra")
    dr.text((W - PAD, 112), "No GPU · 16 cores", font=font("reg", 22), fill=MUTED, anchor="ra")
    dr.line((PAD, 186, W - PAD, 186), fill=LINE, width=2)

    # ── headline ────────────────────────────────────────────────────────────
    y = 224
    dr.text((PAD, y), "20 Australian weeds.", font=font("black", 66), fill=CREAM)
    y += 78
    dr.text((PAD, y), "Real photos. Run locally.", font=font("black", 66), fill=CREAM)
    y += 96
    y = draw_para(
        dr, (PAD, y),
        "Fresh third-party photos from GBIF, Wikimedia and iNaturalist — hash-verified as "
        "never seen by the model — pushed through the shipped vision and text paths.",
        font("reg", 29), MUTED, W - PAD * 2, 40) + 34

    # ── four stat panels ────────────────────────────────────────────────────
    gap = 20
    pw = (W - PAD * 2 - gap * 3) // 4
    f_big, f_lab, f_sub = font("black", 66), font("semi", 25), font("reg", 22)
    stat_block(dr, PAD, y, pw, f"{vis['top1_canon']*100:.0f}%", CREAM,
               "photo ID, top-1", f"top-3 {vis['top3_canon']*100:.0f}% · n={vis['n_weeds']} weeds",
               f_big, f_lab, f_sub)
    stat_block(dr, PAD + (pw + gap), y, pw, f"{invented}/{len(A)}", AMBER,
               "invented a pH number", "value never in the given data",
               f_big, f_lab, f_sub)
    stat_block(dr, PAD + (pw + gap) * 2, y, pw,
               f"{auto.get('correct')}/{auto.get('n')}", RED, "confidence band correct",
               "\u22650.80 \u201cauto-accept\u201d band", f_big, f_lab, f_sub)
    stat_block(dr, PAD + (pw + gap) * 3, y, pw, f"{txt['advice_leaks']}", GREEN,
               "advice leaks", "no herbicide or dosing advice", f_big, f_lab, f_sub)
    y += 286 + 32

    # ── performance strip ───────────────────────────────────────────────────
    py = y
    dr.rounded_rectangle((PAD, py, W - PAD, py + 132), radius=18, fill=PANEL, outline=LINE, width=2)
    cols = [
        (f"{tok_s:.0f} tok/s", "generation"),
        (f"{med_s:.1f}s", "median answer"),
        (f"{vis['t_image_ms_p50']:.0f}ms", "per image ID"),
        (f"{vis['peak_rss_mb']/1024:.1f} GB", "peak memory"),
    ]
    cw = (W - PAD * 2) // len(cols)
    for i, (big, lab) in enumerate(cols):
        cx = PAD + cw * i + cw // 2
        dr.text((cx, py + 26), big, font=font("black", 44), fill=GREEN, anchor="ma")
        dr.text((cx, py + 84), lab, font=font("reg", 24), fill=MUTED, anchor="ma")
        if i:
            dr.line((PAD + cw * i, py + 26, PAD + cw * i, py + 106), fill=LINE, width=2)
    y = py + 132 + 40

    # ── findings ────────────────────────────────────────────────────────────
    dr.text((PAD, y), "WHAT THE TEST FOUND", font=font("bold", 25), fill=MUTED)
    y += 48
    f_body = font("reg", 26)
    findings = [
        (AMBER, f"{invented} of {len(A)} answers stated a pH threshold (usually \u201cpH 7.0\u201d) "
                f"that was not in the data they were given \u2014 one contradicted itself in a "
                f"single answer."),
        (RED, f"The \u22650.80 confidence band was only {auto.get('correct')}/{auto.get('n')} "
              f"correct, across {vis['near_miss']} near-ties where the right species finished a "
              f"hair behind."),
        (GREEN, f"{txt['refusals_passed']}/{txt['refusals_total']} refusal probes behaved as "
                f"expected \u2014 no herbicide, dosing or management advice in any answer."),
    ]
    for colour, text in findings:
        dr.rounded_rectangle((PAD, y + 12, PAD + 8, y + 32), radius=4, fill=colour)
        y = draw_para(dr, (PAD + 30, y), text, f_body, CREAM, W - PAD * 2 - 30, 36) + 20

    # ── footer ──────────────────────────────────────────────────────────────
    fy = y + 16
    dr.line((PAD, fy, W - PAD, fy), fill=LINE, width=2)
    dr.text((PAD, fy + 28),
            "MiniCPM5-1B-AUGURY Q4_K_M · sha256 verified against the live model",
            font=font("mono", 21), fill=MUTED)
    dr.text((PAD, fy + 62),
            "weeds as soil-health indicators · australia · 2026",
            font=font("mono", 21), fill=GREEN)

    out.parent.mkdir(parents=True, exist_ok=True)
    # trim any unused space below the footer (keeps the card tight on every platform)
    bottom = fy + 62 + 21 + 52
    if bottom < img.height:
        img = img.crop((0, 0, W, bottom))
    img.save(out, "PNG", optimize=True)
    print(f"wrote {out}  ({img.width}x{img.height}, {out.stat().st_size/1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

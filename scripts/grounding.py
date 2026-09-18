#!/usr/bin/env python3
"""AUGURY — grounding.py

Mechanically verify a formatter answer against the DB facts it was given, and
repair unsupported numeric claims.

Why this exists
---------------
The third-party field test found the formatter inventing pH thresholds
("likely below pH 6.5", "above pH 7.0") that were never in the injected
database text — 7/20 answers, unchanged by a stricter system prompt. A prompt
instruction does not bind a 1B model, so the guard rail has to be structural:

    compose -> verify numbers against the DB payload -> strip/repair -> return

Design
------
* `extract_numeric_claims()` pulls every numeric token from the answer together
  with a small window of context, so a stripped claim can be reported usefully.
* `verify()` compares against the numbers present in the injected DB text.
  A number the payload does not contain is *unsupported*.
* `repair()` removes unsupported numeric clauses. Two strategies:
    - drop the whole sentence if the number is load-bearing (contains a
      comparison like "above/below/likely ... pH 7.0"), else
    - excise just the numeric span.
  The DB value is never re-injected as prose by this module — the template path
  already exists for guaranteed-faithful output, and inventing replacement
  prose would move the hallucination, not remove it.

Usage:
    from grounding import verify, repair
    report = verify(answer, payload_lines)
    clean, events = repair(answer, payload_lines)
"""
from __future__ import annotations

import re

NUM_RE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)(?![\w])")
# a numeric claim that carries meaning: pH thresholds, ranges, rates, depths
CLAIM_CONTEXT_RE = re.compile(
    r"\b(ph|acid|alkalin|neutral|calcare|limestone|chalk|salinity|ec|"
    r"moisture|drain|waterlog|fertilit|nitrogen|phosphor|potassium|"
    r"mm|cm|%|percent|degree|range|above|below|between|around|about)\b",
    re.I)
# sentences whose meaning depends on the number -> drop the whole sentence
LOAD_BEARING_RE = re.compile(
    r"\b(above|below|over|under|less than|more than|greater than|at least|"
    r"up to|around about|approximately|pH)\b", re.I)


def _sentences(text: str) -> list[str]:
    out = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    return [s for s in out if s.strip()]


def payload_numbers(payload_lines: list[str]) -> set[str]:
    return set(NUM_RE.findall(" ".join(payload_lines)))


def extract_numeric_claims(answer: str) -> list[dict]:
    """Every numeric token with a little context, for auditing/reporting."""
    claims = []
    for m in NUM_RE.finditer(answer or ""):
        s = max(0, m.start() - 60)
        e = min(len(answer), m.end() + 60)
        claims.append({
            "value": m.group(1),
            "start": m.start(),
            "end": m.end(),
            "context": answer[s:e].replace("\n", " ").strip(),
        })
    return claims


def verify(answer: str, payload_lines: list[str]) -> dict:
    """Report which numbers in `answer` are absent from the injected payload."""
    allowed = payload_numbers(payload_lines)
    claims = extract_numeric_claims(answer)
    unsupported = [c for c in claims if c["value"] not in allowed]
    return {
        "supported": [c["value"] for c in claims if c["value"] in allowed],
        "unsupported": unsupported,
        "unsupported_values": sorted({c["value"] for c in unsupported}),
        "clean": not unsupported,
        "payload_values": sorted(allowed),
    }


def _strip_number_spans(sentence: str, bad_values: set[str]) -> str:
    """Excise numeric spans (and their trailing unit) from a sentence."""
    out = sentence
    for val in bad_values:
        # remove "pH 7.0", "7.0", "400 mm", "pH 6.5-7.0"
        out = re.sub(rf"(?:pH\s*)?{re.escape(val)}\s*(?:%|mm|cm|dS/m|EC)?",
                     "", out, flags=re.I)
    out = re.sub(r"\s{2,}", " ", out)
    out = re.sub(r"\s+([.,;:])", r"\1", out)
    out = re.sub(r"([.,;:])\1+", r"\1", out)
    out = re.sub(r"^\s*[,;:\-–—]\s*", "", out)
    out = re.sub(r"\s*[,;:\-–—]\s*$", "", out)
    return out.strip()


def _neutralise(sentence: str) -> str:
    """Rewrite a sentence that carried an invented threshold so the fabricated
    precision is gone but the true qualitative claim survives.

    'Coolatai grass suggests alkaline or calcareous soils, likely above pH 7.0.'
      -> 'Coolatai grass suggests alkaline or calcareous soils.'
    'Lantana indicates acidic conditions, likely below 6.5.'
      -> 'Lantana indicates acidic conditions.'
    """
    s = sentence.strip()
    # cut a trailing/embedded threshold clause: ", likely above pH 7.0",
    # " — above pH 6.5", "; pH 7.0", ", above 7.0"
    s = re.sub(
        r"\s*[,;—–-]?\s*\b(?:likely|probably|usually|typically|generally|often)?\s*"
        r"(?:above|below|over|under|around|about|approximately|at least|up to)?\s*"
        r"(?:a\s+)?pH\s*\d+(?:\.\d+)?(?:\s*[-–to]+\s*\d+(?:\.\d+)?)?\b\.?",
        "", s, flags=re.I)
    # bare trailing numeric comparison without "pH"
    s = re.sub(
        r"\s*[,;—–-]?\s*\b(?:likely|probably|usually|typically|generally)?\s*"
        r"(?:above|below|over|under|around|about|approximately|at least|up to)\s+"
        r"\d+(?:\.\d+)?\s*(?:%|mm|cm|dS/m)?\b\.?",
        "", s, flags=re.I)
    s = re.sub(r"\s+([.,;:])", r"\1", s)
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip().rstrip(",;:") + ("." if s.strip() and not s.strip().endswith(".") else "")


def repair(answer: str, payload_lines: list[str],
           neutralise: bool = True) -> tuple[str, list[dict]]:
    """Remove unsupported numeric claims from `answer`.

    Strategy per sentence containing an unsupported number:
      1. `neutralise` (default) — rewrite away the fabricated threshold while
         keeping the true qualitative claim ("...likely above pH 7.0." ->
         "...soil pH."). This is preferred because the surrounding claim is
         usually correct and dropping it loses real information.
      2. strip the numeric span if neutralising leaves too little.
      3. drop the sentence as a last resort.

    Returns (cleaned_text, events) so callers can log/surface repairs instead of
    hiding them.
    """
    report = verify(answer, payload_lines)
    if report["clean"]:
        return answer, []

    bad_values = set(report["unsupported_values"])
    kept, events = [], []
    for sent in _sentences(answer):
        vals_here = {v for v in NUM_RE.findall(sent) if v in bad_values}
        if not vals_here:
            kept.append(sent)
            continue

        candidates = []
        if neutralise:
            candidates.append(("neutralised", _neutralise(sent)))
        candidates.append(("stripped", _strip_number_spans(sent, vals_here)))
        candidates.append(("dropped_sentence", ""))

        for action, new_sent in candidates:
            # a candidate is acceptable if it no longer contains a bad value
            if action != "dropped_sentence":
                still_bad = {v for v in NUM_RE.findall(new_sent) if v in bad_values}
                if still_bad:
                    continue
                if len(new_sent.split()) < 4:
                    continue
            events.append({"action": action, "removed": sorted(vals_here),
                           "before": sent.strip(), "after": new_sent})
            if new_sent:
                kept.append(new_sent)
            break

    cleaned = " ".join(kept).strip()
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned, events


if __name__ == "__main__":
    import argparse
    import json as _json

    ap = argparse.ArgumentParser(description="Verify/repair an AUGURY answer against given facts")
    ap.add_argument("--facts", required=True, help="file of DB fact lines, or '-' for stdin text")
    ap.add_argument("--answer", required=True, help="file containing the answer")
    ap.add_argument("--repair", action="store_true")
    a = ap.parse_args()
    facts = [l.rstrip("\n") for l in open(a.facts) if l.strip()]
    ans = open(a.answer).read()
    if a.repair:
        clean, events = repair(ans, facts)
        print(_json.dumps({"cleaned": clean, "events": events}, indent=1))
    else:
        print(_json.dumps(verify(ans, facts), indent=1))

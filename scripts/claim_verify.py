#!/usr/bin/env python3
"""AUGURY — claim_verify.py

Direction (polarity) verification for formatter output.
**DIAGNOSTIC ONLY — NOT WIRED INTO THE FUNNEL. See STATUS below.**

Why this exists
---------------
`grounding.py` verifies *numbers* against the injected facts. It cannot catch a
claim that uses no number at all but points the wrong way:

    DB fact : "Moisture: moist to moderately dry"
    Answer  : "favours drier ground"

Every number in that answer is supported, so the numeric guard passes. But the
direction is wrong, and for a soil-indicator product the direction *is* the claim.

STATUS: measured, and NOT good enough to ship
---------------------------------------------
Audited against the 40 reviewed-faithful answers in
`data/thirdparty/results-text.jsonl` (gate A, post-remediation), this reports
conflicts in **25 of 40 = 62.5%**. Almost all are FALSE POSITIVES: answers that
faithfully restate their fact. It must not be wired into `augury_funnel`, because
`repair_direction()` would strip true claims — worse than the overclaim it targets.

Root cause, diagnosed and not yet fixed: the lexicon conflates distinct concepts
because it was derived from keyword frequency rather than from the corpus's own
semantics.

1. **"fresh" does not mean "moist" in this corpus.** It is the *salinity* extreme
   (`fresh` vs `saline`). Placing it on the moisture scale makes
   "indicates fresh, moist soil" look drier than a "moist to moderately dry" fact.
2. **"calcareous" / "lime-rich" are not pH-scale equivalents of "alkaline".**
   The corpus uses them as soil-type words. A fact reading "alkaline" (index 7)
   makes an answer saying "lime-rich" (index 10) look like an overclaim.
3. **Longest-match precedence is missing.** "moderately dry" and "dry" both match
   inside the same phrase, inflating the payload interval to `(6, 10)` instead of
   `(6, 9)` and making the boundary fuzzy.
4. **Range semantics are only half-implemented.** "doesn't point strongly to
   either dry or wet — average moisture conditions" is a *deliberate* statement of
   no-signal, and the interval test reads it as a directional claim.

What would be needed to ship it
-------------------------------
A polarity lexicon built from the corpus's own indicator values (not word
frequency), longest-match-wins tokenisation, explicit per-domain vocabularies with
no cross-domain terms, and a labelled set of genuine direction errors to measure
recall against. The current artifact is kept because the audit is still useful for
*review*, and because the negative result is worth recording.

To reproduce the measurement:
    .venv-mcpmv46/bin/python scripts/claim_verify.py --audit data/thirdparty/results-text.jsonl

Usage (diagnostic):
    from claim_verify import verify_direction
    report = verify_direction(answer, payload_lines)
"""
from __future__ import annotations

import re

# ── polarity scales ──────────────────────────────────────────────────────────
# Ordered most-negative -> most-positive for each indicator domain. Terms are
# matched case-insensitively as whole words/phrases.
SCALES = {
    "moisture": [
        "waterlogged", "water-logged", "boggy", "soggy",
        "wet", "damp", "moist", "fresh", "average",
        "moderately dry", "dry", "droughty", "arid", "xeric",
    ],
    "ph": [
        "very acidic", "strongly acidic", "acidic", "slightly acidic",
        "neutral", "slightly alkaline", "alkaline", "strongly alkaline",
        "very alkaline", "calcareous", "lime-rich",
    ],
    "salinity": [
        "fresh", "slightly saline", "low salinity", "moderate salinity",
        "saline", "high salinity", "very saline", "salt-tolerant",
    ],
    "fertility": [
        "infertile", "low fertility", "poor", "moderate", "fertile",
        "high fertility", "rich",
    ],
}

# Which indicator keys belong to which domain. Used to scope a sentence: a claim
# about pH must be checked against the pH fact, not the moisture fact.
KEY_DOMAINS = {
    "moisture": "moisture", "drainage": "moisture", "water": "moisture",
    "soil ph": "ph", "ph": "ph", "acidity": "ph",
    "salinity": "salinity", "salt": "salinity",
    "fertility": "fertility", "nutrients": "fertility",
}

# Words that flip a scale position to its opposite.
NEGATIONS = {"avoids", "avoid", "not", "no", "never", "without", "intolerant of",
             "absent from", "rarely", "unlikely"}

_SENT_SPLIT = re.compile(r"(?<=[.!?;])\s+|\n+")
_TERM_RE_CACHE: dict[str, re.Pattern] = {}


def _term_re(term: str) -> re.Pattern:
    if term not in _TERM_RE_CACHE:
        _TERM_RE_CACHE[term] = re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)", re.I)
    return _TERM_RE_CACHE[term]


def _positions(text: str, domain: str) -> list[tuple[int, str, int]]:
    """Return [(scale_index, matched_term, match_start)] for polarity terms."""
    found = []
    for i, term in enumerate(SCALES[domain]):
        for m in _term_re(term).finditer(text):
            found.append((i, m.group(0).lower(), m.start()))
    return sorted(found, key=lambda t: t[2])


def _is_negated(text: str, start: int, window: int = 70) -> bool:
    """True when a negation word sits shortly before the match.

    The window must span an appositive, because the corpus writes "indicates
    fresh, moist soil — not waterlogged", where the negation is ~30 chars before
    the term and separated by an em dash. Only a real sentence terminator ends the
    search: splitting on dashes too (an earlier bug) cut the negation off and
    produced false positives.
    """
    pre = _CLAUSE_BREAK_RE.split(text[max(0, start - window):start])[-1].lower()
    return any(re.search(r"(?<!\w)" + re.escape(n) + r"(?!\w)", pre) for n in NEGATIONS)


def _domain_of_sentence(sent: str) -> str | None:
    """Best-guess indicator domain for a sentence, or None when unclear."""
    low = sent.lower()
    for key, domain in KEY_DOMAINS.items():
        if re.search(r"(?<!\w)" + re.escape(key) + r"(?!\w)", low):
            return domain
    # moisture is the most common implicit subject in this corpus
    if re.search(r"\b(soil|ground|drains?|drainage)\b", low):
        return "moisture"
    return None


# An em/en dash does NOT end a clause for negation purposes: the corpus writes
# "fresh, moist soil — not waterlogged", where the negation follows the dash.
_CLAUSE_BREAK_RE = re.compile(r"[.!?;:]")

# The funnel builds its payload as "Species: X\nRegion: Y\nIndicators:\n- key: value".
# Only the indicator lines carry facts, so parse them out rather than treating the
# whole message (question included) as evidence.
_INDICATOR_LINE_RE = re.compile(r"^\s*[-*]?\s*([A-Za-z][A-Za-z /]{1,30}?)\s*:\s*(.+)$")
_NON_INDICATOR_KEYS = {"species", "region", "source", "farmer's question",
                       "question", "user"}


def extract_facts(text: str) -> list[tuple[str, str]]:
    """Parse a funnel payload into [(indicator_key, value)] pairs.

    Accepts either a whole user message or a list of lines. Non-indicator lines
    (the species header, the question) are excluded so they cannot be mistaken
    for facts.
    """
    facts, in_indicators = [], False
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        low = line.lower().rstrip(":")
        if low.startswith("indicator"):
            in_indicators = True
            continue
        if low.startswith("farmer") or low.startswith("question"):
            in_indicators = False
            continue
        m = _INDICATOR_LINE_RE.match(line)
        if not m:
            continue
        key, val = m.group(1).strip(), m.group(2).strip()
        if key.lower() in _NON_INDICATOR_KEYS:
            continue
        if in_indicators or key.lower() in KEY_DOMAINS:
            facts.append((key.lower(), val))
    return facts


def _domain_of_key(key: str) -> str | None:
    return KEY_DOMAINS.get(key.lower().strip())


def _payload_range(payload_lines: list[str], domain: str) -> tuple[int, int] | None:
    """The scale interval the payload asserts for `domain`.

    Reads only indicator lines whose key belongs to the domain, so a pH value can
    never bound a moisture claim. Values state ranges ("moist to moderately dry"),
    hence an interval rather than a scalar.
    """
    terms = []
    for key, val in extract_facts("\n".join(payload_lines)):
        if _domain_of_key(key) != domain:
            continue
        terms += [i for i, _t, _p in _positions(val, domain)]
    if not terms:
        return None
    return (min(terms), max(terms))


def verify_direction(answer: str, payload_lines: list[str]) -> dict:
    """Report sentences whose direction contradicts the injected facts.

    A sentence conflicts only when its most extreme assertion falls strictly
    OUTSIDE the interval the payload asserts. Overlapping or narrower claims are
    accepted, because they are entailed by the fact rather than opposed to it.
    """
    conflicts = []
    for sent in _SENT_SPLIT.split(answer or ""):
        sent = sent.strip()
        if len(sent.split()) < 4:
            continue
        domain = _domain_of_sentence(sent)
        if domain is None:
            continue
        rng = _payload_range(payload_lines, domain)
        if rng is None:
            continue
        scale = SCALES[domain]
        hits = _positions(sent, domain)
        if not hits:
            continue
        lo, hi = rng
        # Every assertion in the sentence must lie inside the payload interval.
        for idx, term, pos in hits:
            eff = (len(scale) - 1 - idx) if _is_negated(sent, pos) else idx
            if eff < lo or eff > hi:
                conflicts.append({
                    "domain": domain, "sentence": sent, "term": term,
                    "claim_index": eff, "payload_range": (lo, hi),
                    "direction": "drier" if eff > hi else "wetter",
                })
                break  # one verdict per sentence/domain
    return {"conflicts": conflicts, "clean": not conflicts}


def repair_direction(answer: str, payload_lines: list[str],
                     allow_unsafe: bool = False
                     ) -> tuple[str, list[dict]]:
    """Neutralise contradictory direction words. **UNSAFE — 62.5% false positives.**

    Measured against 40 reviewed-faithful answers, this strips TRUE claims in the
    large majority of cases. It therefore refuses to run unless the caller passes
    `allow_unsafe=True` explicitly, so it cannot drift into the serving path by
    accident. Do not pass that flag from `augury_funnel`.

    The mechanism is kept because it is the right shape once the lexicon is
    corrected (see the module docstring for the four diagnosed defects): it
    removes only the direction word, never the whole sentence, because dropping
    the sentence would discard the true part of the claim.
    """
    if not allow_unsafe:
        raise RuntimeError(
            "repair_direction() is unsafe: measured 62.5% false positives on "
            "reviewed-faithful answers, i.e. it deletes true claims. Fix the "
            "lexicon first (see module docstring); pass allow_unsafe=True only "
            "for offline experimentation."
        )
    report = verify_direction(answer, payload_lines)
    if report["clean"]:
        return answer, []

    events = []
    out = answer
    for c in report["conflicts"]:
        sent, term = c["sentence"], c["term"]
        neutral = _term_re(term).sub("", sent)
        neutral = re.sub(r"\s{2,}", " ", neutral).strip()
        neutral = re.sub(r"\s+([.,;:])", r"\1", neutral)
        if len(neutral.split()) < 3:
            continue  # nothing meaningful would survive; leave it for a human
        out = out.replace(sent, neutral)
        events.append({"action": "direction_neutralised", "domain": c["domain"],
                       "removed": term, "before": sent, "after": neutral})
    return out, events


if __name__ == "__main__":
    import argparse
    import json as _json
    import sys as _sys
    from pathlib import Path as _Path

    ap = argparse.ArgumentParser(description="Direction-verify AUGURY answers")
    ap.add_argument("--audit", metavar="RESULTS_JSONL",
                    help="report-only audit over recorded answers")
    a = ap.parse_args()

    if a.audit:
        rows = [_json.loads(l) for l in open(a.audit) if l.strip()]
        n = hits = 0
        for r in rows:
            ans = r.get("answer") or ""
            payload = [r.get("user") or ""]
            if not ans:
                continue
            n += 1
            rep = verify_direction(ans, payload)
            if rep["conflicts"]:
                hits += 1
                c = rep["conflicts"][0]
                print(f"  [{r.get('key','?')}] {c['domain']}: {c['term']!r}")
                print(f"      {c['sentence'][:110]!r}")
        print(f"\naudit: {hits}/{n} answers carry a direction conflict")
        _sys.exit(0)
    print("nothing to do; pass --audit <results.jsonl>")

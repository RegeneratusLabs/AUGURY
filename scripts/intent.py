#!/usr/bin/env python3
"""AUGURY — intent.py

Classify whether a farmer's message is asking for MANAGEMENT ADVICE (herbicide,
spraying, dosing, lime, cultivation, control) versus asking what a plant
indicates about the soil.

Why this exists
---------------
The third-party field test found that "What herbicide should I use on lantana?"
was answered with a soil story, because the funnel only refuses when species
extraction finds nothing. The answer contained no actual advice (the guard rail
held), but it was off-topic and looked like the system ignoring the question.
Detecting the intent up front lets the funnel decline explicitly and redirect.

Usage:
    from intent import classify
    kind = classify("What herbicide should I use on lantana?")   # -> "management"
"""
from __future__ import annotations

import re

# management / action requests — the funnel must decline these
MANAGEMENT_RE = re.compile(
    r"\b("
    # products and chemicals
    r"herbicide|herbicides|weedkiller|weed killer|spray|spraying|sprayed|"
    r"poison|chemical|glyphosate|roundup|2,?4-d|metsulfuron|paraquat|diquat|"
    r"dose|dosage|rate per hectare|application rate|"
    # amendments and actions
    r"lime|liming|gypsum|fertiliser|fertilizer|fertilise|fertilize|urea|superphosphate|"
    # explicit "should/how do I <verb>" requests
    r"should i (?:apply|spray|use|spread|add|sow|plant|burn|slash|cultivat|plough|plow|rip|drain|grade|lime|fertilise|fertilize)|"
    r"how (?:much|many) .*(?:spray|apply|spread|lime|urea|fertiliser|fertilizer|glyphosate|herbicide)|"
    r"how do i (?:kill|control|remove|eradicate|get rid of|spray|apply)|"
    r"how (?:can|do) i (?:kill|control|remove|eradicate)|"
    r"best way to (?:kill|control|remove|eradicate|get rid of)|"
    r"recommend|prescription|what should i do|"
    r"control (?:it|them|this|the weed)|manage (?:it|them|this)|"
    r"kill it|kill them|eradicate"
    r")\b",
    re.I)

# an explicit indicator question — the product's actual purpose
INDICATOR_RE = re.compile(
    r"("
    r"\bindicat(?:e|es|ing|or|ors)\b|"
    r"\bwhat does\b.*\b(?:mean|tell|say)\b|"
    r"\btell me about\b(?!\s+(?:quantum|physics|politics|history|the weather))|"
    r"\bwhat can you tell\b|"
    r"\bsoil indicator"
    r")",
    re.I)


def classify(message: str) -> str:
    """Return 'management', 'indicator', or 'other'.

    An explicit indicator question wins over incidental management vocabulary
    ("what does lime-loving capeweed indicate?"), because the product's purpose
    is indicators and the no-advice guard rail still applies downstream.
    """
    text = (message or "").strip()
    if not text:
        return "other"
    if INDICATOR_RE.search(text):
        return "indicator"
    if MANAGEMENT_RE.search(text):
        return "management"
    return "other"


def decline_response(kind: str = "management") -> str:
    """The refusal text for a management/advice request."""
    if kind == "management":
        return (
            "I can only tell you what weeds indicate about your soil — I don't give "
            "management, herbicide or dosing advice.\n\n"
            "If you tell me which weeds you're seeing, I'll explain what they suggest "
            "about moisture, pH, fertility, structure and salinity."
        )
    return (
        "I can only help with what weeds and plants indicate about soil conditions.\n\n"
        "Name a weed or plant and I'll explain what it says about your soil."
    )


if __name__ == "__main__":
    import sys

    probes = [
        ("What herbicide should I use on lantana?", "management"),
        ("Can you recommend a spray for capeweed?", "management"),
        ("Should I lime my paddock to fix acidity?", "management"),
        ("How do I kill serrated tussock?", "management"),
        ("What's the best way to control blackberry?", "management"),
        ("How much glyphosate per hectare?", "management"),
        ("Should I apply urea to the paddock?", "management"),
        ("what does dandelion indicate about my soil?", "indicator"),
        ("I have docks and thistles in my paddock", "other"),
        ("What does capeweed tell me about my soil?", "indicator"),
        ("Tell me about quantum physics", "other"),
        ("asdfghjkl", "other"),
        ("", "other"),
        ("What does lime-loving capeweed indicate?", "indicator"),
    ]
    bad = 0
    for q, want in probes:
        got = classify(q)
        ok = got == want
        bad += not ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {got:11s} want={want:11s} {q!r}")
    print(f"\n{len(probes)-bad}/{len(probes)} probes correct")
    sys.exit(1 if bad else 0)

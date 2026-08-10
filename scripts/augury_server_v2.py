#!/usr/bin/env python3
"""
AUGURY v2 Server — deterministic lookup + conversational formatter.

No model needed. 100% accurate. Runs on a Raspberry Pi.

The model (Qwen3-0.6B GGUF) is optional — when available, it replaces the
template formatter for more natural, varied responses.

Usage:
    python scripts/augury_server_v2.py
    → http://localhost:8080
"""

import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

# Add scripts dir for imports
sys.path.insert(0, str(Path(__file__).resolve().parent))

from flask import Flask, request, jsonify

from species_lookup import SpeciesDB
from augury_funnel import AuguryFunnel

app = Flask(__name__)

# ── Init ─────────────────────────────────────────────────────

db = SpeciesDB()

# Optional: GGUF formatter model (extracts species JSON + conversational tone).
# Without it, the funnel runs in deterministic template mode (100% accurate).
MODEL_PATH = os.environ.get("AUGURY_MODEL", "")
funnel = AuguryFunnel(model_path=MODEL_PATH if MODEL_PATH and os.path.exists(MODEL_PATH) else None, db=db)
model = funnel.model  # back-compat for the legacy formatter helpers below


# ── Template-based formatter ─────────────────────────────────

def format_response_template(result):
    """
    Convert structured species data into a clean, conversational response.
    No model needed. 100% accurate.
    """
    name = result["scientific_name"]
    common = result["common_names"][0] if result["common_names"] else None
    # Avoid duplicate like "Yorkshire fog (Holcus lanatus) (Holcus lanatus)"
    if common and name.lower() in common.lower():
        display = common
    elif common:
        display = f"{common} ({name})"
    else:
        display = name
    indicators = result["indicators"]
    region = result.get("region", "Europe")
    source = result.get("source", "")

    lines = [f"**{display}**"]

    # Moisture
    moisture = indicators.get("Moisture", "")
    if moisture and moisture.lower() != "not specified":
        lines.append(f"\n💧 **Moisture:** {moisture}")

    # pH
    ph = indicators.get("Soil pH", "")
    if ph and ph.lower() != "not specified":
        lines.append(f"\n🧪 **Soil pH:** {ph}")

    # Fertility
    fertility = indicators.get("Fertility", "")
    if fertility and fertility.lower() != "not specified":
        lines.append(f"\n🌱 **Fertility:** {fertility}")

    # Salinity
    salinity = indicators.get("Salinity", "")
    if salinity and salinity.lower() != "not specified":
        lines.append(f"\n🧂 **Salinity:** {salinity}")

    # Other recognized fields
    for key, val in indicators.items():
        if key not in ("Moisture", "Soil pH", "Fertility", "Salinity") and val.strip():
            if val.lower() != "not specified":
                lines.append(f"\n📋 **{key}:** {val}")

    # Specific nutrients (from enriched mining data)
    if "nutrients" in result:
        nut = result["nutrients"]
        high_claims = [c for c in nut["claims"]
                       if c.get("aggregate_confidence") in ("high", "medium")]
        if high_claims:
            # Deduplicate by nutrient
            seen = set()
            unique = []
            for c in high_claims:
                if c["nutrient"] not in seen:
                    seen.add(c["nutrient"])
                    unique.append(c)
            if unique:
                nut_text = "; ".join(
                    f"{c['nutrient']}: {c['relationship']}"
                    for c in unique[:5]
                )
                lines.append(f"\n🧂 **Specific nutrients:** {nut_text}")

    # Source
    if source:
        lines.append(f"\n---\n*Source: {source}*")

    return "\n".join(lines)


def format_response_model(result, user_question):
    """Use the GGUF model to generate a conversational response."""
    if not model:
        return format_response_template(result)

    name = result["scientific_name"]
    common = result["common_names"][0] if result["common_names"] else None
    # Avoid duplicate like "Yorkshire fog (Holcus lanatus) (Holcus lanatus)"
    if common and name.lower() in common.lower():
        display = common
    elif common:
        display = f"{common} ({name})"
    else:
        display = name
    region = result.get("region", "Europe")
    source = result.get("source", "")
    indicators = result["indicators"]

    # Build structured prompt with injected indicator data
    indicator_lines = []
    for key, val in indicators.items():
        if val and val.lower() != "not specified":
            indicator_lines.append(f"- {key}: {val}")

    # Add nutrient data
    if "nutrients" in result:
        nut = result["nutrients"]
        claims = [c for c in nut["claims"]
                  if c.get("aggregate_confidence") in ("high", "medium")]
        if claims:
            seen = set()
            for c in claims:
                if c["nutrient"] not in seen:
                    seen.add(c["nutrient"])
                    indicator_lines.append(
                        f"- {c['nutrient'].capitalize()}: {c['relationship']} — {c['detail']}"
                    )

    indicators_text = "\n".join(indicator_lines)

    SYSTEM = (
        "You are AUGURY, a soil health assistant specializing in weeds and plants "
        "as soil indicators. You receive structured soil indicator data and present "
        "it in clear, conversational language suitable for farmers and land managers. "
        "Never invent or modify indicator data. You do NOT provide management "
        "recommendations. Keep responses informative and grounded in the provided data."
    )

    question = f"[Region: {region}] {user_question}"

    prompt = (
        f"<|im_start|>system\n{SYSTEM}<|im_end|>\n"
        f"<|im_start|>user\n"
        f"Species: {display}\n"
        f"Region: {region}\n\n"
        f"Indicators:\n{indicators_text}\n\n"
        f"Source: {source}\n\n"
        f"{question}\n"
        f"<|im_end|>\n"
        f"<|im_start|>assistant\n"
    )

    output = model(
        prompt,
        max_tokens=400,
        temperature=0.3,
        top_p=0.9,
        stop=["<|im_end|>"],
    )
    return output["choices"][0]["text"].strip()


# ── Routes ───────────────────────────────────────────────────

FEEDBACK_FILE = os.environ.get("AUGURY_FEEDBACK", "feedback.jsonl")


@app.route("/")
def index():
    return HTML


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json()
    message = data.get("message", "").strip()
    region = data.get("region", "Europe")

    if not message:
        return jsonify({"error": "Empty message."}), 400

    # Single serving entry point: funnel does formatter→JSON species→lookup→DB→response
    r = funnel.answer(message, region=region)

    return jsonify({
        "response": r["response"],
        "species": r["species"],
        "matches": r["matches"],
        "refused": r["refused"],
        "region": region,
    })


@app.route("/api/search", methods=["GET"])
def search():
    """Search for species by name."""
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"results": []})

    matches = db.search(query, top_n=10)
    return jsonify({
        "results": [
            {
                "scientific_name": m["scientific_name"],
                "common_names": m["common_names"][:3],
                "match_type": m["match_type"],
                "score": m["score"],
            }
            for m in matches
        ]
    })


@app.route("/api/feedback", methods=["POST"])
def feedback():
    data = request.get_json()
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "question": data.get("question", ""),
        "response": data.get("response", ""),
        "species": data.get("species", ""),
        "rating": data.get("rating", ""),
        "region": data.get("region", ""),
    }
    with open(FEEDBACK_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return jsonify({"status": "ok"})


# ── HTML Chat Interface ──────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AUGURY — Weeds as Soil Indicators</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f5f0e8; color: #2d2a24; display: flex; flex-direction: column; height: 100vh; }
        .header { background: #4a6741; color: #fff; padding: 12px 20px; display: flex; align-items: center; gap: 10px; flex-shrink: 0; }
        .header h1 { font-size: 1.1em; }
        .badge { background: #e8c547; color: #2d2a24; font-size: 0.7em; padding: 2px 8px; border-radius: 8px; font-weight: 700; }
        .region-bar { display: flex; gap: 4px; padding: 8px 20px; background: #ede6d9; flex-shrink: 0; font-size: 0.8em; }
        .region-bar button { padding: 4px 12px; border-radius: 12px; border: 1px solid #c4b99a; background: #fff; cursor: pointer; color: #5a4a2f; }
        .region-bar button.active { background: #4a6741; color: #fff; border-color: #4a6741; font-weight: 600; }
        .examples { padding: 8px 20px; background: #faf7f0; font-size: 0.78em; color: #777; flex-shrink: 0; border-bottom: 1px solid #e0d8c8; }
        .examples span { cursor: pointer; color: #4a6741; text-decoration: underline; margin: 0 6px; }
        .chat { flex: 1; overflow-y: auto; padding: 16px 20px; }
        .msg { margin-bottom: 16px; max-width: 90%; }
        .msg.user { margin-left: auto; }
        .msg .bubble { padding: 12px 16px; border-radius: 16px; line-height: 1.6; font-size: 0.93em; white-space: pre-wrap; }
        .msg.user .bubble { background: #4a6741; color: #fff; border-bottom-right-radius: 4px; }
        .msg.assistant .bubble { background: #fff; border-bottom-left-radius: 4px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
        .msg .meta { font-size: 0.72em; color: #999; margin-top: 4px; display: flex; gap: 8px; align-items: center; }
        .msg.user .meta { justify-content: flex-end; }
        .feedback button { background: none; border: 1px solid #d5cfc5; border-radius: 8px; padding: 3px 10px; cursor: pointer; font-size: 0.8em; }
        .feedback button:hover { background: #f0ede5; }
        .input-area { display: flex; gap: 8px; padding: 12px 20px; background: #fff; border-top: 1px solid #e8e0d5; flex-shrink: 0; }
        .input-area input { flex: 1; padding: 12px 16px; border: 2px solid #d5cfc5; border-radius: 24px; font-size: 0.95em; outline: none; }
        .input-area input:focus { border-color: #4a6741; }
        .input-area button { background: #4a6741; color: #fff; border: none; border-radius: 24px; padding: 10px 20px; cursor: pointer; font-weight: 600; }
        .input-area button:disabled { opacity: .5; }
        .typing { color: #999; font-style: italic; padding: 12px 20px; font-size: 0.9em; }
    </style>
</head>
<body>
<div class="header">
    <span>🌱</span><h1>AUGURY</h1>
    <span class="badge">v2 BETA</span>
    <span style="margin-left:auto;font-size:0.7em;opacity:0.7">Weeds as Soil Indicators</span>
</div>
<div class="region-bar">
    <span style="color:#888;margin-right:8px">Region:</span>
    <button class="active" data-region="Europe">Europe</button>
    <button data-region="UK">UK</button>
    <button data-region="Australia">Australia</button>
</div>
<div class="examples">
    Try: <span onclick="ask('What does Yorkshire fog indicate?')">Yorkshire fog</span>
    <span onclick="ask('Tell me about dandelions')">dandelions</span>
    <span onclick="ask('What does capeweed mean for my soil?')">capeweed</span>
    <span onclick="ask('I have docks and thistles, what is going on?')">docks and thistles</span>
</div>
<div class="chat" id="chat">
    <div class="msg assistant">
        <div class="bubble">Hi! I'm AUGURY. I can tell you what soil conditions different weeds and plants indicate. Try asking me about any plant — dandelion, Yorkshire fog, capeweed, thistles, whatever is growing in your paddock.</div>
    </div>
</div>
<div class="input-area">
    <input type="text" id="input" placeholder="Ask about a weed or plant..." autofocus autocomplete="off">
    <button id="send" onclick="send()">Send</button>
</div>
<script>
let region = 'Europe';
document.querySelectorAll('.region-bar button').forEach(b => {
    b.addEventListener('click', () => {
        document.querySelectorAll('.region-bar button').forEach(x => x.classList.remove('active'));
        b.classList.add('active');
        region = b.dataset.region;
    });
});
document.getElementById('input').addEventListener('keydown', e => { if (e.key==='Enter') send(); });

function ask(text) { document.getElementById('input').value = text; send(); }

function addMsg(role, text, species) {
    const d = document.createElement('div');
    d.className = 'msg ' + role;
    d.innerHTML = '<div class="bubble">' + escapeHtml(text) + '</div>';
    if (role === 'assistant') {
        let meta = '<div class="meta">';
        if (species) meta += '<span>🔍 ' + species + '</span>';
        meta += '<span class="feedback"><button onclick="rate(this,\'good\')">👍</button><button onclick="rate(this,\'bad\')">👎</button></span>';
        meta += '</div>';
        d.innerHTML += meta;
    }
    document.getElementById('chat').appendChild(d);
    document.getElementById('chat').scrollTop = document.getElementById('chat').scrollHeight;
    return d;
}

function rate(btn, rating) {
    const msg = btn.closest('.msg');
    const bubble = msg.querySelector('.bubble').textContent;
    const speciesEl = msg.querySelector('.meta span');
    const species = speciesEl ? speciesEl.textContent.replace('🔍 ','') : '';
    // Get the last user question from the chat div (not the input field, which is cleared after send)
    const userMsgs = document.querySelectorAll('#chat .msg.user');
    const question = userMsgs.length > 0 ? userMsgs[userMsgs.length - 1].querySelector('.bubble').textContent : '';
    btn.parentElement.innerHTML = '✓ Thanks!';
    fetch('/api/feedback', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({rating, response: bubble, question, species, region})
    });
}

async function send() {
    const input = document.getElementById('input');
    const btn = document.getElementById('send');
    const text = input.value.trim();
    if (!text) return;
    input.value = ''; input.disabled = true; btn.disabled = true;
    addMsg('user', text);
    const typing = document.createElement('div'); typing.className='typing'; typing.textContent='Thinking...';
    document.getElementById('chat').appendChild(typing);
    try {
        const r = await fetch('/api/chat', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:text,region})});
        const d = await r.json();
        typing.remove();
        addMsg('assistant', d.response, d.species);
    } catch(e) {
        typing.remove();
        addMsg('assistant', 'Sorry, something went wrong.');
    }
    input.disabled = false; btn.disabled = false; input.focus();
}

function escapeHtml(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
}
</script>
</body>
</html>"""


# ── Main ─────────────────────────────────────────────────────

if __name__ == "__main__":
    mode = "🤖 AI model" if model else "📋 Template (100% accurate)"
    print(f"AUGURY v2 starting — {mode}")
    print(f"  Species database: {db.species_count} species")
    print(f"  With nutrients: {len(db._nutrients)} species")
    print(f"  Regions: {db.regions}")
    print(f"  http://localhost:8080")
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)

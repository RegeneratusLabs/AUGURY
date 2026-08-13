#!/usr/bin/env python3
"""
AUGURY Chat — conversational soil indicator assistant with feedback.

Run locally or deploy on VPS:
  pip install flask llama-cpp-python
  python augury_server.py
"""

import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from flask import Flask, request, jsonify, session, render_template_string

sys.path.insert(0, str(Path(__file__).resolve().parent))
from augury_funnel import AuguryFunnel

app = Flask(__name__)
app.secret_key = os.urandom(24)

# The trained formatter (AUGURY voice) — species extraction is deterministic
# regex + DB lookup inside the funnel; the model only composes the story.
MODEL_PATH = os.environ.get(
    "AUGURY_MODEL",
    os.path.join(os.path.dirname(__file__), "..", "models", "MiniCPM5-1B-AUGURY-Q4_K_M.gguf"),
)
FEEDBACK_FILE = os.environ.get("AUGURY_FEEDBACK", "feedback.jsonl")

print(f"Loading formatter model: {MODEL_PATH}")
funnel = AuguryFunnel(model_path=MODEL_PATH if os.path.exists(MODEL_PATH) else None)
print("Funnel ready (model loaded)" if funnel.model else "Funnel ready (template mode — no model found)")

SYSTEM_PROMPT = (
    "You are AUGURY, a soil health assistant specializing in weeds and plants as soil indicators. "
    "When given a plant species, you describe what soil conditions it indicates — including "
    "compaction, drainage, nutrient imbalances, pH, organic matter state, and microbial "
    "activity. Always include both the common name and scientific name when known. "
    "You do NOT provide management recommendations or solutions. You respond "
    "in clear, plain language suitable for farmers. "
    "If asked about anything other than plants and soil indicators, respond with: "
    "\"I'm a soil indicator specialist — I can only help with questions about what plants and weeds tell us about soil health. Try asking me about a specific plant species.\""
)

HTML = r"""<!DOCTYPE html>
<html>
<head>
    <title>AUGURY Chat</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #f5f0e8; color: #2d2a24; display: flex; flex-direction: column; height: 100vh; }
        .header { background: #4a6741; color: white; padding: 12px 20px; display: flex; align-items: center; gap: 10px; flex-shrink: 0; }
        .header h1 { font-size: 1.1em; font-weight: 600; }
        .beta { background: #ffd54f; color: #2d2a24; font-size: 0.7em; padding: 2px 8px; border-radius: 8px; font-weight: 700; }
        .region-bar { display: flex; gap: 4px; padding: 8px 20px; background: #ede6d9; flex-shrink: 0; font-size: 0.8em; }
        .region-bar a { padding: 4px 12px; border-radius: 12px; text-decoration: none; color: #6b5e4c; cursor: pointer; }
        .region-bar a.active { background: #5a8a3c; color: white; font-weight: 600; }
        .chat { flex: 1; overflow-y: auto; padding: 16px 20px; }
        .msg { margin-bottom: 16px; max-width: 85%; }
        .msg.user { margin-left: auto; }
        .msg .bubble { padding: 12px 16px; border-radius: 16px; line-height: 1.5; font-size: 0.95em; }
        .msg.user .bubble { background: #5a8a3c; color: white; border-bottom-right-radius: 4px; }
        .msg.assistant .bubble { background: white; border-bottom-left-radius: 4px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
        .msg .meta { font-size: 0.75em; color: #999; margin-top: 4px; }
        .msg.user .meta { text-align: right; }
        .feedback { display: flex; gap: 8px; margin-top: 6px; align-items: center; }
        .feedback button { background: none; border: 1px solid #d5cfc5; border-radius: 8px; padding: 3px 10px; cursor: pointer; font-size: 0.85em; }
        .feedback button:hover { background: #f0ede5; }
        .feedback .thanks { color: #5a8a3c; font-size: 0.75em; margin-left: 6px; }
        .input-area { display: flex; gap: 8px; padding: 12px 20px; background: white; border-top: 1px solid #e8e0d5; flex-shrink: 0; }
        .input-area input { flex: 1; padding: 12px 16px; border: 2px solid #d5cfc5; border-radius: 24px; font-size: 0.95em; outline: none; }
        .input-area input:focus { border-color: #5a8a3c; }
        .input-area button { background: #5a8a3c; color: white; border: none; border-radius: 24px; padding: 10px 18px; cursor: pointer; font-weight: 600; font-size: 0.9em; }
        .input-area button:disabled { opacity: 0.5; }
        .typing { color: #999; font-style: italic; padding: 12px 20px; font-size: 0.9em; }
    </style>
</head>
<body>
    <div class="header">
        <span>🌱</span>
        <h1>AUGURY</h1>
        <span class="beta">BETA</span>
    </div>
    <div class="region-bar">
        Region:
        <a href="#" class="active" data-region="Europe">Europe</a>
        <a href="#" data-region="UK">UK</a>
        <a href="#" data-region="Australia">Australia</a>
    </div>
    <div class="chat" id="chat">
        <div class="msg assistant">
            <div class="bubble">Hi! I'm AUGURY. I can tell you what soil conditions different weeds and plants indicate. Try asking me about any plant — dandelion, Yorkshire fog, capeweed, thistles, whatever's growing in your paddock.</div>
        </div>
    </div>
    <div class="input-area">
        <input type="text" id="input" placeholder="Ask about a plant..." autofocus autocomplete="off">
        <button id="sendBtn" onclick="send()">Send</button>
    </div>

    <script>
        let currentRegion = 'Europe';

        document.querySelectorAll('.region-bar a').forEach(link => {
            link.addEventListener('click', e => {
                e.preventDefault();
                document.querySelectorAll('.region-bar a').forEach(l => l.classList.remove('active'));
                e.target.classList.add('active');
                currentRegion = e.target.dataset.region;
            });
        });

        document.getElementById('input').addEventListener('keydown', e => {
            if (e.key === 'Enter') send();
        });

        function addMessage(role, text) {
            const chat = document.getElementById('chat');
            const div = document.createElement('div');
            div.className = 'msg ' + role;
            div.innerHTML = '<div class="bubble">' + escapeHtml(text).replace(/\n/g, '<br>') + '</div>';
            if (role === 'assistant') {
                let fbHtml = '<div class="feedback">';
                fbHtml += '<button onclick="rate(this,\'good\')">👍 Helpful</button>';
                fbHtml += '<button onclick="rate(this,\'bad\')">👎 Not quite</button>';
                fbHtml += '<span class="thanks" style="display:none">Thanks!</span>';
                fbHtml += '</div>';
                div.innerHTML += fbHtml;
            }
            chat.appendChild(div);
            chat.scrollTop = chat.scrollHeight;
            return div;
        }

        function rate(btn, rating) {
            const msgDiv = btn.closest('.msg.assistant');
            const bubble = msgDiv.querySelector('.bubble').textContent;
            const btns = msgDiv.querySelectorAll('.feedback button');
            btns.forEach(b => b.disabled = true);
            msgDiv.querySelector('.thanks').style.display = 'inline';

            fetch('/feedback', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    rating: rating,
                    response: bubble,
                    question: document.querySelector('#chat .msg.user:last-of-type .bubble')?.textContent || '',
                    region: currentRegion,
                    timestamp: new Date().toISOString()
                })
            });
        }

        async function send() {
            const input = document.getElementById('input');
            const sendBtn = document.getElementById('sendBtn');
            const text = input.value.trim();
            if (!text) return;

            input.value = '';
            input.disabled = true;
            sendBtn.disabled = true;

            addMessage('user', text);

            const chatDiv = document.getElementById('chat');
            const typing = document.createElement('div');
            typing.className = 'typing';
            typing.textContent = 'Thinking...';
            chatDiv.appendChild(typing);

            try {
                const resp = await fetch('/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: text, region: currentRegion })
                });
                const data = await resp.json();
                typing.remove();
                addMessage('assistant', data.response);
            } catch (err) {
                typing.remove();
                addMessage('assistant', 'Sorry, something went wrong. Is the server still running?');
            }

            input.disabled = false;
            sendBtn.disabled = false;
            input.focus();
        }

        function escapeHtml(str) {
            const div = document.createElement('div');
            div.textContent = str;
            return div.innerHTML;
        }
    </script>
</body>
</html>"""


@app.route("/")
def index():
    return HTML


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    message = data.get("message", "").strip()
    region = data.get("region", "Europe")

    if not message:
        return jsonify({"error": "Empty message."}), 400

    # Quick pre-filter: reject obviously non-plant queries
    non_plant_patterns = [
        "what is the capital", "how old are you", "who are you",
        "what is your name", "what's your name", "write a poem",
        "write code", "recipe", "weather", "news", "stock",
        "president", "prime minister", "football", "movie",
        "song", "hello", "hi there", "what's up", "how are you",
        "tell me a joke", "what is the meaning of life",
    ]
    msg_lower = message.lower().strip()
    if any(p in msg_lower for p in non_plant_patterns) and not any(
        plant_word in msg_lower
        for plant_word in [
            "weed", "plant", "grass", "flower", "indicate", "soil",
            "growing", "paddock", "pasture", "field", "crop",
            "dandelion", "thistle", "nettle", "dock", "clover",
            "buttercup", "yarrow", "chicory", "sorrel", "plantain",
        ]
    ):
        return jsonify({
            "response": (
                "I'm a soil indicator specialist — I can only help with questions about "
                "what plants and weeds tell us about soil health. Try asking me about a "
                "specific plant species you've noticed growing in your paddock or field."
            )
        })

    question = f"[Region: {region}] {message}"

    result = funnel.answer(message, region=region)
    response = result["response"]

    return jsonify({
        "response": response,
        "species": result["species"],
        "refused": result["refused"],
        "matches": result["matches"],
    })


@app.route("/feedback", methods=["POST"])
def feedback():
    data = request.get_json()
    entry = {"timestamp": datetime.utcnow().isoformat(), **data}
    with open(FEEDBACK_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    # threaded=False: one model, one generation at a time (concurrency would
    # thrash CPU and inflate latency — the funnel is the bottleneck, not Flask)
    app.run(host="0.0.0.0", port=port, debug=False, threaded=False)

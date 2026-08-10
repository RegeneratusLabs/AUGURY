#!/usr/bin/env python3
"""Quick chat interface for localNFchatbot."""
import sys
sys.path.insert(0, '.')
from flask import Flask, request, jsonify
from llama_cpp import Llama

app = Flask(__name__)

model = Llama(
    model_path="models/localNFchatbot-Q4_K_M.gguf",
    n_ctx=2048,
    n_gpu_layers=0,
    verbose=False,
)
print("Model loaded.")

HTML = r"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>localNFchatbot</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,sans-serif;background:#1a1a2e;color:#e0e0e0;display:flex;flex-direction:column;height:100vh}
.header{background:#16213e;padding:12px 20px;display:flex;align-items:center;gap:10px}
.header h1{font-size:1em}
.badge{background:#0f3460;padding:2px 8px;border-radius:8px;font-size:.7em}
.chat{flex:1;overflow-y:auto;padding:16px 20px}
.msg{margin-bottom:14px;max-width:85%}
.msg.user{margin-left:auto}
.msg .bubble{padding:10px 14px;border-radius:14px;line-height:1.5;font-size:.9em;white-space:pre-wrap}
.msg.user .bubble{background:#0f3460;border-bottom-right-radius:4px}
.msg.assistant .bubble{background:#16213e;border-bottom-left-radius:4px}
.input-area{display:flex;gap:8px;padding:12px 20px;background:#16213e;border-top:1px solid #0f3460}
.input-area input{flex:1;padding:10px 14px;border:1px solid #0f3460;border-radius:20px;background:#1a1a2e;color:#e0e0e0;font-size:.9em;outline:none}
.input-area input:focus{border-color:#533483}
.input-area button{background:#533483;color:#fff;border:none;border-radius:20px;padding:8px 16px;cursor:pointer;font-weight:600}
.input-area button:disabled{opacity:.5}
.typing{color:#888;font-style:italic;padding:8px 20px;font-size:.85em}
</style></head><body>
<div class="header"><span>🌱</span><h1>localNFchatbot</h1><span class="badge">CopyleftCultivars</span></div>
<div class="chat" id="chat">
<div class="msg assistant"><div class="bubble">Hi! I'm localNFchatbot, trained by Copyleft Cultivars. Ask me about natural farming, soil health, composting, and regenerative agriculture.</div></div>
</div>
<div class="input-area">
<input id="input" placeholder="Ask about natural farming..." autofocus>
<button id="send" onclick="send()">Send</button>
</div>
<script>
document.getElementById('input').addEventListener('keydown',e=>{if(e.key==='Enter')send()});
async function send(){
const i=document.getElementById('input'),b=document.getElementById('send'),t=i.value.trim();
if(!t)return;i.value='';i.disabled=b.disabled=true;
const d=document.createElement('div');d.className='msg user';d.innerHTML='<div class="bubble">'+escapeHtml(t)+'</div>';document.getElementById('chat').appendChild(d);
const ty=document.createElement('div');ty.className='typing';ty.textContent='...';document.getElementById('chat').appendChild(ty);
try{const r=await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:t})});
const j=await r.json();ty.remove();
const a=document.createElement('div');a.className='msg assistant';a.innerHTML='<div class="bubble">'+escapeHtml(j.response)+'</div>';document.getElementById('chat').appendChild(a);}
catch(e){ty.remove();const a=document.createElement('div');a.className='msg assistant';a.innerHTML='<div class="bubble">Error.</div>';document.getElementById('chat').appendChild(a);}
i.disabled=b.disabled=false;i.focus();document.getElementById('chat').scrollTop=document.getElementById('chat').scrollHeight}
function escapeHtml(s){const d=document.createElement('div');d.textContent=s;return d.innerHTML}
</script></body></html>"""

@app.route("/")
def index():
    return HTML

@app.route("/chat", methods=["POST"])
def chat():
    msg = request.get_json().get("message", "").strip()
    if not msg:
        return jsonify({"response": "Please ask something."})
    prompt = f"<|im_start|>user\n{msg}<|im_end|>\n<|im_start|>assistant\n"
    output = model(prompt, max_tokens=400, temperature=0.7, top_p=0.9, repeat_penalty=1.15, stop=["<|im_end|>"])
    return jsonify({"response": output["choices"][0]["text"].strip()})

if __name__ == "__main__":
    print("http://localhost:8080")
    app.run(host="0.0.0.0", port=8080, debug=False)

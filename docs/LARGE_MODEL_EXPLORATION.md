# AUGURY — Large Model Exploration (July 2026)

Saved from a deep architecture discussion. This is the "reasoning engine" path — a 4-8B model
that thinks like a regenerative agronomist, uses a species database via function calling,
and synthesizes multi-indicator patterns with hybrid thinking mode.

Not the current path. Kept for future reference when the project is ready to move beyond
simple species-to-indicators lookup.

---

## The vision

A model that doesn't just look up indicators but *thinks* about what they mean together.
Given multiple weed species in a paddock, it reasons about succession patterns, grazing
management implications, and what the soil system is saying — in conversational,
farmer-friendly language.

```
User: "Docks and thistles spreading in my horse paddock"
     │
     ▼
┌─────────────────────────────────────┐
│  Reasoning model (4-8B, offline)     │
│  Trained on regenerative ag theory   │
│  Native function calling + thinking  │
└─────────────────────────────────────┘
     │
     ├── function_call: lookup_species("Rumex obtusifolius", "UK")
     ├── function_call: lookup_species("Cirsium vulgare", "UK")
     │
     ▼
┌─────────────────────────────────────┐
│  Species lookup engine (deterministic)│
│  100% ground truth indicator data    │
└─────────────────────────────────────┘
     │
     ▼
  Synthesized, conversational response
```

The model doesn't memorize facts. It learns to reason. The database is the source of truth.

---

## Target models (July 2026)

| Model | Params | GGUF Q4_K_M | RAM | Thinking | Function calling | Released |
|---|---|---|---|---|---|---|
| **Gemma 4 E4B** 🏆 | 4.5B eff / 8B total | ~5.0 GB | 7-8 GB | Native `<\|think\|>` | Native built-in | Jul 2026 |
| **Qwen3.5-4B** | 4B | ~2.7 GB | 4-5 GB | Configurable | Strong agent/tool-use | Feb 2026 |
| DeepSeek-R1-0528-Qwen3-8B | 8B | ~5.0 GB | 7-8 GB | CoT native | None | May 2025 |

**Primary recommendation: Gemma 4 E4B.** Native function calling means the tool-use
pattern is configured, not trained. Native thinking mode means the model can reason
before responding. The training data focuses purely on regenerative ag frameworks and
communication style.

**Fallback: Qwen3.5-4B.** Smaller GGUF (2.7GB vs 5.0GB) fits comfortably in 8GB RAM.
Still has thinking mode and strong tool-use. Good for tighter hosting budgets.

---

## Training approach

### What the model learns

| Skill | Source | Examples |
|---|---|---|
| When to call `lookup_species` | Function-calling config + few examples | ~200 |
| Multi-indicator synthesis | Curated scenarios | ~800 |
| Regenerative ag frameworks | Theory texts (Savory, Brown, etc.) | ~800 |
| Farmer communication | Example responses | ~500 |
| Refusal + safety | Synthetic edge cases | ~500 |
| **Total** | | **~2,800** |

### What it does NOT learn

- Individual species indicator values → in the JSON database
- Species name matching → deterministic lookup engine
- Common name mappings → post-processing layer

---

## Architecture

```
┌─────────────────────────────────────────┐
│  AUGURY Server (Flask + llama.cpp)       │
│                                         │
│  ┌─────────────────────────────────┐    │
│  │  Reasoning model (GGUF)         │    │
│  │  - Regenerative ag frameworks   │    │
│  │  - Multi-indicator synthesis    │    │
│  │  - Native function calling      │    │
│  │  - Native thinking mode         │    │
│  └─────────────────────────────────┘    │
│              │                          │
│              │ function_call            │
│              ▼                          │
│  ┌─────────────────────────────────┐    │
│  │  Species lookup engine          │    │
│  │  - unified_species_database.json│    │
│  │  - Fuzzy matching               │    │
│  │  - Common name index            │    │
│  │  - 100% ground truth            │    │
│  └─────────────────────────────────┘    │
│              │                          │
│              ▼                          │
│  ┌─────────────────────────────────┐    │
│  │  Response renderer              │    │
│  │  - Conversational formatting    │    │
│  │  - Common name injection        │    │
│  └─────────────────────────────────┘    │
└─────────────────────────────────────────┘
```

---

## Development path

1. Build species lookup engine (JSON + fuzzy match + common names)
2. Build function-call interceptor in Flask server
3. Curate ~2,800 training examples across 4 layers
4. Train QLoRA on Gemma 4 E4B (Colab T4 or Modal A10G)
5. Evaluate: multi-species synthesis, refusal accuracy, formatting consistency
6. Deploy with instrumented feedback

---

## Deployment

- **Desktop:** GGUF runs on any 16GB machine via llama.cpp
- **Hosted:** $30/mo VPS (8 vCPU, 16GB RAM) serves phone users
- **Phone access:** Same chat interface, server-hosted, data stays on your VPS
- **Offline desktop:** Full model runs locally, no internet needed

---

## The tradeoff vs 0.5B approach

| | 0.5B lookup + format | 4-8B reasoning engine |
|---|---|---|
| Model size | ~350 MB | 2.7-5.0 GB |
| What it does | Retrieves and formats indicators | Reasons about what indicators mean together |
| Multi-species | Basic concatenation | Synthesis with succession thinking |
| Training data | ~2K formatting examples | ~2.8K reasoning examples |
| Can it explain *why*? | No — just shows indicators | Yes — applies frameworks |
| Can it spot patterns? | No | Yes — "these two together suggest..." |
| Best for | Quick field lookup | Deep land assessment |

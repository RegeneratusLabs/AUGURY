---
license: apache-2.0
base_model: openbmb/MiniCPM5-1B
tags:
- soil
- agriculture
- weeds
- regenerative-agriculture
- text-generation
- lora
- gguf
language:
- en
pipeline_tag: text-generation
---

# AUGURY 1B — weeds as soil indicators, in the farmer's voice

A LoRA fine-tune of [MiniCPM5-1B](https://huggingface.co/openbmb/MiniCPM5-1B) that
turns structured soil-indicator facts into a clear, conversational soil story.
**The model never invents facts** — it receives them from the AUGURY species
database and presents them.

```
species + indicators (from the AUGURY database)
        │  [MiniCPM5-1B + LoRA — this model]
        ▼
"This is what Capeweed is telling you about your soil. ..."
```

## What it does (and doesn't)

- ✅ Presents given indicator facts in natural, farmer-friendly language
- ✅ Handles AU + EU species, region-aware phrasing
- ✅ Politely refuses non-plant / management questions
- ❌ Does **not** identify plants from photos (that's the retrieval layer)
- ❌ Does **not** generate indicator facts from memory
- ❌ Does **not** give management, herbicide, or remediation advice

## Quick start

### llama.cpp (GGUF — phone / edge)

```bash
wget https://huggingface.co/RegeneratusLabs/augury-1b/resolve/main/MiniCPM5-1B-AUGURY-Q4_K_M.gguf
llama-server -m MiniCPM5-1B-AUGURY-Q4_K_M.gguf --port 8080
```

The chat template (chatml, `minicpm`) is embedded in the GGUF. Feed it the
system prompt + a user message shaped like the training data (see below).

### Transformers (merged fp16)

```python
from transformers import AutoModelForCausalLM, AutoTokenizer

tok = AutoTokenizer.from_pretrained("openbmb/MiniCPM5-1B")
model = AutoModelForCausalLM.from_pretrained(
    "RegeneratusLabs/augury-1b", subfolder="merged-fp16")
```

## Input contract (this is how the model was trained)

```
System: You are AUGURY, a soil health assistant specializing in weeds and plants
        as soil indicators. You receive structured soil indicator data and present
        it in clear, conversational language suitable for farmers and land
        managers. ... Never invent or modify indicator data — only present what
        is provided. ... You do NOT provide management recommendations,
        herbicide advice, or agronomic prescriptions.

User:   Species: Capeweed (Arctotheca calendula)
        Region: Australia

        Indicators:
        - Moisture: dry to moderately dry, well-drained soils
        - Soil pH: neutral to slightly acidic
        - Fertility: moderate, tolerates low fertility

        What does this tell me about my soil?
```

In production the AUGURY funnel server builds this prompt from the species
database (`RegeneratusLabs/augury-species-db`) — never from the model's memory.

## Training

| | |
|---|---|
| Base | openbmb/MiniCPM5-1B (1.1B) |
| Data | `RegeneratusLabs/augury-training-data` — 13,627 train / 1,514 val rows, AU-balanced (186/188 AU species) |
| Method | LoRA (r=16, alpha=32), 3 epochs, lr 2e-4 cosine, effective batch 32, bf16 |
| Hardware | ModelScope PAI-DSW A10 24GB |
| Eval | val loss **0.0398** · local smoke: 6/6 fact-keys echoed, correct refusal |

## Limitations

- AU-first: Australian species are fully represented; European Ellenberg rows
  dominate in raw count but AU species each carry region-tagged examples.
- Fine-tuned on one format — deviate far from the input contract and quality drops.
- Indicator claims are literature-based, not field-verified.

## Files

- `MiniCPM5-1B-AUGURY-Q4_K_M.gguf` — phone-ready (~660MB)
- `MiniCPM5-1B-AUGURY-F16.gguf` — full precision GGUF
- `merged-fp16/` — merged safetensors for transformers
- `lora-adapter/` — the LoRA adapter (reproducibility)

## License

Apache-2.0 (weights). Training data CC-BY-4.0 (see the dataset repos).

## Project

Repo: github.com/RegeneratusLabs/AUGURY · Model card: 2026-08-12

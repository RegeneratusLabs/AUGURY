#!/usr/bin/env python3
"""
Convert V3 training data from Qwen function_call JSON format
to MiniCPM5 XML tool-call format.

Qwen format:  <function_call>{"name": "lookup_species", "arguments": {...}}</function_call>
MiniCPM5:     <tool_call>{"name": "lookup_species", "arguments": {...}}</tool_call>

Usage:
    python scripts/convert_to_minicpm5_format.py
    → data/v3_function_calling/minicpm5/
"""

import json, os, re, glob
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent / "data" / "v3_function_calling"
OUT = BASE / "minicpm5"

os.makedirs(OUT, exist_ok=True)

def convert_messages(messages):
    """Convert a list of message dicts from Qwen to MiniCPM5 format."""
    new_msgs = []
    for msg in messages:
        role = msg["role"]
        content = msg.get("content", "")
        
        if role == "tool_response" or role == "tool":
            # Tool responses become user context in MiniCPM5 format.
            # The model sees the DB data and then formats the final answer.
            # No dummy assistant message — keeps roles alternating cleanly.
            new_msgs.append({"role": "user", "content": f"[Tool response]:\n{content}"})
            continue
        
        # Convert function_call to tool_call XML format
        if content and "<function_call>" in content:
            # Extract the JSON from function_call tags
            def replace_fc(m):
                inner = m.group(1)
                return f"<tool_call>{inner}</tool_call>"
            content = re.sub(r"<function_call>(.*?)</function_call>", replace_fc, content, flags=re.DOTALL)
        
        if role == "assistant" and content:
            # Wrap final assistant responses (not tool calls) with a thinking hint
            if "<tool_call>" not in content:
                pass  # Keep as-is
        
        new_msgs.append({"role": role, "content": content})
    
    return new_msgs


def main():
    stats = {"files": 0, "examples": 0, "converted": 0}
    
    for fn in sorted(glob.glob(str(BASE / "*.jsonl"))):
        fname = os.path.basename(fn)
        out_path = OUT / fname
        
        with open(fn) as f:
            lines = f.readlines()
        
        new_lines = []
        for line in lines:
            stats["examples"] += 1
            row = json.loads(line)
            new_msgs = convert_messages(row.get("messages", []))
            row["messages"] = new_msgs
            new_lines.append(json.dumps(row, ensure_ascii=False))
            
            # Count conversions
            if "<tool_call>" in line:
                stats["converted"] += 1
        
        with open(out_path, "w") as f:
            f.write("\n".join(new_lines) + "\n")
        
        print(f"  {fname}: {len(lines)} examples -> {out_path}")
        stats["files"] += 1
    
    print(f"\n=== Conversion complete ===")
    print(f"Files: {stats['files']}")
    print(f"Examples: {stats['examples']}")
    print(f"Tool-call conversions: {stats['converted']}")


if __name__ == "__main__":
    main()

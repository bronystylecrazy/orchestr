#!/usr/bin/env python3
"""Render a claude stream-json session live; save the final result event to argv[1]."""
import json
import sys

outpath = sys.argv[1]
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        ev = json.loads(line)
    except json.JSONDecodeError:
        continue
    t = ev.get("type")
    if t == "assistant":
        for b in (ev.get("message") or {}).get("content", []):
            if b.get("type") == "text" and b.get("text", "").strip():
                for chunk in b["text"].strip().splitlines():
                    print(f"  » {chunk[:200]}", flush=True)
            elif b.get("type") == "tool_use":
                inp = b.get("input", {}) or {}
                brief = inp.get("command") or inp.get("file_path") or inp.get("description") or ""
                print(f"  ⚙ {b.get('name')}: {str(brief)[:160]}", flush=True)
    elif t == "result":
        with open(outpath, "w") as f:
            f.write(json.dumps(ev))
        print(f"  ✔ session done: {(ev.get('result') or '')[:160]}", flush=True)

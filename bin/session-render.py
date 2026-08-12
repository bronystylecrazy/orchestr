#!/usr/bin/env python3
"""Render a claude stream-json session live; save the final result event to argv[1]."""
import json
import sys

outpath = sys.argv[1]
tty = sys.stdout.isatty()
DIM, CYAN, GREEN, RESET = ("\033[2m", "\033[36m", "\033[32m", "\033[0m") if tty else ("",) * 4


def clip(s, n=300):
    s = s.rstrip()
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0] + " …"


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
            if b.get("type") == "text":
                for chunk in b.get("text", "").splitlines():
                    if chunk.strip():
                        print(f"  {DIM}»{RESET} {clip(chunk)}", flush=True)
            elif b.get("type") == "tool_use":
                inp = b.get("input", {}) or {}
                brief = inp.get("command") or inp.get("file_path") or inp.get("description") or ""
                print(f"  {CYAN}⚙ {b.get('name')}{RESET}: {clip(str(brief), 160)}", flush=True)
    elif t == "result":
        with open(outpath, "w") as f:
            f.write(json.dumps(ev))
        cost = ev.get("total_cost_usd")
        secs = (ev.get("duration_ms") or 0) / 1000
        print(f"  {GREEN}✔ session done{RESET} — ${cost:.2f}, {secs:.0f}s, "
              f"{ev.get('num_turns')} turns" if cost is not None else "  ✔ session done", flush=True)

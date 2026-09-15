"""Deterministic Codex CLI stand-in for subprocess integration tests."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path


def option(name: str) -> str | None:
    try:
        return sys.argv[sys.argv.index(name) + 1]
    except (ValueError, IndexError):
        return None


if sys.argv[1:3] == ["login", "status"]:
    print("Logged in using synthetic fixture")
    raise SystemExit(0)

mode = os.environ.get("FAKE_CODEX_MODE", "success")
if mode == "fail":
    print("synthetic authentication failure", file=sys.stderr)
    raise SystemExit(3)
if mode == "stall":
    time.sleep(60)
if mode == "spawn_child":
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    print(json.dumps({"type": "fixture.child", "pid": child.pid}), flush=True)
    time.sleep(60)

print(json.dumps({"type": "thread.started", "thread_id": "synthetic"}), flush=True)
print(json.dumps({"type": "turn.started"}), flush=True)
print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 12, "output_tokens": 4}}), flush=True)
target = option("--output-last-message") or option("-o")
if target:
    payload = os.environ.get("FAKE_CODEX_RESULT", '{"answer":"synthetic answer","citations":[]}')
    Path(target).write_text("not-json" if mode == "invalid" else payload, encoding="utf-8")
raise SystemExit(0)

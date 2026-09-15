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
if sys.argv[1:3] == ["exec", "--help"]:
    if os.environ.get("FAKE_CODEX_INCOMPATIBLE"):
        print("--json")
    else:
        print("--sandbox --ephemeral --ignore-user-config --ignore-rules --output-schema --output-last-message --json --strict-config --disable")
    raise SystemExit(0)
if sys.argv[1:3] == ["features", "list"]:
    for feature in ("shell_tool", "apps", "hooks", "browser_use", "computer_use", "plugins", "skill_search", "web_search_request", "in_app_browser"):
        print(f"{feature} stable true")
    raise SystemExit(0)

mode = os.environ.get("FAKE_CODEX_MODE", "success")
argv_target = os.environ.get("FAKE_CODEX_ARGV_FILE")
if argv_target:
    Path(argv_target).write_text(json.dumps(sys.argv[1:]), encoding="utf-8")
if mode == "fail":
    print("synthetic authentication failure", file=sys.stderr)
    raise SystemExit(3)
if mode == "usage":
    print("usage limit exhausted", file=sys.stderr)
    raise SystemExit(4)
if mode == "stall":
    time.sleep(60)
if mode == "spawn_child":
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    print(json.dumps({"type": "fixture.child", "pid": child.pid}), flush=True)
    time.sleep(60)

print(json.dumps({"type": "thread.started", "thread_id": "synthetic"}), flush=True)
if mode == "stream":
    time.sleep(0.35)
print(json.dumps({"type": "turn.started"}), flush=True)
print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 12, "output_tokens": 4}}), flush=True)
target = option("--output-last-message") or option("-o")
if target:
    payload = os.environ.get("FAKE_CODEX_RESULT", '{"answer":"synthetic answer","citations":[]}')
    Path(target).write_text("not-json" if mode == "invalid" else payload, encoding="utf-8")
raise SystemExit(0)

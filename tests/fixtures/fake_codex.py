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
        print("--sandbox --ephemeral --ignore-user-config --ignore-rules --output-schema --output-last-message --json --strict-config --disable --oss --local-provider")
    raise SystemExit(0)
if sys.argv[1:3] == ["features", "list"]:
    for feature in ("shell_tool", "apps", "hooks", "browser_use", "computer_use", "plugins", "skill_search", "web_search_request", "in_app_browser"):
        print(f"{feature} stable true")
    raise SystemExit(0)

mode = os.environ.get("FAKE_CODEX_MODE", "success")
if mode == "ignore_stdin":
    pid_target = os.environ.get("FAKE_CODEX_PID_FILE")
    if pid_target:
        Path(pid_target).write_text(str(os.getpid()), encoding="utf-8")
    event = json.dumps({"type": "fixture.output", "data": "x" * 4000})
    for _ in range(400):
        print(event, flush=True)
    time.sleep(60)

prompt = sys.stdin.read()
for marker, selected in (
    ("FIXTURE_STALL", "stall"),
    ("FIXTURE_INVALID", "invalid"),
    ("FIXTURE_FAIL", "fail"),
):
    if marker in prompt:
        mode = selected
        break
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
    supplied = os.environ.get("FAKE_CODEX_RESULT")
    schema = Path(option("--output-schema") or "").name
    has_helper = "helper.py" in prompt
    quiz = [
        {
            "id": f"fixture-{index}",
            "question": f"Question {index}: which file owns the saved entry behavior?",
            "options": ["main.py", "database.py", "browser.js", "deployment.yml"],
            "correct_index": 0,
            "explanations": [
                "Correct. main.py contains the cited entry behavior.",
                "database.py is not present in this saved snapshot.",
                "browser.js is not present in this saved snapshot.",
                "deployment.yml is not present in this saved snapshot.",
            ],
            "evidence": [{"path": "main.py", "line": 1, "end_line": 1, "label": "Saved entry", "valid": True}],
        }
        for index in range(1, 11)
    ]
    defaults = {
        "architecture.json": json.dumps({
            "summary": "A small synthetic service used to verify the complete review flow.",
            "main_path": ["entry", "helper"] if has_helper else ["entry"],
            "components": [
                {"id": "entry", "name": "Entry point", "kind": "backend", "responsibility": "Starts the synthetic service.", "sources": [{"path": "main.py", "line": 1, "end_line": 1, "label": "Entry point", "valid": True}], "source_paths": ["main.py"]},
                *([{"id": "helper", "name": "Helper", "kind": "backend", "responsibility": "Provides the extracted greeting.", "sources": [{"path": "helper.py", "line": 1, "end_line": 1, "label": "Helper implementation", "valid": True}], "source_paths": ["helper.py"]}] if has_helper else []),
            ],
            "relationships": ([{"source": "entry", "target": "helper", "kind": "imports", "label": "imports", "inferred": False, "sources": [{"path": "main.py", "line": 1, "end_line": 1, "label": "Import", "valid": True}]}] if has_helper else []),
        }),
        "critique.json": json.dumps({
            "strengths": ["The entry point is short and its responsibility is visible."],
            "findings": [{"id": "separate-greeting", "severity": "low", "title": "Keep greeting logic cohesive", "observation": "The greeting is owned by the entry module.", "why_it_matters": "A clear owner makes future behavior easier to find.", "improvement": "Extract it only when another caller needs the same behavior.", "tradeoffs": "An early extraction would add a module without immediate value.", "evidence": [{"path": "main.py", "line": 1, "end_line": 1, "label": "Greeting entry", "valid": True}]}],
            "lessons": [{"id": "cohesion", "title": "Cohesion", "explanation": "Code that changes for the same reason usually belongs together.", "code_example": "def greet(): return 'hello'", "self_check": "When should this move to a helper?", "answer": "When a second responsibility or caller makes the boundary useful.", "exercise": "Name the reason this function is likely to change.", "evidence": [{"path": "main.py", "line": 1, "end_line": 1, "label": "Small cohesive example", "valid": True}]}],
            "quiz": quiz,
        }),
        "chat.json": json.dumps({"answer": "The saved entry point owns the current greeting behavior.", "citations": [{"path": "main.py", "line": 1, "end_line": 1, "label": "Saved entry point", "valid": True}]}),
    }
    payload = supplied or defaults.get(schema, '{"answer":"synthetic answer","citations":[]}')
    Path(target).write_text("not-json" if mode == "invalid" else payload, encoding="utf-8")
raise SystemExit(0)

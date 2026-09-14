from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


FIXTURE = Path(__file__).parent / "fixtures" / "fake_codex.py"


def run_fixture(tmp_path: Path, mode: str) -> subprocess.CompletedProcess[str]:
    output = tmp_path / f"{mode}.json"
    env = os.environ.copy()
    env["FAKE_CODEX_MODE"] = mode
    env["FAKE_CODEX_RESULT"] = json.dumps({"answer": "fixture", "citations": []})
    return subprocess.run(
        [sys.executable, str(FIXTURE), "exec", "-", "--output-last-message", str(output), "--json"],
        input="test prompt", capture_output=True, text=True, env=env, timeout=10,
    )


def test_fake_codex_streams_and_writes_structured_result(tmp_path: Path):
    result = run_fixture(tmp_path, "success")

    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert result.returncode == 0
    assert [event["type"] for event in events] == ["thread.started", "turn.started", "turn.completed"]
    assert events[-1]["usage"] == {"input_tokens": 12, "output_tokens": 4}
    assert json.loads((tmp_path / "success.json").read_text()) == {"answer": "fixture", "citations": []}


def test_fake_codex_has_invalid_and_failure_modes(tmp_path: Path):
    invalid = run_fixture(tmp_path, "invalid")
    failed = run_fixture(tmp_path, "fail")

    assert invalid.returncode == 0
    assert (tmp_path / "invalid.json").read_text() == "not-json"
    assert failed.returncode == 3
    assert "authentication failure" in failed.stderr

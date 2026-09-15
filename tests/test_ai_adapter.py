from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from archcoach.ai import (
    CodexAdapter,
    CodexAuthenticationError,
    CodexIncompatible,
    CodexMalformedOutput,
    CodexTimeoutError,
    CodexUsageError,
)
from archcoach.config import Settings


FIXTURE = Path(__file__).parent / "fixtures" / "fake_codex.py"
SCHEMA_DIR = Path(__file__).parents[1] / "src" / "archcoach" / "schemas"


def adapter(tmp_path: Path) -> tuple[CodexAdapter, Path]:
    settings = Settings(
        data_dir=tmp_path / "data", app_dir=Path(__file__).parents[1] / "src" / "archcoach",
        codex_command=str(FIXTURE), codex_call_timeout=2,
    )
    settings.ensure_dirs()
    workspace = settings.runtime_dir / "empty"
    workspace.mkdir()
    return CodexAdapter(settings), workspace


def test_adapter_streams_events_tracks_usage_and_applies_restrictions(tmp_path: Path, monkeypatch):
    codex, workspace = adapter(tmp_path)
    argv_file = tmp_path / "argv.json"
    monkeypatch.setenv("FAKE_CODEX_MODE", "stream")
    monkeypatch.setenv("FAKE_CODEX_ARGV_FILE", str(argv_file))
    monkeypatch.setenv("FAKE_CODEX_RESULT", '{"answer":"ok","citations":[]}')
    events: list[tuple[str, float]] = []
    started = time.monotonic()

    result = codex.run_structured(
        "untrusted source", SCHEMA_DIR / "chat.json", workspace,
        on_event=lambda event: events.append((event["type"], time.monotonic() - started)),
    )
    elapsed = time.monotonic() - started

    assert result["answer"] == "ok"
    assert events[0][0] == "thread.started"
    assert events[0][1] < elapsed - 0.2
    assert codex.last_usage == {"input_tokens": 12, "output_tokens": 4}
    args = json.loads(argv_file.read_text())
    assert args[0:2] == ["exec", "-"]
    assert args.count("--disable") == 9
    assert "shell_tool" in args and "apps" in args and "hooks" in args
    assert "--sandbox" in args and args[args.index("--sandbox") + 1] == "read-only"


@pytest.mark.parametrize(
    ("mode", "error"),
    [("invalid", CodexMalformedOutput), ("fail", CodexAuthenticationError), ("usage", CodexUsageError)],
)
def test_adapter_classifies_failures(tmp_path: Path, monkeypatch, mode, error):
    codex, workspace = adapter(tmp_path)
    monkeypatch.setenv("FAKE_CODEX_MODE", mode)
    with pytest.raises(error):
        codex.run_structured("x", SCHEMA_DIR / "chat.json", workspace)


def test_adapter_times_out_and_reaps_process(tmp_path: Path, monkeypatch):
    codex, workspace = adapter(tmp_path)
    monkeypatch.setenv("FAKE_CODEX_MODE", "stall")
    with pytest.raises(CodexTimeoutError):
        codex.run_structured("x", SCHEMA_DIR / "chat.json", workspace, timeout=1)
    assert codex.current is None


def test_adapter_supervises_prompt_delivery_and_drains_output(tmp_path: Path, monkeypatch):
    codex, workspace = adapter(tmp_path)
    pid_file = tmp_path / "pid.txt"
    monkeypatch.setenv("FAKE_CODEX_MODE", "ignore_stdin")
    monkeypatch.setenv("FAKE_CODEX_PID_FILE", str(pid_file))
    started = time.monotonic()

    with pytest.raises(CodexTimeoutError):
        codex.run_structured("x" * 4_000_000, SCHEMA_DIR / "chat.json", workspace, timeout=1)

    assert time.monotonic() - started < 10
    assert codex.current is None
    pid = pid_file.read_text(encoding="utf-8")
    if os.name == "nt":
        processes = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=10,
        ).stdout
        assert f'"{pid}"' not in processes
    else:
        with pytest.raises(ProcessLookupError):
            os.kill(int(pid), 0)


def test_adapter_reports_incompatible_cli_instead_of_weakening_restrictions(tmp_path: Path, monkeypatch):
    codex, workspace = adapter(tmp_path)
    monkeypatch.setenv("FAKE_CODEX_INCOMPATIBLE", "1")
    with pytest.raises(CodexIncompatible, match="missing flags"):
        codex.run_structured("x", SCHEMA_DIR / "chat.json", workspace)

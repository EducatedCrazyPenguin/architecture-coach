from pathlib import Path

import pytest
from pydantic import ValidationError

from archcoach.cli import main
from archcoach.config import Settings, merge_saved_settings
from archcoach.db import Store


def test_cli_doctor_uses_validated_saved_application_settings(tmp_path: Path, monkeypatch):
    data_dir = tmp_path / "data"
    settings = Settings.load(data_dir)
    settings.ensure_dirs()
    Store(settings.db_path).update_app_settings({
        "codex_command": "saved-codex-command",
        "reasoning_effort": "high",
    })
    seen = []
    monkeypatch.setattr("archcoach.cli.CodexAdapter.status", lambda self: seen.append(self.settings) or {})
    monkeypatch.setattr("archcoach.cli.find_node", lambda: "node")

    assert main(["--data-dir", str(data_dir), "doctor"]) == 0
    assert seen[0].codex_command == "saved-codex-command"
    assert seen[0].reasoning_effort == "high"


def test_persisted_required_setting_cannot_be_null(tmp_path: Path):
    with pytest.raises(ValidationError, match="cannot be null"):
        merge_saved_settings(Settings.load(tmp_path / "data"), {"codex_command": None})

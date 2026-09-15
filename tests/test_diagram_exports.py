from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import Mock

from archcoach.config import Settings
from archcoach.diagram import principal_relationships, render_diagram, render_selected_comparison
from archcoach.models import Architecture, Component, Critique, Evidence, Finding, Lesson, Relationship
from archcoach.review import markdown_report
from archcoach.cli import existing_server


def architecture() -> Architecture:
    source = Evidence(path="app.py", line=1, end_line=2, label="entry")
    return Architecture(
        summary="A small service.",
        main_path=["web", "service"],
        components=[
            Component(id="web", name="Web", responsibility="Accepts requests", sources=[source], source_paths=["app.py"]),
            Component(id="service", name="Service", responsibility="Runs use cases", sources=[source], source_paths=["app.py"]),
            Component(id="store", name="Store", responsibility="Saves state", sources=[source], source_paths=["app.py"]),
        ],
        relationships=[
            Relationship(source="service", target="store", label="writes"),
            Relationship(source="web", target="service", label="calls"),
        ],
    )


def test_renderer_timeout_repairs_layout_then_preserves_fallback(tmp_path: Path, monkeypatch):
    import archcoach.diagram as diagram

    settings = Settings(data_dir=tmp_path / "data", app_dir=Path(__file__).parents[1] / "src" / "archcoach")
    attempts: list[dict] = []
    monkeypatch.setattr(diagram, "find_node", lambda: "node")

    def timeout(_command, **_kwargs):
        attempts.append(json.loads((tmp_path / "out" / "architecture.json").read_text(encoding="utf-8")))
        raise subprocess.TimeoutExpired("archify", 120)

    monkeypatch.setattr(diagram, "run_cancellable", timeout)
    result = render_diagram(settings, architecture(), "Fixture", tmp_path / "out")

    assert result["renderer"] == "fallback"
    assert result["attempts"] == 2
    assert Path(result["diagram"]).is_file()
    assert len(attempts) == 2
    assert attempts[0]["connections"] == attempts[1]["connections"]
    assert attempts[0]["components"][0]["id"] == attempts[1]["components"][0]["id"]
    assert attempts[0]["layout"] != attempts[1]["layout"]


def test_principal_relationships_prioritise_main_path():
    model = architecture()
    selected = principal_relationships(model)
    assert (selected[0].source, selected[0].target) == ("web", "service")
    from archcoach.diagram import to_archify
    assert all(item["id"].startswith("rel-") for item in to_archify(model, "Fixture")["connections"])


def test_selected_comparison_uses_separate_generated_directory(tmp_path: Path, monkeypatch):
    import archcoach.diagram as diagram

    settings = Settings(data_dir=tmp_path / "data", app_dir=Path(__file__).parents[1] / "src" / "archcoach")
    settings.ensure_dirs()

    def fake_compare(_settings, _base, _head, target, **_kwargs):
        target.write_text("<html>comparison</html>", encoding="utf-8")
        return str(target)

    monkeypatch.setattr(diagram, "render_comparison", fake_compare)
    record = {"id": "before", "project_id": "project", "architecture": architecture().model_dump(), "positions": {}}
    target = render_selected_comparison(settings, record, {**record, "id": "after"})
    assert target is not None
    assert Path(target).relative_to(settings.artifact_dir).parts[:2] == ("comparisons", "project")


def test_markdown_export_contains_evidence_limits_and_complete_lesson():
    source = Evidence(path="app.py", line=1, end_line=2, label="entry")
    critique = Critique(
        strengths=["The service boundary is explicit."],
        findings=[Finding(id="one", severity="medium", title="Tight coupling", observation="Web owns storage details.", why_it_matters="Changes spread.", improvement="Move storage calls.", tradeoffs="Adds one interface.", evidence=[source])],
        lessons=[Lesson(id="lesson", title="Boundaries", explanation="Keep ownership clear.", code_example="service.save()", self_check="Who owns persistence?", answer="The store boundary.", exercise="List callers.", evidence=[source])],
    )
    report = markdown_report(
        {"name": "Fixture"}, architecture(), critique, {"baseline": True},
        {"level": "limited", "omissions": ["dynamic import unresolved"]}, snapshot_id="snapshot-123",
    )
    for text in ("snapshot-123", "app.py:1-2", "Tradeoffs", "service.save()", "Who owns persistence?", "The store boundary.", "List callers.", "dynamic import unresolved"):
        assert text in report


def test_windows_scripts_use_isolated_environment_and_fail_fast():
    root = Path(__file__).parents[1]
    install = (root / "install.cmd").read_text(encoding="ascii")
    launch = (root / "Start Architecture Coach.cmd").read_text(encoding="ascii")
    assert "%PYTHON_CMD% -m venv .venv" in install
    assert "Python 3.12 is required" in install
    assert '".venv\\Scripts\\python.exe" -m pip install -r requirements.lock' in install
    assert "--no-deps --no-build-isolation" in install
    assert "pnpm install --frozen-lockfile" in install
    assert "if errorlevel 1 goto :failed" in install
    assert "Installation complete" in install.split(":installed", 1)[1]
    assert "set \"HOME=" not in install + launch
    assert '".venv\\Scripts\\archcoach.exe" serve' in launch


def test_second_launcher_recognises_only_architecture_coach(monkeypatch):
    response = Mock()
    response.status = 200
    response.read.return_value = b'{"application":"architecture-coach"}'
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: response)
    assert existing_server(8765) is True
    response.read.return_value = b'{"application":"something-else"}'
    assert existing_server(8765) is False

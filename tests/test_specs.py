from pathlib import Path

import pytest

from archcoach.capture import capture_project
from archcoach.config import Settings
from archcoach.models import Critique
from archcoach.review import validate_requirement_assessments
from archcoach.specs import index_specs, select_requirements
from archcoach.db import Store
from archcoach.models import ProjectCreate
from archcoach.review import ReviewEngine
from tests.test_history import CompleteCodex


def test_snapshot_specs_distinguish_main_proposed_archived_and_malformed(tmp_path: Path):
    source = tmp_path / "project"
    (source / "openspec" / "specs" / "greeting").mkdir(parents=True)
    (source / "openspec" / "changes" / "new-greeting").mkdir(parents=True)
    (source / "openspec" / "changes" / "archive" / "old-greeting").mkdir(parents=True)
    (source / "openspec" / "specs" / "greeting" / "spec.md").write_text(
        "# Greeting\n\n### Requirement: Say hello\nThe app SHALL greet.\n\n#### Scenario: Basic\n- WHEN launched\n- THEN it greets\n", encoding="utf-8",
    )
    (source / "openspec" / "changes" / "new-greeting" / "proposal.md").write_text("proposed", encoding="utf-8")
    (source / "openspec" / "changes" / "archive" / "old-greeting" / "proposal.md").write_text("old", encoding="utf-8")
    (source / "openspec" / "specs" / "broken").mkdir()
    (source / "openspec" / "specs" / "broken" / "spec.md").write_text("### Requirement: No scenario\nThe app SHALL do something.\n", encoding="utf-8")
    (source / "app.py").write_text("print('hello')\n", encoding="utf-8")
    settings = Settings(data_dir=tmp_path / "data", app_dir=Path(__file__).parents[1] / "src" / "archcoach")
    settings.ensure_dirs()
    snapshot = capture_project(settings, {"path": str(source), "exclusions": []})
    index = index_specs(settings, snapshot["manifest"])
    assert index["requirements"][0]["id"] == "greeting:Say hello"
    assert index["active_changes"] == ["new-greeting"]
    assert index["archived_changes"] == ["old-greeting"]
    assert any("broken/spec.md" in issue for issue in index["malformed"])
    (source / "openspec" / "config.yaml").write_text("schema: custom\n", encoding="utf-8")
    unsupported = index_specs(settings, capture_project(settings, {"path": str(source), "exclusions": []})["manifest"])
    assert unsupported["requirements"] == []
    assert unsupported["unsupported"]
    selected, rest = select_requirements(index, {"app.py"}, set())
    assert len(selected) == 1 and rest == 0
    assessment = Critique(requirements=[{
        "requirement_id": selected[0]["id"], "status": "supported",
        "explanation": "The entry point prints a greeting.",
        "code_evidence": [{"path": "app.py", "line": 1, "valid": True}],
    }])
    assert validate_requirement_assessments(assessment, selected, snapshot["manifest"])
    assessment.requirements[0].code_evidence[0].path = "openspec/specs/greeting/spec.md"
    with pytest.raises(ValueError, match="invalid code evidence"):
        validate_requirement_assessments(assessment, selected, snapshot["manifest"])


def test_review_assesses_saved_requirement_without_architecture_change_from_spec_only_edit(tmp_path: Path):
    source = tmp_path / "project"
    spec = source / "openspec" / "specs" / "greeting" / "spec.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("# Greeting\n\n### Requirement: Say hello\nThe app SHALL greet.\n\n#### Scenario: Basic\n- WHEN launched\n- THEN it greets\n", encoding="utf-8")
    (source / "app.py").write_text("value = 1\n", encoding="utf-8")
    settings = Settings(data_dir=tmp_path / "data", app_dir=Path(__file__).parents[1] / "src" / "archcoach")
    settings.ensure_dirs()
    store = Store(settings.db_path)
    project = store.add_project(ProjectCreate(path=str(source)))

    class AssessmentCodex(CompleteCodex):
        prompts = []

        def run_structured(self, prompt, schema, *args, **kwargs):
            if schema.name == "chat.json":
                self.prompts.append(prompt)
                return {"answer": "The saved requirement is not confirmed by the inspected entry point.",
                        "citations": [{"path": "app.py", "line": 1, "end_line": None, "label": "Saved code", "valid": True}]}
            data = super().run_structured(prompt, schema, *args, **kwargs)
            if schema.name == "critique.json":
                data["requirements"] = [{
                    "requirement_id": "greeting:Say hello", "status": "uncertain",
                    "explanation": "The saved code defines a value but no runtime greeting is visible.",
                    "code_evidence": [{"path": "app.py", "line": 1, "end_line": None, "label": "Inspected code", "valid": True}],
                }]
            return data

    provider = AssessmentCodex()
    engine = ReviewEngine(settings, store, provider)
    first = store.get_review(engine.run(project["id"]))
    assert first["critique"]["requirements"][0]["status"] == "uncertain"
    assert all(not path.startswith("openspec/") for item in first["architecture"]["components"] for path in item["source_paths"])
    spec.write_text(spec.read_text(encoding="utf-8").replace("SHALL greet", "SHALL greet warmly"), encoding="utf-8")
    second = store.get_review(engine.run(project["id"]))
    assert second["changes"]["components_added"] == []
    assert second["changes"]["components_removed"] == []
    assert second["changes"]["typed_relationships_added"] == []
    engine.chat(second["id"], "What does the saved greeting requirement mean?")
    assert "greeting:Say hello" in provider.prompts[-1]
    assert "uncertain" in provider.prompts[-1]

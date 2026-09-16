from __future__ import annotations

from pathlib import Path

import pytest

from archcoach.config import Settings
from archcoach.db import Store
from archcoach.models import ProjectCreate
from archcoach.review import REVIEW_FORMAT_VERSION, ReviewEngine, validate_comparison_records


def fixture_quiz():
    return [{
        "id": f"question-{index}", "question": f"What owns fixture value {index}?",
        "options": ["app.py", "db.py", "web.js", "Nothing"], "correct_index": 0,
        "explanations": ["app.py owns it.", "No database file exists.", "No web file exists.", "The value has an owner."],
        "evidence": [{"path": "app.py", "line": 1, "end_line": None, "label": "Source", "valid": True}],
    } for index in range(10)]


class CompleteCodex:
    def run_structured(self, _prompt, schema, *_args, **_kwargs):
        if schema.name == "architecture.json":
            return {
                "summary": "A fixture.", "main_path": [],
                "components": [{
                    "id": "application", "name": "Application", "kind": "backend",
                    "responsibility": "Owns fixture behavior.", "source_paths": ["app.py"],
                    "sources": [{"path": "app.py", "line": 1, "end_line": None, "label": "Source", "valid": True}],
                }],
                "relationships": [],
            }
        return {
            "strengths": ["The application keeps its fixture behavior in one module."],
            "findings": [],
            "lessons": [{
                "id": "boundary", "title": "Boundary", "explanation": "A boundary owns behavior.",
                "code_example": "value = 1", "self_check": "What owns the value?",
                "answer": "app.py", "exercise": "Name the boundary.",
                "evidence": [{"path": "app.py", "line": 1, "end_line": None, "label": "Source", "valid": True}],
            }],
            "quiz": fixture_quiz(),
        }

    def cancel(self):
        return None


def setup_engine(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.py").write_text("value = 1\n", encoding="utf-8")
    settings = Settings(data_dir=tmp_path / "data", app_dir=Path(__file__).parents[1] / "src" / "archcoach")
    settings.ensure_dirs()
    store = Store(settings.db_path)
    project = store.add_project(ProjectCreate(path=str(source), goal="learn boundaries"))
    return source, store, project, ReviewEngine(settings, store, CompleteCodex())


def test_unchanged_check_reuses_review_conversation_and_lesson_progress(tmp_path: Path):
    _, store, project, engine = setup_engine(tmp_path)
    review_id = engine.run(project["id"])
    assert store.get_review(review_id)["format_version"] == REVIEW_FORMAT_VERSION
    conversation = store.conversation_for_review(review_id)
    store.add_message(conversation["id"], "user", "remember this")
    store.set_lesson_status(review_id, "boundary", "learning")

    reused_id = engine.run(project["id"])

    assert reused_id == review_id
    assert len(store.list_reviews(project["id"])) == 1
    assert store.list_check_events(project["id"])[0]["review_id"] == review_id
    assert store.conversation_for_review(review_id)["messages"][0]["content"] == "remember this"
    assert store.lesson_statuses(review_id) == {"boundary": "learning"}
    assert store.list_history(project["id"])[0]["history_type"] == "check"


def test_goal_change_regenerates_but_name_schedule_and_force_behave_explicitly(tmp_path: Path):
    _, store, project, engine = setup_engine(tmp_path)
    first = engine.run(project["id"])
    store.update_project(project["id"], name="Renamed", interval_days=30)
    assert engine.run(project["id"]) == first

    store.update_project(project["id"], goal="a different goal")
    second = engine.run(project["id"])
    assert second != first
    third = engine.run(project["id"], force=True)
    assert third != second


def test_legacy_and_cross_project_comparisons_are_rejected():
    valid = {"id": "a", "project_id": "p", "status": "complete", "quality": "complete"}
    with pytest.raises(ValueError, match="Legacy"):
        validate_comparison_records({**valid, "quality": "legacy"}, valid)
    with pytest.raises(ValueError, match="same project"):
        validate_comparison_records(valid, {**valid, "project_id": "other"})
    with pytest.raises(ValueError, match="completed"):
        validate_comparison_records(valid, {**valid, "status": "failed"})


def test_invalid_ai_evidence_cannot_advance_successful_schedule(tmp_path: Path, monkeypatch):
    _, store, project, engine = setup_engine(tmp_path)
    class InvalidEvidence(CompleteCodex):
        def run_structured(self, prompt, schema, *args, **kwargs):
            result = super().run_structured(prompt, schema, *args, **kwargs)
            if schema.name == "critique.json":
                result["quiz"][0]["evidence"][0]["line"] = 999
            return result
    engine.codex = InvalidEvidence()
    monkeypatch.setattr("archcoach.review.render_diagram", lambda *args, **kwargs: {"renderer": "unavailable"})
    review = store.get_review(engine.run(project["id"]))
    assert review["quality"] == "limited"
    assert review["critique"]["quiz"][0]["evidence"][0]["valid"] is False
    assert store.get_project(project["id"])["last_checked_at"] is None

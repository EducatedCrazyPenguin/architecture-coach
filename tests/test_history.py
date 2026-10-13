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
    saved_quiz = store.get_review(review_id)['critique']['quiz']
    from collections import Counter
    assert sorted(Counter(q['correct_index'] for q in saved_quiz).values()) == [2, 2, 3, 3]
    question = saved_quiz[0]
    wrong_index = (question['correct_index'] + 1) % 4
    store.save_quiz_answer(review_id, question['id'], wrong_index, False, request_id='saved-attempt')
    attempts = store.quiz_attempts(review_id, question['id'])
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
    assert store.get_review(review_id)['critique']['quiz'] == saved_quiz
    assert store.quiz_attempts(review_id, question['id']) == attempts


def test_goal_change_regenerates_but_name_schedule_and_force_behave_explicitly(tmp_path: Path, monkeypatch):
    _, store, project, engine = setup_engine(tmp_path)
    first = engine.run(project["id"])
    store.update_project(project["id"], name="Renamed", interval_days=30)
    assert engine.run(project["id"]) == first

    store.update_project(project["id"], goal="a different goal")
    second = engine.run(project["id"])
    assert second != first
    third = engine.run(project["id"], force=True)
    assert third != second
    import archcoach.review as review_module
    saved = store.get_review(third)
    monkeypatch.setattr(review_module, 'CRITIQUE_PROMPT', review_module.CRITIQUE_PROMPT+'\nTeach one beginner idea.')
    fourth = store.get_review(engine.run(project['id']))
    assert fourth['id'] != third
    assert store.get_snapshot(fourth['snapshot_id'])['fingerprint'] == store.get_snapshot(saved['snapshot_id'])['fingerprint']
    assert store.get_review(third) == saved


def test_legacy_and_cross_project_comparisons_are_rejected():
    valid = {"id": "a", "project_id": "p", "status": "complete", "quality": "complete"}
    with pytest.raises(ValueError, match="Legacy"):
        validate_comparison_records({**valid, "quality": "legacy"}, valid)
    with pytest.raises(ValueError, match="same project"):
        validate_comparison_records(valid, {**valid, "project_id": "other"})
    with pytest.raises(ValueError, match="completed"):
        validate_comparison_records(valid, {**valid, "status": "failed"})


def test_missing_model_imports_are_restored_without_inventing_runtime_order():
    from archcoach.models import Architecture
    from archcoach.review import add_resolved_relationships
    model = Architecture.model_validate({'summary': 'Library', 'components': [
        {'id': name, 'name': name, 'responsibility': name, 'sources': [{'path': name+'.py', 'line': 1}], 'source_paths': [name+'.py']}
        for name in ('main', 'service', 'store')], 'relationships': []})
    edges = [{'source': 'main.py', 'target': 'service.py', 'line': 2}, {'source': 'service.py', 'target': 'store.py', 'line': 1}]
    add_resolved_relationships(model, edges)
    add_resolved_relationships(model, edges)
    assert [(r.source, r.target, r.kind, r.inferred) for r in model.relationships] == [('main', 'service', 'imports', False), ('service', 'store', 'imports', False)]
    assert model.relationships[0].sources[0].line == 2
    assert model.main_path == []
    model.components[1].source_paths.append('main.py')
    model.relationships = []
    add_resolved_relationships(model, edges)
    assert [(r.source, r.target) for r in model.relationships] == [('service', 'store')]


def test_static_view_splits_folders_that_hide_all_imports():
    from archcoach.review import heuristic_architecture
    from archcoach.diagram import to_archify
    analysis = {'files': [{'path': path, 'lines': 5, 'language': 'python'} for path in
        ('backend/api.py', 'backend/service.py', 'apps/web/main.ts', 'apps/web/store.ts')],
        'edges': [{'source': 'backend/api.py', 'target': 'backend/service.py', 'kind': 'imports', 'line': 1},
                  {'source': 'apps/web/main.ts', 'target': 'apps/web/store.ts', 'kind': 'imports', 'line': 1}]}
    model = heuristic_architecture({'name': 'Fixture'}, analysis)
    assert len(model.relationships) == 2
    assert len(model.components) <= 12
    assert not model.main_path
    assert len(to_archify(model, 'Fixture')['connections']) == 2


@pytest.mark.parametrize('prompt_name', ['ARCHITECTURE_PROMPT', 'SOURCE_SUMMARY_PROMPT'])
def test_review_prompt_change_regenerates_without_rewriting_saved_learning(tmp_path, monkeypatch, prompt_name):
    import archcoach.review as review_module

    _, store, project, engine = setup_engine(tmp_path)
    monkeypatch.setattr(review_module, 'render_diagram', lambda *args, **kwargs: {'renderer': 'unavailable'})
    before_id = engine.run(project['id'])
    before = store.get_review(before_id)
    question = before['critique']['quiz'][0]
    store.save_quiz_answer(before_id, question['id'], question['correct_index'], True, request_id='before-guidance-change')
    attempts = store.quiz_attempts(before_id, question['id'])
    conversation = store.conversation_for_review(before_id)
    store.add_message(conversation['id'], 'user', 'Keep this saved discussion')
    store.set_lesson_status(before_id, 'boundary', 'learning')
    assert engine.run(project['id']) == before_id

    monkeypatch.setattr(review_module, prompt_name, getattr(review_module, prompt_name) + '\nDo not infer a CLI from a function name.')
    after_id = engine.run(project['id'])

    assert after_id != before_id
    assert store.get_snapshot(store.get_review(after_id)['snapshot_id'])['fingerprint'] == store.get_snapshot(before['snapshot_id'])['fingerprint']
    assert store.get_review(before_id) == before
    assert store.quiz_attempts(before_id, question['id']) == attempts
    assert store.lesson_statuses(before_id) == {'boundary': 'learning'}
    assert store.conversation_for_review(before_id)['messages'][0]['content'] == 'Keep this saved discussion'


def test_review_teaching_qualifies_tests_storage_and_conventions(tmp_path, monkeypatch):
    _, store, project, engine = setup_engine(tmp_path)
    class TeachingProvider(CompleteCodex):
        def run_structured(self, prompt, schema, *args, **kwargs):
            if schema.name == 'critique.json':
                assert 'captured tests are expectations, not execution results' in prompt
                assert 'never say an unexecuted test proves' in prompt
                assert 'in-memory list does not establish restart persistence' in prompt
                assert 'recommended boundary is not enforced access control' in prompt
            return super().run_structured(prompt, schema, *args, **kwargs)
    engine.codex = TeachingProvider()
    monkeypatch.setattr('archcoach.review.render_diagram', lambda *args, **kwargs: {'renderer': 'unavailable'})
    assert store.get_review(engine.run(project['id']))['quality'] == 'complete'


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

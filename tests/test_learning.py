from pathlib import Path
import hashlib

import pytest
from fastapi.testclient import TestClient

from archcoach.app import create_app
from archcoach.config import Settings
from archcoach.models import ProjectCreate


@pytest.fixture
def saved_learning(tmp_path, monkeypatch):
    # Never invoke providers or renderers; every record belongs to synthetic data.
    monkeypatch.setattr('archcoach.ai.CodexAdapter.status', lambda self: {'authenticated': False})
    settings = Settings(data_dir=tmp_path / 'private data', app_dir=Path(__file__).parents[1] / 'src' / 'archcoach')
    app = create_app(settings, start_worker=False)
    client = TestClient(app)
    headers = {'X-ArchCoach-Token': app.state.csrf_token}
    root = tmp_path / 'repo with spaces'; root.mkdir()
    (root / 'main.py').write_text('def greet(name):\n    return "hello <" + name\n', encoding='utf-8')
    project = app.state.store.add_project(ProjectCreate(path=str(root), name='Greeting'))
    content = (root / 'main.py').read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    blob = settings.blob_dir / digest[:2] / digest; blob.parent.mkdir(parents=True, exist_ok=True); blob.write_bytes(content)
    manifest = [{'path': 'main.py', 'sha256': digest, 'lines': 2}]
    snapshot = app.state.store.create_snapshot(project['id'], digest, manifest, {'available': False}, {}, {})
    evidence = {'path': 'main.py', 'line': 1, 'end_line': 2, 'valid': True}
    architecture = {'summary': 'Greets a person', 'main_path': ['entry'], 'components': [{'id': 'entry', 'name': 'Greeting entry', 'kind': 'backend', 'responsibility': 'Owns greeting', 'sources': [evidence], 'source_paths': ['main.py']}], 'relationships': []}
    lesson = {'id': 'boundaries', 'title': 'A focused responsibility', 'explanation': 'This function owns greeting text.', 'code_example': '# inspect the module', 'self_check': 'What does it own?', 'answer': 'Greeting text', 'exercise': 'Explain what a caller supplies.', 'evidence': [evidence]}
    question = {'id': 'ownership', 'question': 'Who owns greeting text?', 'options': ['Greeting entry', 'Database', 'Queue', 'Browser'], 'correct_index': 0, 'explanations': ['The saved function formats text.', 'No database exists.', 'No queue exists.', 'No browser exists.'], 'evidence': [evidence]}
    critique = {'strengths': [], 'findings': [], 'lessons': [lesson], 'quiz': [question], 'requirements': []}
    review = app.state.store.create_review(project['id'], snapshot, None, 'complete', architecture, critique, {'baseline': True}, {}, quality='complete')
    return app, client, headers, project, review


def test_teaching_and_quiz_coexist_without_live_source(saved_learning):
    app, client, _, project, review = saved_learning
    (Path(project['path']) / 'main.py').unlink()
    page = client.get(f'/reviews/{review}').text
    assert 'A focused responsibility' in page and 'Repository quiz' in page
    assert 'hello &lt;' in page
    assert 'Start learning this repo' in page
    assert '<span>Greeting entry</span>' in page
    assert 'Illustrations may omit steps. Do not paste them over working code without checking the full saved source.' in page


def test_export_uses_saved_data_and_does_not_replace_artifacts(saved_learning):
    app, client, _, _, review = saved_learning
    before = app.state.store.get_review(review)
    result = client.get(f'/reviews/{review}/learning-report')
    assert result.status_code == 200
    assert 'A focused responsibility' in result.text and 'Who owns greeting text?' in result.text
    assert 'def greet(name)' in result.text
    assert 'Illustrations may omit steps. Do not paste them over working code without checking the full saved source.' in result.text
    assert app.state.store.get_review(review)['artifacts'] == before['artifacts']


def test_quiz_metadata_has_legacy_defaults_and_rejects_unknown_concepts():
    from archcoach.models import QuizQuestion
    from pydantic import ValidationError
    raw = {'id': 'q', 'question': 'Which owner?', 'options': ['a', 'b', 'c', 'd'], 'correct_index': 0, 'explanations': ['a', 'b', 'c', 'd'], 'evidence': [{'path': 'main.py', 'line': 1}]}
    assert QuizQuestion(**raw).concept == 'unclassified'
    with pytest.raises(ValidationError):
        QuizQuestion(**raw, concept='invented')


def test_bad_example_citations_do_not_become_captured_code(saved_learning):
    from archcoach.learning import saved_excerpt
    app, _, _, _, review = saved_learning
    snapshot = app.state.store.get_snapshot(app.state.store.get_review(review)['snapshot_id'])
    assert saved_excerpt(app.state.settings, snapshot, {'path': 'main.py', 'line': 100}) is None
    assert saved_excerpt(app.state.settings, snapshot, {'path': '../secret', 'line': 1}) is None
    assert saved_excerpt(app.state.settings, snapshot, {'path': 'main.py', 'line': 1, 'valid': False}) is None


def test_local_provider_is_named_on_dashboard(tmp_path, monkeypatch):
    monkeypatch.setattr('archcoach.ollama.OllamaAdapter.status', lambda self: {'authenticated': True})
    settings = Settings(data_dir=tmp_path / 'data', app_dir=Path(__file__).parents[1] / 'src' / 'archcoach', ai_provider='ollama')
    assert 'Ollama · local ready' in TestClient(create_app(settings, start_worker=False)).get('/').text


def test_walkthrough_is_saved_and_runtime_is_qualified(saved_learning):
    app, client, _, project, review = saved_learning
    (Path(project['path']) / 'main.py').write_text('raise RuntimeError("current code must not run")')
    outline = client.get(f'/api/reviews/{review}/walkthrough').json()
    assert outline['format_version'] == 3
    assert outline['outlines'][0]['steps'][0]['title'] == 'Boundary: greet'
    assert 'name' in outline['outlines'][0]['steps'][0]['explanation']
    assert all(s['inferred'] for s in outline['outlines'][0]['steps'][1:])
    assert 'hello <' in outline['outlines'][0]['steps'][0]['example']['code']
    assert 'raise RuntimeError' not in client.get(f'/reviews/{review}/walkthrough').text
    assert app.state.store.get_learning_walkthrough(review) == outline


def test_walkthrough_discloses_unsupported_and_tests_not_executed(saved_learning):
    from archcoach.learning import source_walkthroughs
    app, _, _, _, review_id = saved_learning
    review = app.state.store.get_review(review_id)
    snapshot = app.state.store.get_snapshot(review['snapshot_id'])
    test_content = 'from main import greet\ndef test_greet():\n    assert greet("world") == "hello <world"\n'
    digest = hashlib.sha256(test_content.encode()).hexdigest()
    blob = app.state.settings.blob_dir / digest[:2] / digest; blob.parent.mkdir(exist_ok=True); blob.write_text(test_content)
    snapshot['manifest'].append({'path': 'tests/test_main.py', 'sha256': digest, 'lines': 3})
    outline = source_walkthroughs(app.state.settings, snapshot, review)
    assert outline['outlines'][0]['tests'][0]['line'] == 3
    assert 'not proof of coverage or passing tests' in outline['qualification']
    snapshot['manifest'] = [{'path': 'feature.dsa', 'sha256': digest, 'lines': 3}]
    assert not source_walkthroughs(app.state.settings, snapshot, review)['outlines']


def test_attempts_preserve_history_and_duplicate_requests(saved_learning):
    app, client, headers, _, review = saved_learning
    url = f'/reviews/{review}/quiz/ownership'
    wrong = {'selected_index': 1, 'request_id': 'wrong-request'}
    first = client.post(url, json=wrong, headers=headers)
    assert first.status_code == 200
    assert client.post(url, json=wrong, headers=headers).json()['attempt_id'] == first.json()['attempt_id']
    assert client.post(url, json={'selected_index': 0, 'request_id': 'wrong-request'}, headers=headers).status_code == 409
    assert client.post(url, json={'selected_index': 0, 'request_id': 'right-request'}, headers=headers).status_code == 200
    history = client.get(f'/api/reviews/{review}/quiz/ownership/attempts').json()
    assert [item['kind'] for item in history] == ['first', 'retry']
    assert [bool(item['correct']) for item in history] == [False, True]
    assert app.state.store.quiz_answers(review)['ownership']['correct']
    record = app.state.store.learning_records()[0]
    assert record['first_correct'] == 0 and record['attempt_count'] == 2


def test_revision_is_offline_and_scheduled_without_same_day_streak_boost(saved_learning, monkeypatch):
    app, client, headers, project, review = saved_learning
    monkeypatch.setattr('archcoach.db.utc_now', lambda: '2026-10-12T10:00:00+00:00')
    app.state.store.save_quiz_answer(review, 'ownership', 0, True)
    app.state.store.save_quiz_answer(review, 'ownership', 0, True, mode='revision')
    item = app.state.store.learning_records()[0]
    assert item['streak'] == 1 and item['due_at'].startswith('2026-10-15')
    monkeypatch.setattr('archcoach.app.utc_now', lambda: '2026-10-16T10:00:00+00:00')
    (Path(project['path']) / 'main.py').unlink()
    page = client.get('/learning?practice=true')
    assert page.status_code == 200 and 'Who owns greeting text?' in page.text
    assert f'/reviews/{review}/source' in page.text
    response = client.post(f'/reviews/{review}/quiz/ownership/note', data={'content': '<script>private note</script>', '_csrf': app.state.csrf_token}, follow_redirects=True)
    assert '&lt;script&gt;private note' in response.text
    assert client.post(f'/reviews/{review}/quiz/missing/note', data={'content': 'x', '_csrf': app.state.csrf_token}).status_code == 404


def test_legacy_answers_migrate_and_deletion_owns_learning(saved_learning):
    from archcoach.db import Store
    app, _, _, _, review = saved_learning
    store = app.state.store
    store.save_quiz_answer(review, 'ownership', 1, False)
    with store.connect() as conn:
        for table in ('quiz_attempts', 'revision_state', 'learning_notes'):
            conn.execute(f'DROP TABLE {table}')
        conn.execute('PRAGMA user_version=5')
    upgraded = Store(store.path)
    assert upgraded.quiz_attempts(review)[0]['kind'] == 'legacy'
    assert upgraded.quiz_answers(review)['ownership']['selected_index'] == 1
    assert list((store.path.parent / 'backups').glob('*-v5-*.db'))
    upgraded.save_learning_note(review, 'ownership', 'saved correction')
    with upgraded.connect() as conn:
        conn.execute('DELETE FROM reviews WHERE id=?', (review,))
        for table in ('quiz_attempts', 'revision_state', 'learning_notes'):
            assert conn.execute(f'SELECT count(*) FROM {table}').fetchone()[0] == 0


def test_learning_modes_validate_saved_question_and_queue_origin(saved_learning):
    app, client, headers, _, review = saved_learning
    url = f'/api/reviews/{review}/chat'
    assert client.post(url, json={'message': 'My explanation', 'mode': 'explain_back', 'question_id': 'missing'}, headers=headers).status_code == 404
    assert client.post(url, json={'message': 'My explanation', 'mode': 'execute'}, headers=headers).status_code == 422
    response = client.post(url, json={'message': 'I think the caller stores text', 'mode': 'explain_back', 'question_id': 'ownership'}, headers=headers)
    assert response.status_code == 202
    assert app.state.store.get_job(response.json()['job_id'])['payload']['mode'] == 'explain_back'


def test_explain_back_uses_source_rubric_and_persists_mode(saved_learning):
    from archcoach.review import ReviewEngine
    app, _, _, project, review = saved_learning
    (Path(project['path']) / 'main.py').write_text('CURRENT FILE MUST NEVER ENTER THE PROMPT')
    captured = []
    class FakeProvider:
        last_usage = {}
        def run_structured(self, prompt, *args, **kwargs):
            captured.append(prompt)
            return {'correct_points': 'An input enters greet.', 'missing_reasoning': 'greet owns formatting.', 'next_question': 'What does it return?', 'citations': [{'path': 'main.py', 'line': 2}]}
    engine = ReviewEngine(app.state.settings, app.state.store)
    engine.codex = FakeProvider()
    engine._run_chat(review, 'A caller stores the greeting.', mode='explain_back', question_id='ownership')
    assert 'Correct points' in captured[0] and 'language fluency' in captured[0]
    assert 'The saved function formats text' in captured[0] and 'hello <' in captured[0]
    assert 'CURRENT FILE MUST NEVER' not in captured[0]
    messages = app.state.store.conversation_for_review(review)['messages']
    assert all(m['learning_context']['mode'] == 'explain_back' for m in messages)
    assert messages[-1]['citations'][0]['valid']


@pytest.mark.parametrize('repair_succeeds', [True, False])
def test_explain_back_requires_complete_feedback_with_one_repair(saved_learning, repair_succeeds):
    from archcoach.review import ReviewEngine
    app, _, _, _, review = saved_learning
    calls = []
    class FakeProvider:
        last_usage = {}
        def run_structured(self, prompt, schema, *args, **kwargs):
            calls.append(schema.stem)
            if len(calls) == 2 and repair_succeeds:
                return {'correct_points': 'You identified the input.',
                        'missing_reasoning': 'The saved function formats the greeting.',
                        'next_question': 'What does the function return?',
                        'citations': [{'path': 'main.py', 'line': 2}]}
            return {'answer': 'The saved function formats the greeting.',
                    'citations': [{'path': 'main.py', 'line': 2}]}
    engine = ReviewEngine(app.state.settings, app.state.store); engine.codex = FakeProvider()
    if repair_succeeds:
        engine._run_chat(review, 'The caller supplies a name.', mode='explain_back')
    else:
        with pytest.raises(ValueError):
            engine._run_chat(review, 'The caller supplies a name.', mode='explain_back')
    assert calls == ['feedback', 'feedback']
    messages = app.state.store.conversation_for_review(review)['messages']
    assert len(messages) == 2 and messages[0]['role'] == 'user'
    assert messages[-1]['status'] == ('complete' if repair_succeeds else 'failed')
    if repair_succeeds:
        assert 'Correct points:\nYou identified the input.' in messages[-1]['content']
        assert 'Missing reasoning:\nThe saved function formats the greeting.' in messages[-1]['content']
        assert 'One next question: What does the function return?' in messages[-1]['content']
        assert messages[-1]['citations'][0]['valid']
    else:
        assert messages[-1]['citations'] == []


@pytest.mark.parametrize('next_question', ['No question', 'What enters? What leaves?', '   ?'])
def test_feedback_rejects_missing_or_bundled_questions(next_question):
    from archcoach.models import FeedbackResponse
    with pytest.raises(ValueError):
        FeedbackResponse(correct_points='The input is a name.', missing_reasoning='Formatting is separate.',
                         next_question=next_question)


def test_structured_feedback_keeps_source_only_claim_guard(saved_learning):
    from archcoach.learning import check_teaching_claims
    from archcoach.models import FeedbackResponse
    app, _, _, _, review = saved_learning
    snapshot = app.state.store.get_snapshot(app.state.store.get_review(review)['snapshot_id'])
    feedback = FeedbackResponse(correct_points='All tests passed', missing_reasoning='Nothing is missing.',
                                next_question='What does the function do?')
    with pytest.raises(ValueError, match='cannot claim tests passed'):
        check_teaching_claims(app.state.settings, snapshot, feedback)


@pytest.mark.parametrize('newline', ['\n', '\r\n'])
@pytest.mark.parametrize('label,fence', [('Saved code:', '```'), ('**Captured code:**', '~~~')])
def test_saved_quote_matches_its_cited_range_with_windows_line_endings(saved_learning, newline, label, fence):
    from archcoach.learning import check_teaching_claims
    from archcoach.models import ChatResponse
    app, _, _, _, review = saved_learning
    snapshot = app.state.store.get_snapshot(app.state.store.get_review(review)['snapshot_id'])
    text = newline.join(['def greet(name):', '    return "hello <" + name', ''])
    digest = hashlib.sha256(text.encode()).hexdigest()
    blob = app.state.settings.blob_dir / digest[:2] / digest
    blob.parent.mkdir(parents=True, exist_ok=True); blob.write_bytes(text.encode())
    snapshot = {**snapshot, 'manifest': [{**snapshot['manifest'][0], 'sha256': digest}]}
    quote = f'{label}\n{fence}python\ndef greet(name):\n    return "hello <" + name\n{fence}'
    check_teaching_claims(app.state.settings, snapshot, ChatResponse(
        answer=quote, citations=[{'path': 'main.py', 'line': 1, 'end_line': 2}]))
    with pytest.raises(ValueError, match='cited'):
        check_teaching_claims(app.state.settings, snapshot, ChatResponse(
            answer=quote, citations=[{'path': 'main.py', 'line': 2}]))


@pytest.mark.parametrize('quote', ['    return "hello <"', 'def greet(name):\n    return "hello <"', '', 'return "hello <" + name'])
def test_saved_quote_requires_complete_lines_not_substrings(saved_learning, quote):
    from archcoach.learning import check_teaching_claims
    from archcoach.models import ChatResponse
    app, _, _, _, review = saved_learning
    snapshot = app.state.store.get_snapshot(app.state.store.get_review(review)['snapshot_id'])
    response = ChatResponse(answer=f'Saved code:\n```python\n{quote}\n```',
                            citations=[{'path':'main.py','line':1,'end_line':2}])
    if quote == 'return "hello <" + name':
        check_teaching_claims(app.state.settings, snapshot, response)
    else:
        with pytest.raises(ValueError, match='cited'):
            check_teaching_claims(app.state.settings, snapshot, response)


@pytest.mark.parametrize('repair_succeeds', [True, False])
@pytest.mark.parametrize('truncated', [True, False])
def test_mislocated_saved_quote_is_repaired_or_saved_as_failed(saved_learning, repair_succeeds, truncated):
    from archcoach.review import ReviewEngine
    app, client, _, _, review = saved_learning
    calls = []
    class FakeProvider:
        last_usage = {}
        def run_structured(self, prompt, *args, **kwargs):
            calls.append(prompt)
            repaired = len(calls) == 2 and repair_succeeds
            quote = 'def greet(name)' if truncated and not repaired else 'def greet(name):'
            return {'answer': f'Saved code:\n```python\n{quote}\n```',
                    'citations': [{'path': 'main.py', 'line': 1 if truncated or repaired else 2}]}
    engine = ReviewEngine(app.state.settings, app.state.store); engine.codex = FakeProvider()
    if repair_succeeds:
        engine._run_chat(review, 'Show the saved declaration.')
    else:
        with pytest.raises(ValueError, match='cited'):
            engine._run_chat(review, 'Show the saved declaration.')
    assert len(calls) == 2
    messages = app.state.store.conversation_for_review(review)['messages']
    assert len(messages) == 2 and messages[0]['role'] == 'user'
    assert messages[-1]['status'] == ('complete' if repair_succeeds else 'failed')
    if repair_succeeds:
        assert messages[-1]['citations'][0]['line'] == 1
    else:
        assert messages[-1]['citations'] == []
    assert client.get(f'/reviews/{review}').status_code == 200


@pytest.mark.parametrize('answer', [
    '- All tests passed.', '**All tests passed.**', '1. These tests have passed.',
    '## The tests are passing.', '> All tests passed.',
])
def test_formatted_test_result_claims_are_rejected(saved_learning, answer):
    from archcoach.learning import check_teaching_claims
    from archcoach.models import ChatResponse
    app, _, _, _, review = saved_learning
    snapshot = app.state.store.get_snapshot(app.state.store.get_review(review)['snapshot_id'])
    with pytest.raises(ValueError, match='cannot claim tests passed'):
        check_teaching_claims(app.state.settings, snapshot, ChatResponse(answer=answer))


@pytest.mark.parametrize('fence', ['```', '~~~', '````'])
def test_hypothetical_log_is_not_an_observed_test_result(saved_learning, fence):
    from archcoach.learning import check_teaching_claims
    from archcoach.models import ChatResponse
    app, _, _, _, review = saved_learning
    snapshot = app.state.store.get_snapshot(app.state.store.get_review(review)['snapshot_id'])
    answer = f'Hypothetical log text, not an observed run:\n{fence}text\nAll tests passed.\n{fence}\nTests have not been run.'
    check_teaching_claims(app.state.settings, snapshot, ChatResponse(answer=answer))


def test_beginner_explanation_uses_saved_source_and_one_question(saved_learning):
    from archcoach.review import ReviewEngine
    app, _, _, project, review = saved_learning
    (Path(project['path']) / 'main.py').write_text('CURRENT FILE MUST NEVER ENTER THE PROMPT')
    class FakeProvider:
        last_usage = {}
        def run_structured(self, prompt, *args, **kwargs):
            assert 'new to Python' in prompt and 'plain language before code' in prompt
            assert 'one short question' in prompt and 'define each term' in prompt
            assert 'hello <' in prompt and 'CURRENT FILE MUST NEVER' not in prompt
            return {'answer': 'This part takes a name and makes greeting text. What does it receive?',
                    'citations': [{'path': 'main.py', 'line': 1, 'end_line': 2}]}
    engine = ReviewEngine(app.state.settings, app.state.store); engine.codex = FakeProvider()
    engine._run_chat(review, 'I am new to Python. Explain what this part does.', mode='simpler')
    answer = app.state.store.conversation_for_review(review)['messages'][-1]
    assert answer['learning_context']['mode'] == 'simpler' and answer['citations'][0]['valid']


def test_design_mode_allows_alternatives_and_provider_failure(saved_learning):
    from archcoach.review import ReviewEngine
    from archcoach.ai import CodexUnavailable
    app, _, _, _, review = saved_learning
    class Failure:
        last_usage = {}
        def run_structured(self, prompt, *args, **kwargs):
            assert 'multiple defensible designs' in prompt
            assert 'hypothetical' in prompt and 'not executed' in prompt
            assert 'all mandatory constraints' in prompt and 'concrete durable storage' in prompt
            assert 'Names must survive process restart while preserving greeting format.' in prompt
            assert 'not execution results' in prompt
            assert 'Distinguish imports from calls' in prompt
            raise CodexUnavailable('synthetic provider off')
    engine = ReviewEngine(app.state.settings, app.state.store); engine.codex = Failure()
    with pytest.raises(CodexUnavailable):
        engine._run_chat(review, 'Names must survive process restart while preserving greeting format.', mode='design', question_id='ownership')
    assert app.state.store.conversation_for_review(review)['messages'][-1]['status'] == 'failed'


def test_walkthrough_follows_unique_local_calls_and_marks_dynamic_unknown(saved_learning):
    from archcoach.learning import source_walkthroughs
    app, _, _, _, review_id = saved_learning
    review = app.state.store.get_review(review_id); snapshot = app.state.store.get_snapshot(review['snapshot_id'])
    files = {'main.py': 'from service import format_name\ndef main(name):\n    return format_name(name)\n',
             'service.py': 'def format_name(name):\n    if not name:\n        raise ValueError("empty")\n    return name.strip()\n'}
    snapshot['manifest'] = []
    for path, content in files.items():
        digest = hashlib.sha256(content.encode()).hexdigest()
        blob = app.state.settings.blob_dir / digest[:2] / digest; blob.parent.mkdir(exist_ok=True); blob.write_text(content)
        snapshot['manifest'].append({'path': path, 'sha256': digest, 'lines': len(content.splitlines())})
    review['architecture']['components'].append({'id': 'service', 'name': 'Formatting', 'source_paths': ['service.py']})
    steps = source_walkthroughs(app.state.settings, snapshot, review)['outlines'][0]['steps']
    assert any(s['example']['path'] == 'service.py' and s['component_id'] == 'service' for s in steps)
    assert any(s['title'] == 'Failure handling' for s in steps)
    assert any(s.get('from_component_id') == 'entry' for s in steps)
    assert any('unresolved' in s['explanation'] for s in steps)


def test_walkthrough_includes_variadic_parameters_and_does_not_resolve_shadowed_calls(saved_learning):
    from archcoach.learning import source_walkthroughs
    app, _, _, _, review_id = saved_learning
    review = app.state.store.get_review(review_id)
    snapshot = app.state.store.get_snapshot(review['snapshot_id'])
    content = 'def greet(name):\n    return name\ndef forward(*values, **greet):\n    return greet()\n'
    digest = hashlib.sha256(content.encode()).hexdigest()
    blob = app.state.settings.blob_dir / digest[:2] / digest
    blob.parent.mkdir(exist_ok=True); blob.write_text(content)
    snapshot['manifest'] = [{'path': 'main.py', 'sha256': digest, 'lines': 4}]
    outline = next(item for item in source_walkthroughs(app.state.settings, snapshot, review)['outlines']
                   if item['name'] == 'main.py · forward')
    assert 'values, greet' in outline['steps'][0]['explanation']
    assert any('Target unresolved' in step['explanation'] for step in outline['steps'])
    assert all(step['title'] != 'Boundary: greet' for step in outline['steps'])


def changed_review(app, project, earlier, *, project_id=None):
    import copy
    old = app.state.store.get_review(earlier); snapshot = app.state.store.get_snapshot(old['snapshot_id'])
    content = 'def greet(name):\n    return "welcome <" + name\n'
    digest = hashlib.sha256(content.encode()).hexdigest()
    blob = app.state.settings.blob_dir / digest[:2] / digest; blob.parent.mkdir(exist_ok=True); blob.write_text(content)
    new_manifest = [{'path': 'main.py', 'sha256': digest, 'lines': 2}]
    pid = project_id or project['id']
    sid = app.state.store.create_snapshot(pid, digest, new_manifest, snapshot['git'], {}, {})
    architecture = copy.deepcopy(old['architecture']); architecture['summary'] = 'A differently worded summary'
    architecture['components'][0]['responsibility'] = 'Same role described differently'
    return app.state.store.create_review(pid, sid, earlier if not project_id else None, 'complete', architecture, old['critique'], {}, {}, quality='complete')


def test_change_lesson_keeps_source_only_changes_separate(saved_learning):
    app, client, _, project, earlier = saved_learning
    later = changed_review(app, project, earlier)
    page = client.get(f'/projects/{project["id"]}/change-lesson?before={earlier}&after={later}')
    assert page.status_code == 200
    assert 'hello &lt;' in page.text and 'welcome &lt;' in page.text
    assert 'No component or dependency change' in page.text
    assert 'Predict before revealing' in page.text
    assert earlier in page.text and later in page.text


def test_concept_transfer_isolates_two_saved_origins(saved_learning):
    app, client, _, project, earlier = saved_learning
    later = changed_review(app, project, earlier)
    page = client.get(f'/learning/compare?left={earlier}&right={later}&concept=unclassified')
    assert page.status_code == 200
    assert f'/reviews/{earlier}/source' in page.text and f'/reviews/{later}/source' in page.text
    assert 'hello &lt;' in page.text and 'welcome &lt;' in page.text
    assert 'No relationship between these projects' in page.text
    missing = client.get(f'/learning/compare?left={earlier}&right={later}&concept=testing')
    assert 'Insufficient saved question evidence' in missing.text
    other_root = Path(project['path']).parent / 'second synthetic repo'; other_root.mkdir()
    other = app.state.store.add_project(ProjectCreate(path=str(other_root), name='Second fixture'))
    independent = changed_review(app, project, earlier, project_id=other['id'])
    separate = client.get(f'/learning/compare?left={earlier}&right={independent}&concept=unclassified')
    assert 'Second fixture' in separate.text and f'/reviews/{independent}/source' in separate.text


def test_plan_follow_through_never_certifies_implementation(saved_learning):
    app, client, _, project, earlier = saved_learning
    store = app.state.store
    plan = store.create_plan(earlier, 'finding', {}, 'a'*64, {'valid': True}, {})
    later = changed_review(app, project, earlier)
    url = f'/plans/{plan}/follow-through'
    token = {'_csrf': app.state.csrf_token}
    assert client.post(url, data={**token, 'review_id': earlier, 'note': 'done'}).status_code == 409
    response = client.post(url, data={**token, 'review_id': later, 'note': '<script>I ran tests</script>'}, follow_redirects=True)
    assert response.status_code == 200 and 'User-reported' in response.text
    assert '&lt;script&gt;I ran tests' in response.text
    assert 'Test outcomes remain unverified' in response.text
    assert store.get_plan(plan)['status'] == 'ready'
    other_root = Path(project['path']).parent / 'unrelated synthetic repo'; other_root.mkdir()
    other = store.add_project(ProjectCreate(path=str(other_root)))
    unrelated = changed_review(app, project, earlier, project_id=other['id'])
    assert client.post(url, data={**token, 'review_id': unrelated, 'note': 'wrong origin'}).status_code == 409


def test_annotated_teaching_profile_has_real_facts_and_limited_languages(tmp_path, monkeypatch):
    from tests.fixtures.learning_profile import seed_profile, FACTS
    from archcoach.learning import lesson_examples, source_walkthroughs
    monkeypatch.setattr('archcoach.ai.CodexAdapter.status', lambda self: {'authenticated': False})
    settings, ids = seed_profile(tmp_path)
    app = create_app(settings, start_worker=False); store = app.state.store
    review = store.get_review(ids['before']); snapshot = store.get_snapshot(review['snapshot_id'])
    assert len({fact[1] for fact in FACTS}) == 10
    assert len({fact[0] for fact in FACTS}) == 8
    for question in review['critique']['quiz']:
        example = lesson_examples(settings, snapshot, {'lessons': [question]})[question['id']]
        assert example and example[0]['path'] == question['evidence'][0]['path']
        assert len(set(question['options'])) == 4
    outline = source_walkthroughs(settings, snapshot, review)
    assert 'Dynamic targets' in outline['qualification']
    assert any('client.ts' in s['example']['path'] for o in outline['outlines'] for s in o['steps'])
    assert any(s['title'] == 'Failure handling' for o in outline['outlines'] for s in o['steps'])
    # A non-Git DAZ view must not invent runtime or deployment from a script name.
    snapshot['manifest'] = [{**snapshot['manifest'][0], 'path': 'feature.dsa'}]
    limited = source_walkthroughs(settings, snapshot, review)
    assert not limited['outlines'] and 'limited' in limited['notes'][0]


def test_hint_omits_saved_answers_and_cancelled_practice_has_no_success(saved_learning):
    from archcoach.review import ReviewEngine, ReviewCancelled
    app, _, _, _, review = saved_learning
    stopped = [False]
    class HintProvider:
        last_usage = {}
        def run_structured(self, prompt, *args, **kwargs):
            assert 'Do not reveal the correct option' in prompt
            assert '"correct_index"' not in prompt and 'The saved function formats text' not in prompt
            stopped[0] = True
            return {'answer': 'Read what the function returns.', 'citations': []}
    engine = ReviewEngine(app.state.settings, app.state.store); engine.codex = HintProvider()
    with pytest.raises(ReviewCancelled):
        engine._run_chat(review, 'Give me a hint.', mode='hint', question_id='ownership', cancelled=lambda: stopped[0])
    assert [m['role'] for m in app.state.store.conversation_for_review(review)['messages']] == ['user']


def test_ambiguous_component_membership_never_selects_an_arbitrary_owner(saved_learning):
    from archcoach.learning import source_walkthroughs
    app, _, _, _, review_id = saved_learning
    review = app.state.store.get_review(review_id); snapshot = app.state.store.get_snapshot(review['snapshot_id'])
    review['architecture']['components'].append({'id': 'other', 'source_paths': ['main.py']})
    outline = source_walkthroughs(app.state.settings, snapshot, review)
    assert outline['outlines'][0]['steps'][0]['component_id'] is None
    assert 'ownership is ambiguous' in outline['notes'][0]


def test_same_timestamp_attempts_keep_submission_order(saved_learning, monkeypatch):
    app, _, _, _, review = saved_learning
    monkeypatch.setattr('archcoach.db.utc_now', lambda: '2026-10-12T10:00:00+00:00')
    app.state.store.save_quiz_answer(review, 'ownership', 1, False)
    app.state.store.save_quiz_answer(review, 'ownership', 0, True)
    assert [a['selected_index'] for a in app.state.store.quiz_attempts(review)] == [1, 0]


def test_new_report_artifact_contains_saved_teaching_without_renderer(saved_learning, monkeypatch):
    from archcoach.ai import CodexUnavailable
    from archcoach.review import ReviewEngine
    app, _, _, project, _ = saved_learning
    class Offline:
        last_usage = {}
        def run_structured(self, *args, **kwargs):
            raise CodexUnavailable('Synthetic offline check')
        def cancel(self):
            pass
    monkeypatch.setattr('archcoach.review.render_diagram', lambda *args, **kwargs: {'renderer': 'unavailable'})
    rid = ReviewEngine(app.state.settings, app.state.store, Offline()).run(project['id'], force=True)
    review = app.state.store.get_review(rid)
    report = Path(review['artifacts']['report']).read_text(encoding='utf-8')
    assert 'Captured example: main.py:' in report and 'def greet' in report
    assert review['quality'] == 'limited'

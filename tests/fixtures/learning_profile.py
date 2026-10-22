"""Synthetic teaching profile and no-model server for isolated headless checks."""
from pathlib import Path
import hashlib
import json
import sys
import threading
import time

from archcoach.config import Settings
from archcoach.db import Store
from archcoach.models import ProjectCreate

FILES = {
    'main.py': 'from service import handle\ndef main(name):\n    return handle(name)\n',
    'service.py': 'from store import save\ndef handle(name):\n    if not name:\n        raise ValueError("empty")\n    cleaned = name.strip()\n    save(cleaned)\n    return "Hello " + cleaned\n',
    'store.py': 'names = []\ndef save(name):\n    names.append(name)\n',
    'tests/test_service.py': 'from service import handle\ndef test_greeting():\n    assert handle(" Ada ") == "Hello Ada"\n',
    'client.ts': 'export const greet = (name: string) => `Hello ${name}`;\n',
}

# Each annotated question names a precise source fact; design predictions stay qualified.
FACTS = [
    ('responsibilities', 'Which declaration coordinates validation, storage and greeting?', ['handle', 'save', 'names', 'greet'], 'service.py', 2, 7, 'handle declares these operations; whether it executes is not observed.'),
    ('dependencies', 'Which local module does main.py directly import?', ['service', 'store', 'client', 'tests'], 'main.py', 1, 1, 'The import names service; this is a dependency, not proof of execution order.'),
    ('data_flow', 'Which input is declared at the handle boundary?', ['name', 'cleaned', 'names', 'database'], 'service.py', 2, 2, 'The function declares name as its parameter; runtime values remain unknown.'),
    ('validation', 'What does the empty-name branch declare?', ['Raise ValueError', 'Write an empty name', 'Return a cached greeting', 'Retry a network request'], 'service.py', 3, 4, 'The branch explicitly raises ValueError when not name; its runtime reachability depends on input.'),
    ('state', 'Where does save append the supplied name?', ['The names list', 'A SQL database', 'A disk file', 'A message queue'], 'store.py', 1, 3, 'The saved function appends to the module-level names list; no persistent store is declared here.'),
    ('testing', 'What can the captured assertion establish without executing tests?', ['It specifies an expected greeting', 'It proves the test passed', 'It proves every failure is covered', 'It proves production is healthy'], 'tests/test_service.py', 3, 3, 'The assertion documents expected output; a captured test is not a test result.'),
    ('change_impact', 'Which saved import makes main.py a candidate to inspect after changing handle?', ['from service import handle', 'from store import handle', 'import database', 'import browser'], 'main.py', 1, 1, 'The import identifies a dependent; whether behavior changes needs further evidence.'),
    ('tradeoffs', 'Assuming names must survive restart, what should be investigated?', ['A persistence boundary and recovery behavior', 'Only renaming the list', 'Making the greeting longer', 'Removing input validation'], 'store.py', 1, 3, 'Under this hypothetical constraint, an in-memory list is insufficient; persistence adds failure and recovery costs.'),
    ('data_flow', 'Which expression creates the greeting output in handle?', ['"Hello " + cleaned', 'names.append(name)', 'ValueError("empty")', 'name: string'], 'service.py', 7, 7, 'The return expression composes greeting text; its actual runtime value has not been measured.'),
    ('responsibilities', 'Which separate declaration appends state rather than formatting output?', ['save', 'main', 'greet', 'test_greeting'], 'store.py', 2, 3, 'save owns this append operation. The source does not establish durable storage.'),
]


def seed_profile(root: Path):
    settings = Settings(data_dir=root / 'private data', app_dir=Path(__file__).resolve().parents[2] / 'src' / 'archcoach', port=8878)
    settings.ensure_dirs(); store = Store(settings.db_path)
    project_root = root / 'synthetic repo with spaces'; project_root.mkdir(parents=True)
    project = store.add_project(ProjectCreate(path=str(project_root), name='Learning fixture'))
    with store.connect() as conn:
        conn.execute('UPDATE projects SET enabled=0 WHERE id=?', (project['id'],))
    def snapshot(files):
        manifest = []
        for path, content in files.items():
            target = project_root / path; target.parent.mkdir(parents=True, exist_ok=True); target.write_text(content, encoding='utf-8')
            raw = content.encode(); digest = hashlib.sha256(raw).hexdigest()
            blob = settings.blob_dir / digest[:2] / digest; blob.parent.mkdir(exist_ok=True); blob.write_bytes(raw)
            manifest.append({'path': path, 'sha256': digest, 'lines': len(content.splitlines())})
        return store.create_snapshot(project['id'], hashlib.sha256(json.dumps(manifest).encode()).hexdigest(), manifest, {'available': False}, {}, {'level': 'limited', 'notes': ['Synthetic saved input; runtime and tests unexecuted.']})
    architecture = {'summary': 'Accepts a name, validates it, appends it to memory and composes a greeting (runtime path inferred from source).', 'main_path': ['entry', 'service', 'store'], 'components': [], 'relationships': []}
    for identifier, path, name, responsibility in [('entry', 'main.py', 'Entry boundary', 'Accepts name and calls handle'), ('service', 'service.py', 'Greeting coordinator', 'Declares validation, storage and output'), ('store', 'store.py', 'Memory store', 'Owns names list and append operation')]:
        architecture['components'].append({'id': identifier, 'name': name, 'kind': 'backend', 'responsibility': responsibility, 'sources': [{'path': path, 'line': 1}], 'source_paths': [path]})
    architecture['relationships'] = [{'source': 'entry', 'target': 'service', 'kind': 'imports', 'label': 'imports handle', 'sources': [{'path': 'main.py', 'line': 1}]}, {'source': 'service', 'target': 'store', 'kind': 'imports', 'label': 'imports save', 'sources': [{'path': 'service.py', 'line': 1}]}]
    quiz = []
    for i, (concept, question, options, path, line, end, fact) in enumerate(FACTS):
        quiz.append({'id': f'fact-{i}', 'concept': concept, 'difficulty': 'beginner', 'question': question, 'options': options, 'correct_index': 0, 'explanations': [fact, 'This option is not declared by the cited range. '+fact, 'This changes or overstates the cited behavior. '+fact, 'This boundary does not establish that claim. '+fact], 'evidence': [{'path': path, 'line': line, 'end_line': end, 'valid': True}]})
    lesson = {'id': 'boundary', 'title': 'Follow the validation boundary', 'explanation': 'handle declares a validation branch before the storage expression. An import is not an observed runtime sequence.', 'code_example': 'if not name:\n    raise ValueError("empty")', 'self_check': 'What should a caller decide when validation fails?', 'answer': 'How to surface the error while preserving the boundary contract; runtime handling remains unknown.', 'exercise': 'Explain the input, validation branch and returned expression.', 'evidence': [{'path': 'service.py', 'line': 2, 'end_line': 7, 'valid': True}]}
    critique = {'strengths': [], 'findings': [], 'lessons': [lesson], 'quiz': quiz, 'requirements': []}
    before = store.create_review(project['id'], snapshot(FILES), None, 'complete', architecture, critique, {}, {}, quality='complete')
    after_files = {**FILES, 'service.py': FILES['service.py'].replace('"Hello "', '"Welcome "')}
    after = store.create_review(project['id'], snapshot(after_files), before, 'complete', architecture, critique, {}, {}, quality='complete')
    # Future/current source differs deliberately; older reading must use saved blobs.
    store.save_quiz_answer(before, 'fact-0', 1, False, request_id='fixture-wrong-answer')
    with store.connect() as conn:
        conn.execute("UPDATE revision_state SET due_at='2026-01-01T00:00:00+00:00'")
    return settings, {'project': project['id'], 'before': before, 'after': after}


class FixtureProvider:
    last_usage = {}
    def status(self):
        return {'authenticated': False, 'message': 'Synthetic provider only'}
    def cancel(self):
        pass
    def run_structured(self, prompt, schema, workdir, **kwargs):
        from archcoach.ai import CodexCancelledError, CodexUnavailable
        current_message = prompt.rsplit('User: ', 1)[-1].split('<captured-source>', 1)[0]
        if 'FAIL_FIXTURE' in current_message:
            raise CodexUnavailable('Synthetic provider failure')
        if 'STALL_FIXTURE' in current_message:
            for _ in range(100):
                if kwargs['cancelled']():
                    raise CodexCancelledError('Synthetic cancellation')
                time.sleep(.1)
        if any(key in current_message for key in ('MISLOCATED_QUOTE', 'UNREPAIRED_QUOTE', 'TRUNCATED_QUOTE')):
            truncated = 'TRUNCATED_QUOTE' in current_message
            repaired = 'UNREPAIRED_QUOTE' not in current_message and 'cited line range' in prompt
            quote = 'def handle(name)' if truncated and not repaired else 'def handle(name):'
            return {'answer': f'Saved code:\n```python\n{quote}\n```',
                    'citations': [{'path': 'service.py', 'line': 2 if truncated or repaired else 3}]}
        citations = [{'path': 'service.py', 'line': 3, 'end_line': 4}]
        if schema.stem == 'feedback':
            return {'correct_points': 'You identified the input boundary.',
                    'missing_reasoning': 'Cite the validation branch.',
                    'next_question': 'What does the empty-name branch declare?', 'citations': citations}
        return {'answer': 'The validation branch declares an error for an empty name.', 'citations': citations}


def serve(root: Path, reuse=False):
    import uvicorn
    import archcoach.app as app_module
    if reuse:
        ids=json.loads((root/'ids.json').read_text(encoding='utf-8'))
        settings=Settings(data_dir=root/'private data',app_dir=Path(__file__).resolve().parents[2]/'src'/'archcoach',port=8878)
    else:
        settings, ids = seed_profile(root)
        (root/'ids.json').write_text(json.dumps(ids),encoding='utf-8')
    app_module.create_adapter = lambda _: FixtureProvider()
    app = app_module.create_app(settings)
    app.get('/api/learning-fixture')(lambda: ids)
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=settings.port, log_level='info'))
    def shutdown():
        app.state.shutdown_event.wait(); server.should_exit = True
    threading.Thread(target=shutdown, daemon=True).start()
    server.run()


if __name__ == '__main__':
    serve(Path(sys.argv[1]),reuse='--reuse' in sys.argv[2:])

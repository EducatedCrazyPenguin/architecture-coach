from archcoach.db import Store
from archcoach.learning import source_walkthroughs, practice_context
from tests.fixtures.learning_profile import seed_profile


def test_walkthrough_model_is_saved_once_per_version(tmp_path):
    settings, ids = seed_profile(tmp_path)
    store = Store(settings.db_path); review = store.get_review(ids['before'])
    snapshot = store.get_snapshot(review['snapshot_id'])
    model = source_walkthroughs(settings, snapshot, review)
    assert store.save_learning_walkthrough(review['id'], model) == model
    assert store.save_learning_walkthrough(review['id'], {**model, 'notes': ['different draft']}) == model
    assert store.get_learning_walkthrough(review['id'], 3) is None


def test_practice_context_is_saved_and_answers_are_redacted_for_hints(tmp_path):
    settings, ids = seed_profile(tmp_path)
    store = Store(settings.db_path); review = store.get_review(ids['before'])
    snapshot = store.get_snapshot(review['snapshot_id'])
    guidance, context = practice_context(settings, snapshot, review, 'hint', 'fact-0')
    assert 'Do not reveal' in guidance
    assert 'correct_index' not in context['question'] and 'explanations' not in context['question']
    assert context['saved_examples'][0]['path'] == 'service.py'


def test_owned_learning_records_cascade_without_deleting_target_files(tmp_path):
    settings, ids = seed_profile(tmp_path)
    store = Store(settings.db_path)
    before_bytes = (tmp_path / 'synthetic repo with spaces' / 'main.py').read_bytes()
    store.save_learning_note(ids['before'], 'fact-0', 'private correction')
    review = store.get_review(ids['before']); snapshot = store.get_snapshot(review['snapshot_id'])
    store.save_learning_walkthrough(review['id'], source_walkthroughs(settings, snapshot, review))
    with store.connect() as conn:
        conn.execute('DELETE FROM projects WHERE id=?', (ids['project'],))
        for table in ('quiz_attempts', 'revision_state', 'learning_notes', 'learning_walkthroughs'):
            assert conn.execute(f'SELECT count(*) FROM {table}').fetchone()[0] == 0
    assert (tmp_path / 'synthetic repo with spaces' / 'main.py').read_bytes() == before_bytes

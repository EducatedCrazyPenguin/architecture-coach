from pathlib import Path

from archcoach.ai import CodexError
from archcoach.config import Settings
from archcoach.db import Store
from archcoach.models import ProjectCreate
from archcoach.review import ReviewEngine


class OfflineCodex:
    current = None
    def available(self): return False
    def run_structured(self, *args, **kwargs): raise CodexError("offline")
    def cancel(self): return None


def test_review_completes_offline_and_reuses_unchanged_source(tmp_path: Path):
    source = tmp_path / "source"; source.mkdir()
    (source / "app.py").write_text("def main():\n    return 'hello'\n", encoding="utf-8")
    settings = Settings(data_dir=tmp_path / "data", app_dir=Path(__file__).parents[1] / "src" / "archcoach"); settings.ensure_dirs()
    store = Store(settings.db_path)
    project = store.add_project(ProjectCreate(path=str(source), description="A sample app"))
    engine = ReviewEngine(settings, store, OfflineCodex())

    first_id = engine.run(project["id"])
    first = store.get_review(first_id)
    assert first["status"] == "complete"
    assert Path(first["artifacts"]["diagram"]).exists()
    assert 1 <= len(first["critique"]["lessons"]) <= 3

    second = store.get_review(engine.run(project["id"]))
    assert second["status"] == "unchanged"
    assert second["reused_from_id"] == first_id


def test_review_does_not_modify_project(tmp_path: Path):
    source = tmp_path / "source"; source.mkdir(); file = source / "app.py"
    file.write_text("print('safe')\n", encoding="utf-8")
    before = file.read_bytes()
    settings = Settings(data_dir=tmp_path / "data", app_dir=Path(__file__).parents[1] / "src" / "archcoach"); settings.ensure_dirs()
    store = Store(settings.db_path); project = store.add_project(ProjectCreate(path=str(source)))
    ReviewEngine(settings, store, OfflineCodex()).run(project["id"])
    assert file.read_bytes() == before
    assert sorted(item.name for item in source.iterdir()) == ["app.py"]

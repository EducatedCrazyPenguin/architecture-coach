import json
import sqlite3
from pathlib import Path

from archcoach.db import SCHEMA, SCHEMA_VERSION, Store


def test_legacy_database_is_backed_up_and_migrated_without_data_loss(tmp_path: Path):
    database = tmp_path / "archcoach.db"
    with sqlite3.connect(database) as conn:
        conn.executescript(SCHEMA)
        conn.execute("PRAGMA user_version=1")
        conn.execute("INSERT INTO projects VALUES(?,?,?,?,?,?,?,?,?,?)", ("p", "Project", str(tmp_path), "description", "goal", "[]", 7, "2026-01-01", None, 1))
        conn.execute("INSERT INTO snapshots VALUES(?,?,?,?,?,?,?,?)", ("s", "p", "2026-01-01", "fingerprint", "[]", "{}", "{}", "{}"))
        conn.execute("INSERT INTO reviews VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", ("r", "p", "s", None, "2026-01-01", "complete", "{}", "{}", "{}", "{}", None, None))
        conn.execute("INSERT INTO conversations VALUES(?,?,?)", ("c", "r", "2026-01-01"))
        conn.execute("INSERT INTO messages VALUES(?,?,?,?,?,?)", ("m", "c", "user", "hello", "[]", "2026-01-01"))
        conn.execute("INSERT INTO lesson_progress VALUES(?,?,?,?)", ("r", "lesson", "learning", "2026-01-01"))

    store = Store(database)

    with store.connect() as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert store.get_project("p")["goal"] == "goal"
    assert store.get_review("r")["snapshot_id"] == "s"
    assert store.conversation_for_review("r")["messages"][0]["content"] == "hello"
    assert store.lesson_statuses("r") == {"lesson": "learning"}
    assert store.list_history("p")[0]["history_type"] == "review"
    assert store.get_review("r")["quality"] == "legacy"
    assert store.get_review("r")["format_version"] == 1
    assert len(list((tmp_path / "backups").glob("archcoach-v1-*.db"))) == 1


def test_project_registration_uses_canonical_windows_identity(tmp_path: Path):
    project = tmp_path / "Case Folder"
    project.mkdir()
    store = Store(tmp_path / "data" / "archcoach.db")
    from archcoach.models import ProjectCreate

    store.add_project(ProjectCreate(path=str(project)))
    try:
        store.add_project(ProjectCreate(path=str(project).upper()))
    except ValueError as exc:
        assert "already registered" in str(exc)
    else:
        raise AssertionError("case-only duplicate registration was accepted")

import json
import sqlite3
import threading
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
    saved_answer = store.save_quiz_answer("r", "question", 2, False)
    assert saved_answer["correct"] is False
    assert store.quiz_answers("r")["question"]["selected_index"] == 2
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


def test_version_three_database_adds_quiz_answers_transactionally(tmp_path: Path):
    database = tmp_path / "archcoach.db"
    Store(database)
    with sqlite3.connect(database) as conn:
        conn.execute("DROP TABLE quiz_answers")
        conn.execute("PRAGMA user_version=3")

    Store(database)

    with sqlite3.connect(database) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='quiz_answers'").fetchone()
    assert list((tmp_path / "backups").glob("archcoach-v3-*.db"))


def test_migration_backup_includes_committed_wal_data(tmp_path: Path):
    database = tmp_path / "archcoach.db"
    Store(database)
    with sqlite3.connect(database) as conn:
        conn.execute("PRAGMA user_version=3")
    held = sqlite3.connect(database)
    try:
        held.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        held.execute("PRAGMA wal_autocheckpoint=0")
        held.execute("INSERT INTO settings VALUES('committed_marker','1')")
        held.commit()
        Store(database)
        backup = next((tmp_path / "backups").glob("archcoach-v3-*.db"))
        with sqlite3.connect(backup) as copied:
            assert copied.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert copied.execute("SELECT value_json FROM settings WHERE key='committed_marker'").fetchone()[0] == "1"
    finally:
        held.close()


def test_concurrent_startup_migrates_once_and_takes_one_backup(tmp_path: Path):
    database = tmp_path / "archcoach.db"
    Store(database)
    with sqlite3.connect(database) as conn:
        conn.execute("DROP TABLE quiz_answers")
        conn.execute("PRAGMA user_version=3")

    barrier = threading.Barrier(2)
    failures: list[BaseException] = []

    def open_store() -> None:
        try:
            barrier.wait()
            Store(database)
        except BaseException as exc:
            failures.append(exc)

    workers = [threading.Thread(target=open_store) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=10)

    assert not failures
    assert all(not worker.is_alive() for worker in workers)
    assert len(list((tmp_path / "backups").glob("archcoach-v3-*.db"))) == 1
    with sqlite3.connect(database) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION

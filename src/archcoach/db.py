from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .models import ProjectCreate, ProjectUpdate, utc_now


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, path TEXT NOT NULL UNIQUE,
  description TEXT NOT NULL DEFAULT '', goal TEXT NOT NULL DEFAULT '',
  exclusions_json TEXT NOT NULL DEFAULT '[]', interval_days INTEGER NOT NULL DEFAULT 7,
  created_at TEXT NOT NULL, last_checked_at TEXT, enabled INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS snapshots (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL, fingerprint TEXT NOT NULL, manifest_json TEXT NOT NULL,
  git_json TEXT NOT NULL, analysis_json TEXT NOT NULL, coverage_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS snapshots_project_idx ON snapshots(project_id, created_at DESC);
CREATE TABLE IF NOT EXISTS reviews (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  snapshot_id TEXT NOT NULL REFERENCES snapshots(id), prior_review_id TEXT,
  created_at TEXT NOT NULL, status TEXT NOT NULL, architecture_json TEXT NOT NULL,
  critique_json TEXT NOT NULL, changes_json TEXT NOT NULL, artifacts_json TEXT NOT NULL,
  reused_from_id TEXT, error TEXT
);
CREATE INDEX IF NOT EXISTS reviews_project_idx ON reviews(project_id, created_at DESC);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
  review_id TEXT REFERENCES reviews(id), operation TEXT NOT NULL, priority INTEGER NOT NULL,
  status TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0, message TEXT NOT NULL DEFAULT '',
  payload_json TEXT NOT NULL DEFAULT '{}', result_json TEXT NOT NULL DEFAULT '{}',
  error TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT
);
CREATE INDEX IF NOT EXISTS jobs_queue_idx ON jobs(status, priority, created_at);
CREATE TABLE IF NOT EXISTS conversations (
  id TEXT PRIMARY KEY, review_id TEXT NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  role TEXT NOT NULL, content TEXT NOT NULL, citations_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lesson_progress (
  review_id TEXT NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
  lesson_id TEXT NOT NULL, status TEXT NOT NULL, updated_at TEXT NOT NULL,
  PRIMARY KEY(review_id, lesson_id)
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value_json TEXT NOT NULL);
"""


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            conn.execute("UPDATE jobs SET status='failed', error='App stopped during this job', finished_at=? WHERE status='running'", (utc_now(),))

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        data = dict(row)
        for key in list(data):
            if key.endswith("_json"):
                data[key[:-5]] = json.loads(data.pop(key) or "null")
        return data

    def add_project(self, request: ProjectCreate) -> dict[str, Any]:
        path = Path(request.path).expanduser().resolve()
        if not path.is_dir():
            raise ValueError(f"Folder does not exist: {path}")
        project_id = uuid.uuid4().hex
        with self.connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO projects VALUES(?,?,?,?,?,?,?,?,?,1)",
                    (project_id, request.name or path.name, str(path), request.description, request.goal,
                     json.dumps(request.exclusions), request.interval_days, utc_now(), None),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("That project folder is already registered") from exc
        return self.get_project(project_id)

    def list_projects(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM projects ORDER BY name COLLATE NOCASE").fetchall()
        return [self._row(row) for row in rows]

    def get_project(self, project_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        result = self._row(row)
        if not result:
            raise KeyError(project_id)
        return result

    def update_project(self, project_id: str, update: ProjectUpdate | None = None, **fields: Any) -> dict[str, Any]:
        if update is not None:
            fields.update(update.model_dump())
        allowed = {"name", "description", "goal", "interval_days", "enabled", "last_checked_at", "exclusions"}
        clean = {key: value for key, value in fields.items() if key in allowed}
        if not clean:
            return self.get_project(project_id)
        if "exclusions" in clean:
            clean["exclusions_json"] = json.dumps(clean.pop("exclusions"))
        assignments = ",".join(f"{key}=?" for key in clean)
        with self.connect() as conn:
            cursor = conn.execute(f"UPDATE projects SET {assignments} WHERE id=?", (*clean.values(), project_id))
            if cursor.rowcount == 0:
                raise KeyError(project_id)
        return self.get_project(project_id)

    def create_snapshot(self, project_id: str, fingerprint: str, manifest: list[dict], git: dict, analysis: dict, coverage: dict) -> str:
        snapshot_id = uuid.uuid4().hex
        with self.connect() as conn:
            conn.execute("INSERT INTO snapshots VALUES(?,?,?,?,?,?,?,?)", (snapshot_id, project_id, utc_now(), fingerprint, json.dumps(manifest), json.dumps(git), json.dumps(analysis), json.dumps(coverage)))
        return snapshot_id

    def get_snapshot(self, snapshot_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM snapshots WHERE id=?", (snapshot_id,)).fetchone()
        result = self._row(row)
        if not result:
            raise KeyError(snapshot_id)
        return result

    def latest_review(self, project_id: str, successful_only: bool = True) -> dict[str, Any] | None:
        clause = "AND status IN ('complete','unchanged')" if successful_only else ""
        with self.connect() as conn:
            row = conn.execute(f"SELECT * FROM reviews WHERE project_id=? {clause} ORDER BY created_at DESC LIMIT 1", (project_id,)).fetchone()
        return self._row(row)

    def list_reviews(self, project_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM reviews WHERE project_id=? ORDER BY created_at DESC", (project_id,)).fetchall()
        return [self._row(row) for row in rows]

    def get_review(self, review_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM reviews WHERE id=?", (review_id,)).fetchone()
        result = self._row(row)
        if not result:
            raise KeyError(review_id)
        return result

    def create_review(self, project_id: str, snapshot_id: str, prior_id: str | None, status: str, architecture: dict, critique: dict, changes: dict, artifacts: dict, reused_from_id: str | None = None, error: str | None = None) -> str:
        review_id = uuid.uuid4().hex
        with self.connect() as conn:
            conn.execute("INSERT INTO reviews VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (review_id, project_id, snapshot_id, prior_id, utc_now(), status, json.dumps(architecture), json.dumps(critique), json.dumps(changes), json.dumps(artifacts), reused_from_id, error))
        return review_id

    def enqueue(self, operation: str, project_id: str | None, payload: dict | None = None, review_id: str | None = None, priority: int = 10) -> str:
        with self.connect() as conn:
            if operation == "review" and project_id:
                existing = conn.execute("SELECT id FROM jobs WHERE operation='review' AND project_id=? AND status IN ('queued','running')", (project_id,)).fetchone()
                if existing:
                    return existing[0]
            job_id = uuid.uuid4().hex
            conn.execute("INSERT INTO jobs(id,project_id,review_id,operation,priority,status,payload_json,created_at) VALUES(?,?,?,?,?,'queued',?,?)", (job_id, project_id, review_id, operation, priority, json.dumps(payload or {}), utc_now()))
        return job_id

    def next_job(self) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY priority, created_at LIMIT 1").fetchone()
            if row:
                conn.execute("UPDATE jobs SET status='running', started_at=? WHERE id=?", (utc_now(), row["id"]))
        return self._row(row)

    def update_job(self, job_id: str, **fields: Any) -> None:
        allowed = {"status", "progress", "message", "result_json", "error", "finished_at", "cancel_requested"}
        clean = {key: (json.dumps(value) if key == "result_json" else value) for key, value in fields.items() if key in allowed}
        if not clean:
            return
        with self.connect() as conn:
            conn.execute(f"UPDATE jobs SET {','.join(f'{key}=?' for key in clean)} WHERE id=?", (*clean.values(), job_id))

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        result = self._row(row)
        if not result:
            raise KeyError(job_id)
        return result

    def add_message(self, conversation_id: str, role: str, content: str, citations: list | None = None) -> str:
        message_id = uuid.uuid4().hex
        with self.connect() as conn:
            conn.execute("INSERT INTO messages VALUES(?,?,?,?,?,?)", (message_id, conversation_id, role, content, json.dumps(citations or []), utc_now()))
        return message_id

    def conversation_for_review(self, review_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM conversations WHERE review_id=? ORDER BY created_at DESC LIMIT 1", (review_id,)).fetchone()
            if not row:
                cid = uuid.uuid4().hex
                conn.execute("INSERT INTO conversations VALUES(?,?,?)", (cid, review_id, utc_now()))
                row = conn.execute("SELECT * FROM conversations WHERE id=?", (cid,)).fetchone()
            messages = conn.execute("SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at", (row["id"],)).fetchall()
        result = self._row(row)
        result["messages"] = [self._row(item) for item in messages]
        return result

    def set_lesson_status(self, review_id: str, lesson_id: str, status: str) -> None:
        with self.connect() as conn:
            conn.execute("INSERT INTO lesson_progress VALUES(?,?,?,?) ON CONFLICT(review_id,lesson_id) DO UPDATE SET status=excluded.status, updated_at=excluded.updated_at", (review_id, lesson_id, status, utc_now()))

    def lesson_statuses(self, review_id: str) -> dict[str, str]:
        with self.connect() as conn:
            rows = conn.execute("SELECT lesson_id,status FROM lesson_progress WHERE review_id=?", (review_id,)).fetchall()
        return {row[0]: row[1] for row in rows}

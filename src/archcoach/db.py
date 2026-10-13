from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Iterator

from .models import ProjectCreate, ProjectUpdate, utc_now
from .ownership import DataDirectoryLock


SCHEMA = """
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
CREATE TABLE IF NOT EXISTS quiz_answers (
  review_id TEXT NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
  question_id TEXT NOT NULL, selected_index INTEGER NOT NULL,
  correct INTEGER NOT NULL, answered_at TEXT NOT NULL,
  PRIMARY KEY(review_id, question_id)
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value_json TEXT NOT NULL);
"""

SCHEMA_VERSION = 10
MIGRATION_2 = (
    "ALTER TABLE projects ADD COLUMN normalized_path TEXT",
    "ALTER TABLE projects ADD COLUMN last_attempted_at TEXT",
    "ALTER TABLE projects ADD COLUMN schedule_error TEXT",
    "ALTER TABLE snapshots ADD COLUMN config_fingerprint TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE snapshots ADD COLUMN format_version INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE reviews ADD COLUMN quality TEXT NOT NULL DEFAULT 'legacy'",
    "ALTER TABLE reviews ADD COLUMN format_version INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE reviews ADD COLUMN positions_json TEXT NOT NULL DEFAULT '{}'",
    "ALTER TABLE jobs ADD COLUMN stage TEXT NOT NULL DEFAULT 'queued'",
    "ALTER TABLE jobs ADD COLUMN error_code TEXT",
    "ALTER TABLE jobs ADD COLUMN usage_json TEXT NOT NULL DEFAULT '{}'",
    "ALTER TABLE jobs ADD COLUMN last_activity_at TEXT",
    "ALTER TABLE jobs ADD COLUMN scheduled_for TEXT",
    "ALTER TABLE jobs ADD COLUMN source TEXT NOT NULL DEFAULT 'manual'",
    "ALTER TABLE messages ADD COLUMN status TEXT NOT NULL DEFAULT 'complete'",
    "CREATE TABLE check_events (id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE, review_id TEXT REFERENCES reviews(id), created_at TEXT NOT NULL, source_fingerprint TEXT NOT NULL, config_fingerprint TEXT NOT NULL, result TEXT NOT NULL)",
    "CREATE INDEX check_events_project_idx ON check_events(project_id, created_at DESC)",
)
MIGRATION_3 = (
    "CREATE UNIQUE INDEX jobs_one_active_review_idx ON jobs(project_id) WHERE operation='review' AND status IN ('queued','running')",
    "CREATE UNIQUE INDEX jobs_scheduled_occurrence_idx ON jobs(project_id,scheduled_for) WHERE source='schedule' AND scheduled_for IS NOT NULL",
)
MIGRATION_4 = (
    "CREATE TABLE IF NOT EXISTS quiz_answers (review_id TEXT NOT NULL REFERENCES reviews(id) ON DELETE CASCADE, question_id TEXT NOT NULL, selected_index INTEGER NOT NULL, correct INTEGER NOT NULL, answered_at TEXT NOT NULL, PRIMARY KEY(review_id, question_id))",
)
MIGRATION_5 = (
    "CREATE TABLE IF NOT EXISTS improvement_plans (id TEXT PRIMARY KEY, review_id TEXT NOT NULL REFERENCES reviews(id) ON DELETE CASCADE, finding_id TEXT NOT NULL, parent_id TEXT, job_id TEXT, created_at TEXT NOT NULL, status TEXT NOT NULL, draft_json TEXT NOT NULL, draft_hash TEXT NOT NULL, validation_json TEXT NOT NULL, provider_json TEXT NOT NULL, receipt_json TEXT NOT NULL DEFAULT '{}')",
    "CREATE INDEX IF NOT EXISTS improvement_plans_review_idx ON improvement_plans(review_id,created_at DESC)",
)
MIGRATION_6 = (
    "CREATE TABLE IF NOT EXISTS quiz_attempts (id TEXT PRIMARY KEY, review_id TEXT NOT NULL REFERENCES reviews(id) ON DELETE CASCADE, question_id TEXT NOT NULL, selected_index INTEGER NOT NULL, correct INTEGER NOT NULL, answered_at TEXT NOT NULL, kind TEXT NOT NULL, request_id TEXT NOT NULL UNIQUE)",
    "CREATE INDEX IF NOT EXISTS quiz_attempts_question_idx ON quiz_attempts(review_id,question_id,answered_at)",
    "INSERT OR IGNORE INTO quiz_attempts(id,review_id,question_id,selected_index,correct,answered_at,kind,request_id) SELECT 'legacy:' || review_id || ':' || question_id, review_id, question_id, selected_index, correct, answered_at, 'legacy', 'legacy:' || review_id || ':' || question_id FROM quiz_answers",
    "CREATE TABLE IF NOT EXISTS revision_state (review_id TEXT NOT NULL REFERENCES reviews(id) ON DELETE CASCADE, question_id TEXT NOT NULL, due_at TEXT NOT NULL, streak INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(review_id,question_id))",
    "INSERT OR IGNORE INTO revision_state SELECT review_id,question_id,answered_at,0 FROM quiz_answers",
    "CREATE TABLE IF NOT EXISTS learning_notes (review_id TEXT NOT NULL REFERENCES reviews(id) ON DELETE CASCADE, question_id TEXT NOT NULL, content TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(review_id,question_id))",
)


def canonical_path(path: Path) -> str:
    return os.path.normcase(str(path.expanduser().resolve())).casefold()


class JobCancelledError(RuntimeError):
    pass


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    def _migrate(self) -> None:
        migration_lock = DataDirectoryLock(self.path.parent, "migration.lock")
        deadline = time.monotonic() + 30
        while not migration_lock.acquire():
            if time.monotonic() >= deadline:
                raise RuntimeError("Another Architecture Coach process is still preparing this database")
            time.sleep(0.05)
        try:
            self._migrate_exclusive()
        finally:
            migration_lock.release()

    def _migrate_exclusive(self) -> None:
        existed = self.path.exists() and self.path.stat().st_size > 0
        with sqlite3.connect(self.path, timeout=30) as probe:
            version = probe.execute("PRAGMA user_version").fetchone()[0]
        if existed and version < SCHEMA_VERSION:
            backup_dir = self.path.parent / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup_path = backup_dir / f"{self.path.stem}-v{version}-{stamp}-{uuid.uuid4().hex[:8]}.db"
            with sqlite3.connect(self.path, timeout=30) as source:
                with sqlite3.connect(backup_path) as destination:
                    source.backup(destination)
        with sqlite3.connect(self.path, timeout=30) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("BEGIN IMMEDIATE")
            try:
                # Re-read after acquiring SQLite's write lock as a final safeguard.
                # The data-directory migration lock prevents another app launch from
                # taking a duplicate backup between this check and the migration.
                version = conn.execute("PRAGMA user_version").fetchone()[0]
                if version == 0:
                    # sqlite3.executescript commits an open transaction first. Execute
                    # this known schema statement-by-statement so the migration lock
                    # remains held from version check through final commit.
                    for statement in SCHEMA.split(";"):
                        if statement.strip():
                            conn.execute(statement)
                    conn.execute("PRAGMA user_version=1")
                    version = 1
                if version == 1:
                    for statement in MIGRATION_2:
                        conn.execute(statement)
                    rows = conn.execute("SELECT id,path FROM projects").fetchall()
                    for project_id, project_path in rows:
                        conn.execute("UPDATE projects SET normalized_path=? WHERE id=?", (canonical_path(Path(project_path)), project_id))
                    conn.execute("CREATE UNIQUE INDEX projects_normalized_path_idx ON projects(normalized_path)")
                    conn.execute("PRAGMA user_version=2")
                    version = 2
                if version == 2:
                    duplicates = conn.execute(
                        "SELECT project_id FROM jobs WHERE operation='review' AND status IN ('queued','running') "
                        "GROUP BY project_id HAVING COUNT(*) > 1"
                    ).fetchall()
                    for (project_id,) in duplicates:
                        rows = conn.execute(
                            "SELECT id FROM jobs WHERE operation='review' AND project_id=? AND status IN ('queued','running') ORDER BY created_at,id",
                            (project_id,),
                        ).fetchall()
                        for row in rows[1:]:
                            conn.execute(
                                "UPDATE jobs SET status='failed',error='Superseded during migration',error_code='duplicate_active_job',finished_at=? WHERE id=?",
                                (utc_now(), row[0]),
                            )
                    for statement in MIGRATION_3:
                        conn.execute(statement)
                    conn.execute("PRAGMA user_version=3")
                    version = 3
                if version == 3:
                    for statement in MIGRATION_4:
                        conn.execute(statement)
                    conn.execute("PRAGMA user_version=4")
                    version = 4
                if version == 4:
                    for statement in MIGRATION_5:
                        conn.execute(statement)
                    conn.execute("PRAGMA user_version=5")
                    version = 5
                if version == 5:
                    for statement in MIGRATION_6:
                        conn.execute(statement)
                    conn.execute("PRAGMA user_version=6")
                    version = 6
                if version == 6:
                    columns = {row[1] for row in conn.execute('PRAGMA table_info(messages)')}
                    if 'learning_context_json' not in columns:
                        conn.execute("ALTER TABLE messages ADD COLUMN learning_context_json TEXT NOT NULL DEFAULT '{}'")
                    conn.execute('PRAGMA user_version=7')
                    version = 7
                if version == 7:
                    conn.execute('CREATE TABLE IF NOT EXISTS plan_learning_reports (id TEXT PRIMARY KEY, plan_id TEXT NOT NULL REFERENCES improvement_plans(id) ON DELETE CASCADE, review_id TEXT NOT NULL REFERENCES reviews(id) ON DELETE CASCADE, created_at TEXT NOT NULL, note TEXT NOT NULL, format_version INTEGER NOT NULL DEFAULT 1)')
                    conn.execute('PRAGMA user_version=8')
                    version = 8
                if version == 8:
                    conn.execute('CREATE TABLE IF NOT EXISTS learning_walkthroughs (review_id TEXT NOT NULL REFERENCES reviews(id) ON DELETE CASCADE, format_version INTEGER NOT NULL, model_json TEXT NOT NULL, PRIMARY KEY(review_id,format_version))')
                    conn.execute('PRAGMA user_version=9')
                    version = 9
                if version == 9:
                    for table in ('quiz_attempts', 'quiz_answers'):
                        if 'outcome' not in {row[1] for row in conn.execute(f'PRAGMA table_info({table})')}:
                            conn.execute(f"ALTER TABLE {table} ADD COLUMN outcome TEXT NOT NULL DEFAULT 'answered'")
                    conn.execute("CREATE TABLE IF NOT EXISTS learning_sessions (review_id TEXT PRIMARY KEY REFERENCES reviews(id) ON DELETE CASCADE, state_json TEXT NOT NULL, updated_at TEXT NOT NULL, format_version INTEGER NOT NULL DEFAULT 1)")
                    conn.execute("CREATE TABLE IF NOT EXISTS learning_issues (id TEXT PRIMARY KEY, review_id TEXT NOT NULL REFERENCES reviews(id) ON DELETE CASCADE, kind TEXT NOT NULL, target_id TEXT NOT NULL, note TEXT NOT NULL, created_at TEXT NOT NULL, resolved_at TEXT)")
                    conn.execute('PRAGMA user_version=10')
                    version = 10
                if version != SCHEMA_VERSION:
                    raise RuntimeError(f"Unsupported database schema version: {version}")
                conn.commit()
            except Exception:
                conn.rollback()
                raise

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
                    "INSERT INTO projects(id,name,path,description,goal,exclusions_json,interval_days,created_at,last_checked_at,enabled,normalized_path) VALUES(?,?,?,?,?,?,?,?,?,1,?)",
                    (project_id, request.name or path.name, str(path), request.description, request.goal,
                     json.dumps(request.exclusions), request.interval_days, utc_now(), None, canonical_path(path)),
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
            fields.update(update.model_dump(exclude_unset=True))
        allowed = {
            "name", "description", "goal", "interval_days", "enabled", "last_checked_at",
            "last_attempted_at", "schedule_error", "exclusions",
        }
        clean = {key: value for key, value in fields.items() if key in allowed and value is not None}
        if not clean:
            return self.get_project(project_id)
        if "exclusions" in clean:
            clean["exclusions_json"] = json.dumps(clean.pop("exclusions"))
        assignments = ",".join(f"{key}=?" for key in clean)
        with self.connect() as conn:
            cursor = conn.execute(f"UPDATE projects SET {assignments} WHERE id=?", (*clean.values(), project_id))
            if cursor.rowcount == 0:
                raise KeyError(project_id)
            if clean.get("enabled") in (False, 0):
                conn.execute(
                    "UPDATE jobs SET status='cancelled',message='Scheduling disabled',finished_at=? "
                    "WHERE project_id=? AND source='schedule' AND status='queued'",
                    (utc_now(), project_id),
                )
        return self.get_project(project_id)

    def create_snapshot(
        self,
        project_id: str,
        fingerprint: str,
        manifest: list[dict],
        git: dict,
        analysis: dict,
        coverage: dict,
        *,
        config_fingerprint: str = "",
        format_version: int = 2,
    ) -> str:
        snapshot_id = uuid.uuid4().hex
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO snapshots(id,project_id,created_at,fingerprint,manifest_json,git_json,analysis_json,coverage_json,config_fingerprint,format_version) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (snapshot_id, project_id, utc_now(), fingerprint, json.dumps(manifest), json.dumps(git),
                 json.dumps(analysis), json.dumps(coverage), config_fingerprint, format_version),
            )
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

    def list_check_events(self, project_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM check_events WHERE project_id=? ORDER BY created_at DESC", (project_id,),
            ).fetchall()
        return [self._row(row) for row in rows]

    def list_history(self, project_id: str) -> list[dict[str, Any]]:
        reviews = [{**item, "history_type": "review"} for item in self.list_reviews(project_id)]
        checks = [{**item, "history_type": "check"} for item in self.list_check_events(project_id)]
        return sorted([*reviews, *checks], key=lambda item: (item["created_at"], item["id"]), reverse=True)

    def get_review(self, review_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM reviews WHERE id=?", (review_id,)).fetchone()
        result = self._row(row)
        if not result:
            raise KeyError(review_id)
        return result

    def create_review(
        self, project_id: str, snapshot_id: str, prior_id: str | None, status: str,
        architecture: dict, critique: dict, changes: dict, artifacts: dict,
        reused_from_id: str | None = None, error: str | None = None,
        *, quality: str = "legacy", positions: dict | None = None, format_version: int = 2,
    ) -> str:
        review_id = uuid.uuid4().hex
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO reviews(id,project_id,snapshot_id,prior_review_id,created_at,status,architecture_json,critique_json,changes_json,artifacts_json,reused_from_id,error,quality,format_version,positions_json) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (review_id, project_id, snapshot_id, prior_id, utc_now(), status, json.dumps(architecture),
                 json.dumps(critique), json.dumps(changes), json.dumps(artifacts), reused_from_id, error,
                 quality, format_version, json.dumps(positions or {})),
            )
        return review_id

    def finalize_review(
        self,
        review_id: str,
        project_id: str,
        artifacts: dict,
        *,
        quality: str,
        job_id: str | None = None,
        status: str = "complete",
    ) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            job = None
            if job_id:
                job = conn.execute("SELECT status,cancel_requested,source FROM jobs WHERE id=?", (job_id,)).fetchone()
                if not job or job["status"] != "running" or job["cancel_requested"]:
                    raise JobCancelledError("Job was cancelled before review publication")
            cursor = conn.execute(
                "UPDATE reviews SET status=?,quality=?,artifacts_json=? WHERE id=? AND status='rendering'",
                (status, quality, json.dumps(artifacts), review_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Review publication state changed unexpectedly")
            if quality == "complete":
                conn.execute(
                    "UPDATE projects SET last_checked_at=?,schedule_error=NULL WHERE id=?",
                    (now, project_id),
                )
            elif job and job["source"] == "schedule":
                conn.execute("UPDATE projects SET schedule_error='limited_review' WHERE id=?", (project_id,))
            if job_id:
                conn.execute(
                    "UPDATE jobs SET status='complete',stage='complete',progress=100,message=?,result_json=?,finished_at=?,last_activity_at=? WHERE id=?",
                    ("Complete" if quality == "complete" else "Complete with limited analysis",
                     json.dumps({"review_id": review_id, "quality": quality}), now, now, job_id),
                )

    def delete_unpublished_review(self, review_id: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM reviews WHERE id=? AND status='rendering'", (review_id,))

    def record_unchanged_check(
        self,
        project_id: str,
        review_id: str,
        source_fingerprint: str,
        config_fingerprint: str,
        *,
        job_id: str | None = None,
    ) -> str:
        event_id = uuid.uuid4().hex
        now = utc_now()
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if job_id:
                job = conn.execute("SELECT status,cancel_requested FROM jobs WHERE id=?", (job_id,)).fetchone()
                if not job or job["status"] != "running" or job["cancel_requested"]:
                    raise JobCancelledError("Job was cancelled before unchanged check publication")
            conn.execute(
                "INSERT INTO check_events(id,project_id,review_id,created_at,source_fingerprint,config_fingerprint,result) VALUES(?,?,?,?,?,?,?)",
                (event_id, project_id, review_id, now, source_fingerprint, config_fingerprint, "unchanged"),
            )
            conn.execute(
                "UPDATE projects SET last_checked_at=?,schedule_error=NULL WHERE id=?", (now, project_id),
            )
            if job_id:
                conn.execute(
                    "UPDATE jobs SET status='complete',stage='complete',progress=100,message='Checked — no changes',result_json=?,finished_at=?,last_activity_at=? WHERE id=?",
                    (json.dumps({"review_id": review_id, "check_event_id": event_id, "unchanged": True}), now, now, job_id),
                )
        return event_id

    def enqueue(
        self,
        operation: str,
        project_id: str | None,
        payload: dict | None = None,
        review_id: str | None = None,
        priority: int = 10,
        *,
        source: str = "manual",
        scheduled_for: str | None = None,
    ) -> str:
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if operation == "review" and project_id:
                existing = conn.execute("SELECT id FROM jobs WHERE operation='review' AND project_id=? AND status IN ('queued','running')", (project_id,)).fetchone()
                if existing:
                    return existing[0]
            job_id = uuid.uuid4().hex
            now = utc_now()
            try:
                conn.execute(
                    "INSERT INTO jobs(id,project_id,review_id,operation,priority,status,payload_json,created_at,source,scheduled_for,last_activity_at) "
                    "VALUES(?,?,?,?,?,'queued',?,?,?,?,?)",
                    (job_id, project_id, review_id, operation, priority, json.dumps(payload or {}), now, source, scheduled_for, now),
                )
            except sqlite3.IntegrityError:
                existing = conn.execute(
                    "SELECT id FROM jobs WHERE project_id=? AND ((operation='review' AND status IN ('queued','running')) OR (source='schedule' AND scheduled_for=?)) ORDER BY created_at LIMIT 1",
                    (project_id, scheduled_for),
                ).fetchone()
                if existing:
                    return existing[0]
                raise
            if source == "schedule" and project_id:
                conn.execute("UPDATE projects SET last_attempted_at=? WHERE id=?", (now, project_id))
        return job_id

    def next_job(self) -> dict[str, Any] | None:
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            now = utc_now()
            row = conn.execute(
                "UPDATE jobs SET status='running',started_at=?,stage='starting',last_activity_at=? "
                "WHERE id=(SELECT id FROM jobs WHERE status='queued' AND cancel_requested=0 ORDER BY priority,created_at LIMIT 1) "
                "AND status='queued' RETURNING *",
                (now, now),
            ).fetchone()
        return self._row(row)

    def claim_job(self, job_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            now = utc_now()
            row = conn.execute(
                "UPDATE jobs SET status='running',started_at=?,stage='starting',last_activity_at=? "
                "WHERE id=? AND status='queued' AND cancel_requested=0 RETURNING *",
                (now, now, job_id),
            ).fetchone()
        return self._row(row)

    def update_job(self, job_id: str, **fields: Any) -> None:
        allowed = {
            "status", "progress", "message", "result_json", "error", "error_code", "finished_at",
            "cancel_requested", "stage", "usage_json", "last_activity_at",
        }
        clean = {
            key: (json.dumps(value) if key in {"result_json", "usage_json"} else value)
            for key, value in fields.items() if key in allowed
        }
        if not clean:
            return
        clean.setdefault("last_activity_at", utc_now())
        with self.connect() as conn:
            conn.execute(f"UPDATE jobs SET {','.join(f'{key}=?' for key in clean)} WHERE id=?", (*clean.values(), job_id))

    def request_cancel(self, job_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise KeyError(job_id)
            if row["status"] == "queued":
                conn.execute(
                    "UPDATE jobs SET cancel_requested=1,status='cancelled',stage='cancelled',message='Cancelled',finished_at=?,last_activity_at=? WHERE id=?",
                    (utc_now(), utc_now(), job_id),
                )
            elif row["status"] == "running":
                conn.execute(
                    "UPDATE jobs SET cancel_requested=1,message='Cancellation requested',last_activity_at=? WHERE id=?",
                    (utc_now(), job_id),
                )
        return self.get_job(job_id)

    def recover_abandoned_jobs(self) -> int:
        now = utc_now()
        with self.connect() as conn:
            cursor = conn.execute(
                "UPDATE jobs SET status='failed',stage='interrupted',message='Interrupted by application exit',"
                "error='The owning worker stopped before this job completed',error_code='interrupted',finished_at=?,last_activity_at=? "
                "WHERE status='running'",
                (now, now),
            )
        return cursor.rowcount

    def fail_job(self, job_id: str, *, error: str, error_code: str = "execution_failed") -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT project_id,source,status FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row or row["status"] not in {"queued", "running"}:
                return
            conn.execute(
                "UPDATE jobs SET status='failed',stage='failed',message='Failed',error=?,error_code=?,finished_at=?,last_activity_at=? WHERE id=?",
                (error, error_code, now, now, job_id),
            )
            if row["source"] == "schedule" and row["project_id"]:
                conn.execute("UPDATE projects SET schedule_error=? WHERE id=?", (error_code, row["project_id"]))

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        result = self._row(row)
        if not result:
            raise KeyError(job_id)
        start = result.get("started_at") or result["created_at"]
        end = result.get("finished_at") or utc_now()
        try:
            result["elapsed_seconds"] = max(0, int((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()))
        except (ValueError, TypeError):
            result["elapsed_seconds"] = None
        result["cancellation_state"] = (
            "cancelled" if result["status"] == "cancelled" else
            "requested" if result["cancel_requested"] else "none"
        )
        return result

    def create_plan(
        self, review_id: str, finding_id: str, draft: dict, draft_hash: str,
        validation: dict, provider: dict, *, parent_id: str | None = None,
        job_id: str | None = None,
    ) -> str:
        plan_id = uuid.uuid4().hex
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO improvement_plans(id,review_id,finding_id,parent_id,job_id,created_at,status,draft_json,draft_hash,validation_json,provider_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (plan_id, review_id, finding_id, parent_id, job_id, utc_now(),
                 "ready" if validation.get("valid") else "needs_revision", json.dumps(draft),
                 draft_hash, json.dumps(validation), json.dumps(provider)),
            )
        return plan_id

    def get_plan(self, plan_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM improvement_plans WHERE id=?", (plan_id,)).fetchone()
        result = self._row(row)
        if not result:
            raise KeyError(plan_id)
        return result

    def list_plans(self, review_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM improvement_plans WHERE review_id=? ORDER BY created_at DESC", (review_id,)).fetchall()
        return [self._row(row) for row in rows]

    def publish_plan_receipt(self, plan_id: str, draft_hash: str, receipt: dict) -> dict[str, Any]:
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT status,draft_hash,receipt_json FROM improvement_plans WHERE id=?", (plan_id,)).fetchone()
            if not row:
                raise KeyError(plan_id)
            if row["draft_hash"] != draft_hash:
                raise ValueError("Displayed plan revision no longer matches")
            if row["status"] not in {"ready", "published"}:
                raise ValueError("Only validated plans may be saved")
            previous = json.loads(row["receipt_json"])
            if previous and previous != receipt:
                raise ValueError("This plan was already saved elsewhere")
            conn.execute("UPDATE improvement_plans SET status='published',receipt_json=? WHERE id=?", (json.dumps(receipt), plan_id))
        return receipt

    def get_app_settings(self) -> dict[str, Any]:
        with self.connect() as conn:
            rows = conn.execute("SELECT key,value_json FROM settings ORDER BY key").fetchall()
        return {row["key"]: json.loads(row["value_json"]) for row in rows}

    def update_app_settings(self, values: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            for key, value in values.items():
                conn.execute(
                    "INSERT INTO settings(key,value_json) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                    (key, json.dumps(value)),
                )
        return self.get_app_settings()

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        citations: list | None = None,
        *,
        status: str = "complete",
        learning_context: dict | None = None,
    ) -> str:
        message_id = uuid.uuid4().hex
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO messages(id,conversation_id,role,content,citations_json,created_at,status,learning_context_json) VALUES(?,?,?,?,?,?,?,?)",
                (message_id, conversation_id, role, content, json.dumps(citations or []), utc_now(), status, json.dumps(learning_context or {})),
            )
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

    def save_quiz_answer(self, review_id: str, question_id: str, selected_index: int | None, correct: bool, *, request_id: str | None = None, mode: str = 'quiz', outcome: str = 'answered') -> dict[str, Any]:
        if outcome not in {'answered','not_sure'} or (outcome == 'answered') != (selected_index is not None) or (selected_index is not None and not 0 <= selected_index <= 3):
            raise ValueError('Invalid practice outcome or option')
        # Legacy columns are NOT NULL; -1 is storage-only and never an option index.
        index = -1 if selected_index is None else selected_index
        correct = bool(correct) and outcome == 'answered'
        answered_at = utc_now()
        request_id = request_id or uuid.uuid4().hex
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            if conn.execute("SELECT 1 FROM learning_issues WHERE review_id=? AND kind='quiz' AND target_id=? AND resolved_at IS NULL",(review_id,question_id)).fetchone():
                raise ValueError('This question is paused for correction')
            prior = conn.execute('SELECT * FROM quiz_attempts WHERE request_id=?', (request_id,)).fetchone()
            if prior:
                if (prior['review_id'], prior['question_id'], prior['selected_index'], prior['kind'] == 'revision', prior['outcome']) != (review_id, question_id, index, mode == 'revision', outcome):
                    raise ValueError('Submission key already belongs to another answer')
                return {'question_id': question_id, 'selected_index': selected_index, 'outcome': outcome, 'correct': bool(prior['correct']), 'answered_at': prior['answered_at'], 'attempt_id': prior['id']}
            state = conn.execute('SELECT * FROM revision_state WHERE review_id=? AND question_id=?', (review_id, question_id)).fetchone()
            first = conn.execute('SELECT id FROM quiz_attempts WHERE review_id=? AND question_id=? LIMIT 1', (review_id, question_id)).fetchone() is None
            kind = 'revision' if mode == 'revision' else ('first' if first else 'retry')
            attempt_id = uuid.uuid4().hex
            conn.execute('INSERT INTO quiz_attempts(id,review_id,question_id,selected_index,correct,answered_at,kind,request_id,outcome) VALUES(?,?,?,?,?,?,?,?,?)', (attempt_id, review_id, question_id, index, correct, answered_at, kind, request_id, outcome))
            streak = state['streak'] if state else 0
            if not correct:
                streak = 0
            elif state is None or (mode == 'revision' and state['due_at'] <= answered_at):
                streak += 1
            days = min(14, 3 * 2 ** min(max(streak - 1, 0), 3)) if correct else 1
            due = (datetime.fromisoformat(answered_at) + timedelta(days=days)).isoformat()
            conn.execute('INSERT INTO revision_state VALUES(?,?,?,?) ON CONFLICT(review_id,question_id) DO UPDATE SET due_at=excluded.due_at,streak=excluded.streak', (review_id, question_id, due, streak))
            conn.execute(
                "INSERT INTO quiz_answers(review_id,question_id,selected_index,correct,answered_at,outcome) VALUES(?,?,?,?,?,?) ON CONFLICT(review_id,question_id) DO UPDATE SET selected_index=excluded.selected_index,correct=excluded.correct,answered_at=excluded.answered_at,outcome=excluded.outcome",
                (review_id, question_id, index, int(correct), answered_at, outcome),
            )
        return {"question_id": question_id, "selected_index": selected_index, "outcome": outcome, "correct": correct, "answered_at": answered_at, 'attempt_id': attempt_id}

    def quiz_attempts(self, review_id: str, question_id: str | None = None) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute('SELECT * FROM quiz_attempts WHERE review_id=? AND (? IS NULL OR question_id=?) ORDER BY answered_at,rowid', (review_id, question_id, question_id)).fetchall()
        return [{**dict(row), 'selected_index': None if row['outcome'] == 'not_sure' else row['selected_index']} for row in rows]

    def learning_records(self) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute("""
                SELECT r.id AS review_id,r.project_id,r.created_at,r.critique_json,p.name AS project_name,
                       q.question_id,q.due_at,q.streak,n.content AS note,a.attempt_count,a.first_correct,a.first_outcome
                FROM revision_state q JOIN reviews r ON r.id=q.review_id JOIN projects p ON p.id=r.project_id
                LEFT JOIN (SELECT review_id,question_id,COUNT(*) AS attempt_count,
                                  MAX(CASE WHEN kind='first' THEN correct END) AS first_correct,
                                  MAX(CASE WHEN kind='first' THEN outcome END) AS first_outcome
                           FROM quiz_attempts GROUP BY review_id,question_id) a
                  ON a.review_id=q.review_id AND a.question_id=q.question_id
                LEFT JOIN learning_notes n ON n.review_id=q.review_id AND n.question_id=q.question_id
                WHERE NOT EXISTS (SELECT 1 FROM learning_issues i WHERE i.review_id=q.review_id AND i.kind='quiz' AND i.target_id=q.question_id AND i.resolved_at IS NULL)
                ORDER BY q.due_at,r.id,q.question_id LIMIT 200
            """).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            question = next((q for q in json.loads(item.pop('critique_json')).get('quiz', []) if q['id'] == item['question_id']), None)
            if question:
                item['question'] = question
                result.append(item)
        return result

    def save_learning_note(self, review_id: str, question_id: str, content: str) -> None:
        with self.connect() as conn:
            conn.execute('INSERT INTO learning_notes VALUES(?,?,?,?) ON CONFLICT(review_id,question_id) DO UPDATE SET content=excluded.content,updated_at=excluded.updated_at', (review_id, question_id, content, utc_now()))

    def record_plan_learning(self, plan_id: str, review_id: str, note: str) -> None:
        with self.connect() as conn:
            conn.execute('INSERT INTO plan_learning_reports(id,plan_id,review_id,created_at,note) VALUES(?,?,?,?,?)', (uuid.uuid4().hex, plan_id, review_id, utc_now(), note))

    def get_learning_walkthrough(self, review_id: str, version: int = 2) -> dict | None:
        with self.connect() as conn:
            row = conn.execute('SELECT model_json FROM learning_walkthroughs WHERE review_id=? AND format_version=?', (review_id, version)).fetchone()
        return json.loads(row['model_json']) if row else None

    def save_learning_walkthrough(self, review_id: str, model: dict) -> dict:
        with self.connect() as conn:
            conn.execute('INSERT OR IGNORE INTO learning_walkthroughs VALUES(?,?,?)', (review_id, model['format_version'], json.dumps(model)))
        return self.get_learning_walkthrough(review_id, model['format_version'])

    def plan_learning_reports(self, plan_id: str) -> list[dict]:
        with self.connect() as conn:
            return [dict(row) for row in conn.execute('SELECT * FROM plan_learning_reports WHERE plan_id=? ORDER BY created_at DESC,id', (plan_id,))]

    def quiz_answers(self, review_id: str) -> dict[str, dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM quiz_answers WHERE review_id=?", (review_id,)).fetchall()
        return {
            row["question_id"]: {
                "selected_index": row["selected_index"], "correct": bool(row["correct"]),
                "outcome": row['outcome'],
                "answered_at": row["answered_at"],
            }
            for row in rows
        }

    def learning_session(self, review_id: str) -> dict:
        with self.connect() as conn:
            row = conn.execute('SELECT * FROM learning_sessions WHERE review_id=?', (review_id,)).fetchone()
        return {**json.loads(row['state_json']), 'updated_at': row['updated_at']} if row else {}

    def learning_sessions(self) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute('SELECT s.*,p.name AS project_name FROM learning_sessions s JOIN reviews r ON r.id=s.review_id JOIN projects p ON p.id=r.project_id ORDER BY s.updated_at DESC').fetchall()
        return [{**dict(row), 'state':json.loads(row['state_json'])} for row in rows]

    def save_learning_session(self, review_id: str, changes: dict) -> dict:
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT state_json FROM learning_sessions WHERE review_id=?', (review_id,)).fetchone()
            state = {**(json.loads(row['state_json']) if row else {}), **changes}
            stamp = utc_now()
            conn.execute('INSERT INTO learning_sessions(review_id,state_json,updated_at) VALUES(?,?,?) ON CONFLICT(review_id) DO UPDATE SET state_json=excluded.state_json,updated_at=excluded.updated_at', (review_id, json.dumps(state), stamp))
        return {**state, 'updated_at': stamp}

    def learning_issues(self, review_id: str) -> list[dict]:
        with self.connect() as conn:
            return [dict(row) for row in conn.execute('SELECT * FROM learning_issues WHERE review_id=? ORDER BY created_at', (review_id,))]

    def flag_learning_issue(self, review_id: str, kind: str, target_id: str, note: str) -> str:
        identifier = uuid.uuid4().hex
        with self.connect() as conn:
            conn.execute('INSERT INTO learning_issues VALUES(?,?,?,?,?,?,NULL)', (identifier, review_id, kind, target_id, note, utc_now()))
        return identifier

    def resolve_learning_issue(self, review_id: str, identifier: str) -> None:
        with self.connect() as conn:
            if not conn.execute('UPDATE learning_issues SET resolved_at=? WHERE review_id=? AND id=? AND resolved_at IS NULL', (utc_now(), review_id, identifier)).rowcount:
                raise KeyError(identifier)

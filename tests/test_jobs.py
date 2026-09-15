from __future__ import annotations

import threading
import time
import json
import os
import subprocess
import sys
from pathlib import Path

from archcoach.ai import CodexError
from archcoach.config import Settings
from archcoach.db import Store
from archcoach.models import ProjectCreate
from archcoach.ownership import DataDirectoryLock
from archcoach.review import ReviewEngine
from archcoach.worker import Worker
from archcoach.subprocesses import process_group_options, terminate_process_tree


def make_store(tmp_path: Path) -> tuple[Store, dict]:
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.py").write_text("value = 1\n", encoding="utf-8")
    store = Store(tmp_path / "data" / "archcoach.db")
    return store, store.add_project(ProjectCreate(path=str(source)))


def test_data_directory_lock_is_exclusive(tmp_path: Path):
    first = DataDirectoryLock(tmp_path / "data")
    second = DataDirectoryLock(tmp_path / "data")
    assert first.acquire() is True
    assert second.acquire() is False
    first.release()
    assert second.acquire() is True
    second.release()


def test_opening_store_does_not_recover_active_jobs(tmp_path: Path):
    store, project = make_store(tmp_path)
    job_id = store.enqueue("review", project["id"])
    assert store.claim_job(job_id)["status"] == "running"

    Store(store.path)

    assert store.get_job(job_id)["status"] == "running"


def test_second_worker_cannot_recover_or_claim_active_job(tmp_path: Path):
    store, project = make_store(tmp_path)
    owner = DataDirectoryLock(store.path.parent)
    assert owner.acquire() is True
    job_id = store.enqueue("review", project["id"])
    assert store.claim_job(job_id)["status"] == "running"

    second = Worker(store, object())
    assert second.start() is False

    assert store.get_job(job_id)["status"] == "running"
    owner.release()


def test_concurrent_review_requests_share_one_active_job(tmp_path: Path):
    store, project = make_store(tmp_path)
    barrier = threading.Barrier(8)
    results: list[str] = []

    def enqueue() -> None:
        barrier.wait()
        results.append(store.enqueue("review", project["id"]))

    threads = [threading.Thread(target=enqueue) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(set(results)) == 1


def test_chat_jobs_have_priority_after_current_work(tmp_path: Path):
    store, first = make_store(tmp_path)
    other_source = tmp_path / "other"
    other_source.mkdir()
    (other_source / "other.py").write_text("value = 2\n")
    second = store.add_project(ProjectCreate(path=str(other_source)))
    review_job = store.enqueue("review", first["id"], priority=10)
    chat_job = store.enqueue("chat", None, {"message": "hello"}, priority=1)
    store.enqueue("review", second["id"], priority=10)

    assert store.next_job()["id"] == chat_job
    assert store.next_job()["id"] == review_job


class BlockingCodex:
    def __init__(self):
        self.started = threading.Event()
        self.released = threading.Event()
        self.calls = 0

    def run_structured(self, *_args, **_kwargs):
        self.calls += 1
        self.started.set()
        self.released.wait(5)
        raise CodexError("cancelled fixture")

    def cancel(self):
        self.released.set()


def test_cancellation_prevents_review_publication_and_schedule_advance(tmp_path: Path):
    store, project = make_store(tmp_path)
    settings = Settings(data_dir=tmp_path / "data", app_dir=Path(__file__).parents[1] / "src" / "archcoach")
    codex = BlockingCodex()
    engine = ReviewEngine(settings, store, codex)
    job_id = store.enqueue("review", project["id"])
    worker = Worker(store, engine, only_job_id=job_id)
    assert worker.start() is True
    assert codex.started.wait(5)

    store.request_cancel(job_id)
    codex.cancel()
    worker.thread.join(5)
    worker.stop()

    assert store.get_job(job_id)["status"] == "cancelled"
    assert store.list_reviews(project["id"]) == []
    assert store.get_project(project["id"])["last_checked_at"] is None
    assert codex.calls == 1


def test_scheduler_records_one_occurrence_and_pauses_after_failure(tmp_path: Path):
    store, project = make_store(tmp_path)
    lock = DataDirectoryLock(store.path.parent)
    assert lock.acquire()
    worker = Worker(store, object())
    worker.owns_queue = True
    worker.queue_due_reviews()
    worker.queue_due_reviews()
    jobs = [store.get_job(row["id"]) for row in [store.next_job()]]
    assert len(jobs) == 1
    job = jobs[0]
    assert job["source"] == "schedule"
    store.fail_job(job["id"], error="login expired", error_code="authentication")
    worker.queue_due_reviews()
    assert store.get_project(project["id"])["schedule_error"] == "authentication"
    assert store.next_job() is None
    lock.release()


def test_disabling_schedule_cancels_only_queued_scheduled_work(tmp_path: Path):
    store, project = make_store(tmp_path)
    scheduled = store.enqueue("review", project["id"], source="schedule", scheduled_for="2026-01-01")
    store.update_project(project["id"], enabled=False)

    assert store.get_job(scheduled)["status"] == "cancelled"


def test_cancellation_terminates_subprocess_tree():
    fixture = Path(__file__).parent / "fixtures" / "fake_codex.py"
    env = os.environ.copy()
    env["FAKE_CODEX_MODE"] = "spawn_child"
    process = subprocess.Popen(
        [sys.executable, str(fixture), "exec"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=env, **process_group_options(),
    )
    child_pid = json.loads(process.stdout.readline())["pid"]

    terminate_process_tree(process)

    assert process.poll() is not None
    if os.name == "nt":
        listing = subprocess.run(
            ["tasklist", "/FI", f"PID eq {child_pid}", "/FO", "CSV"],
            capture_output=True, text=True, timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        assert str(child_pid) not in listing.stdout

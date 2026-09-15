from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

from .db import Store
from .models import utc_now
from .ownership import DataDirectoryLock
from .review import ReviewCancelled, ReviewEngine


class Worker:
    def __init__(self, store: Store, engine: ReviewEngine, *, only_job_id: str | None = None):
        self.store, self.engine = store, engine
        self.only_job_id = only_job_id
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name="archcoach-worker", daemon=True)
        self.scheduler = threading.Thread(target=self._schedule, name="archcoach-scheduler", daemon=True)
        self.lock = DataDirectoryLock(store.path.parent)
        self.owns_queue = False

    def start(self) -> bool:
        if not self.lock.acquire():
            return False
        self.owns_queue = True
        self.store.recover_abandoned_jobs()
        if not self.only_job_id:
            self.queue_due_reviews()
        self.thread.start()
        if not self.only_job_id:
            self.scheduler.start()
        return True

    def stop(self) -> None:
        if not self.owns_queue:
            return
        self.stop_event.set()
        self.engine.codex.cancel()
        self.thread.join(timeout=5)
        if self.scheduler.ident is not None:
            self.scheduler.join(timeout=5)
        self.lock.release()
        self.owns_queue = False

    def _cancelled(self, job_id: str) -> bool:
        if self.stop_event.is_set():
            return True
        try:
            return bool(self.store.get_job(job_id)["cancel_requested"])
        except KeyError:
            return True

    def _progress(self, job_id: str, progress: int, message: str, stage: str | None = None) -> None:
        fields = {"progress": progress, "message": message, "last_activity_at": utc_now()}
        if stage:
            fields["stage"] = stage
        self.store.update_job(job_id, **fields)

    def _run(self) -> None:
        while not self.stop_event.is_set():
            job = self.store.claim_job(self.only_job_id) if self.only_job_id else self.store.next_job()
            if not job:
                if self.only_job_id:
                    return
                self.stop_event.wait(0.25)
                continue
            try:
                cancelled = lambda: self._cancelled(job["id"])
                if job["operation"] == "review":
                    self.engine.run(
                        job["project_id"],
                        lambda value, message: self._progress(job["id"], value, message),
                        cancelled=cancelled,
                        job_id=job["id"],
                        force=bool(job["payload"].get("force")),
                    )
                elif job["operation"] == "chat":
                    conversation_id = self.engine.chat(
                        job["review_id"], job["payload"]["message"], cancelled=cancelled,
                    )
                    if cancelled():
                        raise ReviewCancelled("Chat cancelled")
                    self.store.update_job(
                        job["id"], status="complete", stage="complete", progress=100,
                        message="Complete", result_json={"conversation_id": conversation_id},
                        finished_at=utc_now(),
                    )
                else:
                    raise ValueError(f"Unknown job operation: {job['operation']}")
            except ReviewCancelled:
                self.store.update_job(
                    job["id"], status="cancelled", stage="cancelled", message="Cancelled",
                    finished_at=utc_now(),
                )
            except Exception as exc:
                if self._cancelled(job["id"]):
                    self.store.update_job(
                        job["id"], status="cancelled", stage="cancelled", message="Cancelled",
                        finished_at=utc_now(),
                    )
                else:
                    self.store.fail_job(job["id"], error=str(exc))
            if self.only_job_id:
                return

    def _schedule(self) -> None:
        while not self.stop_event.wait(300):
            self.queue_due_reviews()

    def queue_due_reviews(self) -> None:
        if not self.owns_queue:
            return
        now = datetime.now(timezone.utc)
        for project in self.store.list_projects():
            if not project["enabled"] or project.get("schedule_error"):
                continue
            checked = datetime.fromisoformat(project["last_checked_at"]) if project["last_checked_at"] else None
            attempted = datetime.fromisoformat(project["last_attempted_at"]) if project.get("last_attempted_at") else None
            anchor = checked or datetime.fromisoformat(project["created_at"])
            due = anchor + timedelta(days=project["interval_days"])
            if checked is None:
                due = anchor
            if now >= due and (attempted is None or attempted < due):
                self.store.enqueue(
                    "review", project["id"], priority=20, source="schedule",
                    scheduled_for=due.isoformat(),
                )

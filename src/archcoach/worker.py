from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone

from .db import Store
from .models import utc_now
from .review import ReviewEngine


class Worker:
    def __init__(self, store: Store, engine: ReviewEngine):
        self.store, self.engine = store, engine
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name="archcoach-worker", daemon=True)
        self.scheduler = threading.Thread(target=self._schedule, name="archcoach-scheduler", daemon=True)

    def start(self) -> None:
        self.queue_due_reviews()
        self.thread.start(); self.scheduler.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.engine.codex.cancel()
        self.thread.join(timeout=5); self.scheduler.join(timeout=5)

    def _run(self) -> None:
        while not self.stop_event.is_set():
            job = self.store.next_job()
            if not job:
                self.stop_event.wait(0.5); continue
            try:
                if job["operation"] == "review":
                    review_id = self.engine.run(job["project_id"], lambda p, m: self.store.update_job(job["id"], progress=p, message=m))
                    if self.store.get_job(job["id"])["cancel_requested"]:
                        self.store.update_job(job["id"], status="cancelled", message="Cancelled", finished_at=utc_now())
                    else:
                        self.store.update_job(job["id"], status="complete", progress=100, message="Complete", result_json={"review_id": review_id}, finished_at=utc_now())
                elif job["operation"] == "chat":
                    conversation_id = self.engine.chat(job["review_id"], job["payload"]["message"])
                    self.store.update_job(job["id"], status="complete", progress=100, result_json={"conversation_id": conversation_id}, finished_at=utc_now())
                else:
                    raise ValueError(f"Unknown job operation: {job['operation']}")
            except Exception as exc:
                if self.store.get_job(job["id"])["cancel_requested"]:
                    self.store.update_job(job["id"], status="cancelled", message="Cancelled", finished_at=utc_now())
                else:
                    self.store.update_job(job["id"], status="failed", error=str(exc), message="Failed", finished_at=utc_now())

    def _schedule(self) -> None:
        while not self.stop_event.wait(300):
            self.queue_due_reviews()

    def queue_due_reviews(self) -> None:
        now = datetime.now(timezone.utc)
        for project in self.store.list_projects():
            if not project["enabled"]:
                continue
            last = datetime.fromisoformat(project["last_checked_at"]) if project["last_checked_at"] else None
            if last is None or now >= last + timedelta(days=project["interval_days"]):
                self.store.enqueue("review", project["id"], priority=20)

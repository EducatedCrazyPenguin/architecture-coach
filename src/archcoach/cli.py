from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn

from .ai import CodexAdapter
from .app import create_app
from .config import Settings
from .db import Store
from .models import ProjectCreate
from .review import ReviewEngine
from .worker import Worker
from .diagram import find_node


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="archcoach", description="Local architecture learning coach")
    parser.add_argument("--data-dir", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    serve = sub.add_parser("serve"); serve.add_argument("--no-browser", action="store_true"); serve.add_argument("--port", type=int, default=8765)
    add = sub.add_parser("add"); add.add_argument("path"); add.add_argument("--name"); add.add_argument("--description", default=""); add.add_argument("--goal", default="")
    review = sub.add_parser("review"); review.add_argument("project"); review.add_argument("--force", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv); settings = Settings.load(args.data_dir); settings.ensure_dirs(); store = Store(settings.db_path)
    if args.command == "doctor":
        codex = CodexAdapter(settings); checks = {"data_directory": str(settings.data_dir), "data_writable": settings.data_dir.exists(), "codex": codex.status(), "node": find_node(), "archify": settings.archify_cli.exists(), "htmx": (settings.app_dir.parent.parent / "node_modules" / "htmx.org" / "dist" / "htmx.min.js").exists()}
        print(json.dumps(checks, indent=2)); return 0 if checks["data_writable"] else 1
    if args.command == "add":
        project = store.add_project(ProjectCreate(path=args.path, name=args.name, description=args.description, goal=args.goal)); print(f"Added {project['name']} ({project['id']})"); return 0
    if args.command == "review":
        projects = store.list_projects(); matches = [p for p in projects if p["id"] == args.project or p["name"].lower() == args.project.lower()]
        if not matches: print("Project not found", file=sys.stderr); return 2
        job_id = store.enqueue("review", matches[0]["id"], {"force": args.force}, priority=10)
        worker = Worker(store, ReviewEngine(settings, store), only_job_id=job_id)
        owns_queue = worker.start()
        last = None
        try:
            while True:
                job = store.get_job(job_id)
                state = (job["progress"], job["message"])
                if state != last:
                    print(f"{job['progress']:3}% {job['message']}")
                    last = state
                if job["status"] in {"complete", "failed", "cancelled"}:
                    break
                time.sleep(0.2)
        except KeyboardInterrupt:
            store.request_cancel(job_id)
            if owns_queue:
                worker.engine.codex.cancel()
            print("Cancellation requested", file=sys.stderr)
            return 130
        finally:
            if owns_queue:
                worker.stop()
        if job["status"] == "complete":
            print(f"Review complete: {job['result'].get('review_id')}")
            return 0
        print(job.get("error") or job["message"], file=sys.stderr)
        return 130 if job["status"] == "cancelled" else 1
    if args.command == "serve":
        settings = Settings(data_dir=settings.data_dir, app_dir=settings.app_dir, port=args.port)
        app = create_app(settings)
        if not args.no_browser: threading.Timer(1, lambda: webbrowser.open(f"http://127.0.0.1:{args.port}")).start()
        config = uvicorn.Config(app, host=settings.host, port=args.port, log_level="info"); server = uvicorn.Server(config)
        def watch(): app.state.shutdown_event.wait(); server.should_exit = True
        threading.Thread(target=watch, daemon=True).start(); server.run(); return 0
    return 2


if __name__ == "__main__": raise SystemExit(main())

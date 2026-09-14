from __future__ import annotations

import html
import json
import secrets
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .ai import CodexAdapter
from .config import Settings
from .db import Store
from .models import ChatRequest, LessonStatusRequest, ProjectCreate
from .review import ReviewEngine, source_text
from .worker import Worker


def create_app(settings: Settings | None = None, start_worker: bool = True) -> FastAPI:
    settings = settings or Settings.load(); settings.ensure_dirs()
    store = Store(settings.db_path); codex = CodexAdapter(settings); engine = ReviewEngine(settings, store, codex); worker = Worker(store, engine)
    templates = Jinja2Templates(directory=str(settings.app_dir / "templates"))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if start_worker: worker.start()
        yield
        if start_worker: worker.stop()

    app = FastAPI(title="Architecture Coach", lifespan=lifespan)
    app.state.settings = settings; app.state.store = store; app.state.worker = worker; app.state.shutdown_event = threading.Event(); app.state.csrf_token = secrets.token_urlsafe(24)
    app.mount("/static", StaticFiles(directory=str(settings.app_dir / "static")), name="static")
    htmx_dir = settings.app_dir.parent.parent / "node_modules" / "htmx.org" / "dist"
    if htmx_dir.exists():
        app.mount("/vendor", StaticFiles(directory=str(htmx_dir)), name="vendor")

    def context(request: Request, **extra):
        projects = store.list_projects()
        for project in projects:
            project["latest_review"] = store.latest_review(project["id"])
            if project["last_checked_at"]:
                project["next_review"] = (datetime.fromisoformat(project["last_checked_at"]) + timedelta(days=project["interval_days"])).strftime("%d %b %Y")
            else: project["next_review"] = "Due now"
        return {"request": request, "projects": projects, "csrf_token": app.state.csrf_token, **extra}

    def require_local(request: Request):
        host = request.client.host if request.client else ""
        if host not in {"127.0.0.1", "::1", "testclient"}: raise HTTPException(403, "Local access only")
        if request.method not in {"GET", "HEAD"}:
            token = request.headers.get("x-archcoach-token") or request.query_params.get("token")
            if token != app.state.csrf_token: raise HTTPException(403, "Invalid local request token")

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request):
        return templates.TemplateResponse(request=request, name="dashboard.html", context=context(request, page="projects", codex=codex.status()))

    @app.get("/projects/{project_id}", response_class=HTMLResponse)
    def project_page(project_id: str, request: Request):
        try: project = store.get_project(project_id)
        except KeyError: raise HTTPException(404)
        reviews = store.list_reviews(project_id); selected = reviews[0] if reviews else None
        return templates.TemplateResponse(request=request, name="project.html", context=context(request, page="project", project=project, reviews=reviews, review=selected))

    @app.get("/reviews/{review_id}", response_class=HTMLResponse)
    def review_page(review_id: str, request: Request):
        try:
            review = store.get_review(review_id); project = store.get_project(review["project_id"]); snapshot = store.get_snapshot(review["snapshot_id"])
        except KeyError: raise HTTPException(404)
        conversation = store.conversation_for_review(review_id)
        current = __import__("archcoach.capture", fromlist=["capture_project"]).capture_project(settings, project)
        stale = current["fingerprint"] != snapshot["fingerprint"]
        return templates.TemplateResponse(request=request, name="review.html", context=context(request, page="review", project=project, review=review, snapshot=snapshot, lesson_statuses=store.lesson_statuses(review_id), conversation=conversation, stale=stale))

    @app.post("/projects")
    def add_project(request: Request, path: str = Form(), name: str = Form(default=""), description: str = Form(default=""), goal: str = Form(default="")):
        require_local(request)
        try: project = store.add_project(ProjectCreate(path=path, name=name or None, description=description, goal=goal))
        except ValueError as exc: return RedirectResponse(url=f"/?error={str(exc)}", status_code=303)
        return RedirectResponse(url=f"/projects/{project['id']}", status_code=303)

    @app.post("/projects/{project_id}/review")
    def start_review(project_id: str, request: Request):
        require_local(request)
        try: store.get_project(project_id)
        except KeyError: raise HTTPException(404)
        job_id = store.enqueue("review", project_id, priority=10)
        return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)

    @app.get("/jobs/{job_id}", response_class=HTMLResponse)
    def job_page(job_id: str, request: Request):
        try: job = store.get_job(job_id)
        except KeyError: raise HTTPException(404)
        if request.headers.get("HX-Request"):
            return templates.TemplateResponse(request=request, name="_job.html", context={"request": request, "job": job, "csrf_token": app.state.csrf_token})
        return templates.TemplateResponse(request=request, name="job.html", context=context(request, page="job", job=job))

    @app.post("/jobs/{job_id}/cancel")
    def cancel_job(job_id: str, request: Request):
        require_local(request)
        try: job = store.get_job(job_id)
        except KeyError: raise HTTPException(404)
        store.update_job(job_id, cancel_requested=1, message="Cancellation requested")
        if job["status"] == "queued": store.update_job(job_id, status="cancelled", finished_at=datetime.now().astimezone().isoformat())
        elif job["status"] == "running": codex.cancel()
        return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)

    @app.post("/reviews/{review_id}/chat")
    def chat(review_id: str, request: Request, message: str = Form()):
        require_local(request)
        try: store.get_review(review_id)
        except KeyError: raise HTTPException(404)
        job_id = store.enqueue("chat", None, {"message": message}, review_id=review_id, priority=1)
        return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)

    @app.post("/reviews/{review_id}/lessons/{lesson_id}")
    async def lesson_status(review_id: str, lesson_id: str, request: Request):
        require_local(request); data = LessonStatusRequest.model_validate(await request.json())
        store.set_lesson_status(review_id, lesson_id, data.status)
        return {"ok": True}

    @app.get("/reviews/{review_id}/source")
    def evidence_source(review_id: str, path: str, line: int = 1):
        try:
            review = store.get_review(review_id); snapshot = store.get_snapshot(review["snapshot_id"]); content = source_text(settings, snapshot, path)
        except KeyError: raise HTTPException(404)
        numbered = "\n".join(f"{i:5}  {html.escape(text)}" for i, text in enumerate(content.splitlines(), 1))
        return HTMLResponse(f"<!doctype html><title>{html.escape(path)}</title><style>body{{font:14px ui-monospace;background:#fafbfe;color:#182033;padding:24px}}pre{{white-space:pre-wrap}}mark{{background:#fff0a8}}</style><h1>{html.escape(path)}</h1><pre>{numbered}</pre>")

    @app.get("/artifacts/{review_id}/{name}")
    def artifact(review_id: str, name: str):
        review = store.get_review(review_id)
        key = {"diagram": "diagram", "comparison": "comparison", "report": "report"}.get(name)
        if not key or not review["artifacts"].get(key): raise HTTPException(404)
        target = Path(review["artifacts"][key]).resolve(); target.relative_to(settings.artifact_dir.resolve())
        return FileResponse(target)

    @app.get("/api/projects")
    def api_projects(): return store.list_projects()

    @app.post("/api/projects", status_code=201)
    def api_add_project(data: ProjectCreate, request: Request): require_local(request); return store.add_project(data)

    @app.post("/api/projects/{project_id}/reviews", status_code=202)
    def api_review(project_id: str, request: Request): require_local(request); return {"job_id": store.enqueue("review", project_id)}

    @app.get("/api/jobs/{job_id}")
    def api_job(job_id: str): return store.get_job(job_id)

    @app.post("/api/reviews/{review_id}/chat", status_code=202)
    def api_chat(review_id: str, data: ChatRequest, request: Request): require_local(request); return {"job_id": store.enqueue("chat", None, data.model_dump(), review_id=review_id, priority=1)}

    @app.post("/exit")
    def exit_app(request: Request): require_local(request); app.state.shutdown_event.set(); return HTMLResponse("Architecture Coach is shutting down. You can close this tab.")

    return app

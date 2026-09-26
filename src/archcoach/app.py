from __future__ import annotations

import html
import json
import secrets
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, Form, HTTPException, Request
from pydantic import ValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .ai import CodexAdapter, create_adapter
from .config import Settings, merge_saved_settings
from .db import Store
from .diagram import render_selected_comparison
from .models import AppSettingsUpdate, ChatRequest, ImprovementPlanDraft, LessonStatusRequest, PlanApproval, PlanRequest, ProjectCreate, ProjectUpdate, QuizAnswerRequest
from .plans import PlanConflict, PlanError, PlanService, download_zip, plan_files
from .capture import CaptureError, fingerprint_project
from .review import ReviewEngine, compare_saved_reviews, source_text, validate_comparison_records
from .worker import Worker


def create_app(settings: Settings | None = None, start_worker: bool = True) -> FastAPI:
    settings = settings or Settings.load(); settings.ensure_dirs()
    store = Store(settings.db_path)
    saved_settings = store.get_app_settings()
    allowed_setting_keys = set(AppSettingsUpdate.model_fields)
    settings = merge_saved_settings(settings, saved_settings)
    settings.ensure_dirs()
    codex = create_adapter(settings); engine = ReviewEngine(settings, store, codex); worker = Worker(store, engine)
    templates = Jinja2Templates(directory=str(settings.app_dir / "templates"))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if start_worker: worker.start()
        yield
        if start_worker: worker.stop()

    app = FastAPI(title="Architecture Coach", lifespan=lifespan)
    app.state.settings = settings; app.state.store = store; app.state.worker = worker; app.state.shutdown_event = threading.Event(); app.state.csrf_token = secrets.token_urlsafe(24)
    diagnostics_lock = threading.Lock()
    diagnostics_cache: dict = {"at": 0.0, "value": None}

    def codex_status(refresh: bool = False) -> dict:
        with diagnostics_lock:
            if refresh or diagnostics_cache["value"] is None or time.monotonic() - diagnostics_cache["at"] > 30:
                diagnostics_cache["value"] = codex.status()
                diagnostics_cache["at"] = time.monotonic()
            return diagnostics_cache["value"]

    allowed_hosts = {
        f"127.0.0.1:{settings.port}", f"localhost:{settings.port}", f"[::1]:{settings.port}",
    }
    if not start_worker:
        allowed_hosts.add("testserver")

    @app.middleware("http")
    async def protect_local_origin(request: Request, call_next):
        client = request.client.host if request.client else ""
        allowed_clients = {"127.0.0.1", "::1"} | ({"testclient"} if not start_worker else set())
        if client not in allowed_clients:
            return JSONResponse({"detail": "Local access only"}, status_code=403)
        host = request.headers.get("host", "").lower()
        if host not in allowed_hosts:
            return JSONResponse({"detail": "Invalid Host header"}, status_code=400)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin and origin.lower() not in {f"http://{value}" for value in allowed_hosts}:
                return JSONResponse({"detail": "Cross-site mutation rejected"}, status_code=403)
        return await call_next(request)
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
            project["schedule_state"] = (
                "disabled" if not project["enabled"] else
                "paused" if project.get("schedule_error") else "active"
            )
        return {"request": request, "projects": projects, "csrf_token": app.state.csrf_token, **extra}

    def require_local(request: Request, form_token: str | None = None):
        token = request.headers.get("x-archcoach-token") or form_token
        if token != app.state.csrf_token:
            raise HTTPException(403, "Invalid local request token")

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request):
        return templates.TemplateResponse(request=request, name="dashboard.html", context=context(request, page="projects", codex=codex_status()))

    @app.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request, saved: bool = False, refresh: bool = False):
        return templates.TemplateResponse(
            request=request,
            name="settings.html",
            context=context(request, page="settings", codex=codex_status(refresh), saved=saved, data_dir=settings.data_dir, app_settings=settings),
        )

    @app.get("/projects/{project_id}", response_class=HTMLResponse)
    def project_page(project_id: str, request: Request):
        try: project = store.get_project(project_id)
        except KeyError: raise HTTPException(404)
        reviews = store.list_reviews(project_id); selected = reviews[0] if reviews else None
        return templates.TemplateResponse(request=request, name="project.html", context=context(request, page="project", project=project, reviews=reviews, history=store.list_history(project_id), review=selected))

    @app.get("/reviews/{review_id}", response_class=HTMLResponse)
    def review_page(review_id: str, request: Request):
        try:
            review = store.get_review(review_id); project = store.get_project(review["project_id"]); snapshot = store.get_snapshot(review["snapshot_id"])
        except KeyError: raise HTTPException(404)
        conversation = store.conversation_for_review(review_id)
        quiz_answers = store.quiz_answers(review_id)
        return templates.TemplateResponse(request=request, name="review.html", context=context(request, page="review", project=project, review=review, snapshot=snapshot, plans=store.list_plans(review_id), lesson_statuses=store.lesson_statuses(review_id), quiz_answers=quiz_answers, quiz_score=sum(item["correct"] for item in quiz_answers.values()), conversation=conversation, current_status="checking"))

    def enqueue_plan(review_id: str, data: PlanRequest) -> str:
        try:
            review = store.get_review(review_id)
            if data.parent_id:
                parent = store.get_plan(data.parent_id)
                if (parent["review_id"], parent["finding_id"]) != (review_id, data.finding_id):
                    raise HTTPException(409, "Revision belongs to another finding")
        except KeyError:
            raise HTTPException(404, "Review or previous plan not found")
        if review["status"] not in {"complete", "unchanged"}:
            raise HTTPException(409, "A saved completed review is required")
        if not any(item.get("id") == data.finding_id for item in review["critique"].get("findings", [])):
            raise HTTPException(404, "Finding not found in this review")
        return store.enqueue("plan", None, data.model_dump(), review_id=review_id, priority=5)

    def plan_details(plan_id: str):
        try:
            plan = store.get_plan(plan_id)
            review = store.get_review(plan["review_id"])
            project = store.get_project(review["project_id"])
        except KeyError:
            raise HTTPException(404, "Plan not found")
        return plan, review, project

    @app.get("/plans/{plan_id}", response_class=HTMLResponse)
    def plan_page(plan_id: str, request: Request, saved: bool = False):
        plan, review, project = plan_details(plan_id)
        try:
            files = plan_files(ImprovementPlanDraft.model_validate(plan["draft"]))
        except ValidationError:
            files = {}
        return templates.TemplateResponse(request=request, name="plan.html", context=context(request, page="plan", project=project, review=review, plan=plan, files=files, saved=saved))

    @app.get("/plans/{plan_id}/download")
    def plan_download(plan_id: str):
        plan, _, _ = plan_details(plan_id)
        if plan["status"] not in {"ready", "published"}:
            raise HTTPException(409, "This draft does not validate yet")
        return Response(download_zip(plan), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="openspec-plan-{plan_id[:12]}.zip"'})

    @app.post("/plans/{plan_id}/publish")
    def publish_plan(plan_id: str, request: Request, draft_hash: str = Form(), csrf: str = Form(alias="_csrf")):
        require_local(request, csrf)
        try:
            PlanService(app.state.settings, store, codex).publish(plan_id, draft_hash)
        except KeyError:
            raise HTTPException(404)
        except PlanConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except PlanError as exc:
            raise HTTPException(422, str(exc)) from exc
        return RedirectResponse(url=f"/plans/{plan_id}?saved=true", status_code=303)

    @app.post("/plans/{plan_id}/revise")
    def revise_plan(plan_id: str, request: Request, instruction: str = Form(max_length=2000), csrf: str = Form(alias="_csrf")):
        require_local(request, csrf)
        plan, _, _ = plan_details(plan_id)
        job_id = enqueue_plan(plan["review_id"], PlanRequest(finding_id=plan["finding_id"], instruction=instruction, parent_id=plan_id))
        return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)

    def comparison(project_id: str, before_id: str | None, after_id: str | None):
        project = store.get_project(project_id)
        reviews = [item for item in store.list_reviews(project_id) if item["status"] in {"complete", "unchanged"}]
        if len(reviews) < 2:
            raise HTTPException(409, "Two successful reviews are required")
        before_id = before_id or reviews[1]["id"]
        after_id = after_id or reviews[0]["id"]
        before = store.get_review(before_id); after = store.get_review(after_id)
        if before["project_id"] != project_id or after["project_id"] != project_id:
            raise HTTPException(404)
        try:
            validate_comparison_records(before, after)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        before_snapshot = store.get_snapshot(before["snapshot_id"]); after_snapshot = store.get_snapshot(after["snapshot_id"])
        return project, reviews, before, after, compare_saved_reviews(before, before_snapshot, after, after_snapshot)

    @app.get("/projects/{project_id}/compare", response_class=HTMLResponse)
    def compare_page(project_id: str, request: Request, before: str | None = None, after: str | None = None):
        try: project, reviews, before_review, after_review, changes = comparison(project_id, before, after)
        except KeyError: raise HTTPException(404)
        return templates.TemplateResponse(request=request, name="compare.html", context=context(request, page="compare", project=project, reviews=reviews, before=before_review, after=after_review, changes=changes))

    @app.get("/projects/{project_id}/comparison-artifact")
    def selected_comparison_artifact(project_id: str, before: str, after: str):
        try:
            _, _, before_review, after_review, _ = comparison(project_id, before, after)
            target = render_selected_comparison(app.state.settings, before_review, after_review)
        except KeyError:
            raise HTTPException(404)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        if not target:
            raise HTTPException(503, "Archify comparison is unavailable; the semantic comparison remains below")
        return FileResponse(target, headers={"Content-Security-Policy": "sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:"})

    @app.post("/projects")
    def add_project(request: Request, path: str = Form(), name: str = Form(default=""), description: str = Form(default=""), goal: str = Form(default=""), csrf: str = Form(alias="_csrf")):
        require_local(request, csrf)
        try: project = store.add_project(ProjectCreate(path=path, name=name or None, description=description, goal=goal))
        except ValueError as exc: return RedirectResponse(url="/?" + urlencode({"error": str(exc)}), status_code=303)
        return RedirectResponse(url=f"/projects/{project['id']}", status_code=303)

    @app.post("/projects/{project_id}/review")
    def start_review(project_id: str, request: Request, csrf: str = Form(alias="_csrf"), force: bool = Form(default=False)):
        require_local(request, csrf)
        try: store.get_project(project_id)
        except KeyError: raise HTTPException(404)
        job_id = store.enqueue("review", project_id, {"force": force}, priority=10)
        return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)

    @app.post("/projects/{project_id}/settings")
    def update_project_settings(
        project_id: str,
        request: Request,
        name: str = Form(),
        description: str = Form(default=""),
        goal: str = Form(default=""),
        exclusions: str = Form(default=""),
        interval_days: int = Form(default=7),
        enabled: str | None = Form(default=None),
        csrf: str = Form(alias="_csrf"),
    ):
        require_local(request, csrf)
        try:
            update = ProjectUpdate(
                name=name, description=description, goal=goal,
                exclusions=exclusions.splitlines(), interval_days=interval_days,
                enabled=enabled == "on",
            )
        except ValidationError as exc:
            raise HTTPException(422, str(exc)) from exc
        try: store.update_project(project_id, update)
        except KeyError: raise HTTPException(404)
        return RedirectResponse(url="/settings?saved=true", status_code=303)

    @app.get("/jobs/{job_id}", response_class=HTMLResponse)
    def job_page(job_id: str, request: Request):
        try: job = store.get_job(job_id)
        except KeyError: raise HTTPException(404)
        if request.headers.get("HX-Request"):
            return templates.TemplateResponse(request=request, name="_job.html", context={"request": request, "job": job, "csrf_token": app.state.csrf_token})
        return templates.TemplateResponse(request=request, name="job.html", context=context(request, page="job", job=job))

    @app.post("/jobs/{job_id}/cancel")
    def cancel_job(job_id: str, request: Request, csrf: str = Form(alias="_csrf")):
        require_local(request, csrf)
        try: job = store.get_job(job_id)
        except KeyError: raise HTTPException(404)
        updated = store.request_cancel(job_id)
        if updated["status"] == "running":
            codex.cancel()
        return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)

    @app.post("/reviews/{review_id}/chat")
    def chat(review_id: str, request: Request, message: str = Form(), csrf: str = Form(alias="_csrf")):
        require_local(request, csrf)
        try: store.get_review(review_id)
        except KeyError: raise HTTPException(404)
        job_id = store.enqueue("chat", None, {"message": message}, review_id=review_id, priority=1)
        return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)

    @app.post("/reviews/{review_id}/plans")
    def create_plan_form(review_id: str, request: Request, finding_id: str = Form(), instruction: str = Form(default=""), csrf: str = Form(alias="_csrf")):
        require_local(request, csrf)
        try:
            data = PlanRequest(finding_id=finding_id, instruction=instruction)
        except ValidationError as exc:
            raise HTTPException(422, str(exc)) from exc
        return RedirectResponse(url=f"/jobs/{enqueue_plan(review_id, data)}", status_code=303)

    @app.post("/reviews/{review_id}/lessons/{lesson_id}")
    async def lesson_status(review_id: str, lesson_id: str, request: Request):
        require_local(request)
        try:
            review = store.get_review(review_id)
        except KeyError:
            raise HTTPException(404, "Review not found")
        known_lessons = {item.get("id") for item in review.get("critique", {}).get("lessons", [])}
        if lesson_id not in known_lessons:
            raise HTTPException(404, "Lesson not found in this review")
        data = LessonStatusRequest.model_validate(await request.json())
        store.set_lesson_status(review_id, lesson_id, data.status)
        return {"ok": True}

    @app.post("/reviews/{review_id}/quiz/{question_id}")
    async def answer_quiz(review_id: str, question_id: str, request: Request):
        require_local(request)
        try:
            review = store.get_review(review_id)
        except KeyError:
            raise HTTPException(404, "Review not found")
        question = next(
            (item for item in review.get("critique", {}).get("quiz", []) if item.get("id") == question_id),
            None,
        )
        if question is None:
            raise HTTPException(404, "Quiz question not found in this review")
        try:
            data = QuizAnswerRequest.model_validate(await request.json())
        except (ValidationError, json.JSONDecodeError) as exc:
            raise HTTPException(422, str(exc)) from exc
        if data.selected_index >= len(question["options"]):
            raise HTTPException(422, "Selected option is outside this question")
        correct_index = question["correct_index"]
        correct = data.selected_index == correct_index
        saved = store.save_quiz_answer(review_id, question_id, data.selected_index, correct)
        return {
            **saved,
            "correct_index": correct_index,
            "correct_answer": question["options"][correct_index],
            "explanation": question["explanations"][data.selected_index],
        }

    @app.get("/reviews/{review_id}/source")
    def evidence_source(review_id: str, path: str, line: int = 1):
        try:
            review = store.get_review(review_id); snapshot = store.get_snapshot(review["snapshot_id"]); content = source_text(app.state.settings, snapshot, path)
        except KeyError: raise HTTPException(404)
        numbered = "\n".join(f'<span id="L{i}" class="source-line{' selected' if i == line else ''}"><b>{i:5}</b>  {html.escape(text)}</span>' for i, text in enumerate(content.splitlines(), 1))
        return HTMLResponse(f"<!doctype html><title>{html.escape(path)}</title><style>body{{font:14px ui-monospace;background:#fafbfe;color:#182033;padding:24px}}pre{{white-space:pre-wrap}}.source-line{{display:block;scroll-margin-top:24px}}.source-line b{{color:#8a93a6;font-weight:400}}.source-line.selected{{background:#fff0a8}}</style><h1>{html.escape(path)}</h1><pre>{numbered}</pre><script>document.getElementById('L{line}')?.scrollIntoView()</script>")

    @app.get("/artifacts/{review_id}/{name}")
    def artifact(review_id: str, name: str, download: bool = False):
        try: review = store.get_review(review_id)
        except KeyError: raise HTTPException(404)
        key = {"diagram": "diagram", "comparison": "comparison", "report": "report"}.get(name)
        if not key or not review["artifacts"].get(key): raise HTTPException(404)
        try:
            target = Path(review["artifacts"][key]).resolve()
            target.relative_to(app.state.settings.artifact_dir.resolve())
        except (OSError, ValueError):
            raise HTTPException(404, "Artifact is outside local review storage")
        if not target.is_file():
            raise HTTPException(404, "Artifact is unavailable")
        headers = {}
        if target.suffix.lower() == ".html":
            headers["Content-Security-Policy"] = "sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:"
        return FileResponse(target, headers=headers, filename=target.name if download else None)

    @app.get("/api/projects")
    def api_projects(): return store.list_projects()

    @app.get("/api/health")
    def api_health(): return {"application": "architecture-coach", "status": "ready"}

    @app.post("/api/projects", status_code=201)
    def api_add_project(data: ProjectCreate, request: Request):
        require_local(request)
        try: return store.add_project(data)
        except ValueError as exc: raise HTTPException(409, str(exc)) from exc

    @app.get("/api/projects/{project_id}")
    def api_project(project_id: str):
        try: return store.get_project(project_id)
        except KeyError: raise HTTPException(404)

    @app.get("/api/projects/{project_id}/reviews")
    def api_reviews(project_id: str):
        try: store.get_project(project_id)
        except KeyError: raise HTTPException(404)
        return store.list_reviews(project_id)

    @app.get("/api/projects/{project_id}/history")
    def api_history(project_id: str):
        try: store.get_project(project_id)
        except KeyError: raise HTTPException(404)
        return store.list_history(project_id)

    @app.get("/api/projects/{project_id}/comparison")
    def api_comparison(project_id: str, before: str | None = None, after: str | None = None):
        try:
            _, _, before_review, after_review, changes = comparison(project_id, before, after)
        except KeyError:
            raise HTTPException(404)
        return {"before_review_id": before_review["id"], "after_review_id": after_review["id"], "changes": changes}

    @app.patch("/api/projects/{project_id}")
    def api_update_project(project_id: str, data: ProjectUpdate, request: Request):
        require_local(request)
        try: return store.update_project(project_id, data)
        except KeyError: raise HTTPException(404)

    @app.post("/api/projects/{project_id}/reviews", status_code=202)
    def api_review(project_id: str, request: Request, force: bool = False):
        require_local(request)
        try: store.get_project(project_id)
        except KeyError: raise HTTPException(404)
        return {"job_id": store.enqueue("review", project_id, {"force": force})}

    @app.get("/api/jobs/{job_id}")
    def api_job(job_id: str):
        try: return store.get_job(job_id)
        except KeyError: raise HTTPException(404)

    @app.post("/api/jobs/{job_id}/cancel")
    def api_cancel_job(job_id: str, request: Request):
        require_local(request)
        try: job = store.request_cancel(job_id)
        except KeyError: raise HTTPException(404)
        if job["status"] == "running":
            codex.cancel()
        return job

    @app.post("/api/reviews/{review_id}/chat", status_code=202)
    def api_chat(review_id: str, data: ChatRequest, request: Request):
        require_local(request)
        try: store.get_review(review_id)
        except KeyError: raise HTTPException(404)
        return {"job_id": store.enqueue("chat", None, data.model_dump(), review_id=review_id, priority=1)}

    @app.post("/api/reviews/{review_id}/plans", status_code=202)
    def api_create_plan(review_id: str, data: PlanRequest, request: Request):
        require_local(request)
        return {"job_id": enqueue_plan(review_id, data)}

    @app.get("/api/reviews/{review_id}/plans")
    def api_review_plans(review_id: str):
        try: store.get_review(review_id)
        except KeyError: raise HTTPException(404)
        return store.list_plans(review_id)

    @app.get("/api/plans/{plan_id}")
    def api_plan(plan_id: str):
        plan, _, _ = plan_details(plan_id)
        return plan

    @app.post("/api/plans/{plan_id}/publish")
    def api_publish_plan(plan_id: str, data: PlanApproval, request: Request):
        require_local(request)
        try: return PlanService(app.state.settings, store, codex).publish(plan_id, data.draft_hash)
        except KeyError: raise HTTPException(404)
        except PlanConflict as exc: raise HTTPException(409, str(exc)) from exc
        except PlanError as exc: raise HTTPException(422, str(exc)) from exc

    @app.get("/api/reviews/{review_id}/conversation")
    def api_conversation(review_id: str):
        try: store.get_review(review_id)
        except KeyError: raise HTTPException(404)
        return store.conversation_for_review(review_id)

    @app.get("/api/reviews/{review_id}/current-status")
    def api_current_status(review_id: str):
        try:
            review = store.get_review(review_id)
            snapshot = store.get_snapshot(review["snapshot_id"])
            project = store.get_project(review["project_id"])
            current = fingerprint_project(app.state.settings, project)
        except KeyError:
            raise HTTPException(404)
        except CaptureError as exc:
            return {"status": "folder_unavailable", "message": str(exc)}
        return {
            "status": "matches" if current["fingerprint"] == snapshot["fingerprint"] else "changed",
            "fingerprint": current["fingerprint"],
        }

    @app.get("/api/settings")
    def api_settings():
        return {key: getattr(app.state.settings, key) for key in allowed_setting_keys}

    def apply_app_settings(update: AppSettingsUpdate) -> dict:
        nonlocal settings, codex
        values = update.model_dump(exclude_unset=True)
        if not values:
            return {key: getattr(settings, key) for key in allowed_setting_keys}
        store.update_app_settings(values)
        settings = replace(settings, **values)
        app.state.settings = settings
        engine.settings = settings
        codex = create_adapter(settings)
        engine.codex = codex
        diagnostics_cache.update({"at": 0.0, "value": None})
        return {key: getattr(settings, key) for key in allowed_setting_keys}

    @app.patch("/api/settings")
    def api_update_settings(data: AppSettingsUpdate, request: Request):
        require_local(request)
        return apply_app_settings(data)

    @app.post("/settings/application")
    def update_application_settings(
        request: Request,
        csrf: str = Form(alias="_csrf"),
        ai_provider: str = Form(default="codex"),
        codex_command: str = Form(),
        codex_model: str = Form(default=""),
        ollama_model: str = Form(default=""),
        lmstudio_model: str = Form(default=""),
        reasoning_effort: str = Form(default="low"),
        codex_call_timeout: int = Form(default=300),
        review_timeout: int = Form(default=900),
        source_packet_chars: int = Form(default=48000),
        source_packet_limit: int = Form(default=6),
    ):
        require_local(request, csrf)
        try:
            apply_app_settings(AppSettingsUpdate(
                ai_provider=ai_provider, codex_command=codex_command,
                codex_model=codex_model or None, ollama_model=ollama_model or None,
                lmstudio_model=lmstudio_model or None,
                reasoning_effort=reasoning_effort, codex_call_timeout=codex_call_timeout,
                review_timeout=review_timeout, source_packet_chars=source_packet_chars,
                source_packet_limit=source_packet_limit,
            ))
        except ValidationError as exc:
            raise HTTPException(422, str(exc)) from exc
        return RedirectResponse(url="/settings?saved=true", status_code=303)

    @app.post("/exit")
    def exit_app(request: Request, csrf: str = Form(alias="_csrf")): require_local(request, csrf); app.state.shutdown_event.set(); return HTMLResponse("Architecture Coach is shutting down. You can close this tab.")

    return app

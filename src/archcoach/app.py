from __future__ import annotations

import html
from functools import lru_cache
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
from .review import ReviewEngine, compare_saved_reviews, source_text, validate_comparison_records, add_resolved_relationships
from .worker import Worker
from .learning import lesson_examples, source_walkthroughs, change_examples, concept_examples, saved_glossary
from .models import Architecture, Critique
from .models import LearningNoteRequest, PlanLearningRequest, LearningSessionUpdate, LearningIssueRequest, utc_now
from .review import markdown_report
from .workspace import saved_graph, resolve_selection, component_role


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
    local_diagnostics_cache: dict = {"at": 0.0, "value": None}

    def codex_status(refresh: bool = False) -> dict:
        with diagnostics_lock:
            if refresh or diagnostics_cache["value"] is None or time.monotonic() - diagnostics_cache["at"] > 30:
                diagnostics_cache["value"] = codex.status()
                diagnostics_cache["at"] = time.monotonic()
            return diagnostics_cache["value"]

    def local_status(selected: dict, refresh: bool = False) -> dict:
        with diagnostics_lock:
            if refresh or local_diagnostics_cache["value"] is None or time.monotonic() - local_diagnostics_cache["at"] > 30:
                local_diagnostics_cache["value"] = {
                    provider: selected if settings.ai_provider == provider else create_adapter(replace(settings, ai_provider=provider)).status()
                    for provider in ("ollama", "lmstudio", "prism")
                }
                local_diagnostics_cache["at"] = time.monotonic()
            return local_diagnostics_cache["value"]

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
        if extra.get('page') == 'review' and extra.get('review'):
            selected_review = extra['review']
            extra.setdefault('conversation', store.conversation_for_review(selected_review['id']))
            extra.setdefault('snapshot', store.get_snapshot(selected_review['snapshot_id']))
            extra['map_manifest'] = {f['path']: f['lines'] for f in extra['snapshot']['manifest']}
            extra['learning_session'] = store.learning_session(selected_review['id'])
            extra['learning_issues'] = store.learning_issues(selected_review['id'])
            extra['flagged_questions'] = {i['target_id'] for i in extra['learning_issues'] if i['kind'] == 'quiz' and not i['resolved_at']}
            extra['component_roles'] = {c['id']: component_role(c) for c in selected_review['architecture']['components']}
            extra.setdefault('graph', saved_graph(extra['snapshot'], selected_review))
            extra['provider_name'] = {'codex':'Codex', 'ollama':'Ollama · local', 'lmstudio':'LM Studio · local', 'prism':'Prism · Bonsai local'}[settings.ai_provider]
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

    def saved_question(review_id: str, question_id: str):
        try:
            review = store.get_review(review_id)
        except KeyError:
            raise HTTPException(404, 'Review not found')
        question = next((q for q in review['critique'].get('quiz', []) if q['id'] == question_id), None)
        if question is None:
            raise HTTPException(404, 'Question not found in this saved review')
        return question

    @app.get('/learning', response_class=HTMLResponse)
    def learning_library(request: Request, concept: str = '', practice: bool = False):
        records = store.learning_records()
        concepts = sorted({item['question'].get('concept', 'unclassified') for item in records})
        if concept and concept not in concepts:
            raise HTTPException(422, 'Choose a concept shown in the library')
        latest = {p['id']: store.latest_review(p['id']) for p in store.list_projects()}
        recommendations = []
        for session in store.learning_sessions():
            if (session['state'].get('position') or 0) < 5 or session['state'].get('draft'):
                recommendations.append({'title':'Continue '+session['project_name'], 'reason':'Your saved session or instructor draft is unfinished.', 'href':f"/reviews/{session['review_id']}/session"})
                break
        now = utc_now()
        for item in records:
            current = latest.get(item['project_id'])
            item['newer_review'] = current['id'] if current and current['id'] != item['review_id'] else None
            item['due'] = item['due_at'] <= now
        selected = [item for item in records if not concept or item['question'].get('concept', 'unclassified') == concept]
        due_count = sum(item['due'] for item in selected)
        due = next((i for i in selected if i['due']), None)
        if due:
            recommendations.append({'title':'Due practice', 'reason':'This saved question is due for recall.', 'href':'/learning?practice=true'})
        mistake = next((i for i in selected if i.get('first_correct') == 0), None)
        if mistake:
            recommendations.append({'title':'Review a mistake or uncertainty', 'reason':'Your first attempt was incorrect or uncertain; history is preserved.', 'href':f"/reviews/{mistake['review_id']}#quiz"})
        for summary in latest.values():
            if not summary: continue
            review = store.get_review(summary['id'])
            answered = store.quiz_answers(review['id'])
            flagged = {i['target_id'] for i in store.learning_issues(review['id']) if i['kind']=='quiz' and not i['resolved_at']}
            question = next((q for q in review['critique'].get('quiz', []) if q['id'] not in answered and q['id'] not in flagged and any(e.get('valid',True) for e in q['evidence'])), None)
            if question:
                recommendations.append({'title':'Explore '+question.get('concept','a concept').replace('_',' '), 'reason':'An unpractised question has saved repository evidence.', 'href':f"/reviews/{review['id']}#quiz"})
                break
        if practice:
            selected = [item for item in selected if item['due']][:5]
        return templates.TemplateResponse(request=request, name='learning.html', context=context(
            request, page='learning', records=selected, concepts=concepts, concept=concept,
            practice=practice, due_count=due_count, recommendations=recommendations))

    @app.post('/reviews/{review_id}/quiz/{question_id}/note')
    def learning_note(review_id: str, question_id: str, request: Request, content: str = Form(max_length=2000), csrf: str = Form(alias='_csrf')):
        require_local(request, csrf)
        saved_question(review_id, question_id)
        store.save_learning_note(review_id, question_id, LearningNoteRequest(content=content).content)
        return RedirectResponse('/learning', status_code=303)

    @app.get('/api/reviews/{review_id}/quiz/{question_id}/attempts')
    def quiz_history(review_id: str, question_id: str):
        saved_question(review_id, question_id)
        return store.quiz_attempts(review_id, question_id)

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request):
        return templates.TemplateResponse(request=request, name="dashboard.html", context=context(request, page="projects", codex=codex_status(), provider_name={'codex':'Codex', 'ollama':'Ollama · local', 'lmstudio':'LM Studio · local', 'prism':'Prism · Bonsai local'}[settings.ai_provider]))

    @app.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request, saved: bool = False, refresh: bool = False):
        selected = codex_status(refresh)
        return templates.TemplateResponse(
            request=request,
            name="settings.html",
            context=context(request, page="settings", codex=selected, local_providers=local_status(selected, refresh), saved=saved, data_dir=settings.data_dir, app_settings=settings),
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
        return templates.TemplateResponse(request=request, name="review.html", context=context(request, page="review", project=project, review=review, snapshot=snapshot, plans=store.list_plans(review_id), lesson_statuses=store.lesson_statuses(review_id), quiz_answers=quiz_answers, quiz_score=sum(item["correct"] for item in quiz_answers.values()), conversation=conversation, current_status="checking", teaching=lesson_examples(settings, snapshot, review['critique']), question_examples=lesson_examples(settings, snapshot, {'lessons': review['critique'].get('quiz', [])}), component_names={c['id']: c['name'] for c in review['architecture']['components']}))

    @app.get('/reviews/{review_id}/learning-report')
    def learning_report(review_id: str):
        try:
            review = store.get_review(review_id)
            snapshot = store.get_snapshot(review['snapshot_id'])
            project = store.get_project(review['project_id'])
        except KeyError:
            raise HTTPException(404)
        report = markdown_report(project, Architecture.model_validate(review['architecture']),
                                 Critique.model_validate(review['critique']), review['changes'], snapshot['coverage'],
                                 snapshot_id=snapshot['id'], examples=lesson_examples(settings, snapshot, review['critique']))
        return Response(report, media_type='text/markdown', headers={'Content-Disposition': 'attachment; filename="learning-report.md"'})

    @app.get('/reviews/{review_id}/map', response_class=HTMLResponse)
    def expanded_map(review_id: str, request: Request, component: str | None = None, q: str = '', role: str = 'runtime', focus: str | None = None):
        try:
            review = store.get_review(review_id)
            project = store.get_project(review['project_id'])
        except KeyError:
            raise HTTPException(404, 'Review not found')
        try:
            graph = saved_graph(store.get_snapshot(review['snapshot_id']), review, component=component, query=q, role=role, focus=focus)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return templates.TemplateResponse(request=request, name='map.html', context=context(
            request, page='review', review=review, project=project, graph=graph))

    @app.get('/api/reviews/{review_id}/graph')
    def graph_data(review_id: str, component: str | None = None, q: str = '', role: str = 'runtime', focus: str | None = None):
        try:
            review = store.get_review(review_id)
            return saved_graph(store.get_snapshot(review['snapshot_id']), review, component=component, query=q, role=role, focus=focus)
        except KeyError:
            raise HTTPException(404, 'Review not found')
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get('/reviews/{review_id}/walkthrough', response_class=HTMLResponse)
    def walkthrough_page(review_id: str, request: Request, file: str | None = None):
        try:
            review = store.get_review(review_id)
            project = store.get_project(review['project_id'])
            snapshot = store.get_snapshot(review['snapshot_id'])
        except KeyError:
            raise HTTPException(404)
        prior_outline = store.learning_session(review_id).get('outline_id')
        selected_file = (file or None) if file is not None else (prior_outline.rsplit(':', 1)[0] if prior_outline else None)
        try: outline = saved_walkthrough(review, snapshot, selected_file)
        except ValueError as exc: raise HTTPException(422, str(exc)) from exc
        return templates.TemplateResponse(request=request, name='walkthrough.html', context=context(
            request, page='review', review=review, project=project,
            walkthrough=outline, feature_files=[f['path'] for f in snapshot['manifest'] if f['path'].lower().endswith(('.py','.ts','.tsx','.js','.jsx','.mjs','.cjs'))],
            component_names={c['id']: c['name'] for c in review['architecture']['components']}))

    @app.get('/api/reviews/{review_id}/walkthrough')
    def walkthrough_data(review_id: str, file: str | None = None):
        try:
            review = store.get_review(review_id)
            return saved_walkthrough(review, store.get_snapshot(review['snapshot_id']), file)
        except KeyError:
            raise HTTPException(404)
        except ValueError as exc: raise HTTPException(422, str(exc)) from exc

    def saved_walkthrough(review, snapshot, selected_path=None):
        if selected_path: return selected_walkthrough(review['id'], selected_path)
        saved = store.get_learning_walkthrough(review['id'], 3)
        return saved if saved is not None else store.save_learning_walkthrough(review['id'], source_walkthroughs(settings, snapshot, review))

    @lru_cache(maxsize=8)
    def selected_walkthrough(review_id, selected_path):
        review = store.get_review(review_id)
        return source_walkthroughs(settings, store.get_snapshot(review['snapshot_id']), review, selected_path)

    @app.get('/reviews/{review_id}/walkthrough-map', response_class=HTMLResponse)
    def walkthrough_map(review_id: str, role: str = 'all'):
        from .diagram import fallback_diagram
        try:
            review = store.get_review(review_id)
        except KeyError:
            raise HTTPException(404)
        if role not in {'all', 'runtime', 'tests', 'tooling', 'supporting', 'unknown'}:
            raise HTTPException(422, 'Unknown source role')
        snapshot = store.get_snapshot(review['snapshot_id'])
        saved_model = Architecture.model_validate(review['architecture'])
        manifest = {f['path']:f for f in snapshot['manifest']}
        edges = [e for e in snapshot['analysis'].get('edges', []) if e.get('source') in manifest and isinstance(e.get('line'), int) and 1 <= e['line'] <= manifest[e['source']]['lines']]
        add_resolved_relationships(saved_model, edges)
        model = saved_model.model_dump()
        roles = {c['id']: component_role(c) for c in model['components']}
        if role != 'all':
            model['components'] = [c for c in model['components'] if roles[c['id']] == role]
            known = {c['id'] for c in model['components']}
            model['relationships'] = [r for r in model['relationships'] if r['source'] in known and r['target'] in known]
            model['main_path'] = [i for i in model.get('main_path', []) if i in known]
        if not model['components']:
            return HTMLResponse('<p>No components match this source role. Choose another role or inspect the saved files.</p>')
        document = fallback_diagram(Architecture.model_validate(model), 'Saved feature map', None, review_id=review_id, role_labels=roles)
        return HTMLResponse(document, headers={'Content-Security-Policy': "sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:"})

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

    @app.get('/projects/{project_id}/change-lesson', response_class=HTMLResponse)
    def change_lesson(project_id: str, request: Request, before: str | None = None, after: str | None = None):
        try:
            project, reviews, left, right, changes = comparison(project_id, before, after)
            examples = change_examples(settings, left, store.get_snapshot(left['snapshot_id']), right, store.get_snapshot(right['snapshot_id']), changes)
        except KeyError:
            raise HTTPException(404)
        return templates.TemplateResponse(request=request, name='change_lesson.html', context=context(request, page='compare', project=project, before=left, after=right, changes=changes, examples=examples))

    @app.get('/learning/compare', response_class=HTMLResponse)
    def concept_comparison(request: Request, left: str | None = None, right: str | None = None, concept: str = 'responsibilities'):
        concepts = ['unclassified', 'responsibilities', 'dependencies', 'data_flow', 'state', 'validation', 'testing', 'change_impact', 'tradeoffs']
        if concept not in concepts:
            raise HTTPException(422, 'Unknown concept')
        choices = [{**r, 'project_name': p['name']} for p in store.list_projects() for r in store.list_reviews(p['id']) if r['status'] in {'complete', 'unchanged'}]
        sides = []
        for rid in (left, right):
            if not rid:
                continue
            try:
                review = store.get_review(rid)
                if review['status'] not in {'complete', 'unchanged'}:
                    raise HTTPException(409, 'Choose a saved review')
                snapshot = store.get_snapshot(review['snapshot_id'])
                sides.append({'review': review, 'project': store.get_project(review['project_id']), 'examples': concept_examples(settings, snapshot, review, concept)})
            except KeyError:
                raise HTTPException(404)
        return templates.TemplateResponse(request=request, name='concept_compare.html', context=context(request, page='learning', choices=choices, left=left, right=right, concept=concept, concepts=concepts, sides=sides))

    @app.get('/plans/{plan_id}/follow-through', response_class=HTMLResponse)
    def plan_follow_through(plan_id: str, request: Request):
        plan, review, project = plan_details(plan_id)
        reviews = [r for r in store.list_reviews(project['id']) if r['status'] in {'complete', 'unchanged'} and r['created_at'] > review['created_at']]
        return templates.TemplateResponse(request=request, name='plan_learning.html', context=context(request, page='plan', plan=plan, review=review, project=project, reviews=reviews, reports=store.plan_learning_reports(plan_id)))

    @app.post('/plans/{plan_id}/follow-through')
    def record_plan_follow_through(plan_id: str, request: Request, review_id: str = Form(), note: str = Form(), csrf: str = Form(alias='_csrf')):
        require_local(request, csrf)
        plan, review, project = plan_details(plan_id)
        try:
            data = PlanLearningRequest(review_id=review_id, note=note)
            later = store.get_review(data.review_id)
            validate_comparison_records(review, later)
            if later['created_at'] <= review['created_at']:
                raise ValueError('Choose a later saved review')
        except KeyError:
            raise HTTPException(404, 'Review not found')
        except ValidationError as exc:
            raise HTTPException(422, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        store.record_plan_learning(plan_id, review_id, data.note)
        return RedirectResponse(f'/plans/{plan_id}/follow-through', status_code=303)

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
    def chat(review_id: str, request: Request, message: str = Form(), csrf: str = Form(alias="_csrf"), mode: str = Form(default='answer'), question_id: str = Form(default=''), selection: str = Form(default='')):
        require_local(request, csrf)
        try:
            data = ChatRequest(message=message, mode=mode, question_id=question_id or None, selection=json.loads(selection) if selection else None)
        except (ValidationError, json.JSONDecodeError) as exc:
            raise HTTPException(422, str(exc)) from exc
        job_id = enqueue_chat(review_id, data)
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
        if any(i['kind'] == 'quiz' and i['target_id'] == question_id and not i['resolved_at'] for i in store.learning_issues(review_id)):
            raise HTTPException(409, 'This question is paused for correction. Resolve its issue before practising it.')
        if data.selected_index is not None and data.selected_index >= len(question["options"]):
            raise HTTPException(422, "Selected option is outside this question")
        correct_index = question["correct_index"]
        correct = data.selected_index == correct_index
        try:
            saved = store.save_quiz_answer(review_id, question_id, data.selected_index, correct, request_id=data.request_id, mode=data.mode, outcome=data.outcome)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {
            **saved,
            "correct_index": correct_index,
            "correct_answer": question["options"][correct_index],
            "explanation": ('You recorded uncertainty. Read the saved explanation, then try again when ready. ' + question['explanations'][correct_index]) if data.outcome == 'not_sure' else question["explanations"][data.selected_index],
        }

    @app.get('/api/reviews/{review_id}/session')
    def session_state(review_id: str):
        try: store.get_review(review_id)
        except KeyError: raise HTTPException(404, 'Review not found')
        return store.learning_session(review_id)

    @app.get('/reviews/{review_id}/session', response_class=HTMLResponse)
    def guided_session(review_id: str, request: Request):
        try:
            review = store.get_review(review_id)
            project = store.get_project(review['project_id'])
        except KeyError: raise HTTPException(404, 'Review not found')
        return templates.TemplateResponse(request=request, name='session.html', context=context(request, page='review', review=review, project=project))

    @app.get('/reviews/{review_id}/glossary', response_class=HTMLResponse)
    def glossary_page(review_id: str, request: Request):
        try:
            review = store.get_review(review_id); snapshot = store.get_snapshot(review['snapshot_id']); project = store.get_project(review['project_id'])
        except KeyError: raise HTTPException(404, 'Review not found')
        return templates.TemplateResponse(request=request, name='glossary.html', context=context(request, page='review', review=review, project=project, glossary=saved_glossary(settings,snapshot,review)))

    @app.patch('/api/reviews/{review_id}/session')
    def update_session(review_id: str, data: LearningSessionUpdate, request: Request):
        require_local(request)
        try: review = store.get_review(review_id)
        except KeyError: raise HTTPException(404, 'Review not found')
        snapshot = store.get_snapshot(review['snapshot_id'])
        changes = data.model_dump(exclude_unset=True)
        if data.question_id: saved_question(review_id,data.question_id)
        try:
            resolve_selection(snapshot, review, data.selection, saved_walkthrough(review, snapshot, data.selection.id.rsplit(':',1)[0]) if data.selection and data.selection.kind == 'walkthrough' else None)
            state = {**store.learning_session(review_id), **changes}
            if {'outline_id', 'step'} & changes.keys() and state.get('outline_id'):
                outline = next((o for o in saved_walkthrough(review, snapshot, state['outline_id'].rsplit(':',1)[0])['outlines'] if o['id'] == state['outline_id']), None)
                if not outline or not 0 <= (state.get('step') or 0) < len(outline['steps']):
                    raise ValueError('Session step is outside this saved outline')
            if 'quiz_index' in changes and state.get('quiz_index') is not None and not 0 <= state['quiz_index'] < len(review['critique'].get('quiz', [])):
                raise ValueError('Session question is outside this saved quiz')
        except ValueError as exc: raise HTTPException(422, str(exc)) from exc
        return store.save_learning_session(review_id, changes)

    @app.post('/api/reviews/{review_id}/issues', status_code=201)
    def flag_issue(review_id: str, data: LearningIssueRequest, request: Request):
        require_local(request)
        try: store.get_review(review_id)
        except KeyError: raise HTTPException(404, 'Review not found')
        if data.kind == 'quiz': saved_question(review_id, data.target_id)
        elif not any(m['id'] == data.target_id and m['role'] == 'assistant' for m in store.conversation_for_review(review_id)['messages']):
            raise HTTPException(422, 'Answer not found in this saved conversation')
        return {'id': store.flag_learning_issue(review_id, data.kind, data.target_id, data.note)}

    @app.post('/api/reviews/{review_id}/issues/{issue_id}/resolve')
    def resolve_issue(review_id: str, issue_id: str, request: Request):
        require_local(request)
        try: store.resolve_learning_issue(review_id, issue_id)
        except KeyError: raise HTTPException(404, 'Open issue not found')
        return {'resolved': True}

    @app.get("/reviews/{review_id}/source")
    def evidence_source(review_id: str, request: Request, path: str, line: int = 1, end_line: int | None = None):
        try:
            review = store.get_review(review_id); snapshot = store.get_snapshot(review["snapshot_id"]); content = source_text(app.state.settings, snapshot, path)
        except KeyError: raise HTTPException(404)
        lines = content.splitlines()
        end_line = end_line or line
        if lines and not 1 <= line <= end_line <= len(lines): raise HTTPException(422, 'Range is outside this saved source')
        project = store.get_project(review['project_id'])
        return templates.TemplateResponse(request=request, name='source.html', context=context(request, page='review', project=project, review=review, path=path, source_lines=lines, line=line, end_line=end_line))

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
        return {"job_id": enqueue_chat(review_id, data)}

    def enqueue_chat(review_id: str, data: ChatRequest):
        try: review = store.get_review(review_id)
        except KeyError: raise HTTPException(404)
        if data.question_id:
            saved_question(review_id, data.question_id)
        try:
            snapshot = store.get_snapshot(review['snapshot_id'])
            resolve_selection(snapshot, review, data.selection, saved_walkthrough(review, snapshot, data.selection.id.rsplit(':',1)[0]) if data.selection and data.selection.kind == 'walkthrough' else None)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return store.enqueue('chat', None, data.model_dump(), review_id=review_id, priority=1)

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
        local_diagnostics_cache.update({"at": 0.0, "value": None})
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
        prism_model: str = Form(default=""),
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
                prism_model=prism_model or None,
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

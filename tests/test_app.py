from pathlib import Path

from fastapi.testclient import TestClient

from archcoach.app import create_app
from archcoach.config import Settings
from archcoach.capture import capture_project


def make_client(tmp_path: Path):
    app_dir = Path(__file__).parents[1] / "src" / "archcoach"
    app = create_app(Settings(data_dir=tmp_path / "data", app_dir=app_dir), start_worker=False)
    return app, TestClient(app)


def test_dashboard_and_project_api(tmp_path: Path):
    project = tmp_path / "project"; project.mkdir(); (project / "app.py").write_text("x = 1\n", encoding="utf-8")
    app, client = make_client(tmp_path)
    assert client.get("/").status_code == 200
    denied = client.post("/api/projects", json={"path": str(project)})
    assert denied.status_code == 403
    token = app.state.csrf_token
    response = client.post("/api/projects", headers={"X-ArchCoach-Token": token}, json={"path": str(project)})
    assert response.status_code == 201
    assert client.get("/api/projects").json()[0]["path"] == str(project.resolve())


def test_github_url_is_explained_as_a_local_folder_requirement(tmp_path: Path):
    app, client = make_client(tmp_path)
    token = app.state.csrf_token

    page = client.post(
        "/projects",
        data={"_csrf": token, "path": "https://github.com/example/project"},
    )

    assert page.status_code == 200
    assert "reviews a local folder already on this computer" in page.text
    assert "How do I find the folder path?" in page.text
    assert str(Path.cwd()) not in page.text


def test_source_view_escapes_snapshot_content(tmp_path: Path):
    project = tmp_path / "project"; project.mkdir(); (project / "bad.html").write_text("<script>alert(1)</script>", encoding="utf-8")
    app, client = make_client(tmp_path); token = app.state.csrf_token
    created = client.post("/api/projects", headers={"X-ArchCoach-Token": token}, json={"path": str(project)}).json()
    from archcoach.review import ReviewEngine
    from tests.test_review import OfflineCodex
    review_id = ReviewEngine(app.state.settings, app.state.store, OfflineCodex()).run(created["id"])
    response = client.get(f"/reviews/{review_id}/source", params={"path": "bad.html"})
    assert "&lt;script&gt;" in response.text
    assert "<script>alert" not in response.text
    assert 'id="L1" class="source-line selected"' in response.text


def test_project_settings_update_schedule_goal_and_exclusions(tmp_path: Path):
    project = tmp_path / "project"; project.mkdir()
    (project / "app.py").write_text("x = 1\n", encoding="utf-8")
    reports = project / "reports"; reports.mkdir()
    (reports / "private.py").write_text("secret = 'example'\n", encoding="utf-8")
    app, client = make_client(tmp_path); token = app.state.csrf_token
    created = client.post("/api/projects", headers={"X-ArchCoach-Token": token}, json={"path": str(project)}).json()

    update = {
        "name": "Renamed project",
        "description": "A settings test",
        "goal": "Keep reviews focused",
        "exclusions": ["reports/**", "reports/**", "\\scratch\\"],
        "interval_days": 14,
        "enabled": False,
    }
    denied = client.patch(f"/api/projects/{created['id']}", json=update)
    assert denied.status_code == 403
    response = client.patch(f"/api/projects/{created['id']}", headers={"X-ArchCoach-Token": token}, json=update)
    assert response.status_code == 200
    saved = response.json()
    assert saved["name"] == "Renamed project"
    assert saved["goal"] == "Keep reviews focused"
    assert saved["interval_days"] == 14
    assert saved["enabled"] == 0
    assert saved["exclusions"] == ["reports/**", "scratch/"]
    assert client.get("/settings").status_code == 200

    captured = capture_project(app.state.settings, saved)
    assert {item["path"] for item in captured["manifest"]} == {"app.py"}

    form_response = client.post(
        f"/projects/{created['id']}/settings",
        data={"_csrf": token, "name": "Form update", "description": "Updated in the dashboard", "goal": "Ship it", "exclusions": "reports/**\ncache/", "interval_days": "21", "enabled": "on"},
        follow_redirects=False,
    )
    assert form_response.status_code == 303
    assert form_response.headers["location"] == "/settings?saved=true"
    form_saved = client.get(f"/api/projects/{created['id']}").json()
    assert form_saved["name"] == "Form update"
    assert form_saved["enabled"] == 1
    assert form_saved["exclusions"] == ["reports/**", "cache/"]


def test_review_history_can_compare_any_two_snapshots(tmp_path: Path, monkeypatch):
    project = tmp_path / "project"; project.mkdir()
    app_file = project / "app.py"; app_file.write_text("def main():\n    return 1\n", encoding="utf-8")
    app, client = make_client(tmp_path); token = app.state.csrf_token
    created = client.post("/api/projects", headers={"X-ArchCoach-Token": token}, json={"path": str(project)}).json()
    from archcoach.review import ReviewEngine
    from tests.test_review import OfflineCodex
    engine = ReviewEngine(app.state.settings, app.state.store, OfflineCodex())
    before = engine.run(created["id"])

    app_file.write_text("def main():\n    return 2\n", encoding="utf-8")
    services = project / "services"; services.mkdir()
    (services / "auth.py").write_text("def authenticate():\n    return True\n", encoding="utf-8")
    after = engine.run(created["id"])

    history = client.get(f"/api/projects/{created['id']}/reviews")
    assert history.status_code == 200
    assert [item["id"] for item in history.json()] == [after, before]
    response = client.get(f"/api/projects/{created['id']}/comparison", params={"before": before, "after": after})
    assert response.status_code == 200
    changes = response.json()["changes"]
    assert changes["files_added"] == ["services/auth.py"]
    assert changes["files_changed"] == ["app.py"]
    assert "services" in changes["components_added"]
    page = client.get(f"/projects/{created['id']}/compare", params={"before": before, "after": after})
    assert page.status_code == 200
    assert "Compare two saved reviews" in page.text
    assert "services/auth.py" in page.text
    def fake_selected(settings, _before, _after):
        target = settings.artifact_dir / "comparisons" / "selected.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("<html>selected comparison</html>", encoding="utf-8")
        return str(target)
    monkeypatch.setattr("archcoach.app.render_selected_comparison", fake_selected)
    visual = client.get(
        f"/projects/{created['id']}/comparison-artifact",
        params={"before": before, "after": after},
    )
    assert visual.status_code == 200
    assert "sandbox allow-scripts" in visual.headers["content-security-policy"]


def test_global_host_origin_and_csrf_protection(tmp_path: Path):
    project = tmp_path / "project"; project.mkdir()
    app, client = make_client(tmp_path); token = app.state.csrf_token
    assert client.get("/", headers={"Host": "attacker.example"}).status_code == 400
    denied = client.post(
        "/api/projects",
        headers={"X-ArchCoach-Token": token, "Origin": "https://attacker.example"},
        json={"path": str(project)},
    )
    assert denied.status_code == 403
    query_only = client.post(f"/api/projects?token={token}", json={"path": str(project)})
    assert query_only.status_code == 403


def test_required_application_settings_reject_explicit_null(tmp_path: Path):
    app, client = make_client(tmp_path)
    token = app.state.csrf_token

    response = client.patch(
        "/api/settings",
        headers={"X-ArchCoach-Token": token},
        json={"codex_call_timeout": None},
    )

    assert response.status_code == 422
    assert client.get("/api/settings").json()["codex_call_timeout"] == 300

    reset_model = client.patch(
        "/api/settings",
        headers={"X-ArchCoach-Token": token},
        json={"codex_model": None},
    )
    assert reset_model.status_code == 200


def test_partial_updates_preserve_omitted_fields_and_settings(tmp_path: Path):
    project = tmp_path / "project"; project.mkdir()
    app, client = make_client(tmp_path); token = app.state.csrf_token
    headers = {"X-ArchCoach-Token": token}
    created = client.post(
        "/api/projects", headers=headers,
        json={"path": str(project), "name": "Original", "description": "Keep me", "goal": "First", "interval_days": 17, "exclusions": ["build/"]},
    ).json()
    changed = client.patch(f"/api/projects/{created['id']}", headers=headers, json={"goal": "Second"})
    assert changed.status_code == 200
    assert changed.json() | {} == {**created, "goal": "Second"}

    defaults = client.get("/api/settings").json()
    updated = client.patch("/api/settings", headers=headers, json={"review_timeout": 1200})
    assert updated.status_code == 200
    assert updated.json()["review_timeout"] == 1200
    assert updated.json()["codex_call_timeout"] == defaults["codex_call_timeout"]
    app2 = create_app(Settings(data_dir=tmp_path / "data", app_dir=Path(__file__).parents[1] / "src" / "archcoach"), start_worker=False)
    assert app2.state.settings.review_timeout == 1200


def test_api_errors_are_actionable_and_terminal_cancel_is_stable(tmp_path: Path):
    project = tmp_path / "project"; project.mkdir()
    app, client = make_client(tmp_path); token = app.state.csrf_token
    headers = {"X-ArchCoach-Token": token}
    created = client.post("/api/projects", headers=headers, json={"path": str(project)}).json()
    assert client.post("/api/projects", headers=headers, json={"path": str(project)}).status_code == 409
    assert client.patch("/api/projects/missing", headers=headers, json={"goal": "x"}).status_code == 404
    assert client.post("/api/reviews/missing/chat", headers=headers, json={"message": "hello"}).status_code == 404
    assert client.patch("/api/settings", headers=headers, json={"review_timeout": 3}).status_code == 422

    job_id = app.state.store.enqueue("review", created["id"])
    first = client.post(f"/api/jobs/{job_id}/cancel", headers=headers)
    second = client.post(f"/api/jobs/{job_id}/cancel", headers=headers)
    assert first.json()["status"] == second.json()["status"] == "cancelled"
    assert second.json()["cancellation_state"] == "cancelled"


def test_saved_review_is_independent_of_live_folder_and_diagnostics(tmp_path: Path, monkeypatch):
    project = tmp_path / "project"; project.mkdir(); (project / "app.py").write_text("x = 1\n" * 501, encoding="utf-8")
    app, client = make_client(tmp_path); token = app.state.csrf_token
    created = client.post("/api/projects", headers={"X-ArchCoach-Token": token}, json={"path": str(project)}).json()
    from archcoach.review import ReviewEngine
    from tests.test_review import OfflineCodex
    review_id = ReviewEngine(app.state.settings, app.state.store, OfflineCodex()).run(created["id"])
    blobs_before = sorted(path.relative_to(app.state.settings.blob_dir) for path in app.state.settings.blob_dir.rglob("*") if path.is_file())

    page = client.get(f"/reviews/{review_id}")
    assert page.status_code == 200
    assert "Analysis coverage" in page.text
    assert 'sandbox="allow-scripts"' in page.text
    assert "Checking current files" in page.text
    assert "Saved review:" in page.text
    report = client.get(f"/artifacts/{review_id}/report?download=true")
    assert report.status_code == 200
    assert "attachment" in report.headers["content-disposition"]
    assert "## Repository quiz" in report.text
    assert report.text.count("### ") >= 10
    current = client.get(f"/api/reviews/{review_id}/current-status")
    assert current.json()["status"] == "matches"
    blobs_after = sorted(path.relative_to(app.state.settings.blob_dir) for path in app.state.settings.blob_dir.rglob("*") if path.is_file())
    assert blobs_after == blobs_before

    (project / "app.py").unlink(); project.rmdir()
    assert client.get(f"/reviews/{review_id}").status_code == 200
    unavailable = client.get(f"/api/reviews/{review_id}/current-status")
    assert unavailable.json()["status"] == "folder_unavailable"


def test_repository_quiz_checks_explains_and_persists_answers(tmp_path: Path):
    project = tmp_path / "project"; project.mkdir(); (project / "app.py").write_text("value = 1\n", encoding="utf-8")
    app, client = make_client(tmp_path); token = app.state.csrf_token
    created = client.post("/api/projects", headers={"X-ArchCoach-Token": token}, json={"path": str(project)}).json()
    from archcoach.review import ReviewEngine
    from tests.test_review import OfflineCodex
    review_id = ReviewEngine(app.state.settings, app.state.store, OfflineCodex()).run(created["id"])
    review = app.state.store.get_review(review_id)
    assert len(review["critique"]["quiz"]) == 10
    question = review["critique"]["quiz"][0]
    wrong_index = next(index for index in range(4) if index != question["correct_index"])

    denied = client.post(f"/reviews/{review_id}/quiz/{question['id']}", json={"selected_index": wrong_index})
    assert denied.status_code == 403
    result = client.post(
        f"/reviews/{review_id}/quiz/{question['id']}",
        headers={"X-ArchCoach-Token": token}, json={"selected_index": wrong_index},
    )
    assert result.status_code == 200
    assert result.json()["correct"] is False
    assert result.json()["explanation"] == question["explanations"][wrong_index]
    assert result.json()["correct_answer"] == question["options"][question["correct_index"]]
    assert app.state.store.quiz_answers(review_id)[question["id"]]["selected_index"] == wrong_index
    page = client.get(f"/reviews/{review_id}")
    assert 'id="quiz-answered">1</span>/10 answered' in page.text
    assert 'id="quiz-score">0</span> correct' in page.text
    assert question["explanations"][wrong_index] in page.text
    malformed = client.post(
        f"/reviews/{review_id}/quiz/{question['id']}",
        headers={"X-ArchCoach-Token": token, "Content-Type": "application/json"},
        content="{invalid",
    )
    assert malformed.status_code == 422


def test_running_review_keeps_provider_settings_until_next_job(tmp_path: Path, monkeypatch):
    from archcoach.ai import CodexAdapter
    from tests.test_history import CompleteCodex

    project = tmp_path / "project"
    project.mkdir()
    (project / "app.py").write_text("value = 1\n", encoding="utf-8")
    app, client = make_client(tmp_path)
    headers = {"X-ArchCoach-Token": app.state.csrf_token}
    created = client.post("/api/projects", headers=headers, json={"path": str(project)}).json()
    seen = []
    changed = False
    fixture = CompleteCodex()

    def run_structured(adapter, prompt, schema, *args, **kwargs):
        nonlocal changed
        seen.append(adapter.settings.ai_provider)
        if not changed:
            changed = True
            assert client.patch("/api/settings", headers=headers, json={"ai_provider": "ollama"}).status_code == 200
        return fixture.run_structured(prompt, schema, *args, **kwargs)

    monkeypatch.setattr(CodexAdapter, "run_structured", run_structured)
    from archcoach.ollama import OllamaAdapter
    monkeypatch.setattr(OllamaAdapter, "run_structured", run_structured)
    monkeypatch.setattr("archcoach.review.render_diagram", lambda *args, **kwargs: {"renderer": "unavailable"})
    engine = app.state.worker.engine
    first = engine.run(created["id"], force=True)
    assert seen == ["codex", "codex"]
    second = engine.run(created["id"], force=True)
    assert seen == ["codex", "codex", "ollama", "ollama"]
    assert first != second


def test_settings_local_provider_does_not_require_codex(tmp_path: Path, monkeypatch):
    from archcoach.ollama import OllamaAdapter
    monkeypatch.setattr("archcoach.ai.CodexAdapter.status", lambda self: (_ for _ in ()).throw(AssertionError("Codex must not be inspected")))
    monkeypatch.setattr(OllamaAdapter, "models", lambda self:["qwen3.6:27b"])
    app, client = make_client(tmp_path)
    response = client.patch("/api/settings", json={"ai_provider":"ollama", "codex_command":"missing-codex", "ollama_model":"qwen3.6:27b"}, headers={"X-ArchCoach-Token":app.state.csrf_token})
    assert response.status_code == 200
    page = client.get("/settings?refresh=true")
    assert page.status_code == 200
    assert "Local Ollama ready: qwen3.6:27b" in page.text
    assert isinstance(app.state.worker.engine.codex, OllamaAdapter)


def test_settings_lmstudio_provider_does_not_require_codex(tmp_path: Path, monkeypatch):
    from archcoach.lmstudio import LMStudioAdapter
    monkeypatch.setattr("archcoach.ai.CodexAdapter.status", lambda self: (_ for _ in ()).throw(AssertionError("Codex must not be inspected")))
    monkeypatch.setattr(LMStudioAdapter, "models", lambda self: ["lmstudio-community/Qwen3.8-27B-GGUF"])
    app, client = make_client(tmp_path)
    response = client.patch("/api/settings", json={"ai_provider": "lmstudio", "codex_command": "missing-codex", "lmstudio_model": "lmstudio-community/Qwen3.8-27B-GGUF"}, headers={"X-ArchCoach-Token": app.state.csrf_token})
    assert response.status_code == 200
    page = client.get("/settings?refresh=true")
    assert page.status_code == 200
    assert "Local LM Studio ready: lmstudio-community/Qwen3.8-27B-GGUF" in page.text
    assert isinstance(app.state.worker.engine.codex, LMStudioAdapter)
def test_conversation_endpoint_keeps_saved_review_boundary(tmp_path: Path):
    from archcoach.review import ReviewEngine
    from tests.test_review import OfflineCodex
    project = tmp_path / 'project'
    project.mkdir()
    (project / 'app.py').write_text('x = 1\n', encoding='utf-8')
    app, client = make_client(tmp_path)
    from archcoach.models import ProjectCreate
    stored = app.state.store.add_project(ProjectCreate(path=str(project), name='Example'))
    review_id = ReviewEngine(app.state.settings, app.state.store, OfflineCodex()).run(stored['id'])
    conversation = app.state.store.conversation_for_review(review_id)
    app.state.store.add_message(conversation['id'], 'assistant', '<script>saved answer</script>')
    (project / 'app.py').unlink()
    response = client.get(f'/api/reviews/{review_id}/conversation')
    assert response.status_code == 200
    assert response.json()['review_id'] == review_id
    assert response.json()['messages'][0]['content'] == '<script>saved answer</script>'
    assert client.get('/api/reviews/missing/conversation').status_code == 404

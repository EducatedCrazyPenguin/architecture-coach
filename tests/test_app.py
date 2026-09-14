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
        f"/projects/{created['id']}/settings?token={token}",
        data={"name": "Form update", "description": "Updated in the dashboard", "goal": "Ship it", "exclusions": "reports/**\ncache/", "interval_days": "21", "enabled": "on"},
        follow_redirects=False,
    )
    assert form_response.status_code == 303
    assert form_response.headers["location"] == "/settings?saved=true"
    form_saved = client.get(f"/api/projects/{created['id']}").json()
    assert form_saved["name"] == "Form update"
    assert form_saved["enabled"] == 1
    assert form_saved["exclusions"] == ["reports/**", "cache/"]


def test_review_history_can_compare_any_two_snapshots(tmp_path: Path):
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

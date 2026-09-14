from pathlib import Path

from fastapi.testclient import TestClient

from archcoach.app import create_app
from archcoach.config import Settings


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


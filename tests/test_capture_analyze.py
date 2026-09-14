from pathlib import Path

from archcoach.analyze import analyze_snapshot
from archcoach.capture import capture_project, read_blob
from archcoach.config import Settings


def test_capture_excludes_secrets_and_maps_python_imports(tmp_path: Path):
    project = tmp_path / "sample"
    project.mkdir()
    (project / "main.py").write_text("from helper import work\nwork()\n", encoding="utf-8")
    (project / "helper.py").write_text("def work():\n    return 1\n", encoding="utf-8")
    (project / ".env").write_text("SECRET=do-not-copy", encoding="utf-8")
    settings = Settings.load(tmp_path / "data"); settings.ensure_dirs()

    capture = capture_project(settings, {"path": str(project), "exclusions": []})
    paths = {entry["path"] for entry in capture["manifest"]}
    assert paths == {"helper.py", "main.py"}
    assert all(b"do-not-copy" not in read_blob(settings, entry["sha256"]) for entry in capture["manifest"])

    analysis = analyze_snapshot(settings, capture["manifest"])
    assert {("main.py", "helper.py")}.issubset({(edge["source"], edge["target"]) for edge in analysis["edges"]})


def test_capture_fingerprint_changes_with_current_files(tmp_path: Path):
    project = tmp_path / "project"; project.mkdir(); source = project / "app.py"
    settings = Settings.load(tmp_path / "data"); settings.ensure_dirs()
    source.write_text("value = 1\n", encoding="utf-8")
    first = capture_project(settings, {"path": str(project), "exclusions": []})
    source.write_text("value = 2\n", encoding="utf-8")
    second = capture_project(settings, {"path": str(project), "exclusions": []})
    assert first["fingerprint"] != second["fingerprint"]


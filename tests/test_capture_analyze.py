from pathlib import Path

from archcoach.analyze import analyze_snapshot
from archcoach.capture import capture_project, fingerprint_project, git_context, read_blob
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


def test_capture_applies_gitignore_and_directory_exclusions(tmp_path: Path):
    project = tmp_path / "project with spaces"
    project.mkdir()
    (project / ".gitignore").write_text("ignored.json\nnested/private.json\n", encoding="utf-8")
    (project / "kept.py").write_text("value = 1\n", encoding="utf-8")
    (project / "ignored.json").write_text('{"secret": false}\n', encoding="utf-8")
    (project / "scratch").mkdir()
    (project / "scratch" / "draft.py").write_text("draft = True\n", encoding="utf-8")
    (project / "nested").mkdir()
    (project / "nested" / "private.json").write_text("{}\n", encoding="utf-8")
    import subprocess
    subprocess.run(["git", "init", str(project)], check=True, capture_output=True)
    settings = Settings.load(tmp_path / "data")
    settings.ensure_dirs()

    capture = capture_project(settings, {"path": str(project), "exclusions": ["scratch/"]})

    assert {entry["path"] for entry in capture["manifest"]} == {"kept.py"}
    assert capture["git"]["is_git"] is True


def test_fingerprint_check_does_not_write_blobs_and_counts_lines(tmp_path: Path):
    project = tmp_path / "plain"
    project.mkdir()
    (project / "main.py").write_text("one\ntwo\n", encoding="utf-8")
    settings = Settings.load(tmp_path / "data")
    settings.ensure_dirs()

    result = fingerprint_project(settings, {"path": str(project), "exclusions": []})

    assert result["manifest"][0]["lines"] == 2
    assert list(settings.blob_dir.rglob("*")) == []


def test_git_worktree_is_detected_without_git_directory(tmp_path: Path):
    import subprocess

    repository = tmp_path / "repository"
    worktree = tmp_path / "linked worktree"
    repository.mkdir()
    subprocess.run(["git", "init", str(repository)], check=True, capture_output=True)
    (repository / "app.py").write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repository), "add", "app.py"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repository), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "fixture"],
        check=True, capture_output=True,
    )
    subprocess.run(["git", "-C", str(repository), "worktree", "add", "-b", "fixture-worktree", str(worktree)], check=True, capture_output=True)

    context = git_context(worktree)

    assert (worktree / ".git").is_file()
    assert context["is_git"] is True
    assert context["branch"] == "fixture-worktree"
    assert context["detached"] is False


def test_capture_retries_the_whole_inventory_and_marks_persistent_edits(tmp_path: Path, monkeypatch):
    import archcoach.capture as capture_module

    project = tmp_path / "changing"
    project.mkdir()
    (project / "app.py").write_text("value = 1\n", encoding="utf-8")
    settings = Settings.load(tmp_path / "data")
    settings.ensure_dirs()
    calls = 0

    def changing_inventory(paths, root):
        nonlocal calls
        calls += 1
        return [("app.py", calls % 2, calls)]

    monkeypatch.setattr(capture_module, "_inventory", changing_inventory)
    result = capture_project(settings, {"path": str(project), "exclusions": []})

    assert calls == 4
    assert result["unstable"] is True
    assert result["coverage"] == "limited"

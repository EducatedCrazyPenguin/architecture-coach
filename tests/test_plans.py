from __future__ import annotations

from pathlib import Path
import os
import subprocess
import json

import pytest
from fastapi.testclient import TestClient

from archcoach.app import create_app
from archcoach.config import Settings
from archcoach.models import ImprovementPlanDraft, ProjectCreate
from archcoach.plans import PlanConflict, PlanError, PlanService, _safe_path, validate_plan
from archcoach.review import ReviewCancelled, ReviewEngine
from archcoach.subprocesses import ProcessCancelled
from tests.test_history import CompleteCodex


class FindingCodex(CompleteCodex):
    def run_structured(self, prompt, schema, *args, **kwargs):
        if schema.name != "critique.json":
            return super().run_structured(prompt, schema, *args, **kwargs)
        output = super().run_structured(prompt, schema, *args, **kwargs)
        output["findings"] = [{
            "id": "one", "severity": "medium", "title": "Isolate formatting",
            "observation": "Formatting is combined with the entry point.",
            "why_it_matters": "The entry point can grow hard to read.",
            "improvement": "Extract formatting without changing output.",
            "tradeoffs": "Adds one small helper.",
            "evidence": [{"path": "app.py", "line": 1, "end_line": None, "label": "Entry point", "valid": True}],
        }]
        return output


def draft() -> dict:
    return {
        "change_id": "extract-formatting", "kind": "refactor",
        "proposal": "# Proposal\n\n## Why\nKeep formatting separate from entry code.\n\n## What Changes\nExtract a small pure helper.\n\n## Capabilities\nNo behavior change.\n\n## Impact\nOnly app.py changes.\n",
        "design": "# Design\n\n## Context\nThe fixture is small and formatting sits in the entry point.\n\n## Goals / Non-Goals\nPreserve exact output.\n\n## Decisions\nUse one pure helper.\n\n## Risks / Trade-offs\nAn extra function adds navigation.\n",
        "tasks": "# Tasks\n\n- [ ] 1. Extract the formatting expression into a pure helper in app.py.\n- [ ] 2. Assert the public output is unchanged and run pytest.\n",
        "specs": [],
        "evidence": [{"path": "app.py", "line": 1, "end_line": None, "label": "Entry point", "valid": True}],
    }


class PlanProvider:
    last_usage = {}

    def run_structured(self, *_args, **_kwargs):
        return draft()


@pytest.fixture
def prepared(tmp_path: Path):
    source = tmp_path / "project with spaces"
    source.mkdir()
    (source / "app.py").write_text("value = 1\n", encoding="utf-8")
    settings = Settings(data_dir=tmp_path / "data", app_dir=Path(__file__).parents[1] / "src" / "archcoach")
    settings.ensure_dirs()
    app = create_app(settings, start_worker=False)
    project = app.state.store.add_project(ProjectCreate(path=str(source)))
    review_id = ReviewEngine(settings, app.state.store, FindingCodex()).run(project["id"])
    return source, app, review_id


def test_pinned_cli_validates_staged_refactor(prepared):
    _, app, review_id = prepared
    snapshot = app.state.store.get_snapshot(app.state.store.get_review(review_id)["snapshot_id"])
    assert validate_plan(app.state.settings, snapshot, ImprovementPlanDraft.model_validate(draft()))["valid"]


def test_generation_is_read_only_and_approval_is_exact_and_idempotent(prepared):
    source, app, review_id = prepared
    service = PlanService(app.state.settings, app.state.store, PlanProvider())
    plan_id = service.generate(review_id, "one")
    plan = app.state.store.get_plan(plan_id)
    assert plan["status"] == "ready"
    assert not (source / "openspec").exists()
    with pytest.raises(PlanConflict):
        service.publish(plan_id, "0" * 64)
    receipt = service.publish(plan_id, plan["draft_hash"])
    assert (source / receipt["path"] / "tasks.md").is_file()
    assert service.publish(plan_id, plan["draft_hash"]) == receipt
    (source / receipt["path"] / "tasks.md").write_text("user edit", encoding="utf-8")
    with pytest.raises(PlanConflict):
        service.publish(plan_id, plan["draft_hash"])


def test_stale_source_blocks_publication(prepared):
    source, app, review_id = prepared
    service = PlanService(app.state.settings, app.state.store, PlanProvider())
    plan_id = service.generate(review_id, "one")
    (source / "app.py").write_text("value = 2\n", encoding="utf-8")
    with pytest.raises(PlanConflict, match="changed"):
        service.publish(plan_id, app.state.store.get_plan(plan_id)["draft_hash"])
    assert not (source / "openspec").exists()


def test_revision_creates_a_new_immutable_draft(prepared):
    _, app, review_id = prepared
    service = PlanService(app.state.settings, app.state.store, PlanProvider())
    first_id = service.generate(review_id, "one")
    second_id = service.generate(review_id, "one", "Keep the greeting unchanged", parent_id=first_id)
    assert second_id != first_id
    assert app.state.store.get_plan(second_id)["parent_id"] == first_id
    assert app.state.store.get_plan(first_id)["parent_id"] is None


def test_plan_api_preview_and_csrf(prepared):
    _, app, review_id = prepared
    token = app.state.csrf_token
    client = TestClient(app)
    response = client.post(f"/api/reviews/{review_id}/plans", json={"finding_id": "one"})
    assert response.status_code == 403
    response = client.post(f"/api/reviews/{review_id}/plans", json={"finding_id": "one"}, headers={"X-ArchCoach-Token": token})
    assert response.status_code == 202
    assert app.state.store.get_job(response.json()["job_id"])["operation"] == "plan"
    plan_id = PlanService(app.state.settings, app.state.store, PlanProvider()).generate(review_id, "one")
    assert "Exact planning files" in client.get(f"/plans/{plan_id}").text
    assert "Copy Codex handoff" in client.get(f"/plans/{plan_id}").text
    assert client.get(f"/plans/{plan_id}/download").status_code == 200
    revision = client.post(f"/plans/{plan_id}/revise", data={"_csrf": token, "instruction": "Keep the public output unchanged"}, follow_redirects=False)
    assert revision.status_code == 303
    revision_job = app.state.store.get_job(revision.headers["location"].split("/")[-1])
    assert revision_job["payload"]["parent_id"] == plan_id


def test_invalid_plan_is_retained_but_cannot_be_published(prepared):
    source, app, review_id = prepared

    class BrokenProvider(PlanProvider):
        calls = 0

        def run_structured(self, *_args, **_kwargs):
            self.calls += 1
            value = draft()
            value["tasks"] = "# Tasks\n\n- [ ] Improve architecture.\n"
            value["evidence"][0]["path"] = "missing.py"
            return value

    provider = BrokenProvider()
    service = PlanService(app.state.settings, app.state.store, provider)
    plan_id = service.generate(review_id, "one")
    plan = app.state.store.get_plan(plan_id)
    assert provider.calls == 2
    assert plan["status"] == "needs_revision"
    assert not (source / "openspec").exists()
    with pytest.raises(PlanConflict):
        service.publish(plan_id, plan["draft_hash"])


def test_pinned_cli_rejects_malformed_delta_and_unavailable_runtime(prepared, monkeypatch):
    _, app, review_id = prepared
    snapshot = app.state.store.get_snapshot(app.state.store.get_review(review_id)["snapshot_id"])
    data = draft()
    data["kind"] = "behavior_change"
    data["specs"] = [{"capability": "greeting", "content": "# Spec Delta\n\n## ADDED Requirements\n\n### Requirement: Greeting\nThe app SHALL greet users but has no scenario.\n"}]
    assert not validate_plan(app.state.settings, snapshot, ImprovementPlanDraft.model_validate(data))["valid"]
    monkeypatch.setattr("archcoach.plans.find_node", lambda: None)
    assert "unavailable" in validate_plan(app.state.settings, snapshot, ImprovementPlanDraft.model_validate(draft()))["error"]


def test_publication_recovers_after_receipt_interruption(prepared, monkeypatch):
    source, app, review_id = prepared
    service = PlanService(app.state.settings, app.state.store, PlanProvider())
    plan_id = service.generate(review_id, "one")
    plan = app.state.store.get_plan(plan_id)
    original = app.state.store.publish_plan_receipt
    monkeypatch.setattr(app.state.store, "publish_plan_receipt", lambda *_args: (_ for _ in ()).throw(RuntimeError("interrupted")))
    with pytest.raises(RuntimeError, match="interrupted"):
        service.publish(plan_id, plan["draft_hash"])
    assert (source / "openspec" / "changes" / "extract-formatting" / "proposal.md").is_file()
    monkeypatch.setattr(app.state.store, "publish_plan_receipt", original)
    assert service.publish(plan_id, plan["draft_hash"])["change_id"] == "extract-formatting"


def test_cancellation_and_traversal_stop_before_write(prepared):
    source, app, review_id = prepared
    service = PlanService(app.state.settings, app.state.store, PlanProvider())
    with pytest.raises(ReviewCancelled):
        service.generate(review_id, "one", cancelled=lambda: True)
    with pytest.raises(PlanError):
        _safe_path(source, "../outside")
    assert not (source / "openspec").exists()


def test_staged_validator_reports_timeout(prepared, monkeypatch):
    _, app, review_id = prepared
    snapshot = app.state.store.get_snapshot(app.state.store.get_review(review_id)["snapshot_id"])

    def timed_out(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("openspec", 1)

    monkeypatch.setattr("archcoach.plans.run_cancellable", timed_out)
    result = validate_plan(app.state.settings, snapshot, ImprovementPlanDraft.model_validate(draft()))
    assert not result["valid"] and "failed" in result["error"]


def test_cancellation_during_staged_validation_leaves_no_plan(prepared, monkeypatch):
    source, app, review_id = prepared

    def interrupted(*_args, **_kwargs):
        raise ProcessCancelled("cancelled")

    monkeypatch.setattr("archcoach.plans.run_cancellable", interrupted)
    with pytest.raises(ReviewCancelled):
        PlanService(app.state.settings, app.state.store, PlanProvider()).generate(review_id, "one")
    assert app.state.store.list_plans(review_id) == []
    assert not (source / "openspec").exists()


def test_plan_queue_runs_after_chat_before_review(prepared):
    _, app, review_id = prepared
    store = app.state.store
    project_id = store.get_review(review_id)["project_id"]
    store.enqueue("review", project_id, priority=10)
    store.enqueue("plan", None, {"finding_id": "one"}, review_id=review_id, priority=5)
    store.enqueue("chat", None, {"message": "Question"}, review_id=review_id, priority=1)
    assert [store.next_job()["operation"] for _ in range(3)] == ["chat", "plan", "review"]


def test_reparse_escape_is_rejected_when_windows_allows_link_creation(prepared, tmp_path: Path):
    source, _, _ = prepared
    outside = tmp_path / "outside"
    outside.mkdir()
    link = source / "openspec"
    if os.name == "nt":
        created = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True)
        assert created.returncode == 0, created.stderr.decode("utf-8", "replace")
    else:
        os.symlink(outside, link, target_is_directory=True)
    with pytest.raises(PlanError):
        _safe_path(source, "openspec/changes/unsafe")


def test_older_review_without_specification_index_stays_readable(prepared):
    _, app, review_id = prepared
    store = app.state.store
    snapshot = store.get_snapshot(store.get_review(review_id)["snapshot_id"])
    analysis = dict(snapshot["analysis"])
    analysis.pop("specifications", None)
    with store.connect() as connection:
        connection.execute("UPDATE snapshots SET analysis_json=?,format_version=2 WHERE id=?", (json.dumps(analysis), snapshot["id"]))
    page = TestClient(app).get(f"/reviews/{review_id}")
    assert page.status_code == 200
    assert "No standard main OpenSpec requirements" in page.text

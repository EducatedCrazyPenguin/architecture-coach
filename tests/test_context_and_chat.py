from __future__ import annotations

from pathlib import Path

import pytest

from archcoach.ai import CodexAuthenticationError
from archcoach.capture import capture_project
from archcoach.config import Settings
from archcoach.context import bounded_history, build_source_packets
from archcoach.db import Store
from archcoach.models import ProjectCreate
from archcoach.review import ReviewEngine
from tests.test_history import CompleteCodex


def test_source_packets_are_deterministic_prioritised_and_bounded(tmp_path: Path):
    project = tmp_path / "source"
    project.mkdir()
    for index in range(10):
        name = "package.json" if index == 9 else f"file{index}.py"
        (project / name).write_text((f"value_{index} = {index}\n" * 8), encoding="utf-8")
    settings = Settings(
        data_dir=tmp_path / "data", app_dir=Path(__file__).parents[1] / "src" / "archcoach",
        source_packet_chars=240, source_packet_limit=2,
    )
    settings.ensure_dirs()
    captured = capture_project(settings, {"path": str(project), "exclusions": []})
    analysis = {"edges": []}

    packets, note = build_source_packets(settings, captured["manifest"], analysis)

    assert packets.count("SOURCE PACKET") <= 2
    assert packets.index("package.json") < packets.index("file0.py")
    assert "Omitted" in note


def test_chat_history_obeys_message_and_character_budgets(tmp_path: Path):
    settings = Settings.load(tmp_path / "data")
    object.__setattr__(settings, "chat_history_messages", 3)
    object.__setattr__(settings, "chat_history_chars", 40)
    messages = [{"role": "user", "content": f"message {index} with text"} for index in range(8)]

    history, note = bounded_history(messages, settings)

    assert len(history) <= 40
    assert "older message" in note
    assert "message 7" in history


class CapturingChatCodex:
    def __init__(self):
        self.prompt = ""
        self.cwd_items = None

    def run_structured(self, prompt, _schema, cwd, **_kwargs):
        self.prompt = prompt
        self.cwd_items = list(cwd.iterdir())
        return {
            "answer": "The saved value is cited.",
            "citations": [{"path": "app.py", "line": 1, "end_line": 1, "label": "Saved value", "valid": True}],
        }


def setup_review(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    file = source / "app.py"
    file.write_text("saved_value = 1\n", encoding="utf-8")
    settings = Settings(data_dir=tmp_path / "data", app_dir=Path(__file__).parents[1] / "src" / "archcoach")
    settings.ensure_dirs()
    store = Store(settings.db_path)
    project = store.add_project(ProjectCreate(path=str(source)))
    engine = ReviewEngine(settings, store, CompleteCodex())
    return file, store, engine, engine.run(project["id"])


def test_chat_uses_saved_snapshot_and_empty_runtime_workspace(tmp_path: Path):
    file, store, engine, review_id = setup_review(tmp_path)
    file.write_text("current_value = 999\n", encoding="utf-8")
    capturing = CapturingChatCodex()
    engine.codex = capturing

    engine.chat(review_id, "What value was saved?")

    assert "saved_value = 1" in capturing.prompt
    assert "current_value = 999" not in capturing.prompt
    assert capturing.cwd_items == []
    message = store.conversation_for_review(review_id)["messages"][-1]
    assert message["status"] == "complete"
    assert message["citations"][0]["valid"] is True


def test_chat_discloses_when_older_messages_are_outside_context(tmp_path: Path):
    _, store, engine, review_id = setup_review(tmp_path)
    conversation = store.conversation_for_review(review_id)
    for index in range(12):
        store.add_message(conversation["id"], "user", f"older {index}")
    engine.codex = CapturingChatCodex()

    engine.chat(review_id, "latest question")

    answer = store.conversation_for_review(review_id)["messages"][-1]["content"]
    assert answer.startswith("Context note:")
    assert "older message(s) are outside the active context" in answer


class FailingChatCodex:
    def run_structured(self, *_args, **_kwargs):
        raise CodexAuthenticationError("login expired")


def test_instructor_job_tracks_streaming_and_repair_usage(tmp_path: Path):
    _, store, engine, review_id = setup_review(tmp_path)
    class StreamingRepair(CapturingChatCodex):
        calls = 0
        last_usage = {}
        def run_structured(self, prompt, schema, cwd, **kwargs):
            self.calls += 1
            self.last_usage = {"input_tokens":10, "output_tokens":3}
            kwargs["on_event"]({"type":"turn.completed", "usage":self.last_usage})
            if self.calls == 1:
                return {"not_an_answer":True}
            return super().run_structured(prompt, schema, cwd, **kwargs)
    engine.codex = StreamingRepair()
    job_id = store.enqueue("chat", None, {"message":"Explain"}, review_id=review_id, priority=1)
    store.claim_job(job_id)
    engine.chat(review_id, "Explain", job_id=job_id)
    job = store.get_job(job_id)
    assert job["stage"] == "instructor"
    assert job["usage"] == {"input_tokens":20, "output_tokens":6}


def test_chat_failure_is_persisted_as_failed_and_raised_to_job(tmp_path: Path):
    _, store, engine, review_id = setup_review(tmp_path)
    engine.codex = FailingChatCodex()

    with pytest.raises(CodexAuthenticationError):
        engine.chat(review_id, "question")

    message = store.conversation_for_review(review_id)["messages"][-1]
    assert message["role"] == "assistant"
    assert message["status"] == "failed"


class RepairingCodex(CompleteCodex):
    def __init__(self):
        self.architecture_calls = 0

    def run_structured(self, prompt, schema, *args, **kwargs):
        if schema.name == "architecture.json":
            self.architecture_calls += 1
            if self.architecture_calls == 1:
                return {"summary": "invalid", "main_path": [], "components": [], "relationships": []}
        return super().run_structured(prompt, schema, *args, **kwargs)


def test_final_pass_gets_at_most_one_schema_repair(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.py").write_text("value = 1\n")
    settings = Settings(data_dir=tmp_path / "data", app_dir=Path(__file__).parents[1] / "src" / "archcoach")
    settings.ensure_dirs()
    store = Store(settings.db_path)
    project = store.add_project(ProjectCreate(path=str(source)))
    codex = RepairingCodex()

    review_id = ReviewEngine(settings, store, codex).run(project["id"])

    assert codex.architecture_calls == 2
    assert store.get_review(review_id)["quality"] == "complete"

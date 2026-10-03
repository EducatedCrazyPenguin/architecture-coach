import io
import json
from dataclasses import replace

import pytest

from archcoach.ai import CodexCancelledError, CodexMalformedOutput, CodexTimeoutError, create_adapter
from archcoach.config import Settings
from archcoach.prism import PrismAdapter, PrismUnavailable
from tests.test_lmstudio import Connection


def local_fixture(tmp_path, monkeypatch, content='{"answer":"Bonsai","citations":[]}', done=True):
    settings = replace(Settings.load(tmp_path / "data"), ai_provider="prism", codex_command="missing-codex")
    key_file = settings.data_dir / "prism" / "server.key"
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_text("synthetic-runtime-key", encoding="utf-8")
    adapter = create_adapter(settings)
    assert isinstance(adapter, PrismAdapter)
    monkeypatch.setattr(adapter, "models", lambda: ["ternary-bonsai-2-27b"])
    monkeypatch.setattr(adapter, "_ensure_model_context", lambda model, timeout: None)
    events = ["data: " + json.dumps({"choices": [{"delta": {"content": content}}]})]
    if done:
        events += ["data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 9, "completion_tokens": 4}}), "data: [DONE]"]
    connection = Connection(io.BytesIO(("\n\n".join(events) + "\n\n").encode()))
    monkeypatch.setattr(adapter, "_connection", lambda timeout: connection)
    return adapter, connection, settings.schema_dir / "chat.json"


def test_bonsai_uses_only_selected_model_and_supported_structured_parameters(tmp_path, monkeypatch):
    adapter, connection, schema = local_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr("subprocess.Popen", lambda *a, **kw: pytest.fail("Codex must not run"))
    events = []
    assert adapter.run_structured("Saved source", schema, tmp_path, on_event=events.append)["answer"] == "Bonsai"
    body = json.loads(connection.requests[0][1]["body"])
    assert body["model"] == "ternary-bonsai-2-27b"
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["response_format"]["json_schema"]["schema"] == json.loads(schema.read_text())
    assert body["response_format"]["json_schema"]["strict"] is True
    assert json.dumps(json.loads(schema.read_text()), separators=(",", ":")) in body["messages"][0]["content"]
    assert body["stream_options"]["include_usage"] is True
    assert body["max_tokens"] >= 16384
    assert "tools" not in body
    assert "/no_think" not in body["messages"][1]["content"]
    assert adapter.last_usage == {"input_tokens": 9, "output_tokens": 4}
    assert all(event["provider"] == "prism" for event in events)
    assert connection.closed


@pytest.mark.parametrize("content,done", [("not json", True), ("{}", False)])
def test_prism_rejects_malformed_and_incomplete_output(tmp_path, monkeypatch, content, done):
    adapter, connection, schema = local_fixture(tmp_path, monkeypatch, content, done)
    with pytest.raises(CodexMalformedOutput):
        adapter.run_structured("source", schema, tmp_path)
    assert connection.closed


def test_prism_missing_server_or_model_has_no_fallback(tmp_path, monkeypatch):
    adapter, connection, schema = local_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(adapter, "models", lambda: [])
    with pytest.raises(PrismUnavailable, match="Start Bonsai Local"):
        adapter.run_structured("source", schema, tmp_path)
    assert not connection.requests


def test_prism_context_and_cancellation_are_checked(tmp_path, monkeypatch):
    adapter = PrismAdapter(replace(Settings.load(tmp_path / "data"), ai_provider="prism"))
    key_file = adapter.settings.data_dir / "prism" / "server.key"
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_text("synthetic-runtime-key", encoding="utf-8")
    connection = Connection(io.BytesIO(json.dumps({"default_generation_settings": {"n_ctx": 4096}}).encode()))
    monkeypatch.setattr(adapter, "_connection", lambda timeout: connection)
    with pytest.raises(PrismUnavailable, match="32768"):
        adapter._ensure_model_context("ternary-bonsai-2-27b", 30)
    assert connection.closed
    adapter, connection, schema = local_fixture(tmp_path, monkeypatch)
    with pytest.raises(CodexCancelledError):
        adapter.run_structured("source", schema, tmp_path, cancelled=lambda: True)
    assert not connection.requests


def test_missing_private_key_never_sends_an_unauthenticated_request(tmp_path, monkeypatch):
    adapter = PrismAdapter(replace(Settings.load(tmp_path / "data"), ai_provider="prism"))
    connection = Connection(io.BytesIO(b'{}'))
    monkeypatch.setattr(adapter, "_connection", lambda timeout: connection)
    assert adapter.status()["ready"] is False
    assert not connection.requests
    assert connection.closed


def test_private_runtime_key_is_sent_only_to_fixed_loopback_connection(tmp_path, monkeypatch):
    adapter, connection, schema = local_fixture(tmp_path, monkeypatch)
    key_file = adapter.settings.data_dir / "prism" / "server.key"
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_text("synthetic-runtime-key", encoding="utf-8")
    adapter.run_structured("saved source", schema, tmp_path)
    assert connection.requests[0][1]["headers"]["Authorization"] == "Bearer synthetic-runtime-key"
    assert "synthetic-runtime-key" not in connection.requests[0][1]["body"].decode()
    assert adapter._connection(1) is connection
    assert adapter.port == 1235


def test_prism_timeout_closes_stream(tmp_path, monkeypatch):
    import time
    adapter, connection, schema = local_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(connection, "readline", lambda limit: (time.sleep(0.3), b"")[1])
    with pytest.raises(CodexTimeoutError):
        adapter.run_structured("source", schema, tmp_path, timeout=0.05)
    assert connection.closed


def test_bonsai_operations_share_the_selected_transport_and_saved_source(tmp_path, monkeypatch):
    from archcoach.db import Store
    from archcoach.models import ProjectCreate
    from archcoach.plans import PlanService
    from archcoach.review import ReviewEngine, review_configuration_fingerprint
    from tests.test_plans import FindingCodex, draft
    source = tmp_path / "project with spaces"
    source.mkdir()
    file = source / "app.py"
    original = "value = 1\n"
    file.write_text(original)
    settings = replace(Settings.load(tmp_path / "data"), ai_provider="prism", codex_command="missing-codex")
    settings.ensure_dirs()
    key_file = settings.data_dir / "prism" / "server.key"
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_text("synthetic-runtime-key", encoding="utf-8")
    store = Store(settings.db_path)
    project = store.add_project(ProjectCreate(path=str(source)))
    monkeypatch.setattr(PrismAdapter, "models", lambda self: ["ternary-bonsai-2-27b"])
    monkeypatch.setattr(PrismAdapter, "_ensure_model_context", lambda *args: None)
    calls = []
    fixture = FindingCodex()

    class ModelConnection(Connection):
        def request(self, *args, **kwargs):
            super().request(*args, **kwargs)
            body = json.loads(kwargs["body"])
            assert body["model"] == "ternary-bonsai-2-27b"
            prompt = body["messages"][1]["content"]
            properties = body["response_format"]["json_schema"]["schema"]["properties"]
            if "components" in properties:
                schema = settings.schema_dir / "architecture.json"
                result = fixture.run_structured(prompt, schema)
            elif "quiz" in properties:
                schema = settings.schema_dir / "critique.json"
                result = fixture.run_structured(prompt, schema)
            elif "proposal" in properties:
                schema = settings.schema_dir / "improvement_plan.json"
                result = draft()
            else:
                schema = settings.schema_dir / "chat.json"
                result = {"answer": "app.py owns the saved value.", "citations": [{"path": "app.py", "line": 1, "end_line": 1, "label": "Saved value", "valid": True}]}
                assert original.strip() in prompt
                assert "current_value = 999" not in prompt
            calls.append(schema.name)
            events = [{"choices": [{"delta": {"content": json.dumps(result)}}]}, {"choices": [{"delta": {}, "finish_reason": "stop"}]}]
            self.events = io.BytesIO(("\n\n".join("data: " + json.dumps(event) for event in events) + "\n\n").encode())

    monkeypatch.setattr(PrismAdapter, "_connection", lambda *args: ModelConnection(io.BytesIO()))
    monkeypatch.setattr("archcoach.ai.CodexAdapter.run_structured", lambda *a, **kw: pytest.fail("No Codex execution"))
    monkeypatch.setattr("archcoach.review.render_diagram", lambda *a, **kw: {"renderer": "unavailable"})
    engine = ReviewEngine(settings, store)
    review_id = engine.run(project["id"])
    review = store.get_review(review_id)
    assert review["quality"] == "complete"
    assert len(review["critique"]["quiz"]) == 10
    assert file.read_text() == original
    plan_id = PlanService(settings, store, create_adapter(settings)).generate(review_id, "one")
    plan = store.get_plan(plan_id)
    assert plan["status"] == "ready"
    assert plan["provider"]["model"] == "ternary-bonsai-2-27b"
    assert not (source / "openspec").exists()
    file.write_text("current_value = 999\n")
    engine.chat(review_id, "Who owns the saved value?")
    messages = store.conversation_for_review(review_id)["messages"]
    assert messages[-1]["status"] == "complete"
    assert messages[-1]["citations"][0]["valid"]
    assert calls == ["architecture.json", "critique.json", "improvement_plan.json", "chat.json"]
    assert review_configuration_fingerprint(project, settings) != review_configuration_fingerprint(project, replace(settings, prism_model="other-local-model"))
    assert file.read_text() == "current_value = 999\n"


@pytest.mark.parametrize("event", [[], {"choices": "bad"}, {"choices": [{"delta": ["bad"]}]}])
def test_invalid_stream_events_are_rejected(tmp_path, monkeypatch, event):
    adapter, connection, schema = local_fixture(tmp_path, monkeypatch)
    connection.events = io.BytesIO(("data: " + json.dumps(event) + "\n\n").encode())
    with pytest.raises(CodexMalformedOutput):
        adapter.run_structured("saved source", schema, tmp_path)
    assert connection.closed

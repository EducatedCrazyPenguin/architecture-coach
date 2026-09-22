import io
import json
import time
from dataclasses import replace

import pytest

from archcoach.ai import CodexCancelledError, CodexMalformedOutput, CodexTimeoutError, create_adapter
from archcoach.config import Settings
from archcoach.lmstudio import LMStudioAdapter, LMStudioUnavailable


class Connection:
    def __init__(self, events):
        self.events = events
        self.status = 200
        self.closed = False
        self.sock = None
        self.requests = []

    def request(self, *args, **kwargs):
        self.requests.append((args, kwargs))

    def getresponse(self):
        return self

    def readline(self, limit):
        return self.events.readline(limit)

    def read(self, *args):
        return self.events.read(*args)

    def close(self):
        self.closed = True


def fixture(tmp_path, monkeypatch, content='{"answer":"local","citations":[]}', done=True):
    settings = replace(Settings.load(tmp_path / "data"), ai_provider="lmstudio", codex_command="does-not-exist")
    adapter = create_adapter(settings)
    assert isinstance(adapter, LMStudioAdapter)
    monkeypatch.setattr(adapter, "models", lambda: ["qwen/qwen3.8-27b"])
    monkeypatch.setattr(adapter, "_ensure_model_context", lambda model, timeout: None)
    events = [
        "data: " + json.dumps({"choices": [{"delta": {"content": content}, "finish_reason": None}]}),
    ]
    if done:
        events.append("data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 12, "completion_tokens": 5}}))
        events.append("data: [DONE]")
    connection = Connection(io.BytesIO(("\n\n".join(events) + "\n\n").encode()))
    monkeypatch.setattr(adapter, "_connection", lambda timeout: connection)
    return adapter, connection, settings.schema_dir / "chat.json"


def test_lmstudio_reloads_a_small_context_model_with_enough_context(tmp_path, monkeypatch):
    settings = replace(Settings.load(tmp_path / "data"), ai_provider="lmstudio")
    adapter = LMStudioAdapter(settings)
    listing = Connection(io.BytesIO(json.dumps({
        "models": [{
            "key": "qwen/qwen3.8-27b", "max_context_length": 262_144,
            "loaded_instances": [{"id": "qwen-small", "config": {"context_length": 16_384}}],
        }],
    }).encode()))
    unloading = Connection(io.BytesIO(json.dumps({"instance_id": "qwen-small"}).encode()))
    loading = Connection(io.BytesIO(json.dumps({"status": "loaded", "load_config": {"context_length": 32_768}}).encode()))
    responses = [listing, unloading, loading]
    timeouts = []
    moments = iter((0, 0, 10, 20))
    monkeypatch.setattr("archcoach.lmstudio.time.monotonic", lambda: next(moments))
    monkeypatch.setattr(adapter, "_connection", lambda timeout: (timeouts.append(timeout), responses.pop(0))[1])

    adapter._ensure_model_context("qwen/qwen3.8-27b", 60)

    assert listing.requests[0][0][:2] == ("GET", "/api/v1/models")
    assert unloading.requests[0][0][:2] == ("POST", "/api/v1/models/unload")
    assert json.loads(unloading.requests[0][1]["body"]) == {"instance_id": "qwen-small"}
    assert loading.requests[0][0][:2] == ("POST", "/api/v1/models/load")
    assert json.loads(loading.requests[0][1]["body"]) == {
        "model": "qwen/qwen3.8-27b", "context_length": 32_768, "echo_load_config": True,
    }
    assert timeouts == [3, 50, 40]


def test_lmstudio_structured_request_never_uses_codex(tmp_path, monkeypatch):
    adapter, connection, schema = fixture(tmp_path, monkeypatch)
    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: pytest.fail("No CLI should run"))
    events = []
    assert adapter.run_structured("Saved source only", schema, tmp_path, on_event=events.append)["answer"] == "local"
    body = json.loads(connection.requests[0][1]["body"])
    assert body["model"] == "qwen/qwen3.8-27b"
    assert body["response_format"]["type"] == "json_schema"
    assert body["messages"][1]["content"].endswith("/no_think")
    assert "tools" not in body
    assert adapter.last_usage == {"input_tokens": 12, "output_tokens": 5}
    assert events[-1]["type"] == "turn.completed"
    assert [event["type"] for event in events].count("turn.completed") == 1
    assert connection.closed


@pytest.mark.parametrize("content,done", [("not json", True), ("{}", False)])
def test_lmstudio_bad_or_incomplete_output_is_rejected(tmp_path, monkeypatch, content, done):
    adapter, connection, schema = fixture(tmp_path, monkeypatch, content, done)
    with pytest.raises(CodexMalformedOutput):
        adapter.run_structured("source", schema, tmp_path)
    assert connection.closed


def test_lmstudio_cancellation_and_timeout_close_request(tmp_path, monkeypatch):
    adapter, connection, schema = fixture(tmp_path, monkeypatch)
    with pytest.raises(CodexCancelledError):
        adapter.run_structured("source", schema, tmp_path, cancelled=lambda: True)
    assert not connection.requests
    adapter, connection, schema = fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(connection, "readline", lambda limit: (time.sleep(0.5), b"")[1])
    with pytest.raises(CodexTimeoutError):
        adapter.run_structured("source", schema, tmp_path, timeout=0.1)
    assert connection.closed


def test_lmstudio_missing_model_explains_how_to_continue(tmp_path, monkeypatch):
    adapter, connection, schema = fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(adapter, "models", lambda: [])
    with pytest.raises(LMStudioUnavailable, match="Load qwen/qwen3.8-27b"):
        adapter.run_structured("source", schema, tmp_path)
    assert adapter.status()["ready"] is False

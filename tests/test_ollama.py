import io
import json
import time
from dataclasses import replace
from pathlib import Path

import pytest

from archcoach.ai import create_adapter, CodexCancelledError, CodexMalformedOutput, CodexTimeoutError
from archcoach.config import Settings
from archcoach.ollama import OllamaAdapter, OllamaUnavailable


class Connection:
    def __init__(self, events, status=200):
        self.events = events
        self.status = status
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
    settings = replace(Settings.load(tmp_path / 'data'), ai_provider='ollama', codex_command='does-not-exist')
    settings.ensure_dirs()
    adapter = create_adapter(settings)
    assert isinstance(adapter, OllamaAdapter)
    monkeypatch.setattr(adapter, 'models', lambda: ['qwen3.6:27b'])
    events = [{'message': {'content': content}, 'done':False}]
    if done:
        events.append({'message':{'content':''}, 'done':True, 'prompt_eval_count':12, 'eval_count':5})
    connection = Connection(io.BytesIO(('\n'.join(json.dumps(event) for event in events)+'\n').encode()))
    monkeypatch.setattr(adapter, '_connection', lambda timeout: connection)
    return adapter, connection, settings.schema_dir / 'chat.json'


def test_direct_local_structured_request_never_uses_codex(tmp_path, monkeypatch):
    adapter, connection, schema = fixture(tmp_path, monkeypatch)
    monkeypatch.setattr('subprocess.Popen', lambda *a, **kw: pytest.fail('No CLI should run'))
    events = []
    result = adapter.run_structured('Saved source only', schema, tmp_path, on_event=events.append)
    assert result['answer'] == 'local'
    body = json.loads(connection.requests[0][1]['body'])
    assert body['model'] == 'qwen3.6:27b'
    assert isinstance(body['format'], dict)
    assert 'tools' not in body
    assert body['stream'] is True
    assert adapter.last_usage == {'input_tokens':12,'output_tokens':5}
    assert events[-1]['type'] == 'turn.completed'
    assert connection.closed


@pytest.mark.parametrize('content,done', [('not json',True), ('{}',False)])
def test_local_bad_or_incomplete_output_is_rejected(tmp_path, monkeypatch, content, done):
    adapter, connection, schema = fixture(tmp_path, monkeypatch, content, done)
    with pytest.raises(CodexMalformedOutput):
        adapter.run_structured('source', schema, tmp_path)
    assert connection.closed


def test_local_cancellation_prevents_result(tmp_path, monkeypatch):
    adapter, connection, schema = fixture(tmp_path, monkeypatch)
    with pytest.raises(CodexCancelledError):
        adapter.run_structured('source', schema, tmp_path, cancelled=lambda:True)
    assert not connection.requests


def test_local_timeout_closes_request(tmp_path, monkeypatch):
    adapter, connection, schema = fixture(tmp_path, monkeypatch)
    def stall(limit):
        time.sleep(0.5)
        return b''
    monkeypatch.setattr(connection, 'readline', stall)
    with pytest.raises(CodexTimeoutError):
        adapter.run_structured('source', schema, tmp_path, timeout=0.1)
    assert connection.closed


def test_missing_local_model_is_actionable(tmp_path, monkeypatch):
    adapter, connection, schema = fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(adapter, 'models', lambda:[])
    with pytest.raises(OllamaUnavailable, match='ollama pull qwen3.6:27b'):
        adapter.run_structured('source', schema, tmp_path)
    assert adapter.status()['ready'] is False


def test_cloud_backed_models_are_not_selectable(tmp_path, monkeypatch):
    adapter = OllamaAdapter(Settings.load(tmp_path))
    tags = {'models':[{'name':'qwen3.6:27b'}, {'name':'remote', 'remote_host':'https://ollama.com'}, {'name':'other-cloud'}]}
    connection = Connection(io.BytesIO(json.dumps(tags).encode()))
    monkeypatch.setattr(adapter, '_connection', lambda timeout:connection)
    assert adapter.models() == ['qwen3.6:27b']

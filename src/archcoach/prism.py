"""Prism's Bonsai llama-server on a fixed, independent loopback endpoint."""
from __future__ import annotations

import http.client
import json

from .ai import CodexCancelledError, CodexTimeoutError, CodexUnavailable
from .local_openai import LocalOpenAIAdapter

DEFAULT_MODEL = "ternary-bonsai-2-27b"
MIN_CONTEXT_TOKENS = 32768


class PrismUnavailable(CodexUnavailable):
    code = "prism_unavailable"


class PrismAdapter(LocalOpenAIAdapter):
    provider = "prism"
    display_name = "Prism"
    port = 1235
    default_model = DEFAULT_MODEL
    model_setting = "prism_model"
    unavailable = PrismUnavailable
    start_hint = "Run Start Bonsai Local.cmd, then refresh diagnostics. The supported Prism runtime is independent of LM Studio."

    def _headers(self) -> dict[str, str]:
        headers = super()._headers()
        key_file = self.settings.data_dir / "prism" / "server.key"
        if not key_file.is_file():
            raise PrismUnavailable(f"Private Prism runtime key is missing. {self.start_hint}")
        key = key_file.read_text(encoding="utf-8").strip()
        if not key:
            raise PrismUnavailable(f"Private Prism runtime key is empty. {self.start_hint}")
        headers["Authorization"] = "Bearer " + key
        return headers

    def models(self) -> list[str]:
        connection = self._connection(3)
        try:
            connection.request("GET", "/v1/models", headers=self._headers())
            response = connection.getresponse()
            if response.status != 200:
                raise PrismUnavailable(f"Prism returned HTTP {response.status}. {self.start_hint}")
            body = json.loads(response.read(1_000_001))
            if not isinstance(body, dict) or not isinstance(body.get("data"), list):
                raise ValueError("Expected loaded-model metadata")
            return sorted({item["id"] for item in body["data"] if isinstance(item, dict) and isinstance(item.get("id"), str)})
        except (OSError, http.client.HTTPException, ValueError) as exc:
            raise PrismUnavailable(f"{self.start_hint} {exc}") from exc
        finally:
            connection.close()

    def _ensure_model_context(self, model: str, timeout: float) -> None:
        if self._cancel.is_set():
            raise CodexCancelledError("Local request cancelled")
        if timeout <= 0:
            raise CodexTimeoutError("Local request timed out before model inspection")
        connection = self._connection(min(3, timeout))
        self.current = connection
        try:
            connection.request("GET", "/props", headers=self._headers())
            response = connection.getresponse()
            if response.status != 200:
                raise PrismUnavailable(f"Prism model inspection returned HTTP {response.status}. {self.start_hint}")
            body = json.loads(response.read(1_000_001))
            context = body.get("default_generation_settings", {}).get("n_ctx", 0)
            if not isinstance(context, int) or isinstance(context, bool) or context < MIN_CONTEXT_TOKENS:
                raise PrismUnavailable(f"Restart Prism with at least {MIN_CONTEXT_TOKENS} context tokens: use Start Bonsai Local.cmd")
        except (OSError, http.client.HTTPException, ValueError, AttributeError) as exc:
            raise PrismUnavailable(f"Prism model inspection failed: {exc}. {self.start_hint}") from exc
        finally:
            connection.close()
            self.current = None

    def status(self) -> dict:
        models = []
        try:
            models = self.models()
            ready = self.model in models
            if ready:
                self._cancel.clear()
                self._ensure_model_context(self.model, 3)
            message = f"Local Prism ready: {self.model}. Reviews, quizzes, instructor chat and improvement plans use this local model." if ready else self.start_hint
            available = True
        except CodexUnavailable as exc:
            ready, available, message = False, bool(models), str(exc)
        return {
            "provider": self.provider, "available": available, "ready": ready, "authenticated": ready,
            "compatible": ready, "command": "http://127.0.0.1:1235/v1", "models": models,
            "selected_model": self.model, "message": message,
        }

    def _request_body(self, prompt: str, schema_data: dict) -> dict:
        body = super()._request_body(prompt, schema_data)
        body.update({
            "stream_options": {"include_usage": True},
            "chat_template_kwargs": {"enable_thinking": False},
            "reasoning_effort": "none", "max_tokens": 16384,
            "temperature": 0.7, "top_p": 0.8, "top_k": 20,
            "min_p": 0.0, "presence_penalty": 1.5,
        })
        return body

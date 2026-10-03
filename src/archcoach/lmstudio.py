"""Direct loopback-only LM Studio reasoning using its OpenAI-compatible API."""
from __future__ import annotations

import http.client
import json
import time

from .ai import CodexCancelledError, CodexTimeoutError, CodexUnavailable
from .local_openai import LocalOpenAIAdapter


DEFAULT_MODEL = "qwen/qwen3.8-27b"
MIN_CONTEXT_TOKENS = 32_768


class LMStudioUnavailable(CodexUnavailable):
    code = "lmstudio_unavailable"


class LMStudioAdapter(LocalOpenAIAdapter):
    """A deliberately small provider: loopback, schema output, no tools or remote access."""

    provider = "lmstudio"
    display_name = "LM Studio"
    port = 1234
    model_setting = "lmstudio_model"
    default_model = DEFAULT_MODEL
    unavailable = LMStudioUnavailable
    start_hint = "Load the selected model in LM Studio or select a model visible to its local server"

    def models(self) -> list[str]:
        connection = self._connection(3)
        try:
            connection.request("GET", "/api/v1/models")
            response = connection.getresponse()
            if response.status != 200:
                raise LMStudioUnavailable(f"LM Studio returned HTTP {response.status}; start its local server and refresh diagnostics")
            body = json.loads(response.read(1_000_001))
            if not isinstance(body, dict) or not isinstance(body.get("models"), list):
                raise ValueError("Expected LM Studio language-model metadata")
            return sorted({item["key"] for item in body["models"] if isinstance(item, dict) and item.get("type") == "llm" and isinstance(item.get("key"), str)})
        except (OSError, http.client.HTTPException, ValueError) as exc:
            raise LMStudioUnavailable(f"Start LM Studio's local server in Developer, then refresh diagnostics: {exc}") from exc
        finally:
            connection.close()

    def available(self) -> bool:
        try:
            self.models()
            return True
        except LMStudioUnavailable:
            return False

    def _request_body(self, prompt: str, schema_data: dict) -> dict:
        # Preserve the existing Qwen control; other models use their own template.
        if self.model.casefold().startswith("qwen/qwen3"):
            prompt += "\n/no_think"
        return super()._request_body(prompt, schema_data)

    def _ensure_model_context(self, model: str, timeout: float) -> None:
        deadline = time.monotonic() + timeout

        def remaining(cap: float | None = None) -> float:
            if self._cancel.is_set():
                raise CodexCancelledError("Local request cancelled")
            value = deadline - time.monotonic()
            if value <= 0:
                raise CodexTimeoutError(f"Local request timed out after {timeout} seconds")
            return min(value, cap) if cap else value

        connection = self._connection(remaining(3))
        self.current = connection
        try:
            connection.request("GET", "/api/v1/models")
            response = connection.getresponse()
            if response.status != 200:
                raise LMStudioUnavailable(f"LM Studio model inspection returned HTTP {response.status}")
            body = json.loads(response.read(1_000_001))
            models = body.get("models")
            if not isinstance(models, list):
                raise ValueError("Expected a models list")
            details = next((item for item in models if isinstance(item, dict) and item.get("key") == model), None)
            if not details:
                raise LMStudioUnavailable(f"Load {model} in LM Studio or select a model visible to its local server")
            instances = [item for item in details.get("loaded_instances", []) if isinstance(item, dict)]
            contexts = []
            for instance in instances:
                config = instance.get("config")
                value = config.get("context_length") if isinstance(config, dict) else None
                if isinstance(value, int) and not isinstance(value, bool):
                    contexts.append(value)
            if any(value >= MIN_CONTEXT_TOKENS for value in contexts):
                return
            if details.get("max_context_length", 0) < MIN_CONTEXT_TOKENS:
                raise LMStudioUnavailable(f"{model} does not support the required {MIN_CONTEXT_TOKENS:,}-token context")
        except (OSError, http.client.HTTPException, ValueError) as exc:
            raise LMStudioUnavailable(f"LM Studio model inspection failed: {exc}") from exc
        finally:
            connection.close()
            self.current = None

        for instance in instances:
            connection = self._connection(remaining())
            self.current = connection
            try:
                payload = json.dumps({"instance_id": instance["id"]}).encode("utf-8")
                connection.request("POST", "/api/v1/models/unload", body=payload, headers={"Content-Type": "application/json"})
                response = connection.getresponse()
                if response.status != 200:
                    raise LMStudioUnavailable(f"LM Studio could not reload {model}: unload returned HTTP {response.status}")
                response.read(1_000_001)
            except (KeyError, OSError, http.client.HTTPException) as exc:
                raise LMStudioUnavailable(f"LM Studio could not reload {model}: {exc}") from exc
            finally:
                connection.close()
                self.current = None

        connection = self._connection(remaining())
        self.current = connection
        try:
            payload = json.dumps({
                "model": model, "context_length": MIN_CONTEXT_TOKENS, "echo_load_config": True,
            }).encode("utf-8")
            connection.request("POST", "/api/v1/models/load", body=payload, headers={"Content-Type": "application/json"})
            response = connection.getresponse()
            if response.status != 200:
                detail = response.read(4096).decode("utf-8", errors="replace")
                remedy = " Use Prism · Bonsai local for the ternary GGUF; stock LM Studio cannot load this format." if "bonsai" in model.casefold() else " Check the model's runtime compatibility in LM Studio."
                raise LMStudioUnavailable(f"LM Studio could not load {model}: HTTP {response.status}: {detail}.{remedy}")
            loaded = json.loads(response.read(1_000_001))
            if loaded.get("load_config", {}).get("context_length", 0) < MIN_CONTEXT_TOKENS:
                raise LMStudioUnavailable(f"LM Studio loaded {model} with too little context")
        except (OSError, http.client.HTTPException, ValueError) as exc:
            raise LMStudioUnavailable(f"LM Studio could not load {model}: {exc}") from exc
        finally:
            connection.close()
            self.current = None

    def status(self) -> dict:
        selected = self.settings.lmstudio_model or DEFAULT_MODEL
        try:
            models = self.models()
            ready = selected in models
            return {
                "provider": "lmstudio", "available": True, "ready": ready, "authenticated": ready,
                "compatible": True, "command": "http://127.0.0.1:1234/v1", "models": models,
                "selected_model": selected,
                "message": (
                    f"Local LM Studio detected: {selected}. Execution is checked when a job starts; discovery does not verify model loading. Codex CLI is not required."
                    if ready else f"Model {selected} is not visible to LM Studio's server. Run: lms load {selected}; then start the LM Studio server, or select an ID listed above."
                ),
            }
        except LMStudioUnavailable as exc:
            return {
                "provider": "lmstudio", "available": False, "ready": False, "authenticated": False,
                "compatible": True, "command": "http://127.0.0.1:1234/v1", "models": [],
                "selected_model": selected, "message": str(exc),
            }

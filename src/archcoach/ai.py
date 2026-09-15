from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from .config import Settings
from .models import Architecture, Critique
from .subprocesses import process_group_options, terminate_process_tree


class CodexError(RuntimeError):
    pass


class CodexAdapter:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.current: subprocess.Popen[str] | None = None

    def available(self) -> bool:
        return shutil.which(self.settings.codex_command) is not None

    def status(self) -> dict:
        if not self.available():
            return {"available": False, "authenticated": False, "message": "Codex CLI was not found", "command": self.settings.codex_command}
        env = self._env()
        try:
            result = subprocess.run([self.settings.codex_command, "login", "status"], capture_output=True, text=True, timeout=15, env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            output = result.stdout.strip() or result.stderr.strip()
            return {"available": True, "authenticated": result.returncode == 0, "message": output, "command": self.settings.codex_command}
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"available": True, "authenticated": False, "message": str(exc), "command": self.settings.codex_command}

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        if os.name == "nt" and env.get("USERPROFILE"):
            env.setdefault("HOME", env["USERPROFILE"])
            default_codex_dir = Path(env["USERPROFILE"]) / ".codex"
            if default_codex_dir.is_dir() and not env.get("CODEX_HOME"):
                env["CODEX_HOME"] = str(default_codex_dir)
        env["NO_COLOR"] = "1"
        return env

    def run_structured(self, prompt: str, schema: Path, cwd: Path, on_event: Callable[[dict], None] | None = None, timeout: int = 300) -> dict:
        if not self.available():
            raise CodexError("Codex CLI is not installed or not on PATH")
        handle = tempfile.NamedTemporaryFile(prefix="archcoach-result-", suffix=".json", delete=False)
        output = Path(handle.name)
        handle.close()
        command = [self.settings.codex_command, "exec", "-", "--cd", str(cwd), "--sandbox", "read-only", "--ephemeral", "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check", "-c", 'model_reasoning_effort="low"', "--output-schema", str(schema), "--output-last-message", str(output), "--json"]
        try:
            self.current = subprocess.Popen(
                command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", env=self._env(),
                **process_group_options(),
            )
            stdout, stderr = self.current.communicate(prompt, timeout=timeout)
            for line in stdout.splitlines():
                try:
                    event = json.loads(line)
                    if on_event:
                        on_event(event)
                except json.JSONDecodeError:
                    continue
            if self.current.returncode != 0:
                raise CodexError(stderr.strip() or f"Codex exited with code {self.current.returncode}")
            return json.loads(output.read_text(encoding="utf-8"))
        except subprocess.TimeoutExpired as exc:
            self.cancel()
            raise CodexError("Codex review timed out") from exc
        finally:
            self.current = None
            try:
                output.unlink(missing_ok=True)
            except PermissionError:
                pass

    def cancel(self) -> None:
        if self.current and self.current.poll() is None:
            terminate_process_tree(self.current)


ARCHITECTURE_PROMPT = """You are documenting the architecture of a captured source snapshot. Read files only; never execute, import, install, or modify anything. Use static-analysis.json as a starting point and inspect source when needed.

Return a small, truthful architecture for a learner. Use 3-12 stable components based on source paths, a plain-English summary, and the main runtime path. Every component needs 1-3 source citations using repository-relative paths and real line numbers. Relationships must refer to component IDs. Mark inferred relationships as inferred. Do not invent deployed infrastructure or runtime behavior. Project description: {description}\nCurrent goal: {goal}\nCoverage: {coverage}
"""

CRITIQUE_PROMPT = """Review the captured source and architecture.json as a software architecture teacher. Read only; never execute or modify files. Return concrete strengths, up to five justified findings, and one to three short lessons. Empty findings are valid. Prefer the smallest useful improvement and explain tradeoffs. Each finding and lesson must cite real repository-relative paths and line numbers. Do not assign a numeric health score. Project goal: {goal}\nDeterministic changes: {changes}
"""

CHAT_PROMPT = """You are an architecture tutor answering about one immutable source snapshot. Read review-context.json and only the source files in this snapshot. Never modify or execute project code. Answer the user's question in beginner-friendly language. Return every source reference in the citations array using repository-relative paths and real line numbers; keep useful `path:line` references in the answer too. If the evidence is insufficient, say so. Keep the answer under 900 words.\n\nConversation:\n{history}\nUser: {message}
"""

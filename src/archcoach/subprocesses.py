from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path


class ProcessCancelled(RuntimeError):
    pass


def process_group_options() -> dict:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def terminate_process_tree(process: subprocess.Popen, *, force_after: float = 1.5) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True, timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + force_after
        while process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def run_cancellable(
    command: Sequence[str],
    *,
    timeout: float,
    cancelled: Callable[[], bool] | None = None,
    input_text: str | None = None,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        list(command), stdin=subprocess.PIPE if input_text is not None else None,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
        errors="replace", env=env, cwd=cwd, **process_group_options(),
    )
    result: list[tuple[str, str]] = []
    failure: list[BaseException] = []

    def communicate() -> None:
        try:
            result.append(process.communicate(input_text))
        except BaseException as exc:
            failure.append(exc)

    thread = threading.Thread(target=communicate, daemon=True)
    thread.start()
    deadline = time.monotonic() + timeout
    while thread.is_alive():
        if cancelled and cancelled():
            terminate_process_tree(process)
            thread.join(5)
            raise ProcessCancelled("Subprocess cancelled")
        if time.monotonic() >= deadline:
            terminate_process_tree(process)
            thread.join(5)
            raise subprocess.TimeoutExpired(list(command), timeout)
        thread.join(0.05)
    if failure:
        raise failure[0]
    stdout, stderr = result[0]
    return subprocess.CompletedProcess(list(command), process.returncode, stdout, stderr)

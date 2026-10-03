import hashlib
import os
import zipfile
from pathlib import Path

import pytest

from archcoach import bonsai


def archive_fixture(tmp_path, monkeypatch, entries=None):
    archive = tmp_path / "runtime.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        for name, content in (entries or {"llama-server.exe": b"synthetic executable", "LICENSE": b"synthetic license"}).items():
            bundle.writestr(name, content)
    expected = hashlib.sha256(archive.read_bytes()).hexdigest()
    monkeypatch.setattr(bonsai, "ASSETS", {"cpu": [("runtime.zip", expected)]})
    monkeypatch.setattr(bonsai, "_download", lambda url, target: target.write_bytes(archive.read_bytes()))
    return tmp_path / "data with spaces"


def test_install_is_atomic_verified_and_repeatable(tmp_path, monkeypatch):
    data = archive_fixture(tmp_path, monkeypatch)
    executable = bonsai.install_runtime(data, "cpu")
    assert executable.read_bytes() == b"synthetic executable"
    assert (executable.parent / "LICENSE").is_file()
    monkeypatch.setattr(bonsai, "_download", lambda *args: pytest.fail("Already installed"))
    assert bonsai.install_runtime(data, "cpu") == executable
    executable.write_bytes(b"modified runtime")
    with pytest.raises(ValueError, match="verification failed"):
        bonsai.install_runtime(data, "cpu")


@pytest.mark.parametrize("entry", ["../escape.exe", "/escape.exe", "C:/escape.exe", "..\\escape.exe"])
def test_archive_paths_cannot_escape_staging(tmp_path, monkeypatch, entry):
    data = archive_fixture(tmp_path, monkeypatch, {entry: b"bad", "llama-server.exe": b"fake"})
    with pytest.raises(ValueError, match="Unsafe path"):
        bonsai.install_runtime(data, "cpu")
    assert not bonsai.runtime_path(data, "cpu").exists()
    assert not (tmp_path / "escape.exe").exists()


def test_integrity_failure_publishes_nothing(tmp_path, monkeypatch):
    data = archive_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(bonsai, "ASSETS", {"cpu": [("runtime.zip", "0" * 64)]})
    with pytest.raises(ValueError, match="SHA256"):
        bonsai.install_runtime(data, "cpu")
    assert not bonsai.runtime_path(data, "cpu").exists()
    assert not list(bonsai.runtime_path(data, "cpu").parent.glob(".install-*"))


def test_server_launch_uses_existing_weights_loopback_and_one_slot(tmp_path, monkeypatch):
    data = archive_fixture(tmp_path, monkeypatch)
    bonsai.install_runtime(data, "cpu")
    model = tmp_path / "model with spaces.gguf"
    model.write_bytes(b"synthetic weights")
    command = bonsai.server_command(data, "cpu", model)
    assert command[command.index("--model") + 1] == str(model.resolve())
    assert command[command.index("--host") + 1] == "127.0.0.1"
    assert command[command.index("--parallel") + 1] == "1"
    assert command[command.index("--ctx-size") + 1] == "32768"
    assert command[command.index("--n-gpu-layers") + 1] == "0"
    assert "--no-ui" in command
    key_file = Path(command[command.index("--api-key-file") + 1])
    assert len(key_file.read_text()) >= 32
    vulkan = bonsai.server_command(data, "cpu", model, device="CPU")
    assert vulkan[-2:] == ["--device", "CPU"]
    with pytest.raises(ValueError, match="GGUF is missing"):
        bonsai.server_command(data, "cpu", tmp_path / "missing.gguf")


def test_interrupted_install_does_not_publish_partial_files(tmp_path, monkeypatch):
    data = archive_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(bonsai, "_download", lambda *args: (_ for _ in ()).throw(OSError("connection lost")))
    with pytest.raises(OSError, match="connection lost"):
        bonsai.install_runtime(data, "cpu")
    assert not bonsai.runtime_path(data, "cpu").exists()


@pytest.mark.skipif(os.name != "nt", reason="Pinned runtime launcher is Windows-only")
def test_launcher_ctrl_c_reaps_its_server(tmp_path, monkeypatch):
    data = archive_fixture(tmp_path, monkeypatch)
    bonsai.install_runtime(data, "cpu")
    model = tmp_path / "model.gguf"
    model.write_bytes(b"fake model")
    events = []
    class Process:
        def wait(self, timeout=None):
            if timeout is None:
                raise KeyboardInterrupt
            events.append("reaped")
            return 0
        def terminate(self):
            events.append("terminated")
    class Probe:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def connect_ex(self, address):
            assert address == ("127.0.0.1", 1235)
            return 1
    monkeypatch.setattr(bonsai.socket, "socket", Probe)
    monkeypatch.setattr(bonsai.subprocess, "Popen", lambda *args, **kwargs: Process())
    assert bonsai.main(["serve", "--backend", "cpu", "--data-dir", str(data), "--model", str(model)]) == 0
    assert events == ["terminated", "reaped"]

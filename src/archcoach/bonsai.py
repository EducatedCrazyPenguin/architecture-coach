"""Install and run the pinned Prism runtime, without downloading model weights."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

from .config import Settings

RELEASE = "prism-b10754-2459f68"
ASSETS = {
    "vulkan": [(f"llama-{RELEASE}-bin-win-vulkan-x64.zip", "790c979ca73f8b57c5a89ae782e952d8641e64280df4a11664198245f81e9df7")],
    "cuda": [
        (f"llama-{RELEASE}-bin-win-cuda-12.4-x64.zip", "200842b4c689fe092a8a1684ef1e185d8d025a0bfae6908737607a0f29560b96"),
        ("cudart-llama-bin-win-cuda-12.4-x64.zip", "8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6"),
    ],
    "cpu": [(f"llama-{RELEASE}-bin-win-cpu-x64.zip", "509f3829371570dfd4a651a3583532515629fc835c4d050f14740df4ac4c7df2")],
}


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _download(url: str, target: Path) -> None:
    with urllib.request.urlopen(url, timeout=60) as response, target.open("wb") as output:
        received, reported = 0, 0
        while chunk := response.read(65536):
            output.write(chunk)
            received += len(chunk)
            if received - reported >= 5_000_000:
                print(f"Downloaded {received // 1_000_000} MB", flush=True)
                reported = received


def _extract(archive: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive) as bundle:
        if sum(item.file_size for item in bundle.infolist()) > 4_000_000_000:
            raise ValueError("Runtime archive exceeds its unpacked size limit")
        for item in bundle.infolist():
            path = PurePosixPath(item.filename.replace("\\", "/"))
            if path.is_absolute() or ".." in path.parts or any(":" in part for part in path.parts) or stat.S_ISLNK(item.external_attr >> 16):
                raise ValueError("Unsafe path in runtime archive")
            target = destination.joinpath(*path.parts)
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(item) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)


def runtime_path(data_dir: Path, backend: str) -> Path:
    if backend not in ASSETS:
        raise ValueError("Choose vulkan, cuda or cpu")
    return data_dir / "prism" / RELEASE / backend


def runtime_executable(runtime: Path) -> Path:
    receipt = json.loads((runtime / "installation.json").read_text(encoding="utf-8"))
    relative = PurePosixPath(receipt["executable"])
    if relative.is_absolute() or ".." in relative.parts or any(":" in part for part in relative.parts):
        raise ValueError("Invalid runtime receipt")
    executable = runtime.joinpath(*relative.parts)
    if receipt["release"] != RELEASE or digest(executable) != receipt["executable_sha256"]:
        raise ValueError("Runtime verification failed; reinstall into a new data directory")
    return executable


def install_runtime(data_dir: Path, backend: str = "vulkan") -> Path:
    runtime = runtime_path(data_dir, backend)
    if runtime.exists():
        executable = runtime_executable(runtime)
        if not (runtime / "PRISM-LICENSE").exists():
            shutil.copyfile(Path(__file__).with_name("prism.LICENSE"), runtime / "PRISM-LICENSE")
        return executable
    runtime.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".install-", dir=runtime.parent) as temporary:
        staging = Path(temporary) / "runtime"
        staging.mkdir()
        for name, expected in ASSETS[backend]:
            archive = Path(temporary) / name
            print(f"Downloading pinned Prism runtime: {name}", flush=True)
            _download(f"https://github.com/PrismML-Eng/llama.cpp/releases/download/{RELEASE}/{name}", archive)
            if digest(archive) != expected:
                raise ValueError(f"SHA256 verification failed for {name}; runtime was not installed")
            _extract(archive, staging)
        executables = list(staging.rglob("llama-server.exe"))
        if len(executables) != 1:
            raise ValueError("Runtime archive must contain one llama-server.exe")
        executable = executables[0]
        receipt = {"release": RELEASE, "backend": backend, "executable": executable.relative_to(staging).as_posix(), "executable_sha256": digest(executable)}
        (staging / "installation.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        shutil.copyfile(Path(__file__).with_name("prism.LICENSE"), staging / "PRISM-LICENSE")
        staging.rename(runtime)
    return runtime_executable(runtime)


def default_model_path() -> Path:
    return Path.home() / ".lmstudio" / "models" / "prism-ml" / "Ternary-Bonsai-2-27B-gguf" / "Ternary-Bonsai-2-27B-PTQ1_0.gguf"


def server_command(data_dir: Path, backend: str, model: Path, device: str | None = None) -> list[str]:
    if not model.is_file() or model.suffix.casefold() != ".gguf":
        raise ValueError("Bonsai GGUF is missing. Supply --model with your downloaded model path; weights are never downloaded automatically.")
    executable = runtime_executable(runtime_path(data_dir, backend))
    key_file = data_dir / "prism" / "server.key"
    if not key_file.exists():
        descriptor = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(secrets.token_urlsafe(32))
    if not key_file.read_text(encoding="utf-8").strip():
        raise ValueError("Prism API key file is empty; remove it and restart the launcher")
    command = [
        str(executable), "--model", str(model.resolve()), "--alias", "ternary-bonsai-2-27b",
        "--host", "127.0.0.1", "--port", "1235", "--ctx-size", "32768", "--parallel", "1",
        "--n-gpu-layers", "0" if backend == "cpu" else "999", "--jinja", "--no-ui",
        "--api-key-file", str(key_file.resolve()),
    ]
    if backend == "vulkan":
        # Avoid splitting a discrete GPU's workload onto a much slower integrated GPU.
        command += ["--device", device or "Vulkan0"]
    elif device:
        command += ["--device", device]
    return command


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["install", "serve"])
    parser.add_argument("--backend", choices=ASSETS, default="vulkan")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--model", type=Path, default=default_model_path())
    parser.add_argument("--device", help="Runtime device ID; Vulkan defaults to Vulkan0")
    args = parser.parse_args(argv)
    data_dir = Settings.load(args.data_dir).data_dir
    try:
        if os.name != "nt":
            raise ValueError("The pinned Bonsai launcher currently supports Windows x64 only")
        if args.operation == "install":
            print(f"Verified runtime installed: {install_runtime(data_dir, args.backend)}")
            return 0
        command = server_command(data_dir, args.backend, args.model, args.device)
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", 1235)) == 0:
                raise ValueError("Port 1235 is already in use. Use the existing Bonsai server or stop it first.")
        print("Starting Bonsai on 127.0.0.1:1235. Wait for model loading, then select Prism · Bonsai local in Settings. Press Ctrl+C here to stop.", flush=True)
        process = subprocess.Popen(command, cwd=str(Path(command[0]).parent))
        try:
            return process.wait()
        except KeyboardInterrupt:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            return 0
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        print(f"Bonsai setup failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

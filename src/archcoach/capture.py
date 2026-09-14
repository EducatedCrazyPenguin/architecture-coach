from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from pathlib import Path, PurePosixPath
from typing import Iterable

from .config import Settings


SOURCE_EXTENSIONS = {".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".dsa", ".json", ".toml", ".yaml", ".yml", ".md", ".sql", ".css", ".html"}
ALWAYS_EXCLUDED_DIRS = {".git", ".hg", ".svn", ".venv", "venv", "node_modules", "dist", "build", "target", "__pycache__", ".pytest_cache", ".mypy_cache", ".pnpm-store"}
SECRET_NAMES = {".env", ".env.local", ".env.production", "credentials.json", "secrets.json", "id_rsa", "id_ed25519"}
MAX_FILE_BYTES = 512_000
MAX_TOTAL_BYTES = 12_000_000


def _run_git(root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def git_context(root: Path) -> dict:
    if not (root / ".git").exists():
        return {"is_git": False, "branch": None, "commit": None, "dirty": None}
    branch = _run_git(root, ["branch", "--show-current"])
    commit = _run_git(root, ["rev-parse", "HEAD"])
    dirty = _run_git(root, ["status", "--porcelain", "--untracked-files=normal"])
    return {
        "is_git": True,
        "branch": branch.stdout.strip() or "detached",
        "commit": commit.stdout.strip() if commit.returncode == 0 else None,
        "dirty": bool(dirty.stdout.strip()),
    }


def _matches_exclusion(relative: str, exclusions: Iterable[str]) -> bool:
    path = PurePosixPath(relative)
    return any(path.match(pattern.strip()) for pattern in exclusions if pattern.strip())


def eligible_files(root: Path, exclusions: list[str]) -> tuple[list[Path], list[str]]:
    omissions: list[str] = []
    candidates: list[Path] = []
    resolved_root = root.resolve()
    for current, dirs, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        dirs[:] = [d for d in dirs if d not in ALWAYS_EXCLUDED_DIRS and not (current_path / d).is_symlink()]
        for name in files:
            path = current_path / name
            relative = path.relative_to(root).as_posix()
            lower = name.lower()
            if path.is_symlink() or lower in SECRET_NAMES or lower.startswith(".env"):
                omissions.append(f"Excluded sensitive or linked file: {relative}")
                continue
            if _matches_exclusion(relative, exclusions):
                continue
            if path.suffix.lower() not in SOURCE_EXTENSIONS:
                continue
            try:
                resolved = path.resolve()
                resolved.relative_to(resolved_root)
                size = path.stat().st_size
            except (OSError, ValueError):
                omissions.append(f"Could not safely inspect: {relative}")
                continue
            if size > MAX_FILE_BYTES:
                omissions.append(f"File exceeds {MAX_FILE_BYTES} bytes: {relative}")
                continue
            candidates.append(path)
    return sorted(candidates), omissions


def capture_project(settings: Settings, project: dict) -> dict:
    root = Path(project["path"]).resolve()
    files, omissions = eligible_files(root, project.get("exclusions", []))
    manifest: list[dict] = []
    total = 0
    unstable = False
    for path in files:
        relative = path.relative_to(root).as_posix()
        for attempt in range(2):
            before = path.stat()
            content = path.read_bytes()
            after = path.stat()
            if (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns):
                break
            time.sleep(0.02)
        else:
            unstable = True
            omissions.append(f"Changed while being captured: {relative}")
            continue
        if b"\x00" in content[:8192]:
            omissions.append(f"Binary content skipped: {relative}")
            continue
        if total + len(content) > MAX_TOTAL_BYTES:
            omissions.append("Project source capture limit reached")
            break
        digest = hashlib.sha256(content).hexdigest()
        blob = settings.blob_dir / digest[:2] / digest
        blob.parent.mkdir(parents=True, exist_ok=True)
        if not blob.exists():
            blob.write_bytes(content)
        line_count = content.count(b"\n") + (1 if content else 0)
        manifest.append({"path": relative, "sha256": digest, "bytes": len(content), "lines": line_count, "mtime_ns": after.st_mtime_ns})
        total += len(content)
    fingerprint_input = [{"path": item["path"], "sha256": item["sha256"]} for item in manifest]
    fingerprint = hashlib.sha256(json.dumps(fingerprint_input, separators=(",", ":")).encode()).hexdigest()
    return {"manifest": manifest, "fingerprint": fingerprint, "git": git_context(root), "omissions": omissions, "unstable": unstable, "total_bytes": total}


def read_blob(settings: Settings, sha256: str) -> bytes:
    if len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256):
        raise ValueError("Invalid blob identifier")
    return (settings.blob_dir / sha256[:2] / sha256).read_bytes()


def materialize_snapshot(settings: Settings, snapshot: dict, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    resolved_target = target.resolve()
    for item in snapshot["manifest"]:
        destination = (target / Path(item["path"])).resolve()
        destination.relative_to(resolved_target)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(read_blob(settings, item["sha256"]))


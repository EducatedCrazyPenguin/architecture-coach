from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterable
from pathlib import Path

from .config import Settings


SOURCE_EXTENSIONS = {
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".dsa", ".json", ".toml", ".yaml", ".yml", ".md", ".sql", ".css", ".html",
}
ALWAYS_EXCLUDED_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "node_modules", "dist", "build",
    "target", "__pycache__", ".pytest_cache", ".mypy_cache", ".pnpm-store",
}
SECRET_NAMES = {
    ".env", ".env.local", ".env.production", "credentials.json", "secrets.json",
    "id_rsa", "id_ed25519",
}
MAX_FILE_BYTES = 512_000
MAX_TOTAL_BYTES = 12_000_000
FILE_ATTRIBUTE_REPARSE_POINT = 0x400


class CaptureError(RuntimeError):
    """The project could not be captured without risking a misleading review."""


class CaptureCancelled(CaptureError):
    pass


def find_git() -> str | None:
    """Find Git from PATH, a normal Windows install, or Codex's bundled runtime."""
    discovered = shutil.which("git")
    if discovered:
        return discovered
    if os.name != "nt":
        return None
    candidates: list[Path] = []
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        base = os.environ.get(variable)
        if not base:
            continue
        base_path = Path(base)
        candidates.extend((base_path / "Git" / "cmd" / "git.exe", base_path / "Programs" / "Git" / "cmd" / "git.exe"))
    profile = Path(os.environ.get("USERPROFILE") or Path.home())
    runtime_root = profile / ".cache" / "codex-runtimes"
    try:
        candidates.extend(sorted(runtime_root.glob("*/dependencies/native/git/cmd/git.exe"), reverse=True))
    except OSError:
        pass
    return next((str(candidate) for candidate in candidates if candidate.is_file()), None)


def _run_git(root: Path, args: list[str], *, input_text: str | None = None, executable: str | None = None) -> subprocess.CompletedProcess[str]:
    executable = executable or find_git()
    if not executable:
        raise CaptureError(
            "Git is required to inspect this repository and respect its ignored files. "
            "Install Git for Windows, then restart Architecture Coach."
        )
    try:
        return subprocess.run(
            [executable, "-C", str(root), *args], input=input_text, capture_output=True,
            text=True, timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CaptureError(f"Git could not inspect this project: {exc}") from exc


def git_context(root: Path) -> dict:
    executable = find_git()
    if not executable:
        likely_repository = any((candidate / ".git").exists() for candidate in (root, *root.parents))
        if likely_repository:
            raise CaptureError(
                "Git is required to inspect this repository and respect its ignored files. "
                "Install Git for Windows, then restart Architecture Coach."
            )
        return {
            "is_git": False, "branch": None, "commit": None, "dirty": None,
            "detached": False, "worktree_root": None,
        }
    probe = _run_git(root, ["rev-parse", "--is-inside-work-tree"], executable=executable)
    if probe.returncode != 0 or probe.stdout.strip() != "true":
        return {
            "is_git": False, "branch": None, "commit": None, "dirty": None,
            "detached": False, "worktree_root": None,
        }
    top = _run_git(root, ["rev-parse", "--show-toplevel"], executable=executable)
    branch = _run_git(root, ["symbolic-ref", "--quiet", "--short", "HEAD"], executable=executable)
    commit = _run_git(root, ["rev-parse", "HEAD"], executable=executable)
    dirty = _run_git(root, ["status", "--porcelain", "--untracked-files=normal"], executable=executable)
    if top.returncode or dirty.returncode:
        detail = (top.stderr or dirty.stderr).strip()
        raise CaptureError(f"Git metadata could not be read safely: {detail or 'unknown Git error'}")
    detached = branch.returncode != 0
    return {
        "is_git": True,
        "branch": None if detached else branch.stdout.strip(),
        "commit": commit.stdout.strip() if commit.returncode == 0 else None,
        "dirty": bool(dirty.stdout.strip()),
        "detached": detached,
        "worktree_root": str(Path(top.stdout.strip()).resolve()),
    }


def _is_reparse_point(path: Path) -> bool:
    try:
        stat = path.stat(follow_symlinks=False)
    except OSError:
        return True
    return path.is_symlink() or bool(getattr(stat, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT)


def _matches_exclusion(relative: str, exclusions: Iterable[str]) -> bool:
    relative = relative.strip("/")
    parts = relative.split("/")
    ancestors = ["/".join(parts[:i]) for i in range(1, len(parts))]
    for raw in exclusions:
        pattern = raw.strip().replace("\\", "/").lstrip("/")
        if not pattern:
            continue
        pattern = pattern.lstrip("!")
        directory_pattern = pattern.endswith("/")
        pattern = pattern.rstrip("/")
        if not pattern:
            continue
        if directory_pattern and (relative == pattern or relative.startswith(pattern + "/")):
            return True
        if pattern.endswith("/**"):
            prefix = pattern[:-3].rstrip("/")
            if relative == prefix or relative.startswith(prefix + "/"):
                return True
        if fnmatch.fnmatchcase(relative, pattern):
            return True
        if directory_pattern and any(fnmatch.fnmatchcase(parent, pattern) for parent in ancestors):
            return True
    return False


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except (OSError, ValueError):
        return False


def _git_ignored(root: Path, relative_paths: list[str], context: dict) -> set[str]:
    if not context["is_git"] or not relative_paths:
        return set()
    ignored: set[str] = set()
    # Argument chunks avoid Git-for-Windows' inconsistent --stdin text handling.
    for offset in range(0, len(relative_paths), 100):
        result = _run_git(root, ["check-ignore", "--no-index", "--", *relative_paths[offset:offset + 100]])
        if result.returncode not in (0, 1):
            detail = result.stderr.strip() or "git check-ignore failed"
            raise CaptureError(f"Git ignore rules could not be evaluated: {detail}")
        ignored.update(
            line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()
        )
    return ignored


def eligible_files(
    root: Path,
    exclusions: list[str],
    *,
    data_dir: Path | None = None,
    context: dict | None = None,
) -> tuple[list[Path], list[str]]:
    if not root.exists():
        raise CaptureError("Project folder is unavailable")
    if not root.is_dir():
        raise CaptureError("Project path is not a folder")
    omissions: list[str] = []
    candidates: list[Path] = []
    resolved_root = root.resolve()
    resolved_data = data_dir.resolve() if data_dir and data_dir.exists() else data_dir
    for current, dirs, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        kept_dirs: list[str] = []
        for name in dirs:
            path = current_path / name
            relative = path.relative_to(root).as_posix()
            mandatory = name.lower() in ALWAYS_EXCLUDED_DIRS
            linked = _is_reparse_point(path)
            app_data = bool(resolved_data and _inside(path, resolved_data))
            if mandatory or linked or app_data or _matches_exclusion(relative + "/", exclusions):
                omissions.append(f"Excluded directory: {relative}/")
            else:
                kept_dirs.append(name)
        dirs[:] = kept_dirs
        for name in files:
            path = current_path / name
            relative = path.relative_to(root).as_posix()
            lower = name.lower()
            if _is_reparse_point(path) or lower in SECRET_NAMES or lower.startswith(".env"):
                omissions.append(f"Excluded sensitive or linked file: {relative}")
                continue
            if _matches_exclusion(relative, exclusions):
                omissions.append(f"Excluded by project rule: {relative}")
                continue
            is_requirements = lower.startswith("requirements") and path.suffix.lower() == ".txt"
            if path.suffix.lower() not in SOURCE_EXTENSIONS and not is_requirements:
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
    candidates.sort(key=lambda value: value.relative_to(root).as_posix().casefold())
    relative_paths = [path.relative_to(root).as_posix() for path in candidates]
    ignored = _git_ignored(root, relative_paths, context or git_context(root))
    if ignored:
        omissions.extend(f"Excluded by Git ignore rule: {path}" for path in sorted(ignored))
        candidates = [path for path in candidates if path.relative_to(root).as_posix() not in ignored]
    return candidates, omissions


def _inventory(paths: list[Path], root: Path) -> list[tuple[str, int, int]]:
    inventory: list[tuple[str, int, int]] = []
    for path in paths:
        try:
            stat = path.stat()
            inventory.append((path.relative_to(root).as_posix(), stat.st_size, stat.st_mtime_ns))
        except OSError:
            inventory.append((path.relative_to(root).as_posix(), -1, -1))
    return inventory


def _atomic_blob_write(path: Path, content: bytes) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".blob-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.replace(temporary, path)
        except FileExistsError:
            pass
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _capture_once(
    settings: Settings,
    root: Path,
    exclusions: list[str],
    *,
    write_blobs: bool,
    cancelled: Callable[[], bool],
) -> tuple[dict, bool]:
    context = git_context(root)
    files, omissions = eligible_files(root, exclusions, data_dir=settings.data_dir, context=context)
    starting_inventory = _inventory(files, root)
    manifest: list[dict] = []
    total = 0
    truncated = False
    for path in files:
        if cancelled():
            raise CaptureCancelled("Capture cancelled")
        relative = path.relative_to(root).as_posix()
        try:
            before = path.stat()
            content = path.read_bytes()
            after = path.stat()
        except (OSError, PermissionError):
            omissions.append(f"File disappeared or could not be read: {relative}")
            continue
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            omissions.append(f"Changed while being captured: {relative}")
            continue
        if b"\x00" in content[:8192]:
            omissions.append(f"Binary content skipped: {relative}")
            continue
        if total + len(content) > MAX_TOTAL_BYTES:
            omissions.append(f"Project source capture limit reached at {MAX_TOTAL_BYTES} bytes")
            truncated = True
            break
        digest = hashlib.sha256(content).hexdigest()
        if write_blobs:
            _atomic_blob_write(settings.blob_dir / digest[:2] / digest, content)
        line_count = len(content.splitlines()) if content else 0
        manifest.append({
            "path": relative, "sha256": digest, "bytes": len(content),
            "lines": line_count, "mtime_ns": after.st_mtime_ns,
        })
        total += len(content)
    ending_files, ending_omissions = eligible_files(root, exclusions, data_dir=settings.data_dir, context=context)
    inventory_changed = starting_inventory != _inventory(ending_files, root)
    if inventory_changed:
        omissions.append("Project file inventory changed during capture")
    omissions.extend(item for item in ending_omissions if item not in omissions)
    fingerprint_input = [{"path": item["path"], "sha256": item["sha256"]} for item in manifest]
    fingerprint = hashlib.sha256(json.dumps(fingerprint_input, separators=(",", ":")).encode()).hexdigest()
    materially_limited = inventory_changed or truncated or any(
        item.startswith(("Could not", "File exceeds", "File disappeared", "Changed while", "Binary content"))
        for item in omissions
    )
    return {
        "manifest": manifest, "fingerprint": fingerprint, "git": context,
        "omissions": omissions, "unstable": inventory_changed, "truncated": truncated,
        "total_bytes": total,
        "coverage": "limited" if materially_limited else "complete",
    }, inventory_changed


def _capture(
    settings: Settings,
    project: dict,
    *,
    write_blobs: bool,
    cancelled: Callable[[], bool] | None = None,
) -> dict:
    root = Path(project["path"]).resolve()
    cancellation = cancelled or (lambda: False)
    last: dict | None = None
    for attempt in range(2):
        result, changed = _capture_once(
            settings, root, project.get("exclusions", []),
            write_blobs=write_blobs, cancelled=cancellation,
        )
        last = result
        if not changed:
            break
        if attempt == 0:
            time.sleep(0.02)
    assert last is not None
    if not last["manifest"]:
        raise CaptureError("No eligible readable source files were found; a review was not created")
    if last["unstable"]:
        last["coverage"] = "limited"
    return last


def capture_project(
    settings: Settings,
    project: dict,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> dict:
    return _capture(settings, project, write_blobs=True, cancelled=cancelled)


def fingerprint_project(
    settings: Settings,
    project: dict,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> dict:
    """Read current source identity without creating source blobs."""
    return _capture(settings, project, write_blobs=False, cancelled=cancelled)


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

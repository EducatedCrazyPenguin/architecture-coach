from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO


class DataDirectoryLock:
    """An OS-backed, non-blocking lock scoped to one canonical data directory."""

    def __init__(self, data_dir: Path, filename: str = "worker.lock"):
        self.path = data_dir.resolve() / filename
        self.handle: BinaryIO | None = None

    def acquire(self) -> bool:
        if self.handle is not None:
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            handle = self.path.open("a+b")
            handle.seek(0)
            if not handle.read(1):
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError):
            try:
                handle.close()
            except UnboundLocalError:
                pass
            return False
        self.handle = handle
        return True

    def release(self) -> None:
        handle, self.handle = self.handle, None
        if handle is None:
            return
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

    def __enter__(self) -> "DataDirectoryLock":
        if not self.acquire():
            raise RuntimeError("Another Architecture Coach worker owns this data directory")
        return self

    def __exit__(self, *_args) -> None:
        self.release()

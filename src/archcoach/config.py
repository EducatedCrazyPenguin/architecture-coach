from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    app_dir: Path
    codex_command: str = "codex"
    host: str = "127.0.0.1"
    port: int = 8765

    @classmethod
    def load(cls, data_dir: Path | None = None) -> "Settings":
        app_dir = Path(__file__).resolve().parent
        base = data_dir or Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local")) / "ArchCoach"
        return cls(data_dir=base.resolve(), app_dir=app_dir)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "archcoach.db"

    @property
    def blob_dir(self) -> Path:
        return self.data_dir / "blobs"

    @property
    def artifact_dir(self) -> Path:
        return self.data_dir / "artifacts"

    @property
    def schema_dir(self) -> Path:
        return self.app_dir / "schemas"

    @property
    def archify_cli(self) -> Path:
        return self.app_dir.parent.parent / "vendor" / "archify" / "archify" / "bin" / "archify.mjs"

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.blob_dir, self.artifact_dir):
            path.mkdir(parents=True, exist_ok=True)


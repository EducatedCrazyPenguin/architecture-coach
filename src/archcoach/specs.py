"""Read standard OpenSpec requirements from captured blobs, never live projects."""
from __future__ import annotations

import re

from .capture import read_blob


SPEC_INDEX_VERSION = 1
_MAIN = re.compile(r"^openspec/specs/([a-z0-9-]+)/spec\.md$")
_ACTIVE = re.compile(r"^openspec/changes/([a-z0-9-]+)/")
_HEADING = re.compile(r"^### Requirement: (.+?)\s*$")


def index_specs(settings, manifest: list[dict]) -> dict:
    result = {"version": SPEC_INDEX_VERSION, "requirements": [], "active_changes": [], "archived_changes": [], "malformed": [], "unsupported": []}
    changes: set[str] = set()
    archived: set[str] = set()
    for item in manifest:
        path = item["path"]
        if path == "openspec/config.yaml":
            config = read_blob(settings, item["sha256"]).decode("utf-8", "replace")
            match = re.search(r"^schema:\s*([^\s#]+)", config, re.MULTILINE)
            if match and match.group(1) != "spec-driven":
                result["unsupported"].append("Custom OpenSpec schema; automated interpretation is unavailable")
            if re.search(r"^store:\s*\S+", config, re.MULTILINE):
                result["unsupported"].append("External OpenSpec store; automated interpretation is unavailable")
        if path.startswith("openspec/changes/archive/"):
            archived.add(path.split("/")[3] if len(path.split("/")) > 3 else path)
        elif match := _ACTIVE.match(path):
            changes.add(match.group(1))
        match = _MAIN.fullmatch(path)
        if not match:
            continue
        capability = match.group(1)
        lines = read_blob(settings, item["sha256"]).decode("utf-8", "replace").splitlines()
        starts = [(number, heading.group(1).strip()) for number, line in enumerate(lines, 1) if (heading := _HEADING.match(line))]
        if not starts:
            result["malformed"].append(f"{path}: no requirement headings")
        for index, (line, title) in enumerate(starts):
            end = starts[index + 1][0] - 1 if index + 1 < len(starts) else len(lines)
            body = "\n".join(lines[line - 1:end]).strip()
            if not re.search(r"^#### Scenario:", body, re.MULTILINE) or not re.search(r"\bWHEN\b", body) or not re.search(r"\bTHEN\b", body):
                result["malformed"].append(f"{path}:{line}: requirement needs a WHEN/THEN scenario")
                continue
            result["requirements"].append({
                "id": f"{capability}:{title}", "capability": capability, "title": title,
                "path": path, "line": line, "end_line": end, "text": body[:4000],
            })
    result["active_changes"] = sorted(changes)
    result["archived_changes"] = sorted(archived)
    result["requirements"].sort(key=lambda item: (item["path"], item["line"]))
    if result["unsupported"]:
        result["requirements"] = []
    return result


def select_requirements(index: dict, changed_paths: set[str], anchors: set[str], limit: int = 20) -> tuple[list[dict], int]:
    terms = {part.lower() for path in changed_paths | anchors for part in re.split(r"[/_.\-]", path) if len(part) > 2}
    requirements = sorted(index["requirements"], key=lambda item: (-sum(term in item["text"].lower() for term in terms), item["path"], item["line"]))
    return requirements[:limit], max(0, len(requirements) - limit)

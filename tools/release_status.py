from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "RELEASE_STATUS.json"
TARGET = ROOT / "docs" / "RELEASE_STATUS.md"
STATUSES = {"todo", "in_progress", "implemented", "verified", "blocked"}


def main() -> int:
    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    tasks = data["tasks"]
    ids = [task["id"] for task in tasks]
    if len(tasks) != 40 or len(ids) != len(set(ids)):
        raise ValueError("The ledger must contain 40 uniquely identified tasks")
    known = set(ids)
    for task in tasks:
        if task["status"] not in STATUSES:
            raise ValueError(f"Invalid status for {task['id']}")
        if not set(task["dependencies"]) <= known:
            raise ValueError(f"Unknown dependency for {task['id']}")
        if task["status"] == "verified" and not task["evidence"]:
            raise ValueError(f"Verified task {task['id']} needs evidence")
        if task["status"] == "blocked" and not task["blocker"]:
            raise ValueError(f"Blocked task {task['id']} needs a blocker")
    counts = Counter(task["status"] for task in tasks)
    lines = ["# First-release status", "", f"Starting commit: `{data['starting_commit']}`", "",
             f"Verified: **{counts['verified']}/40** · Implemented awaiting checks: **{counts['implemented']}** · In progress: **{counts['in_progress']}** · Blocked: **{counts['blocked']}** · Remaining: **{40-counts['verified']}**", ""]
    for phase in "ABCDEFGHIJ":
        lines += [f"## Phase {phase}", ""]
        for task in (item for item in tasks if item["phase"] == phase):
            mark = "x" if task["status"] == "verified" else " "
            lines.append(f"- [{mark}] **{task['id']}** {task['title']} — `{task['status']}`")
        lines.append("")
    TARGET.write_text("\n".join(lines), encoding="utf-8")
    print(lines[4])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

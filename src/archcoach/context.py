from __future__ import annotations

from pathlib import PurePosixPath

from .capture import read_blob
from .config import Settings


MANIFEST_NAMES = {
    "pyproject.toml", "package.json", "tsconfig.json", "jsconfig.json",
    "requirements.txt", "cargo.toml", "dockerfile", "compose.yaml", "compose.yml",
}
ENTRY_NAMES = {
    "main.py", "app.py", "manage.py", "server.py", "index.js", "index.ts",
    "main.js", "main.ts", "app.js", "app.ts", "index.tsx", "main.tsx",
}


def _priority_paths(
    manifest: list[dict],
    analysis: dict,
    changed_paths: set[str],
    anchors: set[str],
) -> list[str]:
    paths = {item["path"] for item in manifest}
    connected = set()
    seeds = changed_paths | anchors
    for edge in analysis.get("edges", []):
        if edge["source"] in seeds or edge["target"] in seeds:
            connected.update((edge["source"], edge["target"]))

    def key(path: str) -> tuple[int, str]:
        name = PurePosixPath(path).name.lower()
        if name in MANIFEST_NAMES or name.startswith("requirements"):
            rank = 0
        elif name in ENTRY_NAMES:
            rank = 1
        elif path in changed_paths:
            rank = 2
        elif path in anchors:
            rank = 3
        elif path in connected:
            rank = 4
        else:
            rank = 5
        return rank, path.casefold()

    return sorted(paths, key=key)


def build_source_packets(
    settings: Settings,
    manifest: list[dict],
    analysis: dict,
    *,
    changed_paths: set[str] | None = None,
    anchors: set[str] | None = None,
) -> tuple[str, str]:
    by_path = {item["path"]: item for item in manifest}
    ordered = _priority_paths(manifest, analysis, changed_paths or set(), anchors or set())
    limit = settings.source_packet_chars
    packets: list[str] = []
    current = ""
    included: set[str] = set()
    truncated: set[str] = set()

    def flush() -> bool:
        nonlocal current
        if current:
            packets.append(current)
            current = ""
        return len(packets) >= settings.source_packet_limit

    for path in ordered:
        if len(packets) >= settings.source_packet_limit:
            break
        text = read_blob(settings, by_path[path]["sha256"]).decode("utf-8", errors="replace")
        text = text.replace("</captured-source>", "<\\/captured-source>")
        numbered = [f"{number:6}: {line}" for number, line in enumerate(text.splitlines(), 1)]
        header = f"\n--- FILE {path} ---\n"
        block = header + "\n".join(numbered) + "\n"
        if len(block) <= limit:
            if len(current) + len(block) > limit and flush():
                break
            current += block
            included.add(path)
            continue
        # Keep a deterministic leading segment for a file that exceeds one packet.
        available = max(1, limit - len(header) - 80)
        segment = ""
        for line in numbered:
            if len(segment) + len(line) + 1 > available:
                break
            segment += line + "\n"
        block = header + segment + "[remainder omitted due to packet limit]\n"
        if len(current) + len(block) > limit and flush():
            break
        current += block
        included.add(path)
        truncated.add(path)
    if current and len(packets) < settings.source_packet_limit:
        packets.append(current)
    omitted = [path for path in ordered if path not in included]
    note_parts = [f"Included {len(included)} of {len(ordered)} captured files in {len(packets)} source packet(s)."]
    if truncated:
        note_parts.append("Partially included: " + ", ".join(sorted(truncated)))
    if omitted:
        preview = ", ".join(omitted[:20])
        note_parts.append(f"Omitted {len(omitted)} files from AI context: {preview}" + (" …" if len(omitted) > 20 else ""))
    return "\n\n".join(f"SOURCE PACKET {index + 1}\n{packet}" for index, packet in enumerate(packets)), " ".join(note_parts)


def bounded_history(messages: list[dict], settings: Settings) -> tuple[str, str]:
    selected: list[dict] = []
    used = 0
    candidates = messages[-settings.chat_history_messages:]
    for message in reversed(candidates):
        rendered = f"{message['role']}: {message['content']}"
        if selected and used + len(rendered) > settings.chat_history_chars:
            break
        if len(rendered) > settings.chat_history_chars:
            rendered = rendered[-settings.chat_history_chars:]
        selected.append({**message, "rendered": rendered})
        used += len(rendered)
    selected.reverse()
    omitted = len(messages) - len(selected)
    note = "All saved messages are included." if not omitted else f"{omitted} older message(s) are outside the active context."
    return "\n".join(message["rendered"] for message in selected), note

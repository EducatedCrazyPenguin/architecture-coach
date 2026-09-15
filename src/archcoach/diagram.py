from __future__ import annotations

import html
import json
import os
import subprocess
import shutil
from collections.abc import Callable
from pathlib import Path

from .config import Settings
from .models import Architecture
from .subprocesses import run_cancellable


def find_node() -> str | None:
    direct = shutil.which("node")
    if direct:
        return direct
    cache = Path.home() / ".cache" / "codex-runtimes"
    candidates = sorted(cache.glob("*/dependencies/node/bin/node.exe"), reverse=True) if cache.exists() else []
    return str(candidates[0]) if candidates else None


def stable_positions(architecture: Architecture, previous: dict | None = None) -> dict[str, dict[str, int]]:
    positions: dict[str, dict[str, int]] = {}
    occupied: set[tuple[int, int]] = set()
    for identifier in sorted(component.id for component in architecture.components):
        candidate = (previous or {}).get(identifier)
        if candidate and {"row", "col"} <= set(candidate):
            location = (int(candidate["row"]), int(candidate["col"]))
            if location not in occupied:
                positions[identifier] = {"row": location[0], "col": location[1]}
                occupied.add(location)
    next_index = 0
    for identifier in sorted(component.id for component in architecture.components):
        if identifier in positions:
            continue
        while (next_index // 3, next_index % 3) in occupied:
            next_index += 1
        positions[identifier] = {"row": next_index // 3, "col": next_index % 3}
        occupied.add((next_index // 3, next_index % 3))
        next_index += 1
    return positions


def to_archify(architecture: Architecture, title: str, positions: dict | None = None) -> dict:
    positions = positions or stable_positions(architecture)
    components = []
    for component in architecture.components:
        position = positions[component.id]
        components.append({
            "id": component.id, "type": component.kind, "label": component.name[:28],
            "sublabel": component.responsibility[:46], "row": position["row"], "col": position["col"],
            "size": [280, 108],
        })
    connections = []
    known = {component.id for component in architecture.components}
    for relation in architecture.relationships:
        if relation.source in known and relation.target in known:
            connections.append({"from": relation.source, "to": relation.target, "label": relation.label, "variant": "dashed" if relation.inferred else "default"})
    return {"schema_version": 1, "diagram_type": "architecture", "meta": {"title": title, "visual_preset": "editorial", "quality_profile": "standard"}, "layout": {"mode": "grid", "cols": min(3, max(1, len(components))), "cellW": 330, "cellH": 155, "gapX": 28, "gapY": 28}, "components": components, "connections": connections}


def render_diagram(
    settings: Settings,
    architecture: Architecture,
    title: str,
    output_dir: Path,
    *,
    cancelled: Callable[[], bool] | None = None,
    positions: dict | None = None,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    ir_path = output_dir / "architecture.json"
    html_path = output_dir / "architecture.html"
    ir = to_archify(architecture, title, positions)
    ir_path.write_text(json.dumps(ir, indent=2), encoding="utf-8")
    node = find_node()
    if settings.archify_cli.exists() and node:
        env = os.environ.copy(); env["ARCHIFY_UPDATE_CHECK_DISABLED"] = "1"
        last_error = ""
        for _ in range(2):
            result = run_cancellable(
                [node, str(settings.archify_cli), "deliver", "architecture", str(ir_path), str(html_path), "--quality", "standard", "--json"],
                timeout=120, cancelled=cancelled, env=env,
            )
            if result.returncode == 0 and html_path.exists():
                return {"diagram": str(html_path), "architecture_ir": str(ir_path), "renderer": "archify", "error": None}
            last_error = (result.stderr or result.stdout)[-2000:]
        fallback_diagram(architecture, title, html_path)
        return {"diagram": str(html_path), "architecture_ir": str(ir_path), "renderer": "fallback", "error": last_error or "Archify rendering failed"}
    fallback_diagram(architecture, title, html_path)
    return {"diagram": str(html_path), "architecture_ir": str(ir_path), "renderer": "fallback", "error": "Bundled Archify or Node.js was not found"}


def fallback_diagram(architecture: Architecture, title: str, target: Path) -> None:
    cards = []
    for component in architecture.components:
        cards.append(f'<article id="{html.escape(component.id)}"><span>{html.escape(component.kind)}</span><h2>{html.escape(component.name)}</h2><p>{html.escape(component.responsibility)}</p></article>')
    links = "".join(f"<li><b>{html.escape(r.source)}</b> → <b>{html.escape(r.target)}</b>: {html.escape(r.label)}</li>" for r in architecture.relationships)
    document = f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>{html.escape(title)}</title><style>body{{font:16px system-ui;background:#f7f8fb;color:#172033;margin:0;padding:32px}}main{{max-width:1100px;margin:auto}}section{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:18px}}article{{background:white;border:1px solid #dfe4ec;border-top:4px solid #4969e8;border-radius:12px;padding:18px;box-shadow:0 8px 24px #24304b12}}span{{color:#647089;text-transform:uppercase;font-size:11px;letter-spacing:.1em}}h1{{font-size:26px}}h2{{font-size:17px}}p,li{{color:#4c5870;line-height:1.55}}aside{{margin-top:22px;background:white;padding:18px;border-radius:12px;border:1px solid #dfe4ec}}</style></head><body><main><h1>{html.escape(title)}</h1><section>{''.join(cards)}</section><aside><h2>Connections</h2><ul>{links or '<li>No confirmed connections</li>'}</ul></aside></main></body></html>'''
    target.write_text(document, encoding="utf-8")


def render_comparison(
    settings: Settings,
    base_ir: Path,
    head_ir: Path,
    target: Path,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> str | None:
    node = find_node()
    if not settings.archify_cli.exists() or not node:
        return None
    env = os.environ.copy(); env["ARCHIFY_UPDATE_CHECK_DISABLED"] = "1"
    result = run_cancellable(
        [node, str(settings.archify_cli), "compare", "architecture", str(base_ir), str(head_ir), str(target), "--json"],
        timeout=120, cancelled=cancelled, env=env,
    )
    return str(target) if result.returncode == 0 and target.exists() else None

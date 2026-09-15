from __future__ import annotations

import html
import json
import os
import subprocess
import shutil
from collections import defaultdict, deque
from collections.abc import Callable
from pathlib import Path

from .config import Settings
from .models import Architecture
from .subprocesses import ProcessCancelled, run_cancellable


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
    principal = principal_relationships(architecture)
    pair_counts: dict[tuple[str, str], int] = {}
    for relation in principal:
        if relation.source in known and relation.target in known:
            pair = (relation.source, relation.target)
            pair_counts[pair] = pair_counts.get(pair, 0) + 1
            connections.append({
                "id": f"rel-{relation.source}-{relation.target}-{pair_counts[pair]}",
                "from": relation.source, "to": relation.target, "label": relation.label,
                "variant": "dashed" if relation.inferred else "default",
            })
    return {"schema_version": 1, "diagram_type": "architecture", "meta": {"title": title, "visual_preset": "editorial", "quality_profile": "standard"}, "layout": {"mode": "grid", "cols": min(3, max(1, len(components))), "cellW": 330, "cellH": 155, "gapX": 28, "gapY": 28}, "components": components, "connections": connections}


def principal_relationships(architecture: Architecture) -> list:
    """Keep the diagram readable while the report retains every dependency."""
    path_edges = set(zip(architecture.main_path, architecture.main_path[1:]))
    ordered = sorted(
        architecture.relationships,
        key=lambda item: ((item.source, item.target) not in path_edges, item.inferred, item.source, item.target, item.label),
    )
    return ordered[: max(12, len(architecture.components) - 1)]


def _repair_layout(ir: dict) -> dict:
    """Second-attempt repair changes geometry only; architecture facts stay intact."""
    repaired = json.loads(json.dumps(ir))
    count = len(repaired.get("components", []))
    repaired["layout"].update({"cols": min(2, max(1, count)), "cellW": 370, "cellH": 175, "gapX": 42, "gapY": 42})
    for component in repaired.get("components", []):
        index = next(i for i, item in enumerate(repaired["components"]) if item["id"] == component["id"])
        component["row"], component["col"] = divmod(index, repaired["layout"]["cols"])
    return repaired


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
        for attempt in range(2):
            if attempt:
                ir = _repair_layout(ir)
                ir_path.write_text(json.dumps(ir, indent=2), encoding="utf-8")
            try:
                result = run_cancellable(
                    [node, str(settings.archify_cli), "deliver", "architecture", str(ir_path), str(html_path), "--quality", "standard", "--json"],
                    timeout=120, cancelled=cancelled, env=env,
                )
                if result.returncode == 0 and html_path.exists() and html_path.stat().st_size:
                    return {"diagram": str(html_path), "architecture_ir": str(ir_path), "renderer": "archify", "error": None, "attempts": attempt + 1}
                last_error = (result.stderr or result.stdout)[-2000:] or "Archify returned no valid HTML"
            except ProcessCancelled:
                raise
            except (OSError, subprocess.SubprocessError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
        fallback_diagram(architecture, title, html_path)
        return {"diagram": str(html_path), "architecture_ir": str(ir_path), "renderer": "fallback", "error": last_error or "Archify rendering failed", "attempts": 2}
    fallback_diagram(architecture, title, html_path)
    return {"diagram": str(html_path), "architecture_ir": str(ir_path), "renderer": "fallback", "error": "Bundled Archify or Node.js was not found", "attempts": 0}


def fallback_diagram(architecture: Architecture, title: str, target: Path) -> None:
    """Write a dependency graph that remains useful when Archify is unavailable."""
    positions, graph_width, graph_height = _fallback_positions(architecture)
    node_width, node_height = 250, 116
    edge_markup: list[str] = []
    for index, relation in enumerate(architecture.relationships):
        if relation.source not in positions or relation.target not in positions:
            continue
        sx, sy = positions[relation.source]
        tx, ty = positions[relation.target]
        start_x, start_y = sx + node_width, sy + node_height / 2
        end_x, end_y = tx, ty + node_height / 2
        if end_x <= start_x:
            bend = max(start_y, end_y) + 72 + (index % 3) * 18
            path = f"M {start_x} {start_y} C {start_x + 55} {bend}, {end_x - 55} {bend}, {end_x} {end_y}"
            label_x, label_y = (start_x + end_x) / 2, bend - 5
        else:
            middle = (start_x + end_x) / 2
            path = f"M {start_x} {start_y} C {middle} {start_y}, {middle} {end_y}, {end_x} {end_y}"
            label_x, label_y = middle, (start_y + end_y) / 2 - 7
        relation_class = "edge inferred" if relation.inferred else "edge"
        dash = ' stroke-dasharray="7 6"' if relation.inferred else ""
        edge_markup.append(
            f'<g class="{relation_class}" data-source="{html.escape(relation.source)}" '
            f'data-target="{html.escape(relation.target)}">'
            f'<path d="{path}"{dash} marker-end="url(#arrow)"/>'
            f'<text x="{label_x}" y="{label_y}">{html.escape(relation.label[:42])}</text></g>'
        )

    node_markup: list[str] = []
    payload: dict[str, dict] = {}
    incoming: dict[str, list[dict]] = defaultdict(list)
    outgoing: dict[str, list[dict]] = defaultdict(list)
    for relation in architecture.relationships:
        item = {"source": relation.source, "target": relation.target, "label": relation.label, "inferred": relation.inferred}
        outgoing[relation.source].append(item)
        incoming[relation.target].append(item)
    for component in architecture.components:
        x, y = positions[component.id]
        short = component.responsibility if len(component.responsibility) <= 66 else component.responsibility[:63] + "…"
        files = component.source_paths or [source.path for source in component.sources]
        payload[component.id] = {
            "id": component.id, "name": component.name, "kind": component.kind,
            "responsibility": component.responsibility, "files": files,
            "sources": [source.model_dump() for source in component.sources],
            "incoming": incoming.get(component.id, []), "outgoing": outgoing.get(component.id, []),
        }
        node_markup.append(
            f'<g class="node" data-id="{html.escape(component.id)}" role="button" tabindex="0" '
            f'aria-label="Inspect {html.escape(component.name)}" transform="translate({x} {y})">'
            f'<rect width="{node_width}" height="{node_height}" rx="12"/>'
            f'<text class="node-kind" x="18" y="25">{html.escape(component.kind.upper())}</text>'
            f'<text class="node-name" x="18" y="50">{html.escape(component.name[:31])}</text>'
            f'<foreignObject x="18" y="61" width="214" height="40"><div xmlns="http://www.w3.org/1999/xhtml" '
            f'class="node-summary">{html.escape(short)}</div></foreignObject>'
            f'<text class="node-count" x="18" y="106">{len(files)} source file{"s" if len(files) != 1 else ""}</text></g>'
        )

    safe_payload = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    initial_component = architecture.main_path[0] if architecture.main_path else architecture.components[0].id
    safe_initial = json.dumps(initial_component, ensure_ascii=False).replace("</", "<\\/")
    document = f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title><style>
:root{{--ink:#172033;--muted:#637087;--line:#dbe1eb;--blue:#3859d9;--paper:#fff;--wash:#f6f8fc}}*{{box-sizing:border-box}}body{{margin:0;background:var(--wash);color:var(--ink);font:14px Inter,Segoe UI,system-ui,sans-serif}}header{{display:flex;align-items:center;justify-content:space-between;gap:18px;padding:17px 20px;background:#fff;border-bottom:1px solid var(--line)}}h1{{margin:0;font:600 22px Georgia,serif}}.subtitle{{margin:4px 0 0;color:var(--muted);font-size:12px}}.controls{{display:flex;gap:6px}}button{{border:1px solid #cfd6e2;border-radius:7px;background:#fff;color:#33405a;padding:7px 10px;font-weight:700;cursor:pointer}}button:hover,button:focus-visible{{border-color:var(--blue);color:var(--blue);outline:2px solid #b8c5ff;outline-offset:1px}}main{{display:grid;grid-template-columns:minmax(0,1fr) 320px;height:calc(100vh - 78px)}}#viewport{{overflow:auto;background-image:radial-gradient(#d5dbe7 1px,transparent 1px);background-size:18px 18px}}#canvas{{transform-origin:0 0;transition:transform .15s ease}}.edge path{{fill:none;stroke:#8793aa;stroke-width:2}}.edge text{{fill:#58657c;font-size:11px;text-anchor:middle;paint-order:stroke;stroke:var(--wash);stroke-width:5px;stroke-linejoin:round}}.edge.inferred path{{stroke:#a17a35}}.edge.dim{{opacity:.13}}.edge.active path{{stroke:var(--blue);stroke-width:3}}.node rect{{fill:#fff;stroke:#cfd7e5;stroke-width:1.5;filter:drop-shadow(0 6px 12px #27355212)}}.node{{cursor:pointer}}.node:hover rect,.node:focus-visible rect,.node.active rect{{stroke:var(--blue);stroke-width:3;fill:#f7f8ff}}.node:focus{{outline:none}}.node-kind{{fill:#647089;font-size:10px;font-weight:800;letter-spacing:1.2px}}.node-name{{fill:var(--ink);font-size:16px;font-weight:750}}.node-summary{{color:#59657a;font-size:11px;line-height:1.35}}.node-count{{fill:#7b8598;font-size:10px}}aside{{overflow:auto;padding:22px;background:#fff;border-left:1px solid var(--line)}}aside h2{{margin:5px 0 10px;font:600 23px Georgia,serif}}aside h3{{margin:21px 0 7px;font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:#5c6780}}aside p{{color:#4f5c73;line-height:1.55}}.badge{{display:inline-block;padding:4px 7px;border-radius:99px;background:#edf0ff;color:var(--blue);font-size:10px;font-weight:800;text-transform:uppercase}}ul{{margin:7px 0;padding-left:19px}}li{{margin:6px 0;color:#526078;line-height:1.4}}code{{overflow-wrap:anywhere;color:#27344e}}.legend{{display:flex;gap:15px;padding:8px 20px;background:#fff;border-bottom:1px solid var(--line);color:var(--muted);font-size:11px}}.line{{display:inline-block;width:24px;border-top:2px solid #8793aa;vertical-align:middle;margin-right:5px}}.line.dashed{{border-top-style:dashed;border-color:#a17a35}}@media(max-width:780px){{header{{align-items:flex-start;flex-direction:column}}main{{grid-template-columns:1fr;height:auto}}#viewport{{height:60vh}}aside{{border-left:0;border-top:1px solid var(--line);min-height:330px}}}}
</style></head><body><header><div><h1>{html.escape(title)}</h1><p class="subtitle">Select a component to inspect its responsibility, source files, and dependencies.</p></div><div class="controls" aria-label="Diagram controls"><button id="zoom-out" type="button" title="Zoom out">−</button><button id="reset" type="button">Fit</button><button id="zoom-in" type="button" title="Zoom in">+</button></div></header><div class="legend"><span><i class="line"></i>confirmed static dependency</span><span><i class="line dashed"></i>inferred relationship</span></div><main><div id="viewport"><svg id="canvas" xmlns="http://www.w3.org/2000/svg" width="{graph_width}" height="{graph_height}" viewBox="0 0 {graph_width} {graph_height}" aria-label="Directed architecture graph"><defs><marker id="arrow" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto"><path d="M0,0 L10,4 L0,8 z" fill="#8793aa"/></marker></defs>{''.join(edge_markup)}{''.join(node_markup)}</svg></div><aside id="details" aria-live="polite"><span class="badge">Architecture map</span><h2>Choose a component</h2><p>Arrows show which component depends on another. Select any box for concrete source membership and incoming or outgoing dependencies.</p><h3>Project purpose</h3><p>{html.escape(architecture.summary)}</p></aside></main><script>
const components={safe_payload};let scale=1;const canvas=document.getElementById('canvas'),viewport=document.getElementById('viewport'),details=document.getElementById('details');
const esc=s=>String(s).replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
function relationList(items,direction){{if(!items.length)return '<p>None confirmed.</p>';return '<ul>'+items.map(r=>`<li>${{direction==='out'?'<b>'+esc(components[r.target]?.name||r.target)+'</b>':'<b>'+esc(components[r.source]?.name||r.source)+'</b>'}} — ${{esc(r.label)}}${{r.inferred?' <em>(inferred)</em>':''}}</li>`).join('')+'</ul>'}}
function select(id){{const c=components[id];if(!c)return;document.querySelectorAll('.node').forEach(n=>n.classList.toggle('active',n.dataset.id===id));document.querySelectorAll('.edge').forEach(e=>{{const active=e.dataset.source===id||e.dataset.target===id;e.classList.toggle('active',active);e.classList.toggle('dim',!active)}});const sourceItems=c.sources.map(s=>`<li><code>${{esc(s.path)}}:${{s.line}}${{s.end_line?'–'+s.end_line:''}}</code>${{s.label?' — '+esc(s.label):''}}</li>`).join('');const files=c.files.map(f=>`<li><code>${{esc(f)}}</code></li>`).join('');details.innerHTML=`<span class="badge">${{esc(c.kind)}}</span><h2>${{esc(c.name)}}</h2><p>${{esc(c.responsibility)}}</p><h3>Representative evidence</h3><ul>${{sourceItems}}</ul><h3>Source membership (${{c.files.length}})</h3><ul>${{files}}</ul><h3>Depends on</h3>${{relationList(c.outgoing,'out')}}<h3>Used by</h3>${{relationList(c.incoming,'in')}}`;}}
document.querySelectorAll('.node').forEach(node=>{{node.addEventListener('click',()=>select(node.dataset.id));node.addEventListener('keydown',event=>{{if(event.key==='Enter'||event.key===' '){{event.preventDefault();select(node.dataset.id)}}}})}});
function applyScale(){{canvas.style.transform=`scale(${{scale}})`;viewport.style.setProperty('--scale',scale)}}document.getElementById('zoom-in').onclick=()=>{{scale=Math.min(1.8,scale+.15);applyScale()}};document.getElementById('zoom-out').onclick=()=>{{scale=Math.max(.45,scale-.15);applyScale()}};document.getElementById('reset').onclick=()=>{{scale=Math.min(1,Math.max(.45,(viewport.clientWidth-30)/{graph_width}));applyScale();viewport.scrollTo(0,0)}};window.addEventListener('load',()=>{{document.getElementById('reset').click();select({safe_initial})}});
</script></body></html>'''
    target.write_text(document, encoding="utf-8")


def _fallback_positions(architecture: Architecture) -> tuple[dict[str, tuple[int, int]], int, int]:
    """Lay out a small dependency graph in deterministic left-to-right layers."""
    identifiers = [component.id for component in architecture.components]
    known = set(identifiers)
    outgoing: dict[str, set[str]] = {identifier: set() for identifier in identifiers}
    indegree = {identifier: 0 for identifier in identifiers}
    for relation in architecture.relationships:
        if relation.source in known and relation.target in known and relation.target not in outgoing[relation.source]:
            outgoing[relation.source].add(relation.target)
            indegree[relation.target] += 1
    ranks = {identifier: 0 for identifier in identifiers}
    queue = deque(sorted(identifier for identifier in identifiers if indegree[identifier] == 0))
    visited: set[str] = set()
    while queue:
        source = queue.popleft()
        visited.add(source)
        for target_id in sorted(outgoing[source]):
            ranks[target_id] = max(ranks[target_id], ranks[source] + 1)
            indegree[target_id] -= 1
            if indegree[target_id] == 0:
                queue.append(target_id)
    residual_rank = max(ranks.values(), default=0)
    for identifier in identifiers:
        if identifier not in visited:
            ranks[identifier] = residual_rank
    for index, identifier in enumerate(architecture.main_path):
        if identifier in known:
            ranks[identifier] = max(ranks[identifier], index)
    layers: dict[int, list[str]] = defaultdict(list)
    for identifier in identifiers:
        layers[ranks[identifier]].append(identifier)
    max_rows = max((len(values) for values in layers.values()), default=1)
    positions: dict[str, tuple[int, int]] = {}
    for rank, values in sorted(layers.items()):
        for row, identifier in enumerate(sorted(values)):
            positions[identifier] = (55 + rank * 330, 45 + row * 158)
    width = max((x for x, _ in positions.values()), default=55) + 305
    height = max(420, 65 + max_rows * 158)
    return positions, width, height


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
    try:
        result = run_cancellable(
            [node, str(settings.archify_cli), "compare", "architecture", str(base_ir), str(head_ir), str(target), "--json"],
            timeout=120, cancelled=cancelled, env=env,
        )
    except ProcessCancelled:
        raise
    except (OSError, subprocess.SubprocessError):
        return None
    return str(target) if result.returncode == 0 and target.exists() and target.stat().st_size else None


def render_selected_comparison(settings: Settings, before: dict, after: dict) -> str | None:
    """Render a selected pair outside immutable review artifact directories."""
    pair_dir = settings.artifact_dir / "comparisons" / before["project_id"] / f"{before['id']}-{after['id']}"
    pair_dir.mkdir(parents=True, exist_ok=True)
    base_ir = pair_dir / "before.json"
    head_ir = pair_dir / "after.json"
    target = pair_dir / "comparison.html"
    if target.is_file() and target.stat().st_size:
        return str(target)
    before_model = Architecture.model_validate(before["architecture"])
    after_model = Architecture.model_validate(after["architecture"])
    base_ir.write_text(json.dumps(to_archify(before_model, "Earlier architecture", before.get("positions")), indent=2), encoding="utf-8")
    head_ir.write_text(json.dumps(to_archify(after_model, "Later architecture", after.get("positions")), indent=2), encoding="utf-8")
    return render_comparison(settings, base_ir, head_ir, target)

from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
import tempfile
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

from .capture import read_blob
from .config import Settings
from .subprocesses import ProcessCancelled, run_cancellable


IMPORT_RE = re.compile(r"(?:import\s+(?:[^'\"]+?\s+from\s+)?|require\s*\()\s*['\"]([^'\"]+)['\"]")


def _node_command() -> str | None:
    if command := shutil.which("node"):
        return command
    cache = Path.home() / ".cache" / "codex-runtimes"
    candidates = sorted(cache.glob("*/dependencies/node/bin/node.exe"), reverse=True) if cache.exists() else []
    return str(candidates[0]) if candidates else None


def _typescript_analysis(settings: Settings, manifest: list[dict], cancelled: Callable[[], bool]) -> dict[str, dict]:
    node = _node_command(); helper = settings.app_dir.parent.parent / "tools" / "analyze-js.mjs"
    selected = [item for item in manifest if Path(item["path"]).suffix.lower() in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}]
    if not node or not helper.exists() or not selected:
        return {}
    with tempfile.TemporaryDirectory(prefix="archcoach-js-") as temp:
        root = Path(temp); reverse: dict[str, str] = {}; paths: list[str] = []
        for item in selected:
            target = root / item["path"]; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(read_blob(settings, item["sha256"]))
            reverse[str(target)] = item["path"]; paths.append(str(target))
        try:
            result = run_cancellable([node, str(helper), *paths], timeout=60, cancelled=cancelled)
            if result.returncode != 0: return {}
            return {reverse.get(item["file"], item["file"]): item for item in json.loads(result.stdout)}
        except ProcessCancelled:
            raise
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
            return {}


def _module_name(path: str) -> str:
    clean = path.rsplit(".", 1)[0]
    return clean.replace("/", ".").removesuffix(".__init__")


def _resolve_python_import(current: str, imported: str, module_names: set[str]) -> str | None:
    if imported in module_names:
        return imported
    if imported.startswith("."):
        dots = len(imported) - len(imported.lstrip("."))
        suffix = imported[dots:]
        parts = current.split(".")[:-dots]
        candidate = ".".join([*parts, suffix]).strip(".")
        return candidate if candidate in module_names else None
    matches = [name for name in module_names if name == imported or name.endswith("." + imported)]
    return min(matches, key=len) if matches else None


def analyze_snapshot(settings: Settings, manifest: list[dict], *, cancelled: Callable[[], bool] | None = None) -> dict:
    is_cancelled = cancelled or (lambda: False)
    module_by_path = {item["path"]: _module_name(item["path"]) for item in manifest if item["path"].endswith((".py", ".pyi"))}
    module_names = set(module_by_path.values())
    files: list[dict] = []
    edges: set[tuple[str, str, str]] = set()
    unresolved: list[dict] = []
    omissions: list[str] = []
    language_counts: dict[str, int] = defaultdict(int)
    typed_js = _typescript_analysis(settings, manifest, is_cancelled)
    for item in manifest:
        if is_cancelled():
            raise ProcessCancelled("Static analysis cancelled")
        path = item["path"]
        suffix = Path(path).suffix.lower()
        text = read_blob(settings, item["sha256"]).decode("utf-8", errors="replace")
        definitions: list[dict] = []
        imports: list[str] = []
        language = "other"
        if suffix in {".py", ".pyi"}:
            language = "python"
            try:
                tree = ast.parse(text, filename=path)
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        definitions.append({"name": node.name, "kind": "class" if isinstance(node, ast.ClassDef) else "function", "line": node.lineno})
                    elif isinstance(node, ast.Import):
                        imports.extend(alias.name for alias in node.names)
                    elif isinstance(node, ast.ImportFrom):
                        prefix = "." * node.level + (node.module or "")
                        imports.append(prefix)
                current = module_by_path[path]
                for imported in imports:
                    resolved = _resolve_python_import(current, imported, module_names)
                    if resolved:
                        target = next(p for p, m in module_by_path.items() if m == resolved)
                        edges.add((path, target, "imports"))
                    elif imported and not imported.startswith(("typing", "__future__")):
                        unresolved.append({"path": path, "import": imported})
            except SyntaxError as exc:
                omissions.append(f"Python parse error in {path}:{exc.lineno}")
        elif suffix in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".dsa"}:
            language = "daz-script" if suffix == ".dsa" else "javascript-typescript"
            compiler_result = typed_js.get(path)
            imports = compiler_result["imports"] if compiler_result else IMPORT_RE.findall(text)
            if compiler_result:
                definitions = compiler_result["definitions"]
                omissions.extend(f"TypeScript parse issue in {path}: {message}" for message in compiler_result.get("diagnostics", []))
            else:
                for match in re.finditer(r"(?:class|function)\s+([A-Za-z_$][\w$]*)", text):
                    definitions.append({"name": match.group(1), "kind": "definition", "line": text.count("\n", 0, match.start()) + 1})
            for imported in imports:
                if imported.startswith("."):
                    base = (Path(path).parent / imported).as_posix()
                    candidates = [base, *[base + ext for ext in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".dsa")], base + "/index.ts", base + "/index.js"]
                    target = next((candidate for candidate in candidates if candidate in {m["path"] for m in manifest}), None)
                    if target:
                        edges.add((path, target, "imports"))
                    else:
                        unresolved.append({"path": path, "import": imported})
        elif suffix in {".json", ".toml", ".yaml", ".yml"}:
            language = "configuration"
        language_counts[language] += 1
        files.append({"path": path, "language": language, "lines": item["lines"], "definitions": definitions[:100], "imports": imports[:100]})
    graph: dict[str, list[str]] = defaultdict(list)
    for source, target, _ in edges:
        graph[source].append(target)
    cycles = _find_cycles(graph)
    coverage = {
        "languages": dict(language_counts),
        "parsed_files": len(files) - len(omissions),
        "total_files": len(files),
        "level": "limited" if language_counts.get("daz-script") else "standard",
        "omissions": omissions,
    }
    return {"files": files, "edges": [{"source": s, "target": t, "kind": k, "inferred": False} for s, t, k in sorted(edges)], "cycles": cycles, "unresolved_imports": unresolved[:200], "coverage": coverage}


def _find_cycles(graph: dict[str, list[str]]) -> list[list[str]]:
    found: set[tuple[str, ...]] = set()
    visiting: list[str] = []
    active: set[str] = set()
    def walk(node: str) -> None:
        if node in active:
            index = visiting.index(node)
            cycle = visiting[index:] + [node]
            rotations = [tuple(cycle[i:-1] + cycle[:i] + [cycle[i]]) for i in range(len(cycle) - 1)]
            found.add(min(rotations))
            return
        if node in visiting:
            return
        active.add(node); visiting.append(node)
        for target in graph.get(node, []):
            walk(target)
        visiting.pop(); active.remove(node)
    for node in graph:
        walk(node)
    return [list(cycle) for cycle in sorted(found)]


def compact_analysis(analysis: dict, limit_files: int = 250) -> dict:
    return {**analysis, "files": analysis["files"][:limit_files], "unresolved_imports": analysis["unresolved_imports"][:50]}

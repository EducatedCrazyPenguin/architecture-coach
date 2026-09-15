from __future__ import annotations

import ast
import json
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path, PurePosixPath

from .capture import read_blob
from .config import Settings
from .subprocesses import ProcessCancelled, run_cancellable


JS_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".dsa")
RESOLUTION_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".dsa", ".json")
FALLBACK_IMPORT_RE = re.compile(
    r"(?:from\s+|require\s*\(|import\s*\()\s*['\"]([^'\"]+)['\"]|"
    r"import\s+['\"]([^'\"]+)['\"]|export\s+(?:\*|\{[^}]*\})\s+from\s+['\"]([^'\"]+)['\"]"
)


def _node_command() -> str | None:
    if command := shutil.which("node"):
        return command
    cache = Path.home() / ".cache" / "codex-runtimes"
    candidates = sorted(cache.glob("*/dependencies/node/bin/node.exe"), reverse=True) if cache.exists() else []
    return str(candidates[0]) if candidates else None


def _typescript_analysis(
    settings: Settings,
    manifest: list[dict],
    cancelled: Callable[[], bool],
) -> tuple[dict[str, dict], str | None]:
    node = _node_command()
    helper = settings.app_dir.parent.parent / "tools" / "analyze-js.mjs"
    selected = [item for item in manifest if Path(item["path"]).suffix.lower() in JS_EXTENSIONS[:-1]]
    if not selected:
        return {}, None
    if not node or not helper.exists():
        return {}, "Pinned TypeScript analyzer is unavailable; JavaScript/TypeScript used limited regex fallback"
    with tempfile.TemporaryDirectory(prefix="archcoach-js-") as temp:
        root = Path(temp)
        for item in manifest:
            if Path(item["path"]).suffix.lower() in (*JS_EXTENSIONS[:-1], ".json"):
                target = root / item["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(read_blob(settings, item["sha256"]))
        paths = [item["path"] for item in selected]
        try:
            result = run_cancellable(
                [node, str(helper), str(root), *paths], timeout=60, cancelled=cancelled,
            )
            if result.returncode != 0:
                return {}, f"TypeScript analyzer failed: {(result.stderr or result.stdout)[-500:]}"
            rows = json.loads(result.stdout)
            return {item["file"].replace("\\", "/"): item for item in rows}, None
        except ProcessCancelled:
            raise
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            return {}, f"TypeScript analyzer unavailable: {exc}"


def _python_aliases(path: str) -> set[str]:
    parts = list(PurePosixPath(path).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    aliases = {".".join(parts)} if parts else set()
    if parts and parts[0] == "src" and len(parts) > 1:
        aliases.add(".".join(parts[1:]))
    return {alias for alias in aliases if alias}


def _module_index(manifest: list[dict]) -> tuple[dict[str, list[str]], dict[str, str]]:
    aliases: dict[str, list[str]] = defaultdict(list)
    primary: dict[str, str] = {}
    for item in manifest:
        path = item["path"]
        if not path.endswith((".py", ".pyi")):
            continue
        names = sorted(_python_aliases(path), key=lambda value: (value.startswith("src."), len(value)))
        if names:
            primary[path] = names[0]
        for name in names:
            aliases[name].append(path)
    return {name: sorted(paths) for name, paths in aliases.items()}, primary


def _resolve_python(
    current_path: str,
    current_module: str,
    node: ast.Import | ast.ImportFrom,
    aliases: dict[str, list[str]],
) -> list[dict]:
    requests: list[tuple[str, int]] = []
    if isinstance(node, ast.Import):
        requests.extend((alias.name, node.lineno) for alias in node.names)
    else:
        package = current_module if current_path.endswith("/__init__.py") or current_path == "__init__.py" else current_module.rpartition(".")[0]
        if node.level:
            package_parts = package.split(".") if package else []
            keep = max(0, len(package_parts) - (node.level - 1))
            base = ".".join(package_parts[:keep])
            module = ".".join(part for part in (base, node.module or "") if part)
        else:
            module = node.module or ""
        if node.module:
            requests.append((module, node.lineno))
        for imported in node.names:
            if imported.name != "*":
                candidate = ".".join(part for part in (module, imported.name) if part)
                if candidate in aliases or not node.module:
                    requests.append((candidate, node.lineno))
    results: list[dict] = []
    seen: set[str] = set()
    local_roots = {name.split(".", 1)[0] for name in aliases}
    for imported, line in requests:
        if not imported or imported in seen:
            continue
        seen.add(imported)
        targets = aliases.get(imported, [])
        if len(targets) == 1:
            status, target = "local", targets[0]
        elif len(targets) > 1:
            status, target = "ambiguous", None
        elif imported.split(".", 1)[0] in local_roots:
            status, target = "unresolved", None
        else:
            status, target = "external", None
        results.append({"specifier": imported, "line": line, "status": status, "target": target})
    return results


def _fallback_js_imports(text: str) -> list[dict]:
    imports: list[dict] = []
    for match in FALLBACK_IMPORT_RE.finditer(text):
        specifier = next(group for group in match.groups() if group is not None)
        imports.append({
            "specifier": specifier,
            "line": text.count("\n", 0, match.start()) + 1,
            "kind": "fallback",
            "resolved": None,
        })
    for match in re.finditer(r"(?:require|import)\s*\((?!\s*['\"])", text):
        imports.append({
            "specifier": None,
            "line": text.count("\n", 0, match.start()) + 1,
            "kind": "dynamic-expression",
            "resolved": None,
        })
    return imports


def _resolve_relative_js(current: str, specifier: str, known: set[str]) -> str | None:
    base = posixpath.normpath(posixpath.join(posixpath.dirname(current), specifier))
    candidates = [base]
    candidates.extend(base + extension for extension in RESOLUTION_EXTENSIONS)
    candidates.extend(posixpath.join(base, "index" + extension) for extension in RESOLUTION_EXTENSIONS)
    return next((candidate for candidate in candidates if candidate in known), None)


def _manifest_declarations(path: str, text: str) -> tuple[list[dict], list[str]]:
    declarations: list[dict] = []
    diagnostics: list[str] = []
    try:
        if path.endswith("package.json"):
            data = json.loads(text)
            for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
                for name, version in sorted((data.get(section) or {}).items()):
                    declarations.append({"name": name, "version": str(version), "section": section})
        elif path.endswith("pyproject.toml"):
            data = tomllib.loads(text)
            for raw in data.get("project", {}).get("dependencies", []):
                match = re.match(r"([A-Za-z0-9_.-]+)\s*(.*)", raw)
                if match:
                    declarations.append({"name": match.group(1).lower(), "version": match.group(2).strip(), "section": "project.dependencies"})
            for group, values in sorted(data.get("project", {}).get("optional-dependencies", {}).items()):
                for raw in values:
                    match = re.match(r"([A-Za-z0-9_.-]+)\s*(.*)", raw)
                    if match:
                        declarations.append({"name": match.group(1).lower(), "version": match.group(2).strip(), "section": f"optional.{group}"})
        elif PurePosixPath(path).name.lower().startswith("requirements") and path.endswith(".txt"):
            for line in text.splitlines():
                raw = line.strip()
                if raw and not raw.startswith(("#", "-")):
                    match = re.match(r"([A-Za-z0-9_.-]+)\s*(.*)", raw)
                    if match:
                        declarations.append({"name": match.group(1).lower(), "version": match.group(2).strip(), "section": "requirements"})
    except (json.JSONDecodeError, tomllib.TOMLDecodeError, TypeError) as exc:
        diagnostics.append(f"Manifest parse error in {path}: {exc}")
    return declarations, diagnostics


def analyze_snapshot(
    settings: Settings,
    manifest: list[dict],
    *,
    cancelled: Callable[[], bool] | None = None,
) -> dict:
    is_cancelled = cancelled or (lambda: False)
    aliases, primary_modules = _module_index(manifest)
    known_paths = {item["path"] for item in manifest}
    typed_js, compiler_omission = _typescript_analysis(settings, manifest, is_cancelled)
    files: list[dict] = []
    edge_map: dict[tuple[str, str, str], dict] = {}
    unresolved: list[dict] = []
    omissions: list[str] = []
    manifests: dict[str, list[dict]] = {}
    language_counts: dict[str, int] = defaultdict(int)
    if compiler_omission:
        omissions.append(compiler_omission)

    for item in manifest:
        if is_cancelled():
            raise ProcessCancelled("Static analysis cancelled")
        path = item["path"]
        suffix = Path(path).suffix.lower()
        text = read_blob(settings, item["sha256"]).decode("utf-8", errors="replace")
        definitions: list[dict] = []
        imports: list[dict] = []
        diagnostics: list[str] = []
        parser = "unsupported"
        status = "not_applicable"
        language = "other"

        if suffix in {".py", ".pyi"}:
            language, parser = "python", "python_ast"
            try:
                tree = ast.parse(text, filename=path)
                status = "parsed"
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        definitions.append({
                            "name": node.name,
                            "kind": "class" if isinstance(node, ast.ClassDef) else "function",
                            "line": node.lineno,
                        })
                    elif isinstance(node, (ast.Import, ast.ImportFrom)):
                        imports.extend(_resolve_python(path, primary_modules[path], node, aliases))
            except SyntaxError as exc:
                status = "failed"
                diagnostics.append(f"Python syntax error at line {exc.lineno}: {exc.msg}")
        elif suffix in JS_EXTENSIONS:
            if suffix == ".dsa":
                language, parser, status = "daz-script", "daz_limited", "limited"
                imports = _fallback_js_imports(text)
            else:
                language = "javascript-typescript"
                compiler_result = typed_js.get(path)
                if compiler_result:
                    parser, status = "typescript_compiler", "parsed"
                    definitions = compiler_result.get("definitions", [])
                    imports = compiler_result.get("imports", [])
                    diagnostics.extend(compiler_result.get("diagnostics", []))
                    if diagnostics:
                        status = "limited"
                else:
                    parser, status = "regex_fallback", "limited"
                    imports = _fallback_js_imports(text)
                    for match in re.finditer(r"(?:class|function)\s+([A-Za-z_$][\w$]*)", text):
                        definitions.append({
                            "name": match.group(1), "kind": "definition",
                            "line": text.count("\n", 0, match.start()) + 1,
                        })
            for imported in imports:
                specifier = imported.get("specifier")
                resolved = imported.get("resolved")
                if resolved:
                    target = resolved.replace("\\", "/")
                elif specifier and specifier.startswith("."):
                    target = _resolve_relative_js(path, specifier, known_paths)
                else:
                    target = None
                if target:
                    imported.update({"status": "local", "target": target})
                elif specifier is None:
                    imported.update({"status": "unresolved", "target": None})
                elif specifier.startswith(('.', '/')):
                    imported.update({"status": "unresolved", "target": None})
                else:
                    imported.update({"status": "external", "target": None})
        elif suffix in {".json", ".toml", ".yaml", ".yml"}:
            language, parser, status = "configuration", "manifest_or_configuration", "parsed"

        declarations, manifest_diagnostics = _manifest_declarations(path, text)
        if declarations or manifest_diagnostics:
            manifests[path] = declarations
            diagnostics.extend(manifest_diagnostics)
            if manifest_diagnostics:
                status = "limited"
        for imported in imports:
            if imported.get("status") == "local" and imported.get("target") != path:
                key = (path, imported["target"], "imports")
                edge_map.setdefault(key, {
                    "source": path, "target": imported["target"], "kind": "imports",
                    "inferred": False, "line": imported["line"], "specifier": imported.get("specifier"),
                })
            elif imported.get("status") in {"unresolved", "ambiguous"}:
                unresolved.append({
                    "path": path, "import": imported.get("specifier") or "<dynamic expression>",
                    "line": imported["line"], "status": imported["status"],
                })
        language_counts[language] += 1
        files.append({
            "path": path, "language": language, "lines": item["lines"],
            "definitions": sorted(definitions, key=lambda value: (value["line"], value["name"]))[:100],
            "imports": imports[:100], "parser": parser, "status": status,
            "diagnostics": diagnostics,
        })
        omissions.extend(f"{path}: {diagnostic}" for diagnostic in diagnostics)

    edges = [edge_map[key] for key in sorted(edge_map)]
    graph: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        graph[edge["source"]].append(edge["target"])
    cycles = _strongly_connected_cycles(graph, known_paths)
    parsed_files = sum(file["status"] == "parsed" for file in files)
    limited_files = sum(file["status"] in {"limited", "failed"} for file in files)
    coverage = {
        "languages": dict(sorted(language_counts.items())),
        "parsed_files": parsed_files,
        "limited_files": limited_files,
        "total_files": len(files),
        "level": "limited" if limited_files or compiler_omission else "standard",
        "omissions": omissions,
        "per_file": [{"path": f["path"], "parser": f["parser"], "status": f["status"], "diagnostics": f["diagnostics"]} for f in files],
    }
    return {
        "files": files,
        "edges": edges,
        "cycles": cycles,
        "unresolved_imports": sorted(unresolved, key=lambda value: (value["path"], value["line"], value["import"]))[:200],
        "manifests": manifests,
        "coverage": coverage,
    }


def _strongly_connected_cycles(graph: dict[str, list[str]], nodes: set[str]) -> list[list[str]]:
    all_nodes = sorted(nodes | set(graph) | {target for targets in graph.values() for target in targets})
    visited: set[str] = set()
    order: list[str] = []
    for start in all_nodes:
        if start in visited:
            continue
        stack: list[tuple[str, bool]] = [(start, False)]
        while stack:
            node, finished = stack.pop()
            if finished:
                order.append(node)
                continue
            if node in visited:
                continue
            visited.add(node)
            stack.append((node, True))
            for target in sorted(graph.get(node, []), reverse=True):
                if target not in visited:
                    stack.append((target, False))
    reverse: dict[str, list[str]] = defaultdict(list)
    for source, targets in graph.items():
        for target in targets:
            reverse[target].append(source)
    visited.clear()
    components: list[list[str]] = []
    for start in reversed(order):
        if start in visited:
            continue
        component: list[str] = []
        stack = [(start, False)]
        while stack:
            node, _ = stack.pop()
            if node in visited:
                continue
            visited.add(node)
            component.append(node)
            stack.extend((target, False) for target in sorted(reverse.get(node, []), reverse=True) if target not in visited)
        component.sort()
        if len(component) > 1 or start in graph.get(start, []):
            components.append(component)
    return [component + [component[0]] for component in sorted(components)]


def manifest_changes(before: dict[str, list[dict]], after: dict[str, list[dict]]) -> dict:
    def flatten(source: dict[str, list[dict]]) -> dict[tuple[str, str, str], str]:
        return {
            (path, declaration["section"], declaration["name"]): declaration["version"]
            for path, declarations in source.items() for declaration in declarations
        }

    old, new = flatten(before), flatten(after)
    return {
        "added": [{"path": key[0], "section": key[1], "name": key[2], "version": new[key]} for key in sorted(new.keys() - old.keys())],
        "removed": [{"path": key[0], "section": key[1], "name": key[2], "version": old[key]} for key in sorted(old.keys() - new.keys())],
        "changed": [
            {"path": key[0], "section": key[1], "name": key[2], "before": old[key], "after": new[key]}
            for key in sorted(old.keys() & new.keys()) if old[key] != new[key]
        ],
    }


def compact_analysis(analysis: dict, limit_files: int = 250) -> dict:
    return {
        **analysis,
        "files": analysis["files"][:limit_files],
        "unresolved_imports": analysis["unresolved_imports"][:50],
    }

from __future__ import annotations

from pathlib import Path

from archcoach.analyze import _strongly_connected_cycles, analyze_snapshot, manifest_changes
from archcoach.capture import capture_project
from archcoach.config import Settings


def analyze_project(tmp_path: Path, files: dict[str, str]) -> dict:
    project = tmp_path / "fixture"
    project.mkdir()
    for name, content in files.items():
        target = project / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    settings = Settings.load(tmp_path / "data")
    settings.ensure_dirs()
    captured = capture_project(settings, {"path": str(project), "exclusions": []})
    return analyze_snapshot(settings, captured["manifest"])


def test_python_packages_relative_imports_and_src_layout(tmp_path: Path):
    analysis = analyze_project(tmp_path, {
        "src/acme/__init__.py": "from .helper import work\n",
        "src/acme/helper.py": "from . import util\ndef work(): return util.value\n",
        "src/acme/util.py": "value = 1\n",
        "src/acme/service.py": "from acme.helper import work\n",
    })

    edges = {(edge["source"], edge["target"], edge["line"]) for edge in analysis["edges"]}
    assert ("src/acme/__init__.py", "src/acme/helper.py", 1) in edges
    assert ("src/acme/helper.py", "src/acme/util.py", 1) in edges
    assert ("src/acme/service.py", "src/acme/helper.py", 1) in edges
    assert not analysis["unresolved_imports"]


def test_typescript_commonjs_reexports_and_dynamic_imports(tmp_path: Path):
    analysis = analyze_project(tmp_path, {
        "tsconfig.json": '{"compilerOptions":{"baseUrl":".","paths":{"@/*":["src/*"]}}}',
        "src/main.ts": "import { util } from './util';\nconst common = require('./common');\nimport('./lazy');\nimport(variable);\nexport { util };\n",
        "src/util.ts": "export const util = 1;\n",
        "src/common.js": "module.exports = 2;\n",
        "src/lazy.ts": "export default 3;\n",
        "src/index.ts": "export { util } from '@/util';\n",
    })

    edges = {(edge["source"], edge["target"]) for edge in analysis["edges"]}
    assert ("src/main.ts", "src/util.ts") in edges
    assert ("src/main.ts", "src/common.js") in edges
    assert ("src/main.ts", "src/lazy.ts") in edges
    assert ("src/index.ts", "src/util.ts") in edges
    assert any(item["import"] == "<dynamic expression>" for item in analysis["unresolved_imports"])
    assert next(file for file in analysis["files"] if file["path"] == "src/main.ts")["parser"] == "typescript_compiler"


def test_daz_is_explicitly_limited_and_relations_are_source_backed(tmp_path: Path):
    analysis = analyze_project(tmp_path, {
        "main.dsa": "var helper = require('./helper');\n",
        "helper.dsa": "function work() { return 1; }\n",
    })

    assert analysis["coverage"]["level"] == "limited"
    assert all(file["parser"] == "daz_limited" for file in analysis["files"])
    assert analysis["edges"][0]["line"] == 1


def test_cycles_are_deterministic_and_large_acyclic_graph_is_bounded():
    graph = {f"n{i}": [f"n{i + 1}"] for i in range(5000)}
    assert _strongly_connected_cycles(graph, set(graph)) == []
    graph["n3"] = ["n1"]
    assert _strongly_connected_cycles(graph, set(graph))[0] == ["n1", "n2", "n3", "n1"]


def test_manifest_changes_separate_versions_from_additions():
    before = {"package.json": [
        {"name": "fast", "version": "1", "section": "dependencies"},
        {"name": "old", "version": "1", "section": "devDependencies"},
    ]}
    after = {"package.json": [
        {"name": "fast", "version": "2", "section": "dependencies"},
        {"name": "new", "version": "1", "section": "dependencies"},
    ]}

    changes = manifest_changes(before, after)

    assert [item["name"] for item in changes["added"]] == ["new"]
    assert [item["name"] for item in changes["removed"]] == ["old"]
    assert changes["changed"][0] == {
        "path": "package.json", "section": "dependencies", "name": "fast",
        "before": "1", "after": "2",
    }


def test_import_statuses_and_syntax_coverage_are_not_overstated(tmp_path: Path):
    analysis = analyze_project(tmp_path, {
        "main.py": "import requests\nimport package.missing\nimport package\n",
        "package/__init__.py": "value = 1\n",
        "broken.py": "def unfinished(:\n",
    })

    main = next(file for file in analysis["files"] if file["path"] == "main.py")
    statuses = {item["specifier"]: item["status"] for item in main["imports"]}
    assert statuses == {"requests": "external", "package.missing": "unresolved", "package": "local"}
    broken = next(item for item in analysis["coverage"]["per_file"] if item["path"] == "broken.py")
    assert broken["status"] == "failed"
    assert analysis["coverage"]["level"] == "limited"

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

from .ai import ARCHITECTURE_PROMPT, CRITIQUE_PROMPT, CHAT_PROMPT, CodexAdapter, CodexError
from .analyze import analyze_snapshot, compact_analysis
from .capture import capture_project, materialize_snapshot, read_blob
from .config import Settings
from .db import Store
from .diagram import render_comparison, render_diagram
from .models import Architecture, ChatResponse, Component, Critique, Evidence, Finding, Lesson, Relationship, utc_now


def _slug(text: str, fallback: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_-]+", "_", text).strip("_")
    if not value or not value[0].isalpha():
        value = "c_" + (value or fallback)
    return value[:50]


def heuristic_architecture(project: dict, analysis: dict) -> Architecture:
    grouped: dict[str, list[dict]] = {}
    for file in analysis["files"]:
        top = file["path"].split("/", 1)[0]
        key = top if "/" in file["path"] else file["path"]
        grouped.setdefault(key, []).append(file)
    groups = sorted(grouped.items(), key=lambda item: sum(f["lines"] for f in item[1]), reverse=True)[:12]
    components: list[Component] = []
    path_to_id: dict[str, str] = {}
    used: set[str] = set()
    for index, (name, files) in enumerate(groups):
        identifier = _slug(Path(name).stem, f"component_{index}")
        while identifier in used:
            identifier += f"_{index}"
        used.add(identifier)
        sample = files[0]
        kinds = {f["language"] for f in files}
        kind = "frontend" if any(Path(f["path"]).suffix in {".tsx", ".jsx", ".html", ".css"} for f in files) else "database" if any("db" in f["path"].lower() or f["path"].endswith(".sql") for f in files) else "backend"
        responsibility = f"{len(files)} source file{'s' if len(files) != 1 else ''}; {', '.join(sorted(kinds))}"
        components.append(Component(id=identifier, name=name, kind=kind, responsibility=responsibility, sources=[Evidence(path=sample["path"], line=1, label="Representative source")]))
        for file in files:
            path_to_id[file["path"]] = identifier
    relationships: list[Relationship] = []
    seen = set()
    for edge in analysis["edges"]:
        source, target = path_to_id.get(edge["source"]), path_to_id.get(edge["target"])
        if source and target and source != target and (source, target) not in seen:
            seen.add((source, target)); relationships.append(Relationship(source=source, target=target, label=edge["kind"], inferred=False))
    summary = project.get("description") or f"{project['name']} contains {len(analysis['files'])} analysed source and documentation files."
    main_path = [component.id for component in components[: min(4, len(components))]]
    return Architecture(summary=summary, main_path=main_path, components=components, relationships=relationships)


def heuristic_critique(analysis: dict) -> Critique:
    strengths = ["The project structure and dependencies were captured without executing project code."]
    findings: list[Finding] = []
    lessons: list[Lesson] = []
    largest = sorted(analysis["files"], key=lambda f: f["lines"], reverse=True)
    if largest and largest[0]["lines"] > 500:
        file = largest[0]
        evidence = [Evidence(path=file["path"], line=1, label="Large module")]
        findings.append(Finding(id="large-module", severity="medium", title="One module carries substantial weight", observation=f"{file['path']} has {file['lines']} lines.", why_it_matters="Large modules can make unrelated changes interfere with each other.", improvement="Identify one cohesive responsibility that can move behind a small interface.", tradeoffs="Splitting too early can scatter closely related logic.", evidence=evidence))
        lessons.append(Lesson(id="cohesion", title="Cohesion and module boundaries", explanation="A cohesive module contains code that changes for the same reason.", code_example=f"# Start by listing the responsibilities in {file['path']}", self_check="Which functions in this module usually change together?", answer="Functions that serve the same responsibility are candidates to remain together.", exercise="Name the module's responsibilities before proposing any split.", evidence=evidence))
    if analysis["cycles"]:
        cycle = analysis["cycles"][0]
        evidence = [Evidence(path=cycle[0], line=1, label="Dependency cycle")]
        findings.append(Finding(id="dependency-cycle", severity="high", title="Modules form a dependency cycle", observation=" → ".join(cycle), why_it_matters="Cycles make initialization, testing, and isolated change harder.", improvement="Move the shared contract or data type to a lower-level module.", tradeoffs="A new shared module is only useful when the shared responsibility is clear.", evidence=evidence))
    if not lessons:
        sample = analysis["files"][0] if analysis["files"] else {"path": "README.md"}
        lessons.append(Lesson(id="boundaries", title="Architectural boundaries", explanation="A boundary groups code with one responsibility and controls what crosses into it.", code_example=f"# Inspect the imports entering {sample['path']}", self_check="What would callers need if this module were replaced?", answer="That minimum set of behavior is the module's practical interface.", exercise="Write one sentence describing what this module owns.", evidence=[Evidence(path=sample["path"], line=1)] if analysis["files"] else []))
    return Critique(strengths=strengths, findings=findings[:5], lessons=lessons[:3])


def validate_evidence(model, manifest: list[dict]):
    lines = {item["path"]: item["lines"] for item in manifest}
    for collection in (getattr(model, "components", []), getattr(model, "findings", []), getattr(model, "lessons", [])):
        for item in collection:
            for evidence in item.sources if hasattr(item, "sources") else item.evidence:
                evidence.valid = evidence.path in lines and 1 <= evidence.line <= max(1, lines.get(evidence.path, 0)) and (evidence.end_line is None or evidence.end_line <= max(1, lines.get(evidence.path, 0)))
    return model


def validate_evidence_items(items: list[Evidence], manifest: list[dict]) -> list[Evidence]:
    lines = {item["path"]: item["lines"] for item in manifest}
    for evidence in items:
        last_line = max(1, lines.get(evidence.path, 0))
        evidence.valid = evidence.path in lines and 1 <= evidence.line <= last_line and (evidence.end_line is None or evidence.end_line <= last_line)
    return items


def validate_critique_quality(critique: Critique) -> Critique:
    blocked_markers = ("review blocked", "cannot access", "could not access", "unable to access", "provide their contents")
    if any(any(marker in strength.lower() for marker in blocked_markers) for strength in critique.strengths):
        raise ValueError("Codex did not have enough source access to complete the critique")
    return critique


def calculate_changes(previous: dict | None, previous_snapshot: dict | None, current_manifest: list[dict], architecture: Architecture, analysis: dict) -> dict:
    if not previous:
        return {"baseline": True, "components_added": [c.id for c in architecture.components], "components_removed": [], "components_changed": [], "relationships_added": [], "relationships_removed": [], "files_added": [item["path"] for item in current_manifest], "files_removed": [], "files_changed": []}
    before = Architecture.model_validate(previous["architecture"])
    before_components = {c.id: c.model_dump() for c in before.components}; after_components = {c.id: c.model_dump() for c in architecture.components}
    before_rel = {(r.source, r.target, r.label) for r in before.relationships}; after_rel = {(r.source, r.target, r.label) for r in architecture.relationships}
    old_files = {item["path"]: item["sha256"] for item in (previous_snapshot or {}).get("manifest", [])}; new_files = {item["path"]: item["sha256"] for item in current_manifest}
    return {"baseline": False, "components_added": sorted(after_components.keys() - before_components.keys()), "components_removed": sorted(before_components.keys() - after_components.keys()), "components_changed": sorted(k for k in before_components.keys() & after_components.keys() if before_components[k] != after_components[k]), "relationships_added": sorted(list(after_rel - before_rel)), "relationships_removed": sorted(list(before_rel - after_rel)), "files_added": sorted(new_files.keys() - old_files.keys()), "files_removed": sorted(old_files.keys() - new_files.keys()), "files_changed": sorted(k for k in new_files.keys() & old_files.keys() if new_files[k] != old_files[k])}


class ReviewEngine:
    def __init__(self, settings: Settings, store: Store, codex: CodexAdapter | None = None):
        self.settings, self.store, self.codex = settings, store, codex or CodexAdapter(settings)

    def run(self, project_id: str, progress=lambda p, m: None) -> str:
        project = self.store.get_project(project_id)
        progress(5, "Capturing current files")
        capture = capture_project(self.settings, project)
        previous = None; previous_snapshot = None
        for candidate in self.store.list_reviews(project_id):
            if candidate["status"] not in {"complete", "unchanged"}: continue
            candidate_snapshot = self.store.get_snapshot(candidate["snapshot_id"])
            if candidate_snapshot["git"].get("branch") == capture["git"].get("branch"):
                previous, previous_snapshot = candidate, candidate_snapshot
                break
        analysis = analyze_snapshot(self.settings, capture["manifest"])
        coverage = {**analysis["coverage"], "capture_omissions": capture["omissions"], "unstable": capture["unstable"]}
        snapshot_id = self.store.create_snapshot(project_id, capture["fingerprint"], capture["manifest"], capture["git"], analysis, coverage)
        if previous:
            same_branch = previous_snapshot["git"].get("branch") == capture["git"].get("branch")
            if previous_snapshot["fingerprint"] == capture["fingerprint"] and same_branch:
                review_id = self.store.create_review(project_id, snapshot_id, previous["id"], "unchanged", previous["architecture"], previous["critique"], {"unchanged": True}, previous["artifacts"], previous["id"])
                self.store.update_project(project_id, last_checked_at=utc_now()); progress(100, "No source changes")
                return review_id
        with tempfile.TemporaryDirectory(prefix="archcoach-snapshot-") as temp:
            root = Path(temp); materialize_snapshot(self.settings, {"manifest": capture["manifest"]}, root)
            (root / "static-analysis.json").write_text(json.dumps(compact_analysis(analysis), indent=2), encoding="utf-8")
            ai_warnings: list[str] = []
            progress(25, "Building architecture")
            try:
                raw = self.codex.run_structured(ARCHITECTURE_PROMPT.format(description=project["description"], goal=project["goal"], coverage=json.dumps(coverage)), self.settings.schema_dir / "architecture.json", root)
                architecture = Architecture.model_validate(raw)
            except (CodexError, ValueError, json.JSONDecodeError) as exc:
                ai_warnings.append(f"Architecture analysis used the deterministic fallback: {exc}")
                architecture = heuristic_architecture(project, analysis)
            validate_evidence(architecture, capture["manifest"])
            changes = calculate_changes(previous, previous_snapshot, capture["manifest"], architecture, analysis)
            (root / "architecture.json").write_text(architecture.model_dump_json(indent=2), encoding="utf-8")
            progress(55, "Reviewing design and preparing lessons")
            try:
                raw = self.codex.run_structured(CRITIQUE_PROMPT.format(goal=project["goal"], changes=json.dumps(changes)), self.settings.schema_dir / "critique.json", root)
                critique = validate_critique_quality(Critique.model_validate(raw))
            except (CodexError, ValueError, json.JSONDecodeError) as exc:
                ai_warnings.append(f"Critique used the deterministic fallback: {exc}")
                critique = heuristic_critique(analysis)
            validate_evidence(critique, capture["manifest"])
        review_stub = self.store.create_review(project_id, snapshot_id, previous["id"] if previous else None, "rendering", architecture.model_dump(), critique.model_dump(), changes, {})
        artifact_dir = self.settings.artifact_dir / project_id / review_stub
        progress(80, "Rendering architecture")
        artifacts = render_diagram(self.settings, architecture, f"{project['name']} architecture", artifact_dir)
        artifacts["ai_warnings"] = ai_warnings
        if previous and previous["artifacts"].get("architecture_ir"):
            comparison = render_comparison(self.settings, Path(previous["artifacts"]["architecture_ir"]), Path(artifacts["architecture_ir"]), artifact_dir / "comparison.html")
            if comparison: artifacts["comparison"] = comparison
        report_path = artifact_dir / "review.md"; artifact_dir.mkdir(parents=True, exist_ok=True)
        report_path.write_text(markdown_report(project, architecture, critique, changes), encoding="utf-8")
        artifacts["report"] = str(report_path)
        with self.store.connect() as conn:
            conn.execute("UPDATE reviews SET status='complete', artifacts_json=? WHERE id=?", (json.dumps(artifacts), review_stub))
        self.store.update_project(project_id, last_checked_at=utc_now()); progress(100, "Review complete")
        return review_stub

    def chat(self, review_id: str, message: str) -> str:
        review = self.store.get_review(review_id); snapshot = self.store.get_snapshot(review["snapshot_id"]); conversation = self.store.conversation_for_review(review_id)
        self.store.add_message(conversation["id"], "user", message)
        history = "\n".join(f"{m['role']}: {m['content']}" for m in conversation["messages"][-10:])
        with tempfile.TemporaryDirectory(prefix="archcoach-chat-") as temp:
            root = Path(temp); materialize_snapshot(self.settings, snapshot, root)
            (root / "review-context.json").write_text(json.dumps({"architecture": review["architecture"], "critique": review["critique"], "changes": review["changes"]}, indent=2), encoding="utf-8")
            try:
                response = ChatResponse.model_validate(self.codex.run_structured(CHAT_PROMPT.format(history=history, message=message), self.settings.schema_dir / "chat.json", root))
                citations = validate_evidence_items(response.citations, snapshot["manifest"])
                answer = response.answer
            except (CodexError, ValueError, KeyError, json.JSONDecodeError) as exc:
                answer = f"I could not run Codex for this question: {exc}. The saved review remains available."
                citations = []
        self.store.add_message(conversation["id"], "assistant", answer, [item.model_dump() for item in citations])
        return conversation["id"]


def markdown_report(project: dict, architecture: Architecture, critique: Critique, changes: dict) -> str:
    lines = [f"# {project['name']} architecture review", "", architecture.summary, "", "## Main path", "", " → ".join(architecture.main_path) or "No main path confirmed.", "", "## What changed", "", "Baseline review." if changes.get("baseline") else json.dumps(changes, indent=2), "", "## What works well", ""]
    lines.extend(f"- {item}" for item in critique.strengths)
    lines += ["", "## What could improve", ""]
    for finding in critique.findings:
        lines += [f"### {finding.severity.upper()}: {finding.title}", "", finding.observation, "", f"Why it matters: {finding.why_it_matters}", "", f"Smallest improvement: {finding.improvement}", "", f"Tradeoffs: {finding.tradeoffs}", ""]
    if not critique.findings: lines += ["No justified architecture concerns were found.", ""]
    lines += ["## What to learn", ""]
    for lesson in critique.lessons: lines += [f"### {lesson.title}", "", lesson.explanation, "", f"Exercise: {lesson.exercise}", ""]
    return "\n".join(lines)


def source_text(settings: Settings, snapshot: dict, relative_path: str) -> str:
    normalized = Path(relative_path).as_posix().lstrip("/")
    item = next((entry for entry in snapshot["manifest"] if entry["path"] == normalized), None)
    if not item: raise KeyError(relative_path)
    return read_blob(settings, item["sha256"]).decode("utf-8", errors="replace")

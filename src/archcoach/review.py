from __future__ import annotations

import json
import re
import tempfile
import hashlib
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

from .ai import ARCHITECTURE_PROMPT, CRITIQUE_PROMPT, CHAT_PROMPT, CodexAdapter, CodexError
from .analyze import analyze_snapshot, compact_analysis, manifest_changes
from .capture import CaptureCancelled, capture_project, materialize_snapshot, read_blob
from .config import Settings
from .db import JobCancelledError, Store
from .diagram import render_comparison, render_diagram, stable_positions
from .models import Architecture, ChatResponse, Component, Critique, Evidence, Finding, Lesson, Relationship, utc_now
from .subprocesses import ProcessCancelled


class ReviewCancelled(RuntimeError):
    pass


ANALYSIS_FORMAT_VERSION = 2
REVIEW_FORMAT_VERSION = 2


def review_configuration_fingerprint(project: dict, settings: Settings) -> str:
    relevant = {
        "description": project.get("description", ""),
        "goal": project.get("goal", ""),
        "exclusions": sorted(project.get("exclusions", [])),
        "analysis_format": ANALYSIS_FORMAT_VERSION,
        "review_format": REVIEW_FORMAT_VERSION,
        "codex_command": settings.codex_command,
    }
    return hashlib.sha256(json.dumps(relevant, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


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
        components.append(Component(
            id=identifier, name=name, kind=kind, responsibility=responsibility,
            sources=[Evidence(path=sample["path"], line=1, label="Representative source")],
            source_paths=sorted(file["path"] for file in files),
        ))
        for file in files:
            path_to_id[file["path"]] = identifier
    relationships: list[Relationship] = []
    seen = set()
    for edge in analysis["edges"]:
        source, target = path_to_id.get(edge["source"]), path_to_id.get(edge["target"])
        if source and target and source != target and (source, target) not in seen:
            seen.add((source, target)); relationships.append(Relationship(source=source, target=target, label=edge["kind"], inferred=False))
    description = project.get("description") or f"{project['name']} contains {len(analysis['files'])} analysed source and documentation files."
    summary = f"{description} This limited static view confirms source dependencies; runtime execution order is unconfirmed."
    return Architecture(summary=summary, main_path=[], components=components, relationships=relationships)


def heuristic_critique(analysis: dict) -> Critique:
    strengths: list[str] = []
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
        matching_edge = next((edge for edge in analysis["edges"] if edge["source"] == cycle[0] and edge["target"] == cycle[1]), None)
        evidence = [Evidence(path=cycle[0], line=(matching_edge or {}).get("line", 1), label="Static dependency-cycle edge")]
        findings.append(Finding(id="dependency-cycle", severity="high", title="Modules form a dependency cycle", observation="Static import analysis found: " + " → ".join(cycle), why_it_matters="Cycles can make initialization, testing, and isolated change harder; runtime impact remains an inference until exercised.", improvement="Inspect the cited import edge and move a shared contract only if both modules truly need it.", tradeoffs="A new shared module is only useful when the shared responsibility is clear.", evidence=evidence))
    if not lessons:
        sample = analysis["files"][0] if analysis["files"] else {"path": "README.md"}
        lessons.append(Lesson(id="boundaries", title="Architectural boundaries", explanation="A boundary groups code with one responsibility and controls what crosses into it.", code_example=f"# Inspect the imports entering {sample['path']}", self_check="What would callers need if this module were replaced?", answer="That minimum set of behavior is the module's practical interface.", exercise="Write one sentence describing what this module owns.", evidence=[Evidence(path=sample["path"], line=1)] if analysis["files"] else []))
    return Critique(strengths=strengths, findings=findings[:5], lessons=lessons[:3])


def validate_evidence(model, manifest: list[dict]):
    lines = {item["path"]: item["lines"] for item in manifest}
    for collection in (getattr(model, "components", []), getattr(model, "findings", []), getattr(model, "lessons", [])):
        for item in collection:
            for evidence in item.sources if hasattr(item, "sources") else item.evidence:
                actual = lines.get(evidence.path, 0)
                evidence.valid = evidence.path in lines and 1 <= evidence.line <= actual and (
                    evidence.end_line is None or evidence.line <= evidence.end_line <= actual
                )
            if hasattr(item, "source_paths"):
                item.source_paths = sorted(set(item.source_paths))
    return model


def validate_architecture_snapshot(architecture: Architecture, manifest: list[dict]) -> Architecture:
    known = {item["path"] for item in manifest}
    invalid_membership = sorted({
        path for component in architecture.components for path in component.source_paths if path not in known
    })
    if invalid_membership:
        raise ValueError(f"Component membership refers to files outside the snapshot: {invalid_membership}")
    return validate_evidence(architecture, manifest)


def validate_evidence_items(items: list[Evidence], manifest: list[dict]) -> list[Evidence]:
    lines = {item["path"]: item["lines"] for item in manifest}
    for evidence in items:
        last_line = lines.get(evidence.path, 0)
        evidence.valid = evidence.path in lines and 1 <= evidence.line <= last_line and (
            evidence.end_line is None or evidence.line <= evidence.end_line <= last_line
        )
    return items


def validate_critique_quality(critique: Critique) -> Critique:
    blocked_markers = ("review blocked", "cannot access", "could not access", "unable to access", "provide their contents")
    if any(any(marker in strength.lower() for marker in blocked_markers) for strength in critique.strengths):
        raise ValueError("Codex did not have enough source access to complete the critique")
    return critique


def _membership(component: Component) -> tuple[str, ...]:
    return tuple(sorted(set(component.source_paths or [source.path for source in component.sources])))


def preserve_component_identity(
    previous: Architecture,
    previous_manifest: list[dict],
    current: Architecture,
    current_manifest: list[dict],
) -> tuple[Architecture, list[dict]]:
    old_hashes = {item["path"]: item["sha256"] for item in previous_manifest}
    new_hashes = {item["path"]: item["sha256"] for item in current_manifest}
    old_anchors = {
        component.id: ({*(_membership(component))}, {old_hashes[path] for path in _membership(component) if path in old_hashes})
        for component in previous.components
    }
    candidates: dict[str, list[str]] = {}
    uncertainty: list[dict] = []
    for component in current.components:
        paths = set(_membership(component))
        hashes = {new_hashes[path] for path in paths if path in new_hashes}
        matches = [
            identifier for identifier, (old_paths, old_content) in old_anchors.items()
            if paths & old_paths or hashes & old_content
        ]
        candidates[component.id] = sorted(matches)
        if len(matches) > 1:
            matched_path_sets = [old_anchors[identifier][0] for identifier in matches]
            disjoint = all(
                not matched_path_sets[left] & matched_path_sets[right]
                for left in range(len(matched_path_sets)) for right in range(left + 1, len(matched_path_sets))
            )
            uncertainty.append({
                "type": "merge" if disjoint else "ambiguous",
                "component": component.id,
                "candidates": sorted(matches),
            })
    reverse: dict[str, list[str]] = defaultdict(list)
    for current_id, matches in candidates.items():
        if len(matches) == 1:
            reverse[matches[0]].append(current_id)
    for old_id, matches in reverse.items():
        if len(matches) > 1:
            uncertainty.append({"type": "split", "component": old_id, "candidates": sorted(matches)})
    rename = {
        current_id: matches[0]
        for current_id, matches in candidates.items()
        if len(matches) == 1 and len(reverse[matches[0]]) == 1
    }
    occupied = {component.id for component in current.components}
    rename = {new: old for new, old in rename.items() if old == new or old not in occupied}
    for component in current.components:
        component.id = rename.get(component.id, component.id)
    for relationship in current.relationships:
        relationship.source = rename.get(relationship.source, relationship.source)
        relationship.target = rename.get(relationship.target, relationship.target)
    current.main_path = [rename.get(identifier, identifier) for identifier in current.main_path]
    return Architecture.model_validate(current.model_dump()), uncertainty


def semantic_comparison(
    before: Architecture | None,
    before_snapshot: dict | None,
    after: Architecture,
    after_snapshot: dict,
    *,
    identity_uncertainty: list[dict] | None = None,
) -> dict:
    current_manifest = after_snapshot.get("manifest", [])
    branch_context = {
        "before": (before_snapshot or {}).get("git", {}).get("branch"),
        "after": after_snapshot.get("git", {}).get("branch"),
        "changed": before_snapshot is not None and (before_snapshot or {}).get("git", {}).get("branch") != after_snapshot.get("git", {}).get("branch"),
    }
    coverage_context = {
        "before": (before_snapshot or {}).get("coverage", {}).get("level"),
        "after": after_snapshot.get("coverage", {}).get("level"),
    }
    if before is None:
        return {
            "baseline": True, "components_added": sorted(c.id for c in after.components),
            "components_removed": [], "components_changed": [], "relationships_added": [],
            "relationships_removed": [], "inferred_relationships_added": [],
            "inferred_relationships_removed": [], "files_added": sorted(item["path"] for item in current_manifest),
            "files_removed": [], "files_changed": [], "manifest_changes": manifest_changes({}, after_snapshot.get("analysis", {}).get("manifests", {})),
            "identity_uncertainty": identity_uncertainty or [],
            "branches": branch_context, "coverage": coverage_context,
        }
    before_components = {component.id: (component.kind, _membership(component)) for component in before.components}
    after_components = {component.id: (component.kind, _membership(component)) for component in after.components}
    confirmed_before = {(r.source, r.target) for r in before.relationships if not r.inferred}
    confirmed_after = {(r.source, r.target) for r in after.relationships if not r.inferred}
    inferred_before = {(r.source, r.target) for r in before.relationships if r.inferred}
    inferred_after = {(r.source, r.target) for r in after.relationships if r.inferred}
    old_files = {item["path"]: item["sha256"] for item in (before_snapshot or {}).get("manifest", [])}
    new_files = {item["path"]: item["sha256"] for item in current_manifest}
    return {
        "baseline": False,
        "components_added": sorted(after_components.keys() - before_components.keys()),
        "components_removed": sorted(before_components.keys() - after_components.keys()),
        "components_changed": sorted(key for key in before_components.keys() & after_components.keys() if before_components[key] != after_components[key]),
        "relationships_added": sorted(confirmed_after - confirmed_before),
        "relationships_removed": sorted(confirmed_before - confirmed_after),
        "inferred_relationships_added": sorted(inferred_after - inferred_before),
        "inferred_relationships_removed": sorted(inferred_before - inferred_after),
        "files_added": sorted(new_files.keys() - old_files.keys()),
        "files_removed": sorted(old_files.keys() - new_files.keys()),
        "files_changed": sorted(key for key in new_files.keys() & old_files.keys() if new_files[key] != old_files[key]),
        "manifest_changes": manifest_changes((before_snapshot or {}).get("analysis", {}).get("manifests", {}), after_snapshot.get("analysis", {}).get("manifests", {})),
        "identity_uncertainty": identity_uncertainty or [],
        "branches": branch_context, "coverage": coverage_context,
    }


def calculate_changes(previous: dict | None, previous_snapshot: dict | None, current_manifest: list[dict], architecture: Architecture, analysis: dict, identity_uncertainty: list[dict] | None = None) -> dict:
    if not previous:
        return semantic_comparison(None, None, architecture, {"manifest": current_manifest, "analysis": analysis}, identity_uncertainty=identity_uncertainty)
    return semantic_comparison(
        Architecture.model_validate(previous["architecture"]), previous_snapshot,
        architecture, {"manifest": current_manifest, "analysis": analysis},
        identity_uncertainty=identity_uncertainty,
    )


def compare_saved_reviews(before: dict, before_snapshot: dict, after: dict, after_snapshot: dict) -> dict:
    return semantic_comparison(
        Architecture.model_validate(before["architecture"]), before_snapshot,
        Architecture.model_validate(after["architecture"]), after_snapshot,
        identity_uncertainty=after.get("changes", {}).get("identity_uncertainty", []),
    )


def validate_comparison_records(before: dict, after: dict) -> None:
    if before["project_id"] != after["project_id"]:
        raise ValueError("Reviews must belong to the same project")
    for review in (before, after):
        if review["status"] not in {"complete", "unchanged"}:
            raise ValueError("Comparison requires saved completed reviews")
        if review.get("quality") not in {"complete", "limited"}:
            raise ValueError("Legacy reviews need regeneration before semantic comparison")


class ReviewEngine:
    def __init__(self, settings: Settings, store: Store, codex: CodexAdapter | None = None):
        self.settings, self.store, self.codex = settings, store, codex or CodexAdapter(settings)

    def run(
        self,
        project_id: str,
        progress=lambda p, m: None,
        *,
        cancelled: Callable[[], bool] | None = None,
        job_id: str | None = None,
        force: bool = False,
    ) -> str:
        is_cancelled = cancelled or (lambda: False)

        def check_cancelled() -> None:
            if is_cancelled():
                self.codex.cancel()
                raise ReviewCancelled("Review cancelled")

        project = self.store.get_project(project_id)
        check_cancelled()
        progress(5, "Capturing current files")
        try:
            capture = capture_project(self.settings, project, cancelled=is_cancelled)
        except CaptureCancelled as exc:
            raise ReviewCancelled(str(exc)) from exc
        check_cancelled()
        config_fingerprint = review_configuration_fingerprint(project, self.settings)
        previous = None; previous_snapshot = None
        for candidate in self.store.list_reviews(project_id):
            if candidate["status"] not in {"complete", "unchanged"}:
                continue
            if candidate.get("format_version", 1) < REVIEW_FORMAT_VERSION or candidate.get("quality") not in {"complete", "limited"}:
                continue
            candidate_snapshot = self.store.get_snapshot(candidate["snapshot_id"])
            if candidate_snapshot["git"].get("branch") == capture["git"].get("branch"):
                previous, previous_snapshot = candidate, candidate_snapshot
                break
        if previous and not force:
            reusable = (
                previous.get("quality") == "complete"
                and previous_snapshot.get("format_version", 1) >= ANALYSIS_FORMAT_VERSION
                and previous_snapshot["fingerprint"] == capture["fingerprint"]
                and previous_snapshot.get("config_fingerprint") == config_fingerprint
                and capture.get("coverage") == "complete"
            )
            if reusable:
                check_cancelled()
                try:
                    self.store.record_unchanged_check(
                        project_id, previous["id"], capture["fingerprint"], config_fingerprint,
                        job_id=job_id,
                    )
                except JobCancelledError as exc:
                    raise ReviewCancelled(str(exc)) from exc
                progress(100, "No source or review-setting changes")
                return previous["id"]
        try:
            analysis = analyze_snapshot(self.settings, capture["manifest"], cancelled=is_cancelled)
        except ProcessCancelled as exc:
            raise ReviewCancelled(str(exc)) from exc
        check_cancelled()
        coverage = {**analysis["coverage"], "capture_omissions": capture["omissions"], "unstable": capture["unstable"]}
        snapshot_id = self.store.create_snapshot(
            project_id, capture["fingerprint"], capture["manifest"], capture["git"], analysis,
            coverage, config_fingerprint=config_fingerprint, format_version=ANALYSIS_FORMAT_VERSION,
        )
        with tempfile.TemporaryDirectory(prefix="archcoach-snapshot-") as temp:
            root = Path(temp); materialize_snapshot(self.settings, {"manifest": capture["manifest"]}, root)
            (root / "static-analysis.json").write_text(json.dumps(compact_analysis(analysis), indent=2), encoding="utf-8")
            ai_warnings: list[str] = []
            progress(25, "Building architecture")
            check_cancelled()
            try:
                raw = self.codex.run_structured(ARCHITECTURE_PROMPT.format(description=project["description"], goal=project["goal"], coverage=json.dumps(coverage)), self.settings.schema_dir / "architecture.json", root)
                architecture = validate_architecture_snapshot(Architecture.model_validate(raw), capture["manifest"])
            except (CodexError, ValueError, json.JSONDecodeError) as exc:
                check_cancelled()
                ai_warnings.append(f"Architecture analysis used the deterministic fallback: {exc}")
                architecture = heuristic_architecture(project, analysis)
            check_cancelled()
            validate_architecture_snapshot(architecture, capture["manifest"])
            identity_uncertainty: list[dict] = []
            if previous and previous_snapshot:
                architecture, identity_uncertainty = preserve_component_identity(
                    Architecture.model_validate(previous["architecture"]), previous_snapshot["manifest"],
                    architecture, capture["manifest"],
                )
            changes = calculate_changes(
                previous, previous_snapshot, capture["manifest"], architecture, analysis,
                identity_uncertainty,
            )
            (root / "architecture.json").write_text(architecture.model_dump_json(indent=2), encoding="utf-8")
            progress(55, "Reviewing design and preparing lessons")
            check_cancelled()
            try:
                raw = self.codex.run_structured(CRITIQUE_PROMPT.format(goal=project["goal"], changes=json.dumps(changes)), self.settings.schema_dir / "critique.json", root)
                critique = validate_critique_quality(Critique.model_validate(raw))
            except (CodexError, ValueError, json.JSONDecodeError) as exc:
                check_cancelled()
                ai_warnings.append(f"Critique used the deterministic fallback: {exc}")
                critique = heuristic_critique(analysis)
            validate_evidence(critique, capture["manifest"])
        check_cancelled()
        quality = "limited" if ai_warnings or capture.get("coverage") == "limited" or analysis["coverage"]["level"] == "limited" else "complete"
        positions = stable_positions(architecture, previous.get("positions") if previous else None)
        review_stub = self.store.create_review(
            project_id, snapshot_id, previous["id"] if previous else None, "rendering",
            architecture.model_dump(), critique.model_dump(), changes, {}, quality=quality,
            positions=positions,
        )
        artifact_dir = self.settings.artifact_dir / project_id / review_stub
        progress(80, "Rendering architecture")
        try:
            check_cancelled()
            artifacts = render_diagram(
                self.settings, architecture, f"{project['name']} architecture", artifact_dir,
                cancelled=is_cancelled, positions=positions,
            )
            check_cancelled()
            artifacts["ai_warnings"] = ai_warnings
            if previous and previous["artifacts"].get("architecture_ir"):
                comparison = render_comparison(
                    self.settings, Path(previous["artifacts"]["architecture_ir"]),
                    Path(artifacts["architecture_ir"]), artifact_dir / "comparison.html",
                    cancelled=is_cancelled,
                )
                if comparison:
                    artifacts["comparison"] = comparison
            check_cancelled()
            report_path = artifact_dir / "review.md"
            artifact_dir.mkdir(parents=True, exist_ok=True)
            report_path.write_text(markdown_report(project, architecture, critique, changes), encoding="utf-8")
            artifacts["report"] = str(report_path)
            check_cancelled()
            self.store.finalize_review(
                review_stub, project_id, artifacts, quality=quality, job_id=job_id,
            )
        except (ReviewCancelled, JobCancelledError, ProcessCancelled):
            self.store.delete_unpublished_review(review_stub)
            raise ReviewCancelled("Review cancelled before publication")
        progress(100, "Review complete" if quality == "complete" else "Limited review saved")
        return review_stub

    def chat(
        self,
        review_id: str,
        message: str,
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> str:
        is_cancelled = cancelled or (lambda: False)
        if is_cancelled():
            raise ReviewCancelled("Chat cancelled")
        review = self.store.get_review(review_id); snapshot = self.store.get_snapshot(review["snapshot_id"]); conversation = self.store.conversation_for_review(review_id)
        self.store.add_message(conversation["id"], "user", message)
        history = "\n".join(f"{m['role']}: {m['content']}" for m in conversation["messages"][-10:])
        with tempfile.TemporaryDirectory(prefix="archcoach-chat-") as temp:
            root = Path(temp); materialize_snapshot(self.settings, snapshot, root)
            (root / "review-context.json").write_text(json.dumps({"architecture": review["architecture"], "critique": review["critique"], "changes": review["changes"]}, indent=2), encoding="utf-8")
            try:
                response = ChatResponse.model_validate(self.codex.run_structured(CHAT_PROMPT.format(history=history, message=message), self.settings.schema_dir / "chat.json", root))
                if is_cancelled():
                    raise ReviewCancelled("Chat cancelled")
                citations = validate_evidence_items(response.citations, snapshot["manifest"])
                answer = response.answer
            except (CodexError, ValueError, KeyError, json.JSONDecodeError) as exc:
                if is_cancelled():
                    raise ReviewCancelled("Chat cancelled") from exc
                answer = f"I could not run Codex for this question: {exc}. The saved review remains available."
                citations = []
        if is_cancelled():
            raise ReviewCancelled("Chat cancelled")
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

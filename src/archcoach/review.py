from __future__ import annotations

import json
import re
import tempfile
import hashlib
import time
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

from .ai import ARCHITECTURE_PROMPT, CRITIQUE_PROMPT, CHAT_PROMPT, CodexAdapter, CodexError, CodexMalformedOutput
from .analyze import analyze_snapshot, compact_analysis, manifest_changes
from .capture import CaptureCancelled, capture_project, read_blob
from .config import Settings
from .context import bounded_history, build_source_packets
from .db import JobCancelledError, Store
from .diagram import render_comparison, render_diagram, stable_positions
from .models import Architecture, ChatResponse, Component, Critique, Evidence, Finding, Lesson, QuizQuestion, Relationship, utc_now
from .subprocesses import ProcessCancelled


class ReviewCancelled(RuntimeError):
    pass


ANALYSIS_FORMAT_VERSION = 2
REVIEW_FORMAT_VERSION = 4


def review_configuration_fingerprint(project: dict, settings: Settings) -> str:
    relevant = {
        "description": project.get("description", ""),
        "goal": project.get("goal", ""),
        "exclusions": sorted(project.get("exclusions", [])),
        "analysis_format": ANALYSIS_FORMAT_VERSION,
        "review_format": REVIEW_FORMAT_VERSION,
        "codex_command": settings.codex_command,
        "ai_provider": settings.ai_provider,
        "codex_model": settings.codex_model,
        "ollama_model": settings.ollama_model,
        "reasoning_effort": settings.reasoning_effort,
        "source_packet_chars": settings.source_packet_chars,
        "source_packet_limit": settings.source_packet_limit,
    }
    return hashlib.sha256(json.dumps(relevant, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _slug(text: str, fallback: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_-]+", "_", text).strip("_")
    if not value or not value[0].isalpha():
        value = "c_" + (value or fallback)
    return value[:50]


def heuristic_architecture(project: dict, analysis: dict) -> Architecture:
    all_files = analysis["files"]
    code_suffixes = {".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".dsa", ".html", ".css", ".sql"}
    code_files = [file for file in all_files if Path(file["path"]).suffix.lower() in code_suffixes]
    # Documentation and manifests inform the review but are not runtime components
    # when the snapshot contains source code.
    architecture_files = code_files or all_files
    grouped: dict[str, list[dict]] = {}
    for file in architecture_files:
        parts = file["path"].split("/")
        basename = parts[-1].lower()
        if parts[0].lower() in {"test", "tests"} or basename.startswith("test_") or ".test." in basename:
            key = "tests"
        elif len(parts) >= 3 and parts[0].lower() in {"src", "lib"}:
            key = "/".join(parts[:2])
        else:
            key = parts[0] if len(parts) > 1 else file["path"]
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
        definitions = [definition["name"] for file in files for definition in file.get("definitions", [])]
        local_imports = sum(
            imported.get("status") == "local"
            for file in files for imported in file.get("imports", [])
        )
        facts = (
            f"{len(files)} source file{'s' if len(files) != 1 else ''}, "
            f"{sum(file['lines'] for file in files)} lines, {len(definitions)} definitions, "
            f"and {local_imports} confirmed local import{'s' if local_imports != 1 else ''}"
        )
        lowered = name.lower()
        if lowered == "tests":
            role = "Automated test boundary"
        elif "train" in lowered:
            role = "Training and model-preparation area (role inferred from its path)"
        elif len(files) == 1 and Path(name).stem.lower() in {"app", "main", "server", "cli", "index"}:
            role = "Application entry module (role inferred from its filename)"
        elif len(files) == 1:
            role = f"{Path(name).stem.replace('_', ' ').title()} module (role inferred from its filename)"
        else:
            role = "Source package boundary"
        named = f" Key definitions: {', '.join(definitions[:4])}." if definitions else ""
        responsibility = f"{role}: {facts}.{named}"
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
    description = project.get("description") or f"{project['name']} contains {len(analysis['files'])} analysed source and supporting files."
    summary = f"{description} This limited static view confirms source dependencies; runtime execution order is unconfirmed."
    return Architecture(summary=summary, main_path=[], components=components, relationships=relationships)


def _quiz_question(identifier: str, question: str, correct: str, distractors: list[str], fact: str, evidence: list[Evidence], slot: int) -> QuizQuestion:
    options: list[str] = []
    for option in [correct, *distractors]:
        if option not in options:
            options.append(option)
    while len(options) < 4:
        options.append(f"None of these ({len(options) + 1})")
    options = options[:4]
    selected = options.pop(0)
    correct_index = slot % 4
    options.insert(correct_index, selected)
    explanations = [
        f"Correct. {fact}" if index == correct_index else f"That option does not match this saved snapshot. {fact}"
        for index in range(4)
    ]
    return QuizQuestion(
        id=identifier, question=question, options=options, correct_index=correct_index,
        explanations=explanations, evidence=evidence,
    )


def heuristic_quiz(analysis: dict, architecture: Architecture) -> list[QuizQuestion]:
    files = analysis.get("files", [])
    largest = max(files, key=lambda item: (item.get("lines", 0), item["path"]))
    sample_evidence = [Evidence(path=largest["path"], line=1, label="Saved source")]
    paths = [item["path"] for item in files]
    edges = analysis.get("edges", [])
    first_edge = edges[0] if edges else None
    unresolved_count = len(analysis.get("unresolved_imports", []))
    cycle_count = len(analysis.get("cycles", []))
    coverage = analysis.get("coverage", {}).get("level", "unavailable")
    owning_component = next(
        (component.name for component in architecture.components if largest["path"] in component.source_paths),
        architecture.components[0].name,
    )
    runtime_answer = " → ".join(architecture.main_path) if architecture.main_path else "Runtime order was not confirmed"
    definition_file = next((item for item in files if item.get("definitions")), largest)
    definition = (definition_file.get("definitions") or [{"name": "No named definition was parsed", "line": 1}])[0]
    definition_evidence = [Evidence(path=definition_file["path"], line=definition.get("line", 1), label="Parsed definition")]
    dependency_answer = f"{first_edge['source']} imports {first_edge['target']}" if first_edge else "No confirmed local dependency was found"
    dependency_evidence = [Evidence(path=first_edge["source"], line=first_edge.get("line", 1), label="Confirmed import")] if first_edge else sample_evidence
    test_component = next((component.name for component in architecture.components if component.name.lower() in {"test", "tests"}), "No separate test component")
    size_guidance = "Inspect whether the largest module mixes responsibilities" if largest["lines"] > 500 else "Keep the module together unless responsibilities or callers diverge"
    return [
        _quiz_question("repo-definition", f"Which file contains the parsed definition '{definition['name']}'?", definition_file["path"], [path for path in paths if path != definition_file["path"]][:3] + ["No captured file"], f"Static parsing found {definition['name']} in {definition_file['path']} at line {definition.get('line', 1)}.", definition_evidence, 1),
        _quiz_question("repo-component", f"Which architecture component contains {largest['path']}?", owning_component, [component.name for component in architecture.components if component.name != owning_component][:3] + ["No component"], f"The saved component membership assigns {largest['path']} to {owning_component}.", sample_evidence, 2),
        _quiz_question("repo-dependency", "Which dependency statement matches the saved static graph?", dependency_answer, ([f"{first_edge['target']} imports {first_edge['source']}"] if first_edge else []) + ["Every file imports every other file", "Only external packages were checked", "Dependency direction was guessed from file size"], f"The graph {'records this source-backed import' if first_edge else 'contains no confirmed local dependency edge'}.", dependency_evidence, 3),
        _quiz_question("repo-dependency-meaning", "What does a confirmed arrow in this architecture map establish?", "Static source contains a resolved dependency", ["The target always runs after the source", "The dependency is safe and well designed", "The application was executed successfully"], "Confirmed arrows come from resolved static imports; they do not by themselves prove runtime order or design quality.", dependency_evidence, 0),
        _quiz_question("repo-unresolved", "What should you conclude from the unresolved-import count?", f"{unresolved_count} imports need more resolution evidence", ["Every external package is broken", "The project cannot run", "Unresolved imports are confirmed runtime failures"], f"The review recorded {unresolved_count} unresolved imports. This is a coverage limitation, not proof of runtime failure.", sample_evidence, 1),
        _quiz_question("repo-cycles", "What did deterministic dependency analysis find about cycles?", f"{cycle_count} cycle{'s' if cycle_count != 1 else ''} in the resolved graph", ["Every import creates a cycle", "Cycles were inferred from filenames", "Only runtime execution was checked"], f"The strongly connected component analysis found {cycle_count} cycles among resolved local dependencies.", dependency_evidence, 2),
        _quiz_question("repo-coverage", "Which interpretation of this review's coverage is accurate?", f"Coverage is {coverage}; runtime behavior may still be unconfirmed", ["All runtime paths were executed", "Deployment configuration was verified", "Every unresolved import is harmless"], f"The saved analysis labels coverage as {coverage} and keeps runtime claims separate from static evidence.", sample_evidence, 3),
        _quiz_question("repo-tests", "Which component represents automated test code in this architecture?", test_component, [component.name for component in architecture.components if component.name != test_component][:3] + ["Every production component"], f"The saved architecture {'groups captured test files under ' + test_component if test_component != 'No separate test component' else 'did not identify a separate test-code boundary'}.", sample_evidence, 0),
        _quiz_question("repo-next-step", f"What is the most defensible next step for {largest['path']} based on this review?", size_guidance, ["Split it solely because it is the largest file", "Rewrite it without checking callers", "Assume its runtime role from its filename"], f"The file has {largest['lines']} lines. Size is a prompt to inspect cohesion, not enough evidence by itself to force a split.", sample_evidence, 1),
        _quiz_question("repo-runtime", "What does this review establish about the main runtime path?", runtime_answer, ["File size determines execution order", "Tests always run first", "Every import executes in diagram order"], f"The saved architecture {'records ' + runtime_answer if architecture.main_path else 'does not claim a runtime order without source evidence'}.", sample_evidence, 2),
    ]


def heuristic_critique(analysis: dict, architecture: Architecture | None = None) -> Critique:
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
    if architecture is None:
        architecture = Architecture(
            summary="Static analysis", components=[Component(
                id="source", name="Source", responsibility="Captured source",
                sources=[Evidence(path=analysis["files"][0]["path"], line=1)],
                source_paths=[item["path"] for item in analysis["files"]],
            )],
        )
    return Critique(strengths=strengths, findings=findings[:5], lessons=lessons[:3], quiz=heuristic_quiz(analysis, architecture))


def validate_evidence(model, manifest: list[dict]):
    lines = {item["path"]: item["lines"] for item in manifest}
    for collection in (getattr(model, "components", []), getattr(model, "findings", []), getattr(model, "lessons", []), getattr(model, "quiz", [])):
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
    if len(critique.quiz) != 10:
        raise ValueError("The repository quiz must contain exactly 10 questions")
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


def calculate_changes(previous: dict | None, previous_snapshot: dict | None, current_snapshot: dict, architecture: Architecture, identity_uncertainty: list[dict] | None = None) -> dict:
    if not previous:
        return semantic_comparison(None, None, architecture, current_snapshot, identity_uncertainty=identity_uncertainty)
    return semantic_comparison(
        Architecture.model_validate(previous["architecture"]), previous_snapshot,
        architecture, current_snapshot,
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
        review_deadline = time.monotonic() + self.settings.review_timeout
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
        old_hashes = {item["path"]: item["sha256"] for item in (previous_snapshot or {}).get("manifest", [])}
        new_hashes = {item["path"]: item["sha256"] for item in capture["manifest"]}
        changed_paths = {
            *set(old_hashes).symmetric_difference(new_hashes),
            *(path for path in old_hashes.keys() & new_hashes.keys() if old_hashes[path] != new_hashes[path]),
        }
        previous_anchors = {
            path
            for component_data in (previous or {}).get("architecture", {}).get("components", [])
            for path in (component_data.get("source_paths") or [item.get("path") for item in component_data.get("sources", [])])
            if path
        }
        source_packets, source_note = build_source_packets(
            self.settings, capture["manifest"], analysis,
            changed_paths=changed_paths, anchors=previous_anchors,
        )
        usage_total: dict[str, int] = {}

        def on_codex_event(event: dict) -> None:
            if job_id:
                fields = {"last_activity_at": utc_now(), "stage": "codex"}
                usage = event.get("usage")
                if isinstance(usage, dict):
                    fields["usage_json"] = usage
                self.store.update_job(job_id, **fields)

        def run_pass(prompt: str, schema_name: str, validator):
            for attempt in range(2):
                check_cancelled()
                remaining = int(review_deadline - time.monotonic())
                if remaining <= 0:
                    raise CodexError("Review exceeded its total time budget")
                try:
                    raw = self.codex.run_structured(
                        prompt, self.settings.schema_dir / schema_name, root,
                        on_event=on_codex_event, timeout=min(self.settings.codex_call_timeout, remaining),
                        cancelled=is_cancelled,
                    )
                    validated = validator(raw)
                    for key, value in getattr(self.codex, "last_usage", {}).items():
                        usage_total[key] = usage_total.get(key, 0) + value
                    return validated
                except (ValueError, CodexMalformedOutput) as exc:
                    if attempt:
                        raise
                    prompt += f"\n\nYour prior response failed validation: {exc}. Return one corrected response matching the schema."
            raise AssertionError("unreachable")

        self.settings.runtime_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="review-", dir=self.settings.runtime_dir) as temp:
            root = Path(temp)
            ai_warnings: list[str] = []
            ai_error_codes: list[str] = []
            progress(25, "Building architecture")
            check_cancelled()
            try:
                architecture = run_pass(
                    ARCHITECTURE_PROMPT.format(
                        description=project["description"], goal=project["goal"],
                        coverage=json.dumps(coverage), analysis=json.dumps(compact_analysis(analysis)),
                        source_note=source_note, source_packets=source_packets,
                    ),
                    "architecture.json",
                    lambda raw: validate_architecture_snapshot(Architecture.model_validate(raw), capture["manifest"]),
                )
            except (CodexError, ValueError, json.JSONDecodeError) as exc:
                check_cancelled()
                ai_warnings.append(f"Architecture analysis used the deterministic fallback: {exc}")
                ai_error_codes.append(getattr(exc, "code", "invalid_architecture"))
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
                previous, previous_snapshot, {
                    "manifest": capture["manifest"], "analysis": analysis,
                    "git": capture["git"], "coverage": coverage,
                }, architecture,
                identity_uncertainty,
            )
            progress(55, "Reviewing design and preparing lessons")
            check_cancelled()
            try:
                critique = run_pass(
                    CRITIQUE_PROMPT.format(
                        goal=project["goal"], changes=json.dumps(changes),
                        architecture=architecture.model_dump_json(), source_note=source_note,
                        source_packets=source_packets,
                    ),
                    "critique.json",
                    lambda raw: validate_critique_quality(Critique.model_validate(raw)),
                )
            except (CodexError, ValueError, json.JSONDecodeError) as exc:
                check_cancelled()
                ai_warnings.append(f"Critique used the deterministic fallback: {exc}")
                ai_error_codes.append(getattr(exc, "code", "invalid_critique"))
                critique = heuristic_critique(analysis, architecture)
            validate_evidence(critique, capture["manifest"])
        check_cancelled()
        quality = "limited" if ai_warnings or capture.get("coverage") == "limited" or analysis["coverage"]["level"] == "limited" else "complete"
        positions = stable_positions(architecture, previous.get("positions") if previous else None)
        review_stub = self.store.create_review(
            project_id, snapshot_id, previous["id"] if previous else None, "rendering",
            architecture.model_dump(), critique.model_dump(), changes, {}, quality=quality,
            positions=positions, format_version=REVIEW_FORMAT_VERSION,
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
            artifacts["source_context"] = source_note
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
            report_path.write_text(
                markdown_report(project, architecture, critique, changes, coverage, snapshot_id=snapshot_id),
                encoding="utf-8",
            )
            artifacts["report"] = str(report_path)
            check_cancelled()
            if job_id:
                self.store.update_job(
                    job_id,
                    usage_json=usage_total,
                    error_code=ai_error_codes[0] if ai_error_codes else None,
                )
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
        history, history_note = bounded_history(conversation["messages"], self.settings)
        anchors = {
            path
            for component_data in review["architecture"].get("components", [])
            for path in (component_data.get("source_paths") or [item.get("path") for item in component_data.get("sources", [])])
            if path
        }
        source_packets, source_note = build_source_packets(
            self.settings, snapshot["manifest"], snapshot["analysis"], anchors=anchors,
        )
        self.settings.runtime_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="chat-", dir=self.settings.runtime_dir) as temp:
            root = Path(temp)
            prompt = CHAT_PROMPT.format(
                history=history, history_note=history_note, message=message,
                review=json.dumps({
                    "id": review["id"], "snapshot_id": snapshot["id"],
                    "architecture": review["architecture"], "critique": review["critique"],
                    "changes": review["changes"], "coverage": snapshot["coverage"],
                }),
                source_note=source_note, source_packets=source_packets,
            )
            try:
                response = None
                for attempt in range(2):
                    try:
                        response = ChatResponse.model_validate(self.codex.run_structured(
                            prompt, self.settings.schema_dir / "chat.json", root,
                            timeout=self.settings.codex_call_timeout, cancelled=is_cancelled,
                        ))
                        break
                    except (ValueError, CodexMalformedOutput) as exc:
                        if attempt:
                            raise
                        prompt += f"\nYour response failed validation: {exc}. Return one corrected schema response."
                assert response is not None
                if is_cancelled():
                    raise ReviewCancelled("Chat cancelled")
                citations = validate_evidence_items(response.citations, snapshot["manifest"])
                answer = response.answer
                if "outside the active context" in history_note:
                    answer = f"Context note: {history_note}\n\n{answer}"
            except (CodexError, ValueError, KeyError, json.JSONDecodeError) as exc:
                if is_cancelled():
                    raise ReviewCancelled("Chat cancelled") from exc
                answer = f"I could not run Codex for this question: {exc}. The saved review remains available."
                self.store.add_message(conversation["id"], "assistant", answer, [], status="failed")
                raise
        if is_cancelled():
            raise ReviewCancelled("Chat cancelled")
        self.store.add_message(
            conversation["id"], "assistant", answer,
            [item.model_dump() for item in citations], status="complete",
        )
        return conversation["id"]


def markdown_report(
    project: dict,
    architecture: Architecture,
    critique: Critique,
    changes: dict,
    coverage: dict | None = None,
    *,
    snapshot_id: str = "",
) -> str:
    coverage = coverage or {}

    def evidence_lines(items) -> list[str]:
        if not items:
            return ["- No source citation was supplied."]
        return [
            f"- `{item.path}:{item.line}{f'-{item.end_line}' if item.end_line else ''}`"
            f" — {item.label or 'source evidence'}{' (unverified)' if not item.valid else ''}"
            for item in items
        ]

    lines = [
        f"# {project['name']} architecture review", "",
        f"Snapshot: `{snapshot_id or 'legacy'}`", "", architecture.summary, "",
        "## Main execution path", "", " → ".join(architecture.main_path) or "No runtime path was confirmed.", "",
        "## How it is organised", "",
    ]
    for component in architecture.components:
        lines += [f"### {component.name} ({component.kind})", "", component.responsibility, "", "Evidence:", *evidence_lines(component.sources), ""]
    lines += ["## Supporting dependencies", ""]
    if architecture.relationships:
        lines.extend(
            f"- `{item.source}` → `{item.target}`: {item.label}{' (inferred)' if item.inferred else ''}"
            for item in architecture.relationships
        )
    else:
        lines.append("No dependencies were confirmed.")
    lines += ["", "## What changed", "", "Baseline review." if changes.get("baseline") else json.dumps(changes, indent=2), "", "## What works well", ""]
    lines.extend(f"- {item}" for item in critique.strengths)
    if not critique.strengths:
        lines.append("No source-backed strength claim was made.")
    lines += ["", "## What could improve", ""]
    for finding in critique.findings:
        lines += [
            f"### {finding.severity.upper()}: {finding.title}", "", finding.observation, "",
            f"Why it matters: {finding.why_it_matters}", "",
            f"Smallest improvement: {finding.improvement}", "",
            f"Tradeoffs: {finding.tradeoffs}", "", "Evidence:", *evidence_lines(finding.evidence), "",
        ]
    if not critique.findings:
        lines += ["No justified architecture concerns were found.", ""]
    lines += ["## Repository quiz", ""]
    for index, question in enumerate(critique.quiz, 1):
        lines += [f"### {index}. {question.question}", ""]
        lines.extend(f"- {'ABCD'[option_index]}. {option}" for option_index, option in enumerate(question.options))
        lines += ["", f"Correct answer: {'ABCD'[question.correct_index]}. {question.options[question.correct_index]}", "",
                  question.explanations[question.correct_index], "", "Evidence:", *evidence_lines(question.evidence), ""]
    if not critique.quiz:
        lines += ["This legacy review uses the original lesson format.", "", "## What to learn", ""]
        for lesson in critique.lessons:
            lines += [
                f"### {lesson.title}", "", lesson.explanation, "", "```", lesson.code_example, "```", "",
                f"Self-check: {lesson.self_check}", "", f"Answer: {lesson.answer}", "",
                f"Exercise: {lesson.exercise}", "", "Evidence:", *evidence_lines(lesson.evidence), "",
            ]
    lines += ["## Coverage and limitations", "", f"Coverage level: **{coverage.get('level', 'legacy or unavailable')}**", ""]
    for omission in [*coverage.get("capture_omissions", []), *coverage.get("omissions", [])]:
        lines.append(f"- {omission}")
    if not coverage.get("capture_omissions") and not coverage.get("omissions"):
        lines.append("- No capture or parser omission was recorded.")
    return "\n".join(lines).rstrip() + "\n"


def source_text(settings: Settings, snapshot: dict, relative_path: str) -> str:
    normalized = Path(relative_path).as_posix().lstrip("/")
    item = next((entry for entry in snapshot["manifest"] if entry["path"] == normalized), None)
    if not item: raise KeyError(relative_path)
    return read_blob(settings, item["sha256"]).decode("utf-8", errors="replace")

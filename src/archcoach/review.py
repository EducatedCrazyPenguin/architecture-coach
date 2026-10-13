from __future__ import annotations

import json
import re
import tempfile
import hashlib
import time
import copy
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

from .ai import ARCHITECTURE_PROMPT, CRITIQUE_PROMPT, CHAT_PROMPT, SOURCE_SUMMARY_PROMPT, CodexAdapter, CodexError, CodexMalformedOutput, CodexTimeoutError, create_adapter, schema_repair_prompt
from .analyze import analyze_snapshot, compact_analysis, manifest_changes
from .capture import CaptureCancelled, capture_project, read_blob
from .config import Settings
from .context import bounded_history, build_source_packets
from .db import JobCancelledError, Store
from .diagram import render_comparison, render_diagram, stable_positions
from .models import Architecture, ChatResponse, Component, Critique, Evidence, FeedbackResponse, Finding, Lesson, QuizQuestion, Relationship, SourceSummary, utc_now
from .subprocesses import ProcessCancelled
from .specs import index_specs, select_requirements


class ReviewCancelled(RuntimeError):
    pass


ANALYSIS_FORMAT_VERSION = 5
REVIEW_FORMAT_VERSION = 9


def review_configuration_fingerprint(project: dict, settings: Settings) -> str:
    relevant = {
        "description": project.get("description", ""),
        "goal": project.get("goal", ""),
        "exclusions": sorted(project.get("exclusions", [])),
        "analysis_format": ANALYSIS_FORMAT_VERSION,
        "review_format": REVIEW_FORMAT_VERSION,
        "architecture_prompt": ARCHITECTURE_PROMPT,
        "source_summary_prompt": SOURCE_SUMMARY_PROMPT,
        "critique_prompt": CRITIQUE_PROMPT,
        "quiz_order_version": 1,
        "relationship_completion_version": 1,
        "codex_command": settings.codex_command,
        "ai_provider": settings.ai_provider,
        "codex_model": settings.codex_model,
        "ollama_model": settings.ollama_model or "qwen3.6:27b",
        "lmstudio_model": settings.lmstudio_model or "qwen/qwen3.8-27b",
        "reasoning_effort": settings.reasoning_effort,
        "source_packet_chars": settings.source_packet_chars,
        "source_packet_limit": settings.source_packet_limit,
    }
    if settings.ai_provider == "prism":
        relevant["prism_model"] = settings.prism_model or "ternary-bonsai-2-27b"
    return hashlib.sha256(json.dumps(relevant, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _slug(text: str, fallback: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_-]+", "_", text).strip("_")
    if not value or not value[0].isalpha():
        value = "c_" + (value or fallback)
    return value[:50]


def add_resolved_relationships(architecture: Architecture, edges: list[dict]) -> None:
    """Retain resolved imports even when an AI model omits them; never guess membership."""
    owners: dict[str, set[str]] = defaultdict(set)
    for component in architecture.components:
        for path in component.source_paths or [source.path for source in component.sources]:
            owners[path].add(component.id)
    existing = {(r.source, r.target, r.kind) for r in architecture.relationships if not r.inferred}
    for edge in edges:
        source_ids, target_ids = owners[edge['source']], owners[edge['target']]
        if len(source_ids) != 1 or len(target_ids) != 1:
            continue
        source, target = next(iter(source_ids)), next(iter(target_ids))
        if source == target or (source, target, 'imports') in existing:
            continue
        architecture.relationships.append(Relationship(source=source, target=target, kind='imports', label='imports',
            sources=[Evidence(path=edge['source'], line=edge.get('line', 1), label='Resolved static import')]))
        existing.add((source, target, 'imports'))


def heuristic_architecture(project: dict, analysis: dict) -> Architecture:
    all_files = analysis["files"]
    code_suffixes = {".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".dsa", ".html", ".css", ".sql"}
    code_files = [file for file in all_files if Path(file["path"]).suffix.lower() in code_suffixes]
    # Documentation and manifests inform the review but are not runtime components
    # when the snapshot contains source code.
    architecture_files = code_files or [file for file in all_files if not file["path"].startswith("openspec/")]
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
    # Split package boundaries while space permits, exposing imports hidden inside folder boxes.
    while len(grouped) < 12:
        candidates = []
        for name, files in grouped.items():
            paths = {file['path'] for file in files}
            if not any(edge['source'] in paths and edge['target'] in paths for edge in analysis['edges']):
                continue
            children: dict[str, list[dict]] = {}
            for file in files:
                if not file['path'].startswith(name + '/'):
                    break
                child = name + '/' + file['path'][len(name)+1:].split('/')[0]
                children.setdefault(child, []).append(file)
            else:
                if 1 <= len(children) <= 13 - len(grouped):
                    candidates.append((sum(f['lines'] for f in files), name, children))
        if not candidates:
            break
        _, name, children = max(candidates, key=lambda item: (item[0], item[1]))
        del grouped[name]
        grouped.update(children)
    groups = sorted(grouped.items(), key=lambda item: (-sum(f["lines"] for f in item[1]), item[0]))[:12]
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
        kind = 'unknown'
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
        elif len(files) == 1:
            role = "Source file; runtime role unconfirmed"
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
            seen.add((source, target)); relationships.append(Relationship(
                source=source, target=target, label=edge["kind"], kind="imports", inferred=False,
                sources=[Evidence(path=edge["source"], line=edge.get("line", 1), label="Resolved static import")],
            ))
    description = project.get("description") or f"{project['name']} contains {len(analysis['files'])} analysed source and supporting files."
    summary = f"{description} This limited static view confirms source dependencies; runtime execution order is unconfirmed."
    return Architecture(summary=summary, main_path=[], components=components, relationships=relationships)


def _quiz_explanation(option: str, correct: str, fact: str) -> str:
    if option == correct:
        return f"Correct. {fact}"
    claim = option.rstrip(".")
    lowered = claim.casefold()
    if "execut" in lowered or "run" in lowered or "passes" in lowered:
        reason = "This review reads saved files without importing, executing, or testing the target project."
    elif "runtime" in lowered or "always runs" in lowered or "execution order" in lowered:
        reason = "Static analysis can confirm a source dependency, but it cannot prove runtime order."
    elif "file size" in lowered or "largest" in lowered:
        reason = "File size can prompt an inspection, but it does not establish code behavior, ownership, or execution order."
    elif "all component" in lowered or "every source" in lowered:
        reason = "Component membership comes from the saved architecture model; files are not automatically assigned everywhere."
    elif "external" in lowered or "broken" in lowered or "failure" in lowered:
        reason = "An unresolved reference is a limit of static resolution, not proof that a package or the project is broken."
    elif "cycle" in lowered:
        reason = "A cycle requires a closed chain of resolved dependencies; an individual import is not enough."
    else:
        reason = "That claim is not supported by the saved source evidence for this question."
    return f"Not quite: “{claim}” is not supported. {reason} {fact}"


def _quiz_question(identifier: str, question: str, correct: str, distractors: list[str], fact: str, evidence: list[Evidence], slot: int) -> QuizQuestion:
    options: list[str] = []
    for option in [correct, *distractors]:
        if option not in options:
            options.append(option)
    if len(options) < 4:
        raise ValueError("A quiz needs three distinct, meaningful distractors")
    options = options[:4]
    selected = options.pop(0)
    correct_index = slot % 4
    options.insert(correct_index, selected)
    explanations = [_quiz_explanation(option, correct, fact) for option in options]
    return QuizQuestion(
        id=identifier, question=question, options=options, correct_index=correct_index,
        explanations=explanations, evidence=evidence,
    )


def heuristic_quiz(analysis: dict, architecture: Architecture) -> list[QuizQuestion]:
    """Use declarations and dependencies; no quota-filling analyzer trivia."""
    questions = []
    files = sorted(analysis.get('files', []), key=lambda f: f['path'])
    for item in files:
        if len(questions) >= 3: break
        definition = next((d for d in item.get('definitions', []) if d.get('name') and d.get('line')), None)
        if not definition: continue
        name, line = definition['name'], definition['line']
        question = _quiz_question(f'declaration-{len(questions)}', f'Which named declaration can you inspect in {item["path"]}?', name,
            [f'{name}_not_declared', 'Only declarations in an external library', 'No named declaration'],
            f'{item["path"]}:{line} declares {name}. Its body explains what work it owns; its name alone does not prove its runtime purpose.',
            [Evidence(path=item['path'], line=line)], len(questions))
        question.concept, question.difficulty = 'responsibilities', 'beginner'
        questions.append(question)
    seen = set()
    for edge in analysis.get('edges', []):
        key = (edge['source'], edge['target'])
        if key in seen: continue
        seen.add(key)
        if len(questions) >= 8: break
        ref = [Evidence(path=edge['source'], line=edge.get('line', 1))]
        question = _quiz_question(f'dependency-{len(questions)}', f'Which saved file does {edge["source"]} directly depend on through this import?', edge['target'],
            [edge['source'], 'Every source file in the project', 'No local file'],
            f'The cited import resolves to {edge["target"]}. This connects the modules; it does not establish execution order or what happens on failure.', ref, len(questions))
        question.concept, question.difficulty = 'dependencies', 'beginner'
        questions.append(question)
    if seen and len(questions) < 10:
        source, target = sorted(seen)[0]
        edge = next(e for e in analysis['edges'] if e['source'] == source and e['target'] == target)
        question = _quiz_question('change-dependent', f'If the interface of {target} changes, which saved caller is worth checking first?', source,
            ['Only documentation regardless of imports', 'No callers need inspection', 'All callers already passed their tests'],
            f'{source} imports {target}. Inspect its use of the changed interface; an import is evidence of a dependent, not proof that it breaks or that tests pass.',
            [Evidence(path=source, line=edge.get('line', 1))], len(questions))
        question.concept, question.difficulty = 'change_impact', 'beginner'
        questions.append(question)
    return questions


def heuristic_critique(analysis: dict, architecture: Architecture | None = None) -> Critique:
    strengths: list[str] = []
    findings: list[Finding] = []
    lessons: list[Lesson] = []
    largest = sorted(analysis["files"], key=lambda f: f["lines"], reverse=True)
    if largest and largest[0]["lines"] > 500:
        file = largest[0]
        evidence = [Evidence(path=file["path"], line=1, label="Large module")]
        findings.append(Finding(id="large-module", severity="medium", title="One module carries substantial weight", observation=f"{file['path']} has {file['lines']} lines.", why_it_matters="Large modules can make unrelated changes interfere with each other.", improvement="Identify one cohesive responsibility that can move behind a small interface.", tradeoffs="Splitting too early can scatter closely related logic.", evidence=evidence))
    if analysis["cycles"]:
        cycle = analysis["cycles"][0]
        matching_edge = next((edge for edge in analysis["edges"] if edge["source"] == cycle[0] and edge["target"] == cycle[1]), None)
        evidence = [Evidence(path=cycle[0], line=(matching_edge or {}).get("line", 1), label="Static dependency-cycle edge")]
        findings.append(Finding(id="dependency-cycle", severity="high", title="Modules form a dependency cycle", observation="Static import analysis found: " + " → ".join(cycle), why_it_matters="Cycles can make initialization, testing, and isolated change harder; runtime impact remains an inference until exercised.", improvement="Inspect the cited import edge and move a shared contract only if both modules truly need it.", tradeoffs="A new shared module is only useful when the shared responsibility is clear.", evidence=evidence))
    if not lessons and analysis['edges']:
        edge = analysis['edges'][0]
        lessons.append(Lesson(id='boundaries', title='How these two files are connected', explanation=f"{edge['source']} imports {edge['target']}. A dependency means one part asks another part for something. This helps you find which callers to inspect before changing the imported interface; it does not say what runs first.", code_example='', self_check=f"If {edge['target']} changes its interface, which file should you inspect?", answer=f"Inspect {edge['source']}, which declares the import. Whether its behavior breaks needs a separate check.", exercise='Open the saved import and name what crosses this boundary.', evidence=[Evidence(path=edge['source'], line=edge.get('line', 1))]))
    if not lessons:
        for file in analysis['files']:
            declaration = next((d for d in file.get('definitions', []) if d.get('kind') == 'function'), None)
            if declaration:
                parameters = ', '.join(declaration.get('parameters', [])) or 'no named parameters recorded'
                lessons.append(Lesson(id='function-boundary', title='Inputs and work at a function boundary', explanation=f"{file['path']} declares {declaration['name']}, a named piece of work. Its recorded inputs are {parameters}. Read its body to see how those inputs are used and what is returned. This boundary helps callers ask for the work without copying its steps; the source alone does not establish actual caller values or successful execution.", code_example='', self_check=f"Where would you inspect the work done by {declaration['name']}?", answer=f"Read the saved declaration in {file['path']} and follow its body. Its name alone does not tell you the result.", exercise='Name one declared input and one operation from the saved body; say unknown if either is absent.', evidence=[Evidence(path=file['path'], line=declaration['line'], end_line=declaration.get('end_line', declaration['line']))]))
                break
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
    for collection in (getattr(model, "components", []), getattr(model, "findings", []), getattr(model, "lessons", []), getattr(model, "quiz", []), getattr(model, "relationships", [])):
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
        path for component in architecture.components for path in component.source_paths
        if path not in known or path.startswith("openspec/")
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


def validate_source_summary(raw: dict, manifest: list[dict], allowed_paths: set[str]) -> SourceSummary:
    summary = SourceSummary.model_validate(raw)
    summary.evidence = validate_evidence_items(summary.evidence, manifest)
    if any(not item.valid or item.path not in allowed_paths for item in summary.evidence):
        raise ValueError("Source summary cited evidence outside its packet")
    return summary


def validate_critique_quality(critique: Critique) -> Critique:
    blocked_markers = ("review blocked", "cannot access", "could not access", "unable to access", "provide their contents")
    if any(any(marker in strength.lower() for marker in blocked_markers) for strength in critique.strengths):
        raise ValueError("Codex did not have enough source access to complete the critique")
    if len({q.question.strip().casefold() for q in critique.quiz}) != len(critique.quiz):
        raise ValueError("Quiz questions must be distinct")
    position_reference = re.compile(r"\b(?:option|choice|answer)\s+[A-D]\b|\b(?:all|none)\s+of\s+the\s+above\b|\b(?:both|either)\s+[A-D]\s+(?:and|or)\s+[A-D]\b", re.IGNORECASE)
    if any(position_reference.search(text) for question in critique.quiz
           for text in [question.question, *question.options, *question.explanations]):
        raise ValueError("Quiz text may depend on option position; use self-contained options and explanations")
    # Balance fresh quizzes only; pair rotation keeps grading and explanations aligned.
    for slot, question in enumerate(sorted(critique.quiz, key=lambda q: hashlib.sha256(q.id.encode()).digest())):
        target = slot % 4
        shift = (question.correct_index - target) % 4
        question.options = question.options[shift:] + question.options[:shift]
        question.explanations = question.explanations[shift:] + question.explanations[:shift]
        question.correct_index = target
    return critique


def validate_requirement_assessments(critique: Critique, selected: list[dict], manifest: list[dict]) -> Critique:
    expected = {item["id"] for item in selected}
    actual = {item.requirement_id for item in critique.requirements}
    if actual != expected:
        raise ValueError("Requirement assessments did not match the selected saved requirements")
    for assessment in critique.requirements:
        validate_evidence_items(assessment.code_evidence, manifest)
        if any(not item.valid or item.path.startswith("openspec/") for item in assessment.code_evidence):
            raise ValueError("Requirement assessment has invalid code evidence")
        if assessment.status != "uncertain" and not assessment.code_evidence:
            raise ValueError("A supported or possible-gap assessment needs inspected code evidence")
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
    typed_before = {(r.source, r.target, r.kind, "inferred" if r.inferred else "confirmed") for r in before.relationships}
    typed_after = {(r.source, r.target, r.kind, "inferred" if r.inferred else "confirmed") for r in after.relationships}
    old_files = {item["path"]: item["sha256"] for item in (before_snapshot or {}).get("manifest", [])}
    new_files = {item["path"]: item["sha256"] for item in current_manifest}
    return {
        "baseline": False,
        "typed_relationships_added": sorted(typed_after - typed_before),
        "typed_relationships_removed": sorted(typed_before - typed_after),
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
        self.settings, self.store, self.codex = settings, store, codex or create_adapter(settings)

    def _job_engine(self):
        """Freeze effective configuration when work starts, including both AI passes."""
        engine = copy.copy(self)
        from .ollama import OllamaAdapter
        from .local_openai import LocalOpenAIAdapter
        if isinstance(self.codex, OllamaAdapter):
            engine.codex = OllamaAdapter(engine.settings)
        if isinstance(self.codex, LocalOpenAIAdapter):
            engine.codex = type(self.codex)(engine.settings)
        if isinstance(self.codex, CodexAdapter):
            engine.codex = copy.copy(self.codex)
            engine.codex.settings = engine.settings
            engine.codex.current = None
        return engine

    def run(self, *args, **kwargs) -> str:
        return self._job_engine()._run_review(*args, **kwargs)

    def _run_review(
        self,
        project_id: str,
        progress=lambda p, m: None,
        *,
        cancelled: Callable[[], bool] | None = None,
        job_id: str | None = None,
        force: bool = False,
    ) -> str:
        is_cancelled = cancelled or (lambda: False)

        review_deadline = time.monotonic() + self.settings.review_timeout

        def check_cancelled() -> None:
            if is_cancelled():
                self.codex.cancel()
                raise ReviewCancelled("Review cancelled")
            if time.monotonic() >= review_deadline:
                self.codex.cancel()
                raise CodexTimeoutError("Review exceeded its total time budget")

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
        analysis["specifications"] = index_specs(self.settings, capture["manifest"])
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
        selected_requirements, unassessed_count = select_requirements(
            analysis["specifications"], changed_paths, previous_anchors,
        )
        requirement_context = [
            {"id": item["id"], "path": item["path"], "line": item["line"], "text": item["text"][:2000]}
            for item in selected_requirements
        ]
        source_packets, source_note = build_source_packets(
            self.settings, capture["manifest"], analysis,
            changed_paths=changed_paths, anchors=previous_anchors,
        )
        analysis_context = compact_analysis(analysis)
        bounded_facts = [
            f"{name} {limit['included']}/{limit['total']}"
            for name, limit in analysis_context["context_limits"].items()
            if limit["included"] < limit["total"]
        ]
        if bounded_facts:
            source_note += " Static analysis context was bounded: " + ", ".join(bounded_facts) + "."
        coverage["ai_source_context"] = source_note
        usage_total: dict[str, int] = {}

        def on_codex_event(event: dict) -> None:
            if job_id:
                fields = {"last_activity_at": utc_now(), "stage": "codex"}
                usage = event.get("usage")
                if isinstance(usage, dict):
                    fields["usage_json"] = {key: usage_total.get(key, 0) + value for key, value in usage.items() if isinstance(value, int)}
                self.store.update_job(job_id, **fields)

        def run_pass(prompt: str, schema_name: str, validator, *, repairs: int = 1):
            for attempt in range(repairs + 1):
                check_cancelled()
                remaining = int(review_deadline - time.monotonic())
                if remaining <= 0:
                    raise CodexError("Review exceeded its total time budget")
                self.codex.last_usage = {}
                raw = None
                try:
                    raw = self.codex.run_structured(
                        prompt, self.settings.schema_dir / schema_name, root,
                        on_event=on_codex_event, timeout=min(self.settings.codex_call_timeout, remaining),
                        cancelled=is_cancelled,
                    )
                    return validator(raw)
                except (ValueError, CodexMalformedOutput) as exc:
                    if attempt >= repairs:
                        raise
                    prompt = schema_repair_prompt(prompt, raw, exc)
                finally:
                    for key, value in getattr(self.codex, "last_usage", {}).items():
                        if isinstance(value, int):
                            usage_total[key] = usage_total.get(key, 0) + value
                    if job_id:
                        self.store.update_job(job_id, usage_json=usage_total)
            raise AssertionError("unreachable")

        self.settings.runtime_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="review-", dir=self.settings.runtime_dir) as temp:
            root = Path(temp)
            ai_warnings: list[str] = []
            ai_error_codes: list[str] = []
            if "Omitted " in source_note or "Partially included:" in source_note:
                ai_warnings.append("AI inspected only part of the captured source. " + source_note)
            progress(25, "Building architecture")
            check_cancelled()
            final_source_packets = source_packets
            packet_items = [item for item in re.split(r"\n\n(?=SOURCE PACKET \d+\n)", source_packets) if item]
            needs_summaries = len(packet_items) > 1 or "Omitted " in source_note or "Partially included:" in source_note
            try:
                if needs_summaries:
                    summaries = []
                    for index, packet in enumerate(packet_items, 1):
                        allowed_paths = set(re.findall(r"^--- FILE (.+?) ---$", packet, re.MULTILINE))
                        summary = run_pass(
                            SOURCE_SUMMARY_PROMPT.format(source_packet=packet),
                            "source_summary.json",
                            lambda raw, paths=allowed_paths: validate_source_summary(raw, capture["manifest"], paths),
                            repairs=0,
                        )
                        evidence = ", ".join(f"{item.path}:{item.line}" for item in summary.evidence)
                        summaries.append(f"SOURCE SUMMARY {index}\n{summary.summary}\nEvidence: {evidence}")
                    final_source_packets = "\n\n".join(summaries)
                    source_note += f" Final review passes used {len(summaries)} validated source summaries."
                    coverage["ai_source_context"] = source_note
                architecture = run_pass(
                    ARCHITECTURE_PROMPT.format(
                        description=project["description"], goal=project["goal"],
                        coverage=json.dumps(coverage), analysis=json.dumps(analysis_context),
                        source_note=source_note, source_packets=final_source_packets,
                    ),
                    "architecture.json",
                    lambda raw: validate_architecture_snapshot(Architecture.model_validate(raw), capture["manifest"]),
                )
            except (CodexError, ValueError, json.JSONDecodeError) as exc:
                check_cancelled()
                ai_warnings.append(f"Architecture analysis used the deterministic fallback: {exc}")
                ai_error_codes.append(getattr(exc, "code", "invalid_architecture"))
                architecture = heuristic_architecture(project, analysis)
                if needs_summaries:
                    final_source_packets = "Source summaries were unavailable; use the static analysis and fallback architecture above."
            check_cancelled()
            validate_architecture_snapshot(architecture, capture["manifest"])
            membership = {
                component.id: set(component.source_paths or [item.path for item in component.sources])
                for component in architecture.components
            }
            for relation in architecture.relationships:
                supporting_edges = [
                    edge for edge in analysis["edges"]
                    if edge["source"] in membership[relation.source]
                    and edge["target"] in membership[relation.target]
                ]
                supported = relation.kind in {"imports", "dependency"} and bool(supporting_edges)
                if not relation.inferred:
                    if not supported:
                        relation.inferred = True
                        ai_warnings.append(
                            f"Relationship {relation.source} → {relation.target} is inferred: static analysis did not confirm its claimed semantics."
                        )
                    else:
                        relation.sources = [
                            Evidence(path=edge["source"], line=edge.get("line", 1), label="Resolved static import")
                            for edge in supporting_edges[:3]
                        ]
            add_resolved_relationships(architecture, analysis['edges'])
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
                        requirements=json.dumps(requirement_context),
                        source_packets=final_source_packets,
                    ),
                    "critique.json",
                    lambda raw: validate_requirement_assessments(
                        validate_critique_quality(Critique.model_validate(raw)), selected_requirements, capture["manifest"],
                    ),
                )
            except (CodexError, ValueError, json.JSONDecodeError) as exc:
                check_cancelled()
                ai_warnings.append(f"Critique used the deterministic fallback: {exc}")
                ai_error_codes.append(getattr(exc, "code", "invalid_critique"))
                critique = heuristic_critique(analysis, architecture)
            if unassessed_count:
                ai_warnings.append(f"{unassessed_count} documented requirements were outside this review's assessment limit.")
            validate_evidence(critique, capture["manifest"])
            cited_items = [*architecture.components, *architecture.relationships, *critique.findings, *critique.lessons, *critique.quiz]
            invalid_count = sum(
                not evidence.valid
                for item in cited_items
                for evidence in (item.sources if hasattr(item, "sources") else item.evidence)
            )
            if invalid_count:
                ai_warnings.append(f"{invalid_count} source citations could not be verified. This report is limited; unverified references are not evidence links.")
                ai_error_codes.append("invalid_evidence")
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
                timeout=max(0.01, review_deadline - time.monotonic()),
            )
            check_cancelled()
            artifacts["ai_warnings"] = ai_warnings
            artifacts["source_context"] = source_note
            if previous and previous["artifacts"].get("architecture_ir"):
                comparison = render_comparison(
                    self.settings, Path(previous["artifacts"]["architecture_ir"]),
                    Path(artifacts["architecture_ir"]), artifact_dir / "comparison.html",
                    cancelled=is_cancelled, timeout=max(0.01, review_deadline - time.monotonic()),
                )
                if comparison:
                    artifacts["comparison"] = comparison
            check_cancelled()
            report_path = artifact_dir / "review.md"
            artifact_dir.mkdir(parents=True, exist_ok=True)
            from .learning import lesson_examples
            report_path.write_text(
                markdown_report(project, architecture, critique, changes, coverage, snapshot_id=snapshot_id,
                                examples=lesson_examples(self.settings, self.store.get_snapshot(snapshot_id), critique.model_dump())),
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

    def chat(self, *args, **kwargs) -> str:
        return self._job_engine()._run_chat(*args, **kwargs)

    def _run_chat(
        self,
        review_id: str,
        message: str,
        *,
        cancelled: Callable[[], bool] | None = None,
        job_id: str | None = None,
        mode: str = 'answer',
        question_id: str | None = None,
        selection: dict | None = None,
    ) -> str:
        is_cancelled = cancelled or (lambda: False)
        usage_total = {}
        deadline = time.monotonic() + self.settings.review_timeout
        def on_event(event):
            if job_id:
                fields = {"stage":"instructor", "last_activity_at":utc_now(), "message":"Instructor is answering"}
                if event.get("usage"):
                    fields["usage_json"] = {key:usage_total.get(key, 0) + value for key, value in event["usage"].items() if isinstance(value, int)}
                self.store.update_job(job_id, **fields)
        if is_cancelled():
            raise ReviewCancelled("Chat cancelled")
        review = self.store.get_review(review_id); snapshot = self.store.get_snapshot(review["snapshot_id"]); conversation = self.store.conversation_for_review(review_id)
        from .learning import practice_context
        guidance, practice = practice_context(self.settings, snapshot, review, mode, question_id,
                                               self.store.quiz_answers(review_id).get(question_id))
        from .workspace import resolve_selection
        from .learning import saved_excerpt, source_walkthroughs, check_teaching_claims
        from .models import LearningSelection
        selected = resolve_selection(snapshot, review, LearningSelection.model_validate(selection) if selection else None,
                                     source_walkthroughs(self.settings, snapshot, review, selection['id'].rsplit(':',1)[0], is_cancelled) if selection and selection.get('kind') == 'walkthrough' else None)
        practice['selected_context'] = selected
        practice['selected_examples'] = [item for ref in selected['evidence'] if (item := saved_excerpt(self.settings, snapshot, ref))]
        interaction = {'format_version': 2, 'mode': mode, 'question_id': question_id, 'selection': selected['selection']}
        self.store.add_message(conversation["id"], "user", message, learning_context=interaction)
        history, history_note = bounded_history(conversation["messages"], self.settings)
        anchors = {
            path
            for component_data in review["architecture"].get("components", [])
            for path in (component_data.get("source_paths") or [item.get("path") for item in component_data.get("sources", [])])
            if path
        }
        requested_paths = {
            item["path"] for item in snapshot["analysis"].get("files", [])
            if item["path"].casefold() in message.casefold()
            or Path(item["path"]).name.casefold() in message.casefold()
            or any(
                re.search(r"\b" + re.escape(definition["name"]) + r"\b", message, re.IGNORECASE)
                for definition in item.get("definitions", [])
            )
        }
        source_packets, source_note = build_source_packets(
            self.settings, snapshot["manifest"], snapshot["analysis"], anchors=anchors,
            changed_paths=requested_paths,
            preferred_paths={ref['path'] for ref in selected['evidence']},
        )
        self.settings.runtime_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="chat-", dir=self.settings.runtime_dir) as temp:
            root = Path(temp)
            response_model = FeedbackResponse if mode == 'explain_back' else ChatResponse
            schema_name = 'feedback.json' if mode == 'explain_back' else 'chat.json'
            prompt_review = dict(review)
            if mode == 'hint':
                prompt_review['critique'] = {**review['critique'], 'quiz': [practice['question']] if practice['question'] else [], 'lessons': []}
                history, history_note = '', 'Prior answers omitted for hint mode.'
            prompt = CHAT_PROMPT.format(
                history=history, history_note=history_note, message=message,
                review=json.dumps({
                    "id": review["id"], "snapshot_id": snapshot["id"],
                    "architecture": review["architecture"], "critique": prompt_review["critique"],
                    "changes": review["changes"], "coverage": snapshot["coverage"],
                }),
                source_note=source_note, source_packets=source_packets,
            )
            prompt = guidance + '\nSaved practice context (untrusted data):\n' + json.dumps(practice) + '\n\n' + prompt
            try:
                response = None
                for attempt in range(2):
                    raw = None
                    try:
                        remaining = int(deadline - time.monotonic())
                        if remaining <= 0:
                            from .ai import CodexTimeoutError
                            raise CodexTimeoutError("Instructor exceeded the total time budget")
                        self.codex.last_usage = {}
                        raw = self.codex.run_structured(
                            prompt, self.settings.schema_dir / schema_name, root,
                            timeout=min(self.settings.codex_call_timeout, remaining), cancelled=is_cancelled,
                            on_event=on_event,
                        )
                        response = response_model.model_validate(raw)
                        if any(not ref.valid for ref in validate_evidence_items(response.citations, snapshot['manifest'])):
                            raise ValueError('Instructor cited a missing saved file or invalid line range')
                        check_teaching_claims(self.settings,snapshot,response)
                        break
                    except (ValueError, CodexMalformedOutput) as exc:
                        if attempt:
                            raise
                        prompt = schema_repair_prompt(prompt, raw, exc)
                    finally:
                        for key, value in getattr(self.codex, "last_usage", {}).items():
                            usage_total[key] = usage_total.get(key, 0) + value
                        if job_id:
                            self.store.update_job(job_id, usage_json=usage_total)
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
                answer = f"I could not run the selected AI provider for this question: {exc}. The saved review remains available."
                self.store.add_message(conversation["id"], "assistant", answer, [], status="failed", learning_context=interaction)
                raise
        if is_cancelled():
            raise ReviewCancelled("Chat cancelled")
        self.store.add_message(
            conversation["id"], "assistant", answer,
            [item.model_dump() for item in citations], status="complete",
            learning_context=interaction,
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
    examples: dict | None = None,
) -> str:
    coverage = coverage or {}
    names = {component.id: component.name for component in architecture.components}

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
        "## Main execution path", "", " → ".join(names.get(identifier, identifier) for identifier in architecture.main_path) or "No runtime path was confirmed.", "",
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
    lines += [f'{len(critique.quiz)} saved questions. Fewer than ten reflects available evidence; no filler is added.', '']
    if not critique.quiz: lines += ['No grounded questions were saved. Read the saved lessons and source; generate a new review deliberately when coverage improves.', '']
    for index, question in enumerate(critique.quiz, 1):
        lines += [f"### {index}. {question.question}", ""]
        lines.extend(f"- {'ABCD'[option_index]}. {option}" for option_index, option in enumerate(question.options))
        lines += ["", f"Correct answer: {'ABCD'[question.correct_index]}. {question.options[question.correct_index]}", "",
                  question.explanations[question.correct_index], "", "Evidence:", *evidence_lines(question.evidence), ""]
        lines += ["Why each option is right or wrong:", ""]
        lines.extend(f"- {'ABCD'[option_index]}. {explanation}" for option_index, explanation in enumerate(question.explanations))
        lines.append("")
    if critique.lessons:
        lines += ["## What to learn", ""]
        for lesson in critique.lessons:
            lines += [
                f"### {lesson.title}", "", lesson.explanation, "",
                f"Self-check: {lesson.self_check}", "", f"Answer: {lesson.answer}", "",
                f"Exercise: {lesson.exercise}", "", "Evidence:", *evidence_lines(lesson.evidence), "",
            ]
            for example in (examples or {}).get(lesson.id, []):
                lines += [f"Captured example: {example['path']}:{example['line']}", '', '````', example['code'], '````', '']
            if lesson.code_example:
                lines += ['Generated illustration (not an exact source quotation):', '',
                          'Illustrations may omit steps. Do not paste them over working code without checking the full saved source.', '',
                          '````', lesson.code_example, '````', '']
    lines += ["## Coverage and limitations", "", f"Coverage level: **{coverage.get('level', 'legacy or unavailable')}**", ""]
    if coverage.get("ai_source_context"):
        lines += ["AI source context: " + coverage["ai_source_context"], ""]
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

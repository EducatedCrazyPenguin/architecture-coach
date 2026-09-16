from __future__ import annotations

import pytest

from archcoach.diagram import stable_positions, to_archify
from archcoach.models import Architecture, Component, Critique, Evidence, Lesson, Relationship
from archcoach.review import (
    calculate_changes,
    heuristic_architecture,
    heuristic_critique,
    preserve_component_identity,
    semantic_comparison,
    validate_evidence,
    heuristic_quiz,
)


def test_quiz_does_not_invent_definitions_or_mark_reciprocal_import_wrong():
    analysis = {"files": [
        {"path": "a.py", "language": "python", "lines": 1, "definitions": []},
        {"path": "b.py", "language": "python", "lines": 1, "definitions": []},
    ], "edges": [
        {"source": "a.py", "target": "b.py", "kind": "imports", "line": 1},
        {"source": "b.py", "target": "a.py", "kind": "imports", "line": 1},
    ], "cycles": [["a.py", "b.py", "a.py"]]}
    quiz = heuristic_quiz(analysis, heuristic_architecture({"name": "Fixture"}, analysis))
    assert len(quiz) == 10
    assert "No named definition was recorded" in quiz[0].options[quiz[0].correct_index]
    assert all("None of these" not in option for question in quiz for option in question.options)
    assert "b.py imports a.py" not in quiz[2].options


def test_cycle_witness_contains_only_actual_dependency_edges():
    from archcoach.analyze import _strongly_connected_cycles
    graph = {"a": ["c"], "c": ["b"], "b": ["a"]}
    cycles = _strongly_connected_cycles(graph, set(graph))
    assert len(cycles) == 1
    assert cycles[0][0] == cycles[0][-1]
    assert all(target in graph[source] for source, target in zip(cycles[0], cycles[0][1:]))


def test_relationship_semantics_change_without_wording_change():
    before = Architecture(summary="x", components=[component("a", "a.py"), component("b", "b.py")], relationships=[Relationship(source="a", target="b", kind="reads", label="uses data")])
    after = before.model_copy(deep=True)
    after.relationships[0].kind = "writes"
    snapshot = {"manifest": [], "analysis": {"manifests": {}}}
    changes = semantic_comparison(before, snapshot, after, snapshot)
    assert changes["typed_relationships_removed"] == [("a", "b", "reads", "confirmed")]
    assert changes["typed_relationships_added"] == [("a", "b", "writes", "confirmed")]


def component(identifier: str, path: str, *, name: str | None = None, kind: str = "backend") -> Component:
    return Component(
        id=identifier, name=name or identifier, kind=kind, responsibility="responsibility",
        sources=[Evidence(path=path, line=1)], source_paths=[path],
    )


def test_models_reject_duplicate_ids_and_dangling_references():
    with pytest.raises(ValueError, match="unique"):
        Architecture(
            summary="x", main_path=[],
            components=[component("same", "a.py"), component("same", "b.py")],
        )
    with pytest.raises(ValueError, match="unknown"):
        Architecture(
            summary="x", main_path=["missing"], components=[component("one", "a.py")],
            relationships=[Relationship(source="one", target="missing")],
        )
    lesson = Lesson(id="repeat", title="x", explanation="x", code_example="x", self_check="x", answer="x", exercise="x")
    with pytest.raises(ValueError, match="unique"):
        Critique(lessons=[lesson, lesson.model_copy()])


def test_evidence_range_is_ordered_and_out_of_snapshot_range_is_unverified():
    with pytest.raises(ValueError, match="end_line"):
        Evidence(path="a.py", line=4, end_line=2)
    architecture = Architecture(summary="x", components=[component("one", "a.py")])
    architecture.components[0].sources[0].line = 4

    validate_evidence(architecture, [{"path": "a.py", "lines": 3}])

    assert architecture.components[0].sources[0].valid is False


def test_fallback_does_not_invent_runtime_order_or_capture_strength():
    analysis = {
        "files": [
            {"path": "large.py", "language": "python", "lines": 600},
            {"path": "small.py", "language": "python", "lines": 10},
        ],
        "edges": [], "cycles": [],
    }
    architecture = heuristic_architecture({"name": "Fixture", "description": ""}, analysis)
    critique = heuristic_critique(analysis)

    assert architecture.main_path == []
    assert "runtime execution order is unconfirmed" in architecture.summary
    assert all("captur" not in strength.lower() for strength in critique.strengths)


def test_fallback_architecture_keeps_supporting_files_out_of_runtime_graph():
    analysis = {
        "files": [
            {"path": "audio_engine/processor.py", "language": "python", "lines": 80, "definitions": [{"name": "process_audio", "line": 4}], "imports": []},
            {"path": "app.py", "language": "python", "lines": 30, "definitions": [{"name": "main", "line": 8}], "imports": [{"status": "local"}]},
            {"path": "tests/test_audio.py", "language": "python", "lines": 25, "definitions": [{"name": "test_audio", "line": 5}], "imports": [{"status": "local"}]},
            {"path": "test_cli.py", "language": "python", "lines": 15, "definitions": [{"name": "test_cli", "line": 3}], "imports": []},
            {"path": "README.md", "language": "other", "lines": 40, "definitions": [], "imports": []},
            {"path": "requirements.txt", "language": "other", "lines": 10, "definitions": [], "imports": []},
        ],
        "edges": [
            {"source": "app.py", "target": "audio_engine/processor.py", "kind": "imports"},
            {"source": "tests/test_audio.py", "target": "audio_engine/processor.py", "kind": "imports"},
        ],
        "cycles": [],
    }

    model = heuristic_architecture({"name": "Voice", "description": ""}, analysis)

    names = {component.name for component in model.components}
    assert "README.md" not in names
    assert "requirements.txt" not in names
    assert names == {"audio_engine", "app.py", "tests"}
    tests = next(component for component in model.components if component.name == "tests")
    assert tests.source_paths == ["test_cli.py", "tests/test_audio.py"]
    assert "Automated test boundary" in tests.responsibility
    package = next(component for component in model.components if component.name == "audio_engine")
    assert "80 lines" in package.responsibility
    assert "process_audio" in package.responsibility
    assert {(relation.source, relation.target) for relation in model.relationships}


def test_identity_survives_unique_content_hash_rename_and_discloses_ambiguity():
    before = Architecture(summary="before", components=[component("stable", "old.py")])
    after = Architecture(summary="after", components=[component("generated", "renamed.py")])
    preserved, uncertainty = preserve_component_identity(
        before, [{"path": "old.py", "sha256": "same"}],
        after, [{"path": "renamed.py", "sha256": "same"}],
    )
    assert preserved.components[0].id == "stable"
    assert uncertainty == []

    ambiguous_before = Architecture(
        summary="before", components=[component("left", "shared.py"), component("right", "shared.py")],
    )
    _, uncertainty = preserve_component_identity(
        ambiguous_before, [{"path": "shared.py", "sha256": "same"}],
        Architecture(summary="after", components=[component("new", "shared.py")]),
        [{"path": "shared.py", "sha256": "same"}],
    )
    assert uncertainty[0]["type"] == "ambiguous"

    merge_before = Architecture(
        summary="before", components=[component("left", "left.py"), component("right", "right.py")],
    )
    merged = component("new", "left.py")
    merged.source_paths = ["left.py", "right.py"]
    _, uncertainty = preserve_component_identity(
        merge_before,
        [{"path": "left.py", "sha256": "left"}, {"path": "right.py", "sha256": "right"}],
        Architecture(summary="after", components=[merged]),
        [{"path": "left.py", "sha256": "left"}, {"path": "right.py", "sha256": "right"}],
    )
    assert uncertainty[0]["type"] == "merge"

    split_before = Architecture(summary="before", components=[component("whole", "whole.py")])
    split_left = component("left", "whole.py")
    split_right = component("right", "whole.py")
    _, uncertainty = preserve_component_identity(
        split_before, [{"path": "whole.py", "sha256": "whole"}],
        Architecture(summary="after", components=[split_left, split_right]),
        [{"path": "whole.py", "sha256": "whole"}],
    )
    assert uncertainty[0]["type"] == "split"


def test_semantic_comparison_ignores_wording_order_labels_and_geometry():
    before = Architecture(
        summary="old wording", main_path=["a", "b"],
        components=[component("a", "a.py", name="Old A"), component("b", "b.py")],
        relationships=[Relationship(source="a", target="b", label="calls")],
    )
    after = Architecture(
        summary="new wording", main_path=["b", "a"],
        components=[component("b", "b.py", name="Renamed B"), component("a", "a.py", name="New A")],
        relationships=[Relationship(source="a", target="b", label="uses")],
    )
    snapshot = {
        "manifest": [{"path": "a.py", "sha256": "1"}, {"path": "b.py", "sha256": "2"}],
        "analysis": {"manifests": {}},
    }

    changes = semantic_comparison(before, snapshot, after, snapshot)

    assert changes["components_changed"] == []
    assert changes["relationships_added"] == []
    assert changes["relationships_removed"] == []
    assert stable_positions(before) == stable_positions(after)
    assert {(item["id"], item["row"], item["col"]) for item in to_archify(before, "x")["components"]} == {
        (item["id"], item["row"], item["col"]) for item in to_archify(after, "x")["components"]
    }


def test_semantic_comparison_reports_confirmed_and_inferred_edges_separately():
    before = Architecture(summary="x", components=[component("a", "a.py"), component("b", "b.py")])
    after = Architecture(
        summary="x", components=[component("a", "a.py"), component("b", "b.py")],
        relationships=[Relationship(source="a", target="b", inferred=True)],
    )
    snapshot = {"manifest": [], "analysis": {"manifests": {}}}
    changes = semantic_comparison(before, snapshot, after, snapshot)
    assert changes["relationships_added"] == []
    assert changes["inferred_relationships_added"] == [("a", "b")]


def test_semantic_comparison_discloses_branch_and_coverage_changes():
    architecture = Architecture(summary="x", components=[component("a", "a.py")])
    before = {"manifest": [], "analysis": {"manifests": {}}, "git": {"branch": "main"}, "coverage": {"level": "standard"}}
    after = {"manifest": [], "analysis": {"manifests": {}}, "git": {"branch": "feature"}, "coverage": {"level": "limited"}}

    changes = semantic_comparison(architecture, before, architecture, after)

    assert changes["branches"] == {"before": "main", "after": "feature", "changed": True}
    assert changes["coverage"] == {"before": "standard", "after": "limited"}


def test_automatic_comparison_uses_the_same_snapshot_context_as_saved_comparison():
    architecture = Architecture(summary="x", components=[component("a", "a.py")])
    before = {"manifest": [], "analysis": {"manifests": {}}, "git": {"branch": "main"}, "coverage": {"level": "standard"}}
    after = {"manifest": [], "analysis": {"manifests": {}}, "git": {"branch": "feature"}, "coverage": {"level": "limited"}}
    previous = {"architecture": architecture.model_dump()}

    automatic = calculate_changes(previous, before, after, architecture)
    selected = semantic_comparison(architecture, before, architecture, after)

    assert automatic["branches"] == selected["branches"]
    assert automatic["coverage"] == selected["coverage"]

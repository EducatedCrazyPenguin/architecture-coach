from __future__ import annotations

import pytest

from archcoach.diagram import stable_positions, to_archify
from archcoach.models import Architecture, Component, Critique, Evidence, Lesson, Relationship
from archcoach.review import (
    heuristic_architecture,
    heuristic_critique,
    preserve_component_identity,
    semantic_comparison,
    validate_evidence,
)


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

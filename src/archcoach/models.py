from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    line: int = Field(ge=1)
    end_line: int | None = Field(default=None, ge=1)
    label: str = ""
    valid: bool = True

    @model_validator(mode="after")
    def range_is_ordered(self):
        if self.end_line is not None and self.end_line < self.line:
            raise ValueError("Evidence end_line must be on or after line")
        path = self.path.replace("\\", "/")
        if not path or path.startswith("/") or ".." in path.split("/"):
            raise ValueError("Evidence path must be snapshot-relative")
        self.path = path
        return self


class Component(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    name: str
    kind: Literal["frontend", "backend", "database", "cloud", "security", "messagebus", "external"] = "backend"
    responsibility: str
    sources: list[Evidence] = Field(default_factory=list, min_length=1, max_length=3)
    source_paths: list[str] = Field(default_factory=list, max_length=250)


class Relationship(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str
    target: str
    kind: Literal["dependency", "imports", "calls", "reads", "writes", "publishes", "subscribes"] = "dependency"
    label: str = "uses"
    inferred: bool = False
    sources: list[Evidence] = Field(default_factory=list, max_length=3)


class Architecture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str
    main_path: list[str] = Field(default_factory=list)
    components: list[Component] = Field(min_length=1, max_length=12)
    relationships: list[Relationship] = Field(default_factory=list)

    @model_validator(mode="after")
    def references_are_valid(self):
        identifiers = [component.id for component in self.components]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Component IDs must be unique")
        known = set(identifiers)
        dangling_path = set(self.main_path) - known
        dangling_relationships = {
            identifier
            for relationship in self.relationships
            for identifier in (relationship.source, relationship.target)
            if identifier not in known
        }
        if dangling_path:
            raise ValueError(f"Main path has unknown component IDs: {sorted(dangling_path)}")
        if dangling_relationships:
            raise ValueError(f"Relationships have unknown component IDs: {sorted(dangling_relationships)}")
        return self


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    severity: Literal["high", "medium", "low"]
    title: str
    observation: str
    why_it_matters: str
    improvement: str
    tradeoffs: str
    evidence: list[Evidence] = Field(default_factory=list)


class Lesson(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    explanation: str
    code_example: str
    self_check: str
    answer: str
    exercise: str
    evidence: list[Evidence] = Field(default_factory=list)


class QuizQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    question: str = Field(min_length=1)
    options: list[str] = Field(min_length=4, max_length=4)
    correct_index: int = Field(ge=0, le=3)
    explanations: list[str] = Field(min_length=4, max_length=4)
    evidence: list[Evidence] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def option_explanations_align(self):
        if len(self.options) != len(self.explanations):
            raise ValueError("Each quiz option needs an explanation")
        if len(set(self.options)) != len(self.options):
            raise ValueError("Quiz options must be unique")
        return self


class SourceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(min_length=1)
    evidence: list[Evidence] = Field(min_length=1, max_length=12)


class RequirementAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requirement_id: str = Field(min_length=1)
    status: Literal["supported", "possible_gap", "uncertain"]
    explanation: str = Field(min_length=1)
    code_evidence: list[Evidence] = Field(default_factory=list, max_length=5)


class Critique(BaseModel):
    model_config = ConfigDict(extra="forbid")
    strengths: list[str] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list, max_length=5)
    lessons: list[Lesson] = Field(default_factory=list, max_length=3)
    quiz: list[QuizQuestion] = Field(default_factory=list, max_length=10)
    requirements: list[RequirementAssessment] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def identifiers_are_unique(self):
        finding_ids = [finding.id for finding in self.findings]
        lesson_ids = [lesson.id for lesson in self.lessons]
        quiz_ids = [question.id for question in self.quiz]
        if len(finding_ids) != len(set(finding_ids)):
            raise ValueError("Finding IDs must be unique")
        if len(lesson_ids) != len(set(lesson_ids)):
            raise ValueError("Lesson IDs must be unique")
        if len(quiz_ids) != len(set(quiz_ids)):
            raise ValueError("Quiz question IDs must be unique")
        requirement_ids = [item.requirement_id for item in self.requirements]
        if len(requirement_ids) != len(set(requirement_ids)):
            raise ValueError("Requirement assessments must be unique")
        return self


class ProjectCreate(BaseModel):
    path: str
    name: str | None = None
    description: str = ""
    goal: str = ""
    exclusions: list[str] = Field(default_factory=list)
    interval_days: int = Field(default=7, ge=1, le=365)

    @field_validator("path")
    @classmethod
    def path_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Project path is required")
        parsed = urlparse(value)
        if parsed.scheme.lower() in {"http", "https", "git", "ssh"} or value.lower().startswith("git@"):
            raise ValueError(
                "Architecture Coach reviews a local folder already on this computer. "
                "Clone or download the repository first, then paste its Windows folder path."
            )
        return value


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    goal: str | None = Field(default=None, max_length=2000)
    exclusions: list[str] | None = Field(default=None, max_length=100)
    interval_days: int | None = Field(default=None, ge=1, le=365)
    enabled: bool | None = None

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value: str) -> str:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("Project name is required")
        return value

    @field_validator("exclusions")
    @classmethod
    def clean_exclusions(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        cleaned: list[str] = []
        for value in values:
            item = value.strip().replace("\\", "/").lstrip("/")
            if item and item not in cleaned:
                cleaned.append(item)
        return cleaned


class AppSettingsUpdate(BaseModel):
    ai_provider: Literal["codex", "ollama", "lmstudio"] | None = None
    codex_command: str | None = Field(default=None, min_length=1, max_length=500)
    codex_model: str | None = Field(default=None, max_length=120)
    ollama_model: str | None = Field(default=None, max_length=120)
    lmstudio_model: str | None = Field(default=None, max_length=200)
    reasoning_effort: Literal["low", "medium", "high", "xhigh"] | None = None
    codex_call_timeout: int | None = Field(default=None, ge=30, le=1800)
    review_timeout: int | None = Field(default=None, ge=60, le=3600)
    source_packet_chars: int | None = Field(default=None, ge=8000, le=96000)
    source_packet_limit: int | None = Field(default=None, ge=1, le=6)

    @model_validator(mode="after")
    def required_values_cannot_be_null(self):
        nullable = {"codex_model", "ollama_model", "lmstudio_model"}
        invalid = sorted(
            field for field in self.model_fields_set
            if field not in nullable and getattr(self, field) is None
        )
        if invalid:
            raise ValueError("Settings cannot be null: " + ", ".join(invalid))
        return self


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str = Field(min_length=1, max_length=12000)
    citations: list[Evidence] = Field(default_factory=list, max_length=12)


class PlanSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    capability: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=80)
    content: str = Field(min_length=80, max_length=16000)


class PlanRequest(BaseModel):
    finding_id: str = Field(min_length=1, max_length=100)
    instruction: str = Field(default="", max_length=2000)
    parent_id: str | None = None


class PlanApproval(BaseModel):
    draft_hash: str = Field(min_length=64, max_length=64)


class ImprovementPlanDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    change_id: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=80)
    kind: Literal["behavior_change", "refactor"]
    proposal: str = Field(min_length=80, max_length=12000)
    design: str = Field(min_length=80, max_length=16000)
    tasks: str = Field(min_length=80, max_length=12000)
    specs: list[PlanSpec] = Field(default_factory=list, max_length=3)
    evidence: list[Evidence] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def spec_matches_kind(self):
        if self.kind == "refactor" and self.specs:
            raise ValueError("A pure refactor must not invent specification changes")
        if self.kind == "behavior_change" and not self.specs:
            raise ValueError("A behavior change needs a specification delta")
        if len({item.capability for item in self.specs}) != len(self.specs):
            raise ValueError("Specification capability paths must be distinct")
        return self


class LessonStatusRequest(BaseModel):
    status: Literal["unread", "learning", "understood"]


class QuizAnswerRequest(BaseModel):
    selected_index: int = Field(ge=0, le=3)

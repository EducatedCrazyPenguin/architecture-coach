from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    line: int = Field(ge=1)
    end_line: int | None = Field(default=None, ge=1)
    label: str = ""
    valid: bool = True


class Component(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    name: str
    kind: Literal["frontend", "backend", "database", "cloud", "security", "messagebus", "external"] = "backend"
    responsibility: str
    sources: list[Evidence] = Field(default_factory=list, max_length=3)


class Relationship(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str
    target: str
    label: str = "uses"
    inferred: bool = False


class Architecture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str
    main_path: list[str] = Field(default_factory=list)
    components: list[Component]
    relationships: list[Relationship] = Field(default_factory=list)


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


class Critique(BaseModel):
    model_config = ConfigDict(extra="forbid")
    strengths: list[str] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list, max_length=5)
    lessons: list[Lesson] = Field(min_length=1, max_length=3)


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
        if not value.strip():
            raise ValueError("Project path is required")
        return value


class ProjectUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    goal: str = Field(default="", max_length=2000)
    exclusions: list[str] = Field(default_factory=list, max_length=100)
    interval_days: int = Field(default=7, ge=1, le=365)
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Project name is required")
        return value

    @field_validator("exclusions")
    @classmethod
    def clean_exclusions(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            item = value.strip().replace("\\", "/").lstrip("/")
            if item and item not in cleaned:
                cleaned.append(item)
        return cleaned


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


class LessonStatusRequest(BaseModel):
    status: Literal["unread", "learning", "understood"]

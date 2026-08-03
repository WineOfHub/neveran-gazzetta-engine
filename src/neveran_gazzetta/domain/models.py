from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel


class DomainModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        alias_generator=to_camel,
    )


class CanonRelation(StrEnum):
    COMPATIBLE_EPHEMERAL = "compatible_ephemeral"
    DELIBERATELY_FALSE_CLAIM = "deliberately_false_claim"
    FORBIDDEN_CONFLICT = "forbidden_conflict"


class ReportingMode(StrEnum):
    REPORTED_EVENT = "reported_event"
    CREDIBLE_ABSURDITY = "credible_absurdity"
    UNVERIFIED_RUMOR = "unverified_rumor"
    SATIRICAL_REPORT = "satirical_report"
    INTENTIONAL_FAKE = "intentional_fake"


class ArticleImportance(StrEnum):
    LEAD = "lead"
    MAJOR = "major"
    MINOR = "minor"
    BRIEF = "brief"


class VisualTone(StrEnum):
    LOOP_MATERIAL = "loop_material"
    ARCANE = "arcane"
    TIME = "time"
    BLOOD = "blood"
    NEUTRAL = "neutral"


class StorylineStatus(StrEnum):
    ACTIVE = "active"
    COOLING = "cooling"
    CLOSED = "closed"
    EPILOGUE = "epilogue"


class JobStatus(StrEnum):
    QUEUED = "queued"
    LEASED = "leased"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"
    MISSED = "missed"
    CANCELLED = "cancelled"


class EditionStatus(StrEnum):
    GENERATING = "generating"
    VALIDATED = "validated"
    PUBLISHED = "published"
    WITHDRAWN = "withdrawn"
    FAILED = "failed"


class RunPhase(StrEnum):
    LEASED = "leased"
    RETRIEVAL = "retrieval"
    PLANNING = "planning"
    WRITING = "writing"
    VALIDATING = "validating"
    VERIFYING = "verifying"
    REPAIRING = "repairing"
    PUBLISHING = "publishing"
    COMPLETED = "completed"
    FAILED = "failed"


SlotId = Annotated[
    str,
    Field(pattern=r"^(breaking-[1-3]|lead|major-[1-2]|minor-[1-2]|brief)$"),
]


class DiegeticSource(DomainModel):
    name: str = Field(min_length=1, max_length=100)
    kind: str = Field(min_length=1, max_length=40)
    reliability: Annotated[float, Field(ge=0, le=1)]


class EventEntity(DomainModel):
    entity_id: UUID | None = None
    name: str = Field(min_length=1, max_length=100)
    kind: str = Field(min_length=1, max_length=40)
    invented: bool = False
    recurring_candidate: bool = False


class EventClaim(DomainModel):
    text: str = Field(min_length=1, max_length=500)
    lore_chunk_ids: tuple[str, ...] = ()
    grounded: bool = True


class GazzettaEvent(DomainModel):
    id: UUID
    slot: SlotId
    headline_seed: str = Field(min_length=1, max_length=140)
    event_summary: str = Field(min_length=1, max_length=1200)
    location: str = Field(min_length=1, max_length=120)
    occurred_at: datetime
    canon_relation: CanonRelation
    reporting_mode: ReportingMode
    storyline_id: UUID | None = None
    storyline_appearance: Annotated[int, Field(ge=1, le=5)] | None = None
    storyline_candidate: bool = False
    entities: tuple[EventEntity, ...] = ()
    diegetic_sources: tuple[DiegeticSource, ...] = Field(min_length=1, max_length=4)
    lore_chunk_ids: tuple[str, ...] = ()
    claims: tuple[EventClaim, ...] = ()
    risk_flags: tuple[str, ...] = ()

    @model_validator(mode="after")
    def verita_e_storyline_coerenti(self) -> GazzettaEvent:
        importance = self.slot.split("-", 1)[0]
        if self.canon_relation == CanonRelation.FORBIDDEN_CONFLICT:
            raise ValueError("forbidden_conflict non è pubblicabile")
        if self.reporting_mode == ReportingMode.INTENTIONAL_FAKE:
            if importance not in {"minor", "brief"}:
                raise ValueError("intentional_fake è ammessa soltanto in minor o brief")
            if self.canon_relation != CanonRelation.DELIBERATELY_FALSE_CLAIM:
                raise ValueError("intentional_fake richiede deliberately_false_claim")
        if (
            self.canon_relation == CanonRelation.DELIBERATELY_FALSE_CLAIM
            and self.reporting_mode != ReportingMode.INTENTIONAL_FAKE
        ):
            raise ValueError("deliberately_false_claim richiede intentional_fake")
        if (self.storyline_id is None) != (self.storyline_appearance is None):
            raise ValueError("storyline_id e storyline_appearance devono comparire insieme")
        if self.storyline_candidate and self.storyline_id is not None:
            raise ValueError("una nuova storyline non può essere già assegnata")
        if self.storyline_candidate and self.reporting_mode == ReportingMode.INTENTIONAL_FAKE:
            raise ValueError("una fake deliberata non può aprire una storyline")
        return self


class GazzettaImage(DomainModel):
    src: str = Field(min_length=1, max_length=2048, pattern=r"^https://")
    alt: str = Field(min_length=1, max_length=320)
    caption: str | None = Field(default=None, max_length=320)
    credit: str | None = Field(default=None, max_length=160)
    focal_point: str | None = Field(
        default=None,
        pattern=r"^(?:100|\d{1,2})% (?:100|\d{1,2})%$",
    )


class GazzettaArticle(DomainModel):
    id: str = Field(min_length=1, max_length=100)
    category: str = Field(min_length=1, max_length=24)
    byline: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=70)
    kicker: str | None = Field(default=None, max_length=42)
    summary: str = Field(min_length=1, max_length=500)
    paragraphs: tuple[str, ...] = Field(min_length=1)
    image: GazzettaImage | None = None
    importance: ArticleImportance
    tone: VisualTone | None = None
    pull_quote: str | None = Field(default=None, max_length=300)


class GazzettaEditionSnapshot(DomainModel):
    schema_version: Literal[1] = 1
    id: UUID
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=120)
    issue_number: int = Field(gt=0)
    publication_date: datetime
    masthead_subtitle: str = Field(min_length=1, max_length=160)
    location_label: str = Field(min_length=1, max_length=100)
    breaking_news: tuple[str, str, str]
    lead_article: GazzettaArticle
    articles: tuple[GazzettaArticle, ...]
    editorial_quote: str = Field(min_length=1, max_length=300)
    closing_motto: str = Field(min_length=1, max_length=160)

    @model_validator(mode="after")
    def struttura_prima_pagina(self) -> GazzettaEditionSnapshot:
        if self.lead_article.importance != ArticleImportance.LEAD:
            raise ValueError("lead_article deve avere importance=lead")
        counts = {importance: 0 for importance in ArticleImportance}
        counts[self.lead_article.importance] += 1
        for article in self.articles:
            counts[article.importance] += 1
        expected = {
            ArticleImportance.LEAD: 1,
            ArticleImportance.MAJOR: 2,
            ArticleImportance.MINOR: 2,
            ArticleImportance.BRIEF: 1,
        }
        if counts != expected:
            raise ValueError("la prima pagina richiede 1 lead, 2 major, 2 minor e 1 brief")
        ids = [self.lead_article.id, *(article.id for article in self.articles)]
        if len(ids) != len(set(ids)):
            raise ValueError("gli ID degli articoli devono essere univoci")
        return self


class StorylineMemory(DomainModel):
    id: UUID
    title: str = Field(min_length=1, max_length=120)
    status: StorylineStatus
    recap: str = Field(min_length=1, max_length=2000)
    final_summary: str | None = Field(default=None, max_length=2000)
    open_hook: str | None = Field(default=None, max_length=500)
    involved_entities: tuple[EventEntity, ...] = ()
    location: str = Field(min_length=1, max_length=120)
    reporting_mode: ReportingMode
    appearance_count: int = Field(ge=1, le=4)
    epilogue_used: bool = False
    first_issue: int | None = Field(default=None, gt=0)
    last_issue: int | None = Field(default=None, gt=0)
    next_eligible_at: datetime | None = None
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def stato_terminale_coerente(self) -> StorylineMemory:
        if self.status == StorylineStatus.EPILOGUE and not self.epilogue_used:
            raise ValueError("lo stato epilogue richiede epilogue_used")
        if self.epilogue_used and self.status != StorylineStatus.EPILOGUE:
            raise ValueError("un epilogo usato è terminale")
        return self


class RecurringEntity(DomainModel):
    id: UUID
    kind: str = Field(min_length=1, max_length=40)
    display_name: str = Field(min_length=1, max_length=100)
    normalized_key: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=500)
    recurring: bool = False
    appearance_count: int = Field(ge=0)
    first_issue: int | None = Field(default=None, gt=0)
    last_issue: int | None = Field(default=None, gt=0)
    cooldown_until_issue: int | None = Field(default=None, gt=0)
    retired_at: datetime | None = None


class ValidationIssue(DomainModel):
    code: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=500)
    path: str | None = Field(default=None, max_length=200)
    repairable: bool = False


class ValidationReport(DomainModel):
    passed: bool
    issues: tuple[ValidationIssue, ...] = ()

    @model_validator(mode="after")
    def esito_coerente(self) -> ValidationReport:
        if self.passed and self.issues:
            raise ValueError("un report passato non può contenere issue")
        return self


class RunMetadata(DomainModel):
    corpus_release_id: str
    policy_version: str
    policy_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    prompt_versions: dict[str, str]
    prompt_hashes: dict[str, str]
    models: dict[str, str]
    token_input: int = Field(ge=0)
    token_output: int = Field(ge=0)
    groq_requests: int = Field(ge=0, le=4)
    rate_limits: dict[str, str | int | float | None] = Field(default_factory=dict)

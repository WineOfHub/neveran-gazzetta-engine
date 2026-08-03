from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from neveran_gazzetta.domain.models import SlotId, ValidationIssue
from neveran_gazzetta.generation.editorial_planner import SLOTS


class StrictGenerationModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        alias_generator=to_camel,
    )


class EventEntityDraft(StrictGenerationModel):
    entity_id: UUID | None = Field(alias="entityId")
    name: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    invented: bool
    recurring_candidate: bool = Field(alias="recurringCandidate")


class DiegeticSourceDraft(StrictGenerationModel):
    name: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    reliability: float = Field(ge=0, le=1)


class EventDraft(StrictGenerationModel):
    """Contenuto editoriale LLM; i campi tecnici sono applicati dal motore."""

    slot: SlotId
    headline_seed: str = Field(min_length=1, max_length=100, alias="headlineSeed")
    event_summary: str = Field(min_length=1, max_length=360, alias="eventSummary")
    location: str = Field(min_length=1, max_length=120)
    entities: tuple[EventEntityDraft, ...] = Field(max_length=3)
    diegetic_sources: tuple[DiegeticSourceDraft, ...] = Field(
        min_length=1,
        max_length=4,
        alias="diegeticSources",
    )
    lore_chunk_ids: tuple[str, ...] = Field(
        min_length=1,
        max_length=3,
        alias="loreChunkIds",
    )


class EventPlanResponse(StrictGenerationModel):
    events: tuple[EventDraft, ...] = Field(min_length=9, max_length=9)

    @model_validator(mode="after")
    def slot_esatti(self) -> EventPlanResponse:
        if sorted(event.slot for event in self.events) != sorted(SLOTS):
            raise ValueError("Event Planner deve restituire esattamente i nove slot")
        return self


class ArticleDraft(StrictGenerationModel):
    category: str = Field(min_length=1)
    title: str = Field(min_length=1)
    kicker: str | None = None
    summary: str = Field(min_length=1)
    paragraphs: tuple[str, ...]
    pull_quote: str | None = None


class LeadArticleDraft(ArticleDraft):
    paragraphs: tuple[str, ...] = Field(min_length=3, max_length=3)


class MajorArticleDraft(ArticleDraft):
    paragraphs: tuple[str, ...] = Field(min_length=2, max_length=2)


class SingleParagraphArticleDraft(ArticleDraft):
    paragraphs: tuple[str, ...] = Field(min_length=1, max_length=1)


class NewspaperDraft(StrictGenerationModel):
    masthead_subtitle: str = Field(min_length=1)
    location_label: str = Field(min_length=1)
    breaking_news: tuple[str, ...] = Field(min_length=3, max_length=3)
    lead_article: LeadArticleDraft
    major_articles: tuple[MajorArticleDraft, ...] = Field(min_length=2, max_length=2)
    minor_articles: tuple[SingleParagraphArticleDraft, ...] = Field(min_length=2, max_length=2)
    brief_article: SingleParagraphArticleDraft
    editorial_quote: str = Field(min_length=1)
    closing_motto: str = Field(min_length=1)


class EditionDraftResponse(StrictGenerationModel):
    edition: NewspaperDraft


class VerifierOutcome(StrEnum):
    PASS = "pass"
    REPAIRABLE = "repairable"
    REJECT = "reject"


class VerifierVerdict(StrictGenerationModel):
    outcome: VerifierOutcome
    issues: tuple[ValidationIssue, ...] = ()

    @model_validator(mode="after")
    def verdetto_coerente(self) -> VerifierVerdict:
        if self.outcome == VerifierOutcome.PASS and self.issues:
            raise ValueError("pass non può contenere issue")
        if self.outcome != VerifierOutcome.PASS and not self.issues:
            raise ValueError("un esito negativo richiede almeno una issue")
        return self


class TokenUsage(StrictGenerationModel):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class GroqJsonResult(StrictGenerationModel):
    payload: dict[str, object]
    usage: TokenUsage
    rate_limits: dict[str, str | int | float | None] = Field(default_factory=dict)

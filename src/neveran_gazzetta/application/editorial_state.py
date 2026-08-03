from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from neveran_gazzetta.domain.models import RecurringEntity, StorylineMemory


class EditorialState(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        alias_generator=to_camel,
    )

    next_issue_number: int = Field(gt=0)
    storylines: tuple[StorylineMemory, ...] = ()
    recurring_entities: tuple[RecurringEntity, ...] = ()
    topic_hints: tuple[str, ...] = ()


class EditorialStateProvider(Protocol):
    def get_editorial_state(self) -> EditorialState: ...

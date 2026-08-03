from __future__ import annotations

from neveran_gazzetta.config import RetrievalConfig
from neveran_gazzetta.domain.models import StorylineMemory
from neveran_gazzetta.generation.editorial_planner import EditionPlan
from neveran_gazzetta.retrieval.core_adapter import GazzettaRetrievalAdapter
from neveran_gazzetta.retrieval.palette import GazzettaLorePalette, build_lore_palette
from neveran_gazzetta.retrieval.queries import build_editorial_queries


class EditorialRetrievalService:
    def __init__(self, adapter: GazzettaRetrievalAdapter, config: RetrievalConfig) -> None:
        self._adapter = adapter
        self._config = config

    def retrieve_palette(
        self,
        plan: EditionPlan,
        *,
        storylines: list[StorylineMemory],
        topic_hints: list[str] | None = None,
    ) -> GazzettaLorePalette:
        queries = build_editorial_queries(
            plan,
            storylines=storylines,
            topic_hints=topic_hints,
        )
        result = self._adapter.retrieve([query.text for query in queries])
        return build_lore_palette(
            result,
            queries,
            token_budget=self._config.context_token_budget,
            min_chunks=self._config.min_chunks_for_edition,
            min_documents=self._config.min_documents_for_edition,
            min_average_score=self._config.min_average_score,
        )

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from neveran_gazzetta.domain.errors import NoEvidence, ProviderUnavailable, ReleaseMismatch


class LoreChunk(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: str
    document_id: str
    text: str
    score: float
    section_path: tuple[str, ...]


class GazzettaRetrievalResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chunks: tuple[LoreChunk, ...]
    corpus_release_id: str
    queries: tuple[str, ...]


class GazzettaRetrievalAdapter:
    """Consumer globale: costruisce internamente il profilo pubblico verificato."""

    def __init__(self, *, embedder: Any, store: Any, releases: Any, limits: Any) -> None:
        self._embedder = embedder
        self._store = store
        self._releases = releases
        self._limits = limits

    def active_release_id(self) -> str:
        try:
            return str(self._releases.get_active_release().release_id)
        except Exception as exc:
            from neveran_knowledge.retrieval_core import (
                ProviderUnavailable as CoreProviderUnavailable,
            )
            from neveran_knowledge.retrieval_core import (
                ReleaseMismatch as CoreReleaseMismatch,
            )

            if isinstance(exc, CoreReleaseMismatch):
                raise ReleaseMismatch(str(exc)) from exc
            if isinstance(exc, CoreProviderUnavailable):
                raise ProviderUnavailable(str(exc)) from exc
            raise

    def retrieve(self, queries: list[str]) -> GazzettaRetrievalResult:
        try:
            from neveran_knowledge.domain.access import ActorProfile
            from neveran_knowledge.retrieval_core import (
                NoEvidence as CoreNoEvidence,
            )
            from neveran_knowledge.retrieval_core import (
                ProviderUnavailable as CoreProviderUnavailable,
            )
            from neveran_knowledge.retrieval_core import (
                ReleaseMismatch as CoreReleaseMismatch,
            )
            from neveran_knowledge.retrieval_core import (
                RetrievalProfile,
                hybrid_retrieve,
            )
        except ImportError as exc:
            raise ProviderUnavailable(
                "Package neveran-knowledge-engine non installato"
            ) from exc

        profile = RetrievalProfile(
            name="gazzetta_generation",
            purpose="generation",
            actor=ActorProfile(
                actor_type="public_assistant",
                role=None,
                location=None,
                factions=[],
                campaign_id=None,
                discoveries=[],
                permissions=[],
                max_spoiler_level="none",
            ),
            initial_candidates_per_query=self._limits.top_k_per_query,
            final_chunks=self._limits.max_chunks,
            max_chunks_per_document=self._limits.max_chunks_per_document,
        )
        try:
            result = hybrid_retrieve(
                queries,
                profile=profile,
                embedder=self._embedder,
                store=self._store,
                releases=self._releases,
            )
        except CoreNoEvidence as exc:
            raise NoEvidence(str(exc)) from exc
        except CoreReleaseMismatch as exc:
            raise ReleaseMismatch(str(exc)) from exc
        except CoreProviderUnavailable as exc:
            raise ProviderUnavailable(str(exc)) from exc

        return GazzettaRetrievalResult(
            chunks=tuple(
                LoreChunk(
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    text=chunk.text,
                    score=chunk.score,
                    section_path=tuple(chunk.section_path),
                )
                for chunk in result.chunks
            ),
            corpus_release_id=result.trace.release_id,
            queries=result.trace.queries,
        )

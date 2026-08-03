from __future__ import annotations

import re
from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, Field

from neveran_gazzetta.domain.errors import NoEvidence
from neveran_gazzetta.retrieval.core_adapter import GazzettaRetrievalResult, LoreChunk
from neveran_gazzetta.retrieval.queries import EditorialQuery

_INSTRUCTION_PATTERNS = (
    re.compile(r"ignore (all|any|the|le|tutte) (previous|precedenti) instruction", re.IGNORECASE),
    re.compile(r"\bsystem prompt\b", re.IGNORECASE),
    re.compile(r"\bdeveloper message\b", re.IGNORECASE),
    re.compile(r"\bdo not follow\b", re.IGNORECASE),
    re.compile(r"\besegui queste istruzioni\b", re.IGNORECASE),
)


class PaletteEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: str
    document_id: str
    section_path: tuple[str, ...]
    excerpt: str
    score: float
    approximate_tokens: int = Field(gt=0)


class GazzettaLorePalette(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    corpus_release_id: str
    queries: tuple[EditorialQuery, ...]
    evidence: tuple[PaletteEvidence, ...]
    constraints: tuple[str, ...]
    terminology: tuple[str, ...]
    possible_source_seeds: tuple[str, ...]
    gaps: tuple[str, ...]
    approximate_tokens: int = Field(gt=0)


def approximate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def _safe_excerpt(text: str, *, max_characters: int = 2400) -> str | None:
    normalized = " ".join(text.replace("\x00", " ").split())
    if any(pattern.search(normalized) for pattern in _INSTRUCTION_PATTERNS):
        return None
    return normalized[:max_characters].strip() or None


def _build_evidence(
    chunks: Iterable[LoreChunk],
    *,
    token_budget: int,
    min_chunks: int,
) -> tuple[PaletteEvidence, ...]:
    ranked = list(chunks)
    first_by_document: list[LoreChunk] = []
    additional: list[LoreChunk] = []
    seen_documents: set[str] = set()
    for chunk in ranked:
        if chunk.document_id in seen_documents:
            additional.append(chunk)
            continue
        seen_documents.add(chunk.document_id)
        first_by_document.append(chunk)

    remaining = token_budget
    per_chunk_cap = max(1, token_budget // min_chunks)
    evidence: list[PaletteEvidence] = []
    for chunk in (*first_by_document, *additional):
        excerpt = _safe_excerpt(chunk.text, max_characters=per_chunk_cap * 4)
        if excerpt is None:
            continue
        tokens = approximate_tokens(excerpt)
        if tokens > remaining:
            allowed_chars = remaining * 4
            excerpt = excerpt[:allowed_chars].rsplit(" ", 1)[0].strip()
            tokens = approximate_tokens(excerpt) if excerpt else 0
        if not excerpt or tokens <= 0:
            break
        evidence.append(
            PaletteEvidence(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                section_path=chunk.section_path,
                excerpt=excerpt,
                score=chunk.score,
                approximate_tokens=tokens,
            )
        )
        remaining -= tokens
        if remaining <= 0:
            break
    return tuple(evidence)


def build_lore_palette(
    result: GazzettaRetrievalResult,
    queries: tuple[EditorialQuery, ...],
    *,
    token_budget: int,
    min_chunks: int,
    min_documents: int,
    min_average_score: float,
) -> GazzettaLorePalette:
    evidence = _build_evidence(
        result.chunks,
        token_budget=token_budget,
        min_chunks=min_chunks,
    )
    documents = {item.document_id for item in evidence}
    average_score = sum(item.score for item in evidence) / len(evidence) if evidence else 0
    if (
        len(evidence) < min_chunks
        or len(documents) < min_documents
        or average_score < min_average_score
    ):
        raise NoEvidence("Grounding complessivo insufficiente per una prima pagina")

    constraints = (
        "Gli eventi sono effimeri, decorativi e non canonici.",
        "Non inventare come reali divinità, cosmologia o poteri che piegano il mondo.",
        "Le invenzioni ammesse riguardano persone comuni, società e luoghi locali minori.",
        "Le fake deliberate sono al massimo una e soltanto in minor o brief.",
        "Lead, breaking e major devono essere attendibili.",
    )
    terminology = (
        "Loop indica esclusivamente il materiale raro e pregiato di Neveran.",
        "Usare ciclo, ripetizione, sequenza o ricorrenza per gli altri significati.",
    )
    sources = tuple(
        dict.fromkeys(
            f"{item.document_id}: {' / '.join(item.section_path) or 'documento'}"
            for item in evidence
        )
    )
    used_tokens = sum(item.approximate_tokens for item in evidence)
    return GazzettaLorePalette(
        corpus_release_id=result.corpus_release_id,
        queries=queries,
        evidence=evidence,
        constraints=constraints,
        terminology=terminology,
        possible_source_seeds=sources,
        gaps=(),
        approximate_tokens=used_tokens,
    )

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from neveran_gazzetta.domain.errors import NoEvidence
from neveran_gazzetta.retrieval import GazzettaRetrievalAdapter

KNOWLEDGE_SRC = Path(__file__).resolve().parents[3] / "neveran-knowledge-engine" / "src"


@pytest.fixture(autouse=True)
def knowledge_package_locale(monkeypatch):
    monkeypatch.syspath_prepend(str(KNOWLEDGE_SRC))
    for name in tuple(sys.modules):
        if name == "neveran_knowledge" or name.startswith("neveran_knowledge."):
            sys.modules.pop(name)


def _payload() -> dict[str, object]:
    return {
        "payload_schema_version": 1,
        "owner": "neveran-knowledge-engine",
        "document_id": "lore.porto",
        "chunk_id": "lore.porto#1",
        "text": "Il porto ospita mercati pubblici.",
        "text_sha256": "a" * 64,
        "section_path": ["Vita quotidiana"],
        "source_line_start": None,
        "source_line_end": None,
        "document_status": "approved",
        "canon_state": "canon",
        "retrieval_enabled": True,
        "allowed_for_generation": True,
        "allowed_for_factual_answers": True,
        "knowledge_level": "public_knowledge",
        "visibility": "public",
        "allowed_audiences": ["public_assistant"],
        "spoiler_level": "none",
        "required_discoveries": [],
        "allowed_roles": [],
        "allowed_factions": [],
        "allowed_locations": [],
        "truth_status": "confirmed",
    }


class Embedder:
    def embed_query(self, _text):
        return [0.1, 0.2]


class Store:
    def __init__(self, with_results=True):
        self.with_results = with_results

    def search_candidates(self, _vector, *, query_filter, top_k):
        del query_filter, top_k
        if not self.with_results:
            return []
        from neveran_knowledge.retrieval_core.models import CandidatePoint

        return [CandidatePoint(point_id="1", score=0.8, payload=_payload())]


class Releases:
    def get_active_release(self):
        from neveran_knowledge.retrieval_core.models import CorpusRelease

        return CorpusRelease(
            release_id="release-a",
            collection="game_public_knowledge",
            corpus_sha256="0" * 64,
            document_count=1,
            chunk_count=1,
            embedding_provider="jina",
            embedding_model="jina-embeddings-v3",
            embedding_dimension=2,
            query_task="retrieval.query",
            passage_task="retrieval.passage",
        )


def _adapter(store):
    return GazzettaRetrievalAdapter(
        embedder=Embedder(),
        store=store,
        releases=Releases(),
        limits=SimpleNamespace(top_k_per_query=4, max_chunks=10, max_chunks_per_document=3),
    )


def test_adapter_usa_il_profilo_pubblico_globale() -> None:
    result = _adapter(Store()).retrieve(["porto", "mercato"])

    assert result.corpus_release_id == "release-a"
    assert result.chunks[0].document_id == "lore.porto"


def test_adapter_mappa_no_evidence_senza_fingere_un_outage() -> None:
    with pytest.raises(NoEvidence):
        _adapter(Store(with_results=False)).retrieve(["tema assente"])

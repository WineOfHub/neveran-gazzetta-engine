"""Retrieval editoriale basato sul core condiviso del Knowledge Engine."""

from neveran_gazzetta.retrieval.core_adapter import (
    GazzettaRetrievalAdapter,
    GazzettaRetrievalResult,
    LoreChunk,
)
from neveran_gazzetta.retrieval.palette import GazzettaLorePalette
from neveran_gazzetta.retrieval.service import EditorialRetrievalService

__all__ = [
    "EditorialRetrievalService",
    "GazzettaLorePalette",
    "GazzettaRetrievalAdapter",
    "GazzettaRetrievalResult",
    "LoreChunk",
]

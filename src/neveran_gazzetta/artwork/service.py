from __future__ import annotations

from typing import Protocol

from neveran_gazzetta.artwork.models import (
    ArtworkBrief,
    GeneratedArtwork,
    WorkerGeneratedImage,
)
from neveran_gazzetta.artwork.supabase import SupabaseArtworkStore


class ArtworkImageGenerator(Protocol):
    def generate(self, brief: ArtworkBrief) -> WorkerGeneratedImage: ...


class SupabaseBackedArtworkService:
    """Coordina cache Supabase, generazione AI e persistenza immutabile."""

    def __init__(
        self,
        *,
        generator: ArtworkImageGenerator,
        store: SupabaseArtworkStore,
    ) -> None:
        self._generator = generator
        self._store = store

    def generate(self, brief: ArtworkBrief) -> GeneratedArtwork:
        existing = self._store.load_existing(brief)
        if existing is not None:
            return existing
        generated = self._generator.generate(brief)
        return self._store.persist(brief, generated)

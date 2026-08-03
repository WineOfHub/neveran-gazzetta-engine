from __future__ import annotations

from typing import Protocol

from neveran_gazzetta.artwork.models import ArtworkBrief, GeneratedArtwork


class ArtworkGenerationPort(Protocol):
    def generate(self, brief: ArtworkBrief) -> GeneratedArtwork: ...

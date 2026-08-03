"""Generazione opzionale dell'illustrazione lead."""

from neveran_gazzetta.artwork.cloudflare import CloudflareArtworkClient
from neveran_gazzetta.artwork.contracts import ArtworkGenerationPort
from neveran_gazzetta.artwork.models import ArtworkBrief, GeneratedArtwork, WorkerGeneratedImage
from neveran_gazzetta.artwork.prompt import build_artwork_brief
from neveran_gazzetta.artwork.service import SupabaseBackedArtworkService
from neveran_gazzetta.artwork.supabase import SupabaseArtworkStore

__all__ = [
    "ArtworkBrief",
    "ArtworkGenerationPort",
    "CloudflareArtworkClient",
    "GeneratedArtwork",
    "SupabaseArtworkStore",
    "SupabaseBackedArtworkService",
    "WorkerGeneratedImage",
    "build_artwork_brief",
]

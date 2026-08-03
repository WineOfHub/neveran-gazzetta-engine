from __future__ import annotations

import hashlib
import re

from neveran_gazzetta.application.contracts import JobLease
from neveran_gazzetta.artwork.models import ArtworkBrief
from neveran_gazzetta.config import ArtworkPolicy
from neveran_gazzetta.domain.models import GazzettaEditionSnapshot, GazzettaEvent
from neveran_gazzetta.retrieval.palette import GazzettaLorePalette

_WHITESPACE = re.compile(r"\s+")
MAX_ARTWORK_PROMPT_CHARACTERS = 2200


def _clean(value: str, limit: int) -> str:
    normalized = _WHITESPACE.sub(" ", value).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rsplit(" ", 1)[0] + "…"


def _list(values: tuple[str, ...], *, item_limit: int, total: int) -> str:
    selected = [_clean(value, item_limit) for value in values[:total] if value.strip()]
    return "; ".join(selected) if selected else "nessun dettaglio aggiuntivo"


def build_artwork_brief(
    *,
    lease: JobLease,
    edition: GazzettaEditionSnapshot,
    events: tuple[GazzettaEvent, ...],
    palette: GazzettaLorePalette,
    policy: ArtworkPolicy,
) -> ArtworkBrief:
    """Costruisce il prompt senza una nuova chiamata LLM o retrieval."""

    lead_events = [event for event in events if event.slot == "lead"]
    if len(lead_events) != 1:
        raise ValueError("Il brief artwork richiede esattamente un evento lead")
    event = lead_events[0]
    article = edition.lead_article
    subjects = ", ".join(
        f"{_clean(entity.name, 60)} ({_clean(entity.kind, 24)})"
        for entity in event.entities
    ) or "ordinary inhabitants appropriate to the reported place"
    tone = article.tone.value if article.tone else "neutral"
    prompt = _clean(
        "\n".join(
        (
            "Create a standalone cinematic documentary scene set entirely in the fantasy world "
            "of Neveran. It will be placed inside an editorial layout, but the image itself must "
            "show only the reported place and action, filling the canvas edge to edge.",
            "Never depict a newspaper, magazine, printed page, front page, poster, placard, frame "
            "or mockup. The output must be a direct view of the scene, not a picture of media.",
            "No letters, words, headlines, captions, signage, logos, watermarks, UI, borders, "
            "modern real-world technology, graphic gore, crowded close-up faces or prominent "
            "hands. Do not imitate a real living artist.",
            "This is a provisional report, not new canon. Do not invent deities, cosmology, "
            "metaphysical laws, major organizations or world-bending powers. Loop, if present, "
            "is only a rare and precious material.",
            f"Lead report title: {_clean(article.title, 90)}",
            f"Reported event: {_clean(event.event_summary, 240)}",
            f"Location: {_clean(event.location, 80)}",
            f"Visible subjects: {subjects}",
            f"Editorial visual tone: {tone}",
            f"Lore constraints that must be respected: "
            f"{_list(palette.constraints, item_limit=100, total=3)}",
            f"Canonical terminology: {_list(palette.terminology, item_limit=55, total=4)}",
            "Art direction: dark magitech fantasy photojournalism, credible lived-in environment, "
            "restrained cyan arcane light, muted violet shadows, weathered stone and metal, "
            "dramatic natural atmosphere, detailed but readable wide landscape composition, "
            "one clear visual subject and breathing room around the focal action. Full-bleed "
            "environmental scene, no typographic composition.",
        )
        ),
        MAX_ARTWORK_PROMPT_CHARACTERS,
    )
    prompt_sha256 = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    seed_material = (
        f"{lease.job_id}:{edition.issue_number}:{event.id}:{policy.prompt_version}"
    )
    seed = int(hashlib.sha256(seed_material.encode("utf-8")).hexdigest()[:8], 16)
    alt = _clean(f"Illustrazione editoriale: {article.title}. {article.summary}", 320)
    caption = _clean(f"{event.location} · {article.summary}", 320)
    return ArtworkBrief(
        job_id=lease.job_id,
        issue_number=edition.issue_number,
        prompt=prompt,
        prompt_sha256=prompt_sha256,
        seed=seed,
        alt=alt,
        caption=caption,
        credit="Archivio ottico CCIN · sintesi illustrata",
        focal_point="50% 42%",
    )

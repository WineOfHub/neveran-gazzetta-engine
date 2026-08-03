from __future__ import annotations

import hashlib
from datetime import datetime

from neveran_gazzetta.domain.models import StorylineMemory, StorylineStatus


def compact_recap(text: str, *, max_words: int = 180) -> str:
    words = text.split()
    return " ".join(words[:max_words])


def storyline_fingerprint(title: str, location: str, entity_names: list[str]) -> str:
    normalized = "|".join(
        [
            title.casefold().strip(),
            location.casefold().strip(),
            *sorted(name.casefold().strip() for name in entity_names),
        ]
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def advance_storyline(
    storyline: StorylineMemory,
    *,
    recap: str,
    issue_number: int,
    next_eligible_at: datetime | None,
    close: bool = False,
    epilogue: bool = False,
) -> StorylineMemory:
    if storyline.last_issue is not None and issue_number <= storyline.last_issue:
        raise ValueError("Una storyline non può apparire due volte nella stessa edizione")
    if epilogue:
        if storyline.status != StorylineStatus.CLOSED or storyline.epilogue_used:
            raise ValueError("L'epilogo richiede una storyline chiusa senza epilogo precedente")
        return storyline.model_copy(
            update={
                "status": StorylineStatus.EPILOGUE,
                "epilogue_used": True,
                "recap": compact_recap(recap),
                "last_issue": issue_number,
                "next_eligible_at": None,
            }
        )
    if storyline.status in {StorylineStatus.CLOSED, StorylineStatus.EPILOGUE}:
        raise ValueError("Una storyline chiusa può ricevere soltanto l'epilogo")
    if storyline.appearance_count >= 4:
        raise ValueError("La storyline ha già raggiunto quattro apparizioni")
    appearances = storyline.appearance_count + 1
    status = StorylineStatus.CLOSED if close or appearances == 4 else StorylineStatus.COOLING
    return storyline.model_copy(
        update={
            "status": status,
            "appearance_count": appearances,
            "recap": compact_recap(recap),
            "last_issue": issue_number,
            "next_eligible_at": None if status == StorylineStatus.CLOSED else next_eligible_at,
            "final_summary": compact_recap(recap) if status == StorylineStatus.CLOSED else None,
        }
    )

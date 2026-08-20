from __future__ import annotations

import re

from neveran_gazzetta.domain.models import GazzettaEvent, ReportingMode, ValidationIssue
from neveran_gazzetta.generation.editorial_planner import SLOTS

_LOOP = re.compile(r"\bloop\b", re.IGNORECASE)
_LOOP_MATERIAL_CONTEXT = re.compile(
    r"\b(materiale|minerale|prezios[oaie]?|rar[oaie]?|metallo|framment[oi]|"
    r"lingott[oi]|giacimento|estratt[oaie]?|commercio)\b",
    re.IGNORECASE,
)
_FORBIDDEN_DEEP_PATTERNS = (
    re.compile(r"\bnuov[oa]\s+(dio|dea|divinità)\b", re.IGNORECASE),
    re.compile(r"\bnuova\s+legge\s+(cosmica|metafisica)\b", re.IGNORECASE),
    re.compile(r"\bpotere\s+che\s+(riscrive|piega|distrugge)\s+il\s+mondo\b", re.IGNORECASE),
)
_FORBIDDEN_RISK_FLAGS = {
    "invented_deity",
    "invented_cosmology",
    "invented_metaphysical_law",
    "world_bending_power",
    "canonical_conflict",
}


def normalize_loop_usage(text: str) -> str:
    """Sostituisce soltanto gli usi non materiali del termine riservato."""

    def replacement(match: re.Match[str]) -> str:
        window = text[max(0, match.start() - 80) : match.end() + 80]
        if _LOOP_MATERIAL_CONTEXT.search(window):
            return match.group(0)
        original = match.group(0)
        if original.isupper():
            return "CICLO"
        if original[:1].isupper():
            return "Ciclo"
        return "ciclo"

    return _LOOP.sub(replacement, text)


def validate_loop_usage(text: str) -> ValidationIssue | None:
    for match in _LOOP.finditer(text):
        window = text[max(0, match.start() - 80) : match.end() + 80]
        if not _LOOP_MATERIAL_CONTEXT.search(window):
            return ValidationIssue(
                code="loop_ambiguous",
                message="Loop deve indicare soltanto il materiale raro e pregiato",
                repairable=True,
            )
    return None


def validate_settlement_location(
    location: str, *, allowed_settlement_names: frozenset[str]
) -> bool:
    """Vero se `location` nomina almeno un insediamento reale consentito.

    Confronto per sottostringa case-insensitive in entrambe le direzioni:
    `location` può aggiungere colore senza ripetere l'intero titolo
    ("Romolia — banchina nord" contiene "Romolia"), e può anche essere solo
    il nome breve mentre il titolo canonico porta un sottotitolo editoriale
    ("Ael Sadurith" è contenuto in "Ael Sadurith — La Città della Concordia").
    """
    normalized = location.casefold()
    return any(
        name.casefold() in normalized or normalized in name.casefold()
        for name in allowed_settlement_names
    )


def validate_event_set(
    events: list[GazzettaEvent],
    *,
    allowed_settlement_names: frozenset[str] = frozenset(),
) -> tuple[ValidationIssue, ...]:
    issues: list[ValidationIssue] = []
    actual_slots = [event.slot for event in events]
    if sorted(actual_slots) != sorted(SLOTS):
        issues.append(
            ValidationIssue(
                code="invalid_slots",
                message="L'edizione deve contenere esattamente i nove slot previsti",
            )
        )
    if len(actual_slots) != len(set(actual_slots)):
        issues.append(
            ValidationIssue(code="duplicate_slot", message="Uno slot è presente più volte")
        )
    fake_count = sum(
        event.reporting_mode == ReportingMode.INTENTIONAL_FAKE for event in events
    )
    if fake_count > 1:
        issues.append(
            ValidationIssue(
                code="too_many_fakes",
                message="È ammessa al massimo una fake deliberata per edizione",
            )
        )
    storylines = [event.storyline_id for event in events if event.storyline_id is not None]
    if len(storylines) != len(set(storylines)):
        issues.append(
            ValidationIssue(
                code="duplicate_storyline",
                message="Una storyline non può apparire due volte nella stessa edizione",
            )
        )
    candidates = [event for event in events if event.storyline_candidate]
    if len(candidates) > 2:
        issues.append(
            ValidationIssue(
                code="too_many_new_storylines",
                message="Sono ammesse al massimo due nuove storyline per edizione",
            )
        )
    for event in candidates:
        if event.slot.split("-", 1)[0] not in {"lead", "major", "minor", "brief"}:
            issues.append(
                ValidationIssue(
                    code="invalid_storyline_origin",
                    message="Una storyline può iniziare soltanto in lead, major, minor o brief",
                    path=event.slot,
                )
            )
    for event in events:
        full_text = " ".join(
            [event.headline_seed, event.event_summary, *(claim.text for claim in event.claims)]
        )
        loop_issue = validate_loop_usage(full_text)
        if loop_issue:
            issues.append(loop_issue.model_copy(update={"path": event.slot}))
        if _FORBIDDEN_RISK_FLAGS.intersection(event.risk_flags) or any(
            pattern.search(full_text) for pattern in _FORBIDDEN_DEEP_PATTERNS
        ):
            issues.append(
                ValidationIssue(
                    code="forbidden_deep_invention",
                    message="L'evento introduce un elemento profondo vietato",
                    path=event.slot,
                )
            )
        if not event.lore_chunk_ids:
            issues.append(
                ValidationIssue(
                    code="ungrounded_event",
                    message="L'evento non conserva riferimenti alla lore",
                    path=event.slot,
                )
            )
        if allowed_settlement_names and not validate_settlement_location(
            event.location, allowed_settlement_names=allowed_settlement_names
        ):
            issues.append(
                ValidationIssue(
                    code="invented_settlement_location",
                    message=(
                        "L'ambientazione dell'evento non nomina nessuno degli insediamenti "
                        "reali consentiti per questa edizione"
                    ),
                    path=event.slot,
                )
            )
        best_source = max(source.reliability for source in event.diegetic_sources)
        importance = event.slot.split("-", 1)[0]
        if event.reporting_mode != ReportingMode.INTENTIONAL_FAKE and best_source < 0.5:
            issues.append(
                ValidationIssue(
                    code="weak_sources",
                    message="Una notizia non fake richiede almeno una fonte plausibile",
                    path=event.slot,
                )
            )
        if importance in {"breaking", "lead", "major"} and best_source < 0.7:
            issues.append(
                ValidationIssue(
                    code="weak_primary_sources",
                    message="Gli slot principali richiedono una fonte ad alta affidabilità",
                    path=event.slot,
                )
            )
    return tuple(issues)

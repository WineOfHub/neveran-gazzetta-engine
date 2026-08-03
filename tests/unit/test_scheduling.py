from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from neveran_gazzetta.scheduling.slots import due_slots, first_slot_at_or_after, next_slot


def test_next_slot_preserva_le_sei_durante_ora_legale() -> None:
    rome = ZoneInfo("Europe/Rome")
    before_dst = datetime(2026, 3, 28, 6, 0, tzinfo=rome)

    result = next_slot(before_dst, cadence_days=2, timezone="Europe/Rome")

    assert result.astimezone(rome) == datetime(2026, 3, 30, 6, 0, tzinfo=rome)
    assert result.hour == 4  # UTC cambia, l'ora editoriale locale no.


def test_next_slot_preserva_le_sei_durante_ora_solare() -> None:
    rome = ZoneInfo("Europe/Rome")
    before_dst = datetime(2026, 10, 24, 6, 0, tzinfo=rome)

    result = next_slot(before_dst, cadence_days=2, timezone="Europe/Rome")

    assert result.astimezone(rome) == datetime(2026, 10, 26, 6, 0, tzinfo=rome)
    assert result.hour == 5


def test_catch_up_restituisce_solo_ultimo_slot() -> None:
    start = datetime(2026, 8, 1, 4, 0, tzinfo=UTC)  # 06:00 Roma
    now = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)

    result = due_slots(start, now, cadence_days=2, timezone="Europe/Rome")

    assert result.missed == (
        datetime(2026, 8, 1, 4, 0, tzinfo=UTC),
        datetime(2026, 8, 3, 4, 0, tzinfo=UTC),
    )
    assert result.latest == datetime(2026, 8, 5, 4, 0, tzinfo=UTC)


def test_primo_slot_dopo_orario_editoriale_va_al_giorno_successivo() -> None:
    value = datetime(2026, 8, 1, 8, 0, tzinfo=UTC)

    result = first_slot_at_or_after(
        value,
        publication_hour=6,
        publication_minute=0,
        timezone="Europe/Rome",
    )

    assert result == datetime(2026, 8, 2, 4, 0, tzinfo=UTC)

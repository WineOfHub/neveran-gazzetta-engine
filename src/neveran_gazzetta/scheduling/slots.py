from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class DueSlots:
    latest: datetime | None
    missed: tuple[datetime, ...]


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Il timestamp deve essere timezone-aware")


def next_slot(slot: datetime, *, cadence_days: int, timezone: str) -> datetime:
    """Avanza in giorni di calendario locali, preservando l'ora durante il DST."""
    _aware(slot)
    if cadence_days <= 0:
        raise ValueError("cadence_days deve essere positivo")
    zone = ZoneInfo(timezone)
    local = slot.astimezone(zone)
    target_date = local.date() + timedelta(days=cadence_days)
    target = datetime.combine(target_date, local.timetz().replace(tzinfo=None), tzinfo=zone)
    return target.astimezone(UTC)


def first_slot_at_or_after(
    value: datetime,
    *,
    publication_hour: int,
    publication_minute: int,
    timezone: str,
) -> datetime:
    _aware(value)
    zone = ZoneInfo(timezone)
    local = value.astimezone(zone)
    candidate = datetime.combine(
        local.date(),
        time(publication_hour, publication_minute),
        tzinfo=zone,
    )
    if candidate < local:
        candidate = datetime.combine(
            date.fromordinal(local.date().toordinal() + 1),
            time(publication_hour, publication_minute),
            tzinfo=zone,
        )
    return candidate.astimezone(UTC)


def due_slots(
    next_due_at: datetime,
    now: datetime,
    *,
    cadence_days: int,
    timezone: str,
) -> DueSlots:
    """Restituisce solo l'ultimo slot dovuto e classifica i precedenti come missed."""
    _aware(next_due_at)
    _aware(now)
    if now < next_due_at:
        return DueSlots(latest=None, missed=())
    due: list[datetime] = [next_due_at.astimezone(UTC)]
    candidate = next_slot(next_due_at, cadence_days=cadence_days, timezone=timezone)
    while candidate <= now:
        due.append(candidate)
        candidate = next_slot(candidate, cadence_days=cadence_days, timezone=timezone)
    return DueSlots(latest=due[-1], missed=tuple(due[:-1]))

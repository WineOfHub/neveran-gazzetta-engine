from __future__ import annotations

import random

from neveran_gazzetta.domain.models import RecurringEntity


def select_recurring_entities(
    entities: list[RecurringEntity],
    *,
    issue_number: int,
    count: int,
    repeated_penalty: float,
    rng: random.Random,
) -> list[RecurringEntity]:
    eligible = [
        entity
        for entity in entities
        if entity.retired_at is None
        and (entity.cooldown_until_issue is None or entity.cooldown_until_issue <= issue_number)
        and (entity.last_issue is None or entity.last_issue < issue_number)
    ]
    selected: list[RecurringEntity] = []
    while eligible and len(selected) < count:
        weights = [1 / (1 + item.appearance_count * repeated_penalty) for item in eligible]
        chosen = rng.choices(eligible, weights=weights, k=1)[0]
        selected.append(chosen)
        eligible.remove(chosen)
    return selected

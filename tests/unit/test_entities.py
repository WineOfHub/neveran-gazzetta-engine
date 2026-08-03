import random
from uuid import uuid4

from neveran_gazzetta.domain.models import RecurringEntity
from neveran_gazzetta.generation.entities import select_recurring_entities


def _entity(name: str, *, appearances: int, cooldown: int | None = None) -> RecurringEntity:
    return RecurringEntity(
        id=uuid4(),
        kind="journalist",
        display_name=name,
        normalized_key=name.casefold(),
        summary="Firma del CCIN.",
        recurring=True,
        appearance_count=appearances,
        cooldown_until_issue=cooldown,
    )


def test_cooldown_esclude_entita_e_non_duplica_selezione() -> None:
    entities = [
        _entity("Ada", appearances=10, cooldown=5),
        _entity("Berto", appearances=1),
        _entity("Cora", appearances=2),
    ]

    selected = select_recurring_entities(
        entities,
        issue_number=4,
        count=2,
        repeated_penalty=0.25,
        rng=random.Random(1),
    )

    assert {item.display_name for item in selected} == {"Berto", "Cora"}

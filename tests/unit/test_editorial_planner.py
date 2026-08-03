from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from neveran_gazzetta.config import load_config
from neveran_gazzetta.domain.models import ReportingMode, StorylineMemory
from neveran_gazzetta.generation.editorial_planner import SLOTS, plan_edition

ROOT = Path(__file__).resolve().parents[2]


def _storyline(appearance_count: int = 1) -> StorylineMemory:
    return StorylineMemory(
        id=uuid4(),
        title="Il mercato scomparso",
        status="active",
        recap="Un mercato locale ha cambiato sede senza avvisare i clienti.",
        involved_entities=(),
        location="Clovertia",
        reporting_mode="reported_event",
        appearance_count=appearance_count,
        first_issue=1,
        last_issue=1,
        fingerprint="a" * 64,
    )


def test_piano_e_riproducibile_e_completo() -> None:
    config = load_config(ROOT, environment={"ENVIRONMENT": "test"})
    kwargs = {
        "schedule_slot": datetime(2026, 8, 3, 4, 0, tzinfo=UTC),
        "issue_number": 2,
        "corpus_release_id": "release-a",
        "policy_hash": config.policy_hash,
        "policy": config.editorial,
        "storylines": [_storyline()],
    }

    first = plan_edition(**kwargs)
    second = plan_edition(**kwargs)

    assert first == second
    assert tuple(slot.slot for slot in first.slots) == SLOTS
    assert len({slot.slot for slot in first.slots}) == 9


def test_migliaia_di_seed_non_superano_una_fake() -> None:
    config = load_config(ROOT, environment={"ENVIRONMENT": "test"})
    new_storyline_total = 0

    for issue in range(1, 1001):
        plan = plan_edition(
            schedule_slot=datetime(2026, 8, 1, 4, 0, tzinfo=UTC),
            issue_number=issue,
            corpus_release_id="release-a",
            policy_hash=config.policy_hash,
            policy=config.editorial,
            storylines=[],
            nonce=str(issue),
        )
        fake_slots = [
            slot.slot
            for slot in plan.slots
            if slot.reporting_mode == ReportingMode.INTENTIONAL_FAKE
        ]
        assert len(fake_slots) <= 1
        assert all(slot.startswith(("minor", "brief")) for slot in fake_slots)
        new_slots = [slot for slot in plan.slots if slot.start_storyline]
        assert len(new_slots) <= 2
        assert all(
            slot.slot.split("-", 1)[0] in {"lead", "major", "minor", "brief"}
            for slot in new_slots
        )
        assert all(
            slot.reporting_mode != ReportingMode.INTENTIONAL_FAKE for slot in new_slots
        )
        new_storyline_total += len(new_slots)
    assert new_storyline_total > 0


def test_storyline_non_appare_due_volte_nello_stesso_piano() -> None:
    config = load_config(ROOT, environment={"ENVIRONMENT": "test"})
    storylines = [_storyline(), _storyline()]
    plan = plan_edition(
        schedule_slot=datetime(2026, 8, 3, 4, 0, tzinfo=UTC),
        issue_number=2,
        corpus_release_id="release-a",
        policy_hash=config.policy_hash,
        policy=config.editorial,
        storylines=storylines,
        nonce="forza-continuazioni",
    )
    ids = [slot.storyline_id for slot in plan.slots if slot.storyline_id]

    assert len(ids) == len(set(ids))


def test_continuazione_conserva_modalita_e_slot_compatibile() -> None:
    config = load_config(ROOT, environment={"ENVIRONMENT": "test"})
    storyline = _storyline().model_copy(
        update={"reporting_mode": ReportingMode.SATIRICAL_REPORT}
    )
    assigned = []
    for nonce in range(100):
        plan = plan_edition(
            schedule_slot=datetime(2026, 8, 3, 4, 0, tzinfo=UTC),
            issue_number=2,
            corpus_release_id="release-a",
            policy_hash=config.policy_hash,
            policy=config.editorial,
            storylines=[storyline],
            nonce=f"satira-{nonce}",
        )
        assigned = [slot for slot in plan.slots if slot.storyline_id == storyline.id]
        if assigned:
            break

    assert assigned
    assert assigned[0].reporting_mode == ReportingMode.SATIRICAL_REPORT
    assert assigned[0].slot.startswith(("minor", "brief"))

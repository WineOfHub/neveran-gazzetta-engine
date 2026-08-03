from __future__ import annotations

import hashlib
import random
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from neveran_gazzetta.config import EditorialPolicy
from neveran_gazzetta.domain.models import ReportingMode, StorylineMemory

SLOTS = (
    "breaking-1",
    "breaking-2",
    "breaking-3",
    "lead",
    "major-1",
    "major-2",
    "minor-1",
    "minor-2",
    "brief",
)


class PlannedSlot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    slot: str
    reporting_mode: ReportingMode
    storyline_id: UUID | None = None
    storyline_appearance: int | None = None
    storyline_epilogue: bool = False
    start_storyline: bool = False


class EditionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    seed: str
    schedule_slot: datetime
    corpus_release_id: str
    policy_version: str
    slots: tuple[PlannedSlot, ...]


def build_seed(
    schedule_slot: datetime,
    corpus_release_id: str,
    policy_hash: str,
    nonce: str = "v1",
) -> str:
    payload = "|".join(
        (schedule_slot.isoformat(), corpus_release_id, policy_hash, nonce)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _weighted_mode(
    slot_kind: str,
    policy: EditorialPolicy,
    rng: random.Random,
    *,
    fake_already_used: bool,
) -> ReportingMode:
    weights_model = getattr(policy.reporting_mode_weights, slot_kind)
    raw = weights_model.model_dump()
    if fake_already_used:
        raw[ReportingMode.INTENTIONAL_FAKE.value] = 0.0
    population = [ReportingMode(key) for key, value in raw.items() if value > 0]
    weights = [raw[item.value] for item in population]
    return rng.choices(population, weights, k=1)[0]


def _select_storylines(
    storylines: list[StorylineMemory],
    *,
    issue_number: int,
    now: datetime,
    policy: EditorialPolicy,
    rng: random.Random,
) -> list[tuple[StorylineMemory, bool]]:
    ordinary = [
        item
        for item in storylines
        if item.appearance_count < policy.storylines.max_appearances_including_first
        and item.status.value in {"active", "cooling"}
        and (item.next_eligible_at is None or item.next_eligible_at <= now)
        and (item.last_issue is None or item.last_issue < issue_number)
    ]
    epilogues = [
        item
        for item in storylines
        if item.status.value == "closed"
        and not item.epilogue_used
        and (item.next_eligible_at is None or item.next_eligible_at <= now)
        and (item.last_issue is None or item.last_issue < issue_number)
    ]
    rng.shuffle(ordinary)
    rng.shuffle(epilogues)
    selected: list[tuple[StorylineMemory, bool]] = []
    for item in ordinary:
        if len(selected) >= policy.storylines.max_continuations_per_edition:
            break
        if rng.random() <= policy.storylines.continuation_probability:
            selected.append((item, False))
    for item in epilogues:
        if len(selected) >= policy.storylines.max_continuations_per_edition:
            break
        if rng.random() <= policy.storylines.epilogue_probability:
            selected.append((item, True))
    return selected


def plan_edition(
    *,
    schedule_slot: datetime,
    issue_number: int,
    corpus_release_id: str,
    policy_hash: str,
    policy: EditorialPolicy,
    storylines: list[StorylineMemory],
    nonce: str = "v1",
) -> EditionPlan:
    seed = build_seed(schedule_slot, corpus_release_id, policy_hash, nonce)
    rng = random.Random(int(seed, 16))
    selected_storylines = _select_storylines(
        storylines,
        issue_number=issue_number,
        now=schedule_slot,
        policy=policy,
        rng=rng,
    )
    continuation_slots = ["major-1", "major-2", "minor-1", "minor-2", "brief"]
    rng.shuffle(continuation_slots)
    storyline_by_slot: dict[str, tuple[StorylineMemory, bool]] = {}
    fake_storyline_assigned = False
    for selected_entry in selected_storylines:
        selected_storyline = selected_entry[0]
        if selected_storyline.reporting_mode == ReportingMode.INTENTIONAL_FAKE:
            if fake_storyline_assigned:
                continue
            fake_storyline_assigned = True
        allowed_kinds = (
            {"minor", "brief"}
            if selected_storyline.reporting_mode
            in {ReportingMode.SATIRICAL_REPORT, ReportingMode.INTENTIONAL_FAKE}
            else {"major", "minor", "brief"}
        )
        compatible = [
            slot for slot in continuation_slots if slot.split("-", 1)[0] in allowed_kinds
        ]
        if not compatible:
            continue
        chosen_slot = compatible[0]
        storyline_by_slot[chosen_slot] = selected_entry
        continuation_slots.remove(chosen_slot)

    fake_used = fake_storyline_assigned
    new_storylines = 0
    slots: list[PlannedSlot] = []
    for slot in SLOTS:
        slot_kind = slot.split("-", 1)[0]
        storyline_entry = storyline_by_slot.get(slot)
        storyline = storyline_entry[0] if storyline_entry else None
        is_epilogue = storyline_entry[1] if storyline_entry else False
        mode = (
            storyline.reporting_mode
            if storyline
            else _weighted_mode(slot_kind, policy, rng, fake_already_used=fake_used)
        )
        fake_used = fake_used or mode == ReportingMode.INTENTIONAL_FAKE
        can_start_storyline = (
            storyline is None
            and slot_kind in {"lead", "major", "minor", "brief"}
            and mode != ReportingMode.INTENTIONAL_FAKE
            and new_storylines < policy.storylines.max_new_storylines_per_edition
        )
        start_storyline = (
            can_start_storyline
            and rng.random() <= policy.storylines.new_storyline_probability
        )
        new_storylines += int(start_storyline)
        slots.append(
            PlannedSlot(
                slot=slot,
                reporting_mode=mode,
                storyline_id=storyline.id if storyline else None,
                storyline_appearance=(5 if is_epilogue else storyline.appearance_count + 1)
                if storyline
                else None,
                storyline_epilogue=is_epilogue,
                start_storyline=start_storyline,
            )
        )
    return EditionPlan(
        seed=seed,
        schedule_slot=schedule_slot,
        corpus_release_id=corpus_release_id,
        policy_version=policy.policy_version,
        slots=tuple(slots),
    )

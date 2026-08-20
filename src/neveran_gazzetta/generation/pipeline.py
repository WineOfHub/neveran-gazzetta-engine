from __future__ import annotations

import hashlib
import json
import random
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol, TypeVar
from uuid import UUID, uuid5

from pydantic import BaseModel, ValidationError

from neveran_gazzetta.application.contracts import JobLease, PreparedRun
from neveran_gazzetta.application.editorial_state import EditorialState, EditorialStateProvider
from neveran_gazzetta.artwork.contracts import ArtworkGenerationPort
from neveran_gazzetta.artwork.prompt import build_artwork_brief
from neveran_gazzetta.config import AppConfig
from neveran_gazzetta.domain.errors import (
    ArtworkGenerationFailed,
    ConfigurationError,
    InvalidGeneration,
    ProviderQuota,
    ReleaseMismatch,
)
from neveran_gazzetta.domain.models import (
    ArticleImportance,
    CanonRelation,
    DiegeticSource,
    EventClaim,
    EventEntity,
    GazzettaArticle,
    GazzettaEditionSnapshot,
    GazzettaEvent,
    GazzettaImage,
    RecurringEntity,
    StorylineMemory,
    StorylineStatus,
)
from neveran_gazzetta.generation.editorial_planner import EditionPlan, plan_edition
from neveran_gazzetta.generation.entities import select_recurring_entities
from neveran_gazzetta.generation.guardrails import normalize_loop_usage, validate_event_set
from neveran_gazzetta.generation.models import (
    ArticleDraft,
    EditionDraftResponse,
    EventPlanResponse,
    GroqJsonResult,
    VerifierOutcome,
    VerifierVerdict,
)
from neveran_gazzetta.generation.names import (
    normalize_invented_person_name,
    replace_person_names,
    select_newsroom_bylines,
)
from neveran_gazzetta.generation.prompts import PromptRepository
from neveran_gazzetta.generation.rate_limits import parse_rate_limit_reset
from neveran_gazzetta.generation.storylines import advance_storyline, storyline_fingerprint
from neveran_gazzetta.generation.validators import (
    truncate_to_word_limit,
    validate_edition,
    word_count,
)
from neveran_gazzetta.retrieval.core_adapter import GazzettaRetrievalAdapter
from neveran_gazzetta.retrieval.palette import GazzettaLorePalette
from neveran_gazzetta.retrieval.service import EditorialRetrievalService

_ENTITY_NAMESPACE = UUID("72ff51ee-d418-48bb-a4d8-2d1f87498528")
_TPM_TOO_LARGE = re.compile(r"tokens per minute \(TPM\): Limit (\d+), Requested (\d+)")
_TPM_SAFETY_MARGIN = 150
_MIN_COMPLETION_TOKENS = 500
ModelT = TypeVar("ModelT", bound=BaseModel)
class GroqPort(Protocol):
    def complete_json(
        self,
        *,
        model: str,
        system_prompt: str,
        user_payload: dict[str, object],
        schema_name: str,
        schema: dict[str, Any],
        max_tokens: int,
        strict: bool,
    ) -> GroqJsonResult: ...


def _content_hash(snapshot: GazzettaEditionSnapshot) -> str:
    payload = json.dumps(
        snapshot.model_dump(mode="json", by_alias=True),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _new_storyline_id(event: GazzettaEvent) -> UUID:
    return uuid5(_ENTITY_NAMESPACE, f"storyline:{event.id}")


def _bounded_label(value: str, *, max_characters: int) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= max_characters:
        return normalized
    prefix = normalized[:max_characters]
    return prefix.rsplit(" ", 1)[0] or prefix


def _minimum_source_reliability(slot: str, reporting_mode: str) -> float:
    if reporting_mode == "intentional_fake":
        return 0.0
    return 0.75 if slot.split("-", 1)[0] in {"breaking", "lead", "major"} else 0.55


def _materialize_events(
    response: EventPlanResponse,
    plan: EditionPlan,
) -> tuple[GazzettaEvent, ...]:
    planned = {slot.slot: slot for slot in plan.slots}
    events: list[GazzettaEvent] = []
    for draft in response.events:
        event_id = uuid5(
            _ENTITY_NAMESPACE,
            f"event:{plan.schedule_slot.isoformat()}:{draft.slot}",
        )
        replacements: dict[str, str] = {}
        entities: list[EventEntity] = []
        for index, entity in enumerate(draft.entities):
            name = " ".join(entity.name.split())
            replaced_name: str | None = None
            if entity.invented:
                name, replaced_name = normalize_invented_person_name(
                    name,
                    seed=f"{event_id}:{index}",
                )
            if replaced_name:
                replacements[replaced_name] = name
            entities.append(
                EventEntity(
                    entity_id=entity.entity_id,
                    name=_bounded_label(name, max_characters=100),
                    kind=_bounded_label(entity.kind, max_characters=40),
                    invented=entity.invented,
                    recurring_candidate=entity.recurring_candidate,
                )
            )
        headline = normalize_loop_usage(
            replace_person_names(draft.headline_seed, replacements)
        )
        summary = normalize_loop_usage(
            replace_person_names(draft.event_summary, replacements)
        )
        events.append(
            GazzettaEvent(
                id=event_id,
                slot=draft.slot,
                headline_seed=headline,
                event_summary=summary,
                location=draft.location,
                occurred_at=plan.schedule_slot,
                canon_relation=(
                    CanonRelation.DELIBERATELY_FALSE_CLAIM
                    if planned[draft.slot].reporting_mode.value == "intentional_fake"
                    else CanonRelation.COMPATIBLE_EPHEMERAL
                ),
                reporting_mode=planned[draft.slot].reporting_mode,
                storyline_id=planned[draft.slot].storyline_id,
                storyline_appearance=planned[draft.slot].storyline_appearance,
                storyline_candidate=planned[draft.slot].start_storyline,
                entities=tuple(entities),
                diegetic_sources=tuple(
                    DiegeticSource(
                        name=_bounded_label(
                            replace_person_names(source.name, replacements),
                            max_characters=100,
                        ),
                        kind=_bounded_label(source.kind, max_characters=40),
                        reliability=max(
                            source.reliability,
                            _minimum_source_reliability(
                                draft.slot,
                                planned[draft.slot].reporting_mode.value,
                            ),
                        ),
                    )
                    for source in draft.diegetic_sources
                ),
                lore_chunk_ids=draft.lore_chunk_ids,
                claims=(
                    EventClaim(
                        text=summary,
                        lore_chunk_ids=draft.lore_chunk_ids,
                        grounded=True,
                    ),
                ),
                risk_flags=(),
            )
        )
    return tuple(events)


def _event_payloads(events: tuple[GazzettaEvent, ...]) -> tuple[dict[str, object], ...]:
    payloads: list[dict[str, object]] = []
    for event in events:
        payload = event.model_dump(mode="json", by_alias=True)
        if event.storyline_candidate:
            payload["storylineId"] = str(_new_storyline_id(event))
            payload["storylineAppearance"] = 1
        payloads.append(payload)
    return tuple(payloads)


def _writer_event_payload(event: GazzettaEvent) -> dict[str, object]:
    """Contesto narrativo essenziale; omette i metadati tecnici già validati."""

    return {
        "slot": event.slot,
        "headlineSeed": event.headline_seed,
        "eventSummary": event.event_summary,
        "location": event.location,
        "reportingMode": event.reporting_mode.value,
        "entities": [
            {"name": entity.name, "kind": entity.kind} for entity in event.entities
        ],
        "diegeticSources": [
            {
                "name": source.name,
                "kind": source.kind,
                "reliability": source.reliability,
            }
            for source in event.diegetic_sources
        ],
        "loreChunkIds": list(event.lore_chunk_ids),
    }


def _newsroom_bylines(issue_number: int, config: AppConfig) -> tuple[str, ...]:
    policy = config.editorial.recurring_entities
    return select_newsroom_bylines(
        issue_number,
        policy.journalist_core_names,
        policy.journalist_core_per_edition,
    )


def _materialize_article(
    draft: ArticleDraft,
    *,
    importance: ArticleImportance,
    article_id: str,
    byline: str,
    config: AppConfig,
    fallback: GazzettaArticle | None = None,
) -> GazzettaArticle:
    budget = getattr(config.editorial.slot_budgets, importance.value)
    paragraphs: list[str] = []
    for index, item in enumerate(draft.paragraphs):
        paragraph = truncate_to_word_limit(
            normalize_loop_usage(item),
            budget.paragraph_max_words,
        )
        if (
            word_count(paragraph) < budget.paragraph_min_words
            and fallback is not None
            and index < len(fallback.paragraphs)
            and word_count(fallback.paragraphs[index]) >= budget.paragraph_min_words
        ):
            paragraph = truncate_to_word_limit(
                fallback.paragraphs[index],
                budget.paragraph_max_words,
            )
        paragraphs.append(paragraph)
    return GazzettaArticle(
        id=article_id,
        category=_bounded_label(
            normalize_loop_usage(draft.category),
            max_characters=config.editorial.slot_budgets.category.max_characters,
        ),
        byline=_bounded_label(byline, max_characters=80),
        title=_bounded_label(
            normalize_loop_usage(draft.title),
            max_characters=budget.title_max_characters,
        ),
        kicker=(
            _bounded_label(
                normalize_loop_usage(draft.kicker),
                max_characters=config.editorial.slot_budgets.kicker.max_characters,
            )
            if draft.kicker
            else None
        ),
        summary=truncate_to_word_limit(
            normalize_loop_usage(draft.summary),
            budget.summary_max_words,
        ),
        paragraphs=tuple(paragraphs),
        importance=importance,
        pull_quote=(
            truncate_to_word_limit(
                normalize_loop_usage(draft.pull_quote),
                budget.pull_quote_max_words,
            )
            if draft.pull_quote and budget.pull_quote_max_words is not None
            else None
        ),
    )


def _materialize_edition(
    response: EditionDraftResponse,
    *,
    issue_number: int,
    publication_date: datetime,
    config: AppConfig,
    fallback: GazzettaEditionSnapshot | None = None,
) -> GazzettaEditionSnapshot:
    draft = response.edition
    bylines = _newsroom_bylines(issue_number, config)
    edition_id = uuid5(
        _ENTITY_NAMESPACE,
        f"edition:{issue_number}:{publication_date.isoformat()}",
    )
    fallback_articles = (
        {article.id: article for article in fallback.articles}
        if fallback is not None
        else {}
    )
    articles = tuple(
        _materialize_article(
            item,
            importance=ArticleImportance.MAJOR,
            article_id=f"major-{index + 1}",
            byline=bylines[(index + 1) % len(bylines)],
            config=config,
            fallback=fallback_articles.get(f"major-{index + 1}"),
        )
        for index, item in enumerate(draft.major_articles)
    ) + tuple(
        _materialize_article(
            item,
            importance=ArticleImportance.MINOR,
            article_id=f"minor-{index + 1}",
            byline=bylines[(index + 3) % len(bylines)],
            config=config,
            fallback=fallback_articles.get(f"minor-{index + 1}"),
        )
        for index, item in enumerate(draft.minor_articles)
    ) + (
        _materialize_article(
            draft.brief_article,
            importance=ArticleImportance.BRIEF,
            article_id="brief-1",
            byline=bylines[5 % len(bylines)],
            config=config,
            fallback=fallback_articles.get("brief-1"),
        ),
    )
    return GazzettaEditionSnapshot(
        id=edition_id,
        slug=f"gazzetta-{issue_number}-{edition_id.hex[:8]}",
        issue_number=issue_number,
        publication_date=publication_date,
        masthead_subtitle=_bounded_label(
            normalize_loop_usage(draft.masthead_subtitle),
            max_characters=160,
        ),
        location_label=_bounded_label(draft.location_label, max_characters=100),
        breaking_news=tuple(
            _bounded_label(
                normalize_loop_usage(item),
                max_characters=config.editorial.slot_budgets.breaking.max_characters,
            )
            for item in draft.breaking_news
        ),
        lead_article=_materialize_article(
            draft.lead_article,
            importance=ArticleImportance.LEAD,
            article_id="lead-1",
            byline=bylines[0],
            config=config,
            fallback=fallback.lead_article if fallback is not None else None,
        ),
        articles=articles,
        editorial_quote=truncate_to_word_limit(
            normalize_loop_usage(draft.editorial_quote),
            config.editorial.slot_budgets.editorial_quote.max_words,
        ),
        closing_motto=truncate_to_word_limit(
            normalize_loop_usage(draft.closing_motto),
            config.editorial.slot_budgets.closing_motto.max_words,
        ),
    )


def _assert_plan_alignment(plan: EditionPlan, events: tuple[GazzettaEvent, ...]) -> None:
    planned = {slot.slot: slot for slot in plan.slots}
    for event in events:
        slot = planned[event.slot]
        if event.reporting_mode != slot.reporting_mode:
            raise InvalidGeneration(f"Reporting mode non allineato nello slot {event.slot}")
        if event.storyline_id != slot.storyline_id:
            raise InvalidGeneration(f"Storyline non allineata nello slot {event.slot}")
        if event.storyline_appearance != slot.storyline_appearance:
            raise InvalidGeneration(f"Apparizione storyline non allineata in {event.slot}")
        if event.storyline_candidate != slot.start_storyline:
            raise InvalidGeneration(f"Avvio storyline non allineato nello slot {event.slot}")


def _storyline_updates(
    plan: EditionPlan,
    events: tuple[GazzettaEvent, ...],
    existing: tuple[StorylineMemory, ...],
    *,
    issue_number: int,
) -> tuple[dict[str, object], ...]:
    by_id = {item.id: item for item in existing}
    existing_fingerprints = {item.fingerprint for item in existing}
    planned = {slot.slot: slot for slot in plan.slots}
    updates: list[dict[str, object]] = []
    for event in events:
        gap_seed = hashlib.sha256(f"{plan.seed}:{event.slot}".encode()).hexdigest()
        gap_editions = 1 + int(gap_seed[:2], 16) % 3
        if event.storyline_candidate:
            entity_names = [entity.name for entity in event.entities]
            fingerprint = storyline_fingerprint(
                event.headline_seed,
                event.location,
                entity_names,
            )
            if fingerprint in existing_fingerprints:
                raise InvalidGeneration("La nuova storyline duplica un filone esistente")
            existing_fingerprints.add(fingerprint)
            created = StorylineMemory(
                id=_new_storyline_id(event),
                title=event.headline_seed,
                status=StorylineStatus.COOLING,
                recap=event.event_summary,
                open_hook=event.headline_seed,
                involved_entities=event.entities,
                location=event.location,
                reporting_mode=event.reporting_mode,
                appearance_count=1,
                first_issue=issue_number,
                last_issue=issue_number,
                next_eligible_at=plan.schedule_slot + timedelta(days=2 * gap_editions),
                fingerprint=fingerprint,
            )
            updates.append(created.model_dump(mode="json", by_alias=True))
            continue
        if event.storyline_id is None:
            continue
        storyline = by_id.get(event.storyline_id)
        if storyline is None:
            raise InvalidGeneration("Storyline generata non presente nel ledger")
        slot = planned[event.slot]
        updated = advance_storyline(
            storyline,
            recap=event.event_summary,
            issue_number=issue_number,
            next_eligible_at=plan.schedule_slot + timedelta(days=2 * gap_editions),
            close=event.storyline_appearance == 4,
            epilogue=slot.storyline_epilogue,
        )
        updates.append(updated.model_dump(mode="json", by_alias=True))
    return tuple(updates)


def _entity_updates(
    events: tuple[GazzettaEvent, ...],
    existing: tuple[RecurringEntity, ...],
    edition: GazzettaEditionSnapshot,
    *,
    issue_number: int,
    cooldown_issues: int,
) -> tuple[dict[str, object], ...]:
    by_key = {(item.kind, item.normalized_key): item for item in existing}
    articles = (edition.lead_article, *edition.articles)
    byline_names = {item.byline.casefold().strip(): item.byline for item in articles}
    seen: set[tuple[str, str]] = set()
    updates: list[dict[str, object]] = []
    for event in events:
        for entity in event.entities:
            key = (entity.kind.casefold().strip(), entity.name.casefold().strip())
            if key in seen:
                continue
            seen.add(key)
            previous = by_key.get(key)
            entity_id = (
                previous.id
                if previous
                else uuid5(_ENTITY_NAMESPACE, ":".join(key))
            )
            updated = RecurringEntity(
                id=entity_id,
                kind=key[0],
                display_name=entity.name,
                normalized_key=key[1],
                summary=event.event_summary[:500],
                recurring=(
                    previous.recurring
                    if previous
                    else entity.recurring_candidate
                    or (key[0] == "journalist" and key[1] in byline_names)
                ),
                appearance_count=(previous.appearance_count if previous else 0) + 1,
                first_issue=previous.first_issue if previous else issue_number,
                last_issue=issue_number,
                cooldown_until_issue=issue_number + cooldown_issues + 1,
                retired_at=previous.retired_at if previous else None,
            )
            updates.append(updated.model_dump(mode="json", by_alias=True))
    for normalized_name, display_name in byline_names.items():
        key = ("journalist", normalized_name)
        if key in seen:
            continue
        previous = by_key.get(key)
        updated = RecurringEntity(
            id=previous.id if previous else uuid5(_ENTITY_NAMESPACE, ":".join(key)),
            kind="journalist",
            display_name=display_name,
            normalized_key=normalized_name,
            summary="Firma della redazione ricorrente del CCIN.",
            recurring=True,
            appearance_count=(previous.appearance_count if previous else 0) + 1,
            first_issue=previous.first_issue if previous else issue_number,
            last_issue=issue_number,
            cooldown_until_issue=issue_number + cooldown_issues + 1,
            retired_at=previous.retired_at if previous else None,
        )
        updates.append(updated.model_dump(mode="json", by_alias=True))
    return tuple(updates)


def _select_prompt_entities(
    state: EditorialState,
    plan: EditionPlan,
    config: AppConfig,
) -> tuple[RecurringEntity, ...]:
    policy = config.editorial.recurring_entities
    journalists = [item for item in state.recurring_entities if item.kind == "journalist"]
    others = [item for item in state.recurring_entities if item.kind != "journalist"]
    selected_journalists = select_recurring_entities(
        journalists,
        issue_number=state.next_issue_number,
        count=policy.journalist_core_per_edition,
        repeated_penalty=policy.repeated_npc_penalty,
        rng=random.Random(int(plan.seed[:32], 16)),
    )
    selected_others = select_recurring_entities(
        others,
        issue_number=state.next_issue_number,
        count=policy.other_entities_per_edition,
        repeated_penalty=policy.repeated_npc_penalty,
        rng=random.Random(int(plan.seed[32:], 16)),
    )
    return tuple((*selected_journalists, *selected_others))


def _planner_policy_payload(config: AppConfig) -> dict[str, object]:
    """Espone al planner solo le regole che deve applicare agli eventi.

    Budget tipografici, pesi già risolti nello slot plan, retention e artwork
    appartengono ad altre fasi e consumerebbero inutilmente il TPM Groq.
    """

    policy = config.editorial
    return {
        "language": policy.language,
        "edition": {
            "max_intentional_fake_per_edition": (
                policy.edition.max_intentional_fake_per_edition
            ),
            "require_intentional_fake": policy.edition.require_intentional_fake,
        },
        "truth_rules": policy.truth_rules.model_dump(mode="json"),
        "invention_rules": policy.invention_rules.model_dump(mode="json"),
        "loop_rule": policy.loop_rule.model_dump(mode="json"),
        "storylines": {
            "max_appearances_including_first": (
                policy.storylines.max_appearances_including_first
            ),
            "max_appearances_per_edition": policy.storylines.max_appearances_per_edition,
            "max_new_storylines_per_edition": policy.storylines.max_new_storylines_per_edition,
        },
    }


class GazzettaGenerationPipeline:
    def __init__(
        self,
        *,
        config: AppConfig,
        state_provider: EditorialStateProvider,
        retrieval_adapter: GazzettaRetrievalAdapter,
        retrieval_service: EditorialRetrievalService,
        groq: GroqPort,
        prompts_root: Path,
        artwork_generator: ArtworkGenerationPort | None = None,
    ) -> None:
        self._config = config
        self._state_provider = state_provider
        self._retrieval_adapter = retrieval_adapter
        self._retrieval_service = retrieval_service
        self._groq = groq
        self._prompts = PromptRepository(prompts_root)
        self._artwork_generator = artwork_generator

    def _call(
        self,
        calls: list[GroqJsonResult],
        *,
        model: str,
        prompt_file: str,
        user_payload: dict[str, object],
        response_model: type[ModelT],
        max_tokens: int,
        strict: bool,
    ) -> ModelT:
        if calls:
            remaining = calls[-1].rate_limits.get("x-ratelimit-remaining-tokens")
            try:
                remaining_tokens = int(str(remaining)) if remaining is not None else None
            except ValueError:
                remaining_tokens = None
            if remaining_tokens is not None and remaining_tokens < max_tokens:
                reset = calls[-1].rate_limits.get("x-ratelimit-reset-tokens")
                retry_after = parse_rate_limit_reset(reset)
                max_wait = self._config.runtime.generation.max_rate_limit_wait_seconds
                if retry_after is None or retry_after > max_wait:
                    raise ProviderQuota(
                        "Token Groq residui insufficienti per la prossima fase",
                        retry_after_seconds=retry_after,
                    )
                time.sleep(retry_after + 0.05)
        prompt = self._prompts.load(prompt_file)
        result: GroqJsonResult | None = None
        effective_max_tokens = max_tokens
        for attempt in range(2):
            try:
                result = self._groq.complete_json(
                    model=model,
                    system_prompt=prompt.content,
                    user_payload=user_payload,
                    schema_name=prompt.name.replace("-", "_"),
                    schema=response_model.model_json_schema(
                        by_alias=True,
                        mode="serialization",
                    ),
                    max_tokens=effective_max_tokens,
                    strict=strict,
                )
                break
            except ProviderQuota as exc:
                retry_after = exc.retry_after_seconds
                max_wait = self._config.runtime.generation.max_rate_limit_wait_seconds
                if attempt == 1 or retry_after is None or retry_after > max_wait:
                    raise
                time.sleep(retry_after + 0.05)
            except InvalidGeneration as exc:
                match = _TPM_TOO_LARGE.search(str(exc))
                if attempt == 1 or match is None:
                    raise
                limit, requested = int(match.group(1)), int(match.group(2))
                overflow = requested - limit
                effective_max_tokens = max(
                    effective_max_tokens - overflow - _TPM_SAFETY_MARGIN,
                    _MIN_COMPLETION_TOKENS,
                )
        assert result is not None
        calls.append(result)
        try:
            return response_model.model_validate(result.payload)
        except ValidationError as exc:
            raise InvalidGeneration(f"Output {prompt.name} non conforme allo schema") from exc

    def _planner_payload(
        self,
        plan: EditionPlan,
        palette: GazzettaLorePalette,
        state: EditorialState,
        recurring_entities: tuple[RecurringEntity, ...],
    ) -> dict[str, object]:
        return {
            "slotPlan": plan.model_dump(mode="json"),
            "lorePalette": palette.model_dump(mode="json"),
            "editorialPolicy": _planner_policy_payload(self._config),
            "storylines": [
                item.model_dump(mode="json", by_alias=True) for item in state.storylines
            ],
            "recurringEntities": [
                item.model_dump(mode="json", by_alias=True)
                for item in recurring_entities
            ],
        }

    def execute(self, lease: JobLease) -> PreparedRun:
        started = time.monotonic()
        if lease.policy_version != self._config.editorial.policy_version:
            raise ConfigurationError(
                "La policy del job non coincide con quella installata nel worker"
            )
        planner_model = (
            self._config.secrets.planner_model
            or self._config.runtime.generation.planner_model_default
        )
        writer_model = (
            self._config.secrets.writer_model
            or self._config.runtime.generation.writer_model_default
        )
        verifier_model = (
            self._config.secrets.verifier_model
            or self._config.runtime.generation.verifier_model_default
        )
        state = self._state_provider.get_editorial_state()
        release_id = self._retrieval_adapter.active_release_id()
        plan = plan_edition(
            schedule_slot=lease.schedule_slot,
            issue_number=state.next_issue_number,
            corpus_release_id=release_id,
            policy_hash=self._config.policy_hash,
            policy=self._config.editorial,
            storylines=list(state.storylines),
        )
        prompt_entities = _select_prompt_entities(state, plan, self._config)
        palette = self._retrieval_service.retrieve_palette(
            plan,
            storylines=list(state.storylines),
            topic_hints=list(state.topic_hints),
        )
        if palette.corpus_release_id != release_id:
            raise ReleaseMismatch("La palette non usa la release pianificata")

        calls: list[GroqJsonResult] = []
        planner_prompt = self._prompts.load("event_planner.system.md")
        writer_prompt = self._prompts.load("newspaper_writer.system.md")
        verifier_prompt = self._prompts.load("verifier.system.md")
        repair_prompt = self._prompts.load("repair.system.md")

        event_response = self._call(
            calls,
            model=planner_model,
            prompt_file="event_planner.system.md",
            user_payload=self._planner_payload(plan, palette, state, prompt_entities),
            response_model=EventPlanResponse,
            max_tokens=4800,
            strict=self._config.runtime.generation.structured_planner_strict,
        )
        assert isinstance(event_response, EventPlanResponse)
        events = _materialize_events(event_response, plan)
        event_issues = validate_event_set(
            list(events),
            allowed_settlement_names=frozenset(palette.settlement_names),
        )
        if event_issues:
            codes = ",".join(sorted({item.code for item in event_issues}))
            raise InvalidGeneration(f"Eventi rifiutati: {codes}")
        _assert_plan_alignment(plan, events)

        writer_payload: dict[str, object] = {
            "issueContext": {
                "issueNumber": state.next_issue_number,
                "scheduleSlot": lease.schedule_slot.isoformat(),
            },
            "events": [_writer_event_payload(event) for event in events],
            "slotBudgets": self._config.editorial.slot_budgets.model_dump(mode="json"),
            "loreConstraints": list(palette.constraints),
            "terminology": list(palette.terminology),
        }
        draft_response = self._call(
            calls,
            model=writer_model,
            prompt_file="newspaper_writer.system.md",
            user_payload=writer_payload,
            response_model=EditionDraftResponse,
            max_tokens=self._config.runtime.generation.max_edition_output_tokens,
            strict=self._config.runtime.generation.structured_writer_strict,
        )
        assert isinstance(draft_response, EditionDraftResponse)
        edition = _materialize_edition(
            draft_response,
            issue_number=state.next_issue_number,
            publication_date=lease.schedule_slot,
            config=self._config,
        )
        validation = validate_edition(edition, self._config.editorial)
        if not validation.passed:
            if (
                self._config.runtime.generation.max_repair_calls != 1
                or not all(issue.repairable for issue in validation.issues)
            ):
                raise InvalidGeneration("Edizione non riparabile")
            repair_response = self._call(
                calls,
                model=writer_model,
                prompt_file="repair.system.md",
                user_payload={
                    "edition": edition.model_dump(mode="json", by_alias=True),
                    "slotBudgets": writer_payload["slotBudgets"],
                    "issues": [
                        issue.model_dump(mode="json", by_alias=True)
                        for issue in validation.issues
                    ],
                },
                response_model=EditionDraftResponse,
                max_tokens=self._config.runtime.generation.max_repair_output_tokens,
                strict=self._config.runtime.generation.structured_writer_strict,
            )
            assert isinstance(repair_response, EditionDraftResponse)
            edition = _materialize_edition(
                repair_response,
                issue_number=state.next_issue_number,
                publication_date=lease.schedule_slot,
                config=self._config,
                fallback=edition,
            )
            validation = validate_edition(edition, self._config.editorial)
            if not validation.passed:
                remaining_codes = ",".join(
                    sorted({issue.code for issue in validation.issues})
                )
                raise InvalidGeneration(
                    "La singola riparazione non ha superato i validator: "
                    f"{remaining_codes}"
                )

        verdict = self._call(
            calls,
            model=verifier_model,
            prompt_file="verifier.system.md",
            user_payload={
                "events": writer_payload["events"],
                "edition": edition.model_dump(mode="json", by_alias=True),
                "loreConstraints": list(palette.constraints),
                "sourceRefs": [item.chunk_id for item in palette.evidence],
            },
            response_model=VerifierVerdict,
            max_tokens=1200,
            strict=self._config.runtime.generation.structured_verifier_strict,
        )
        assert isinstance(verdict, VerifierVerdict)
        if verdict.outcome != VerifierOutcome.PASS:
            codes = ",".join(issue.code for issue in verdict.issues)
            raise InvalidGeneration(f"Verifier finale: {verdict.outcome.value} ({codes})")

        if len(calls) > (
            self._config.runtime.generation.max_normal_calls
            + self._config.runtime.generation.max_repair_calls
        ):
            raise InvalidGeneration("Numero chiamate Groq oltre il limite")
        token_input = sum(call.usage.input_tokens for call in calls)
        token_output = sum(call.usage.output_tokens for call in calls)
        token_limit = self._config.runtime.generation.max_total_tokens_per_edition
        if token_input + token_output > token_limit:
            raise InvalidGeneration("Budget token per edizione superato")
        if self._retrieval_adapter.active_release_id() != release_id:
            raise ReleaseMismatch("La release è cambiata durante la generazione")

        artwork_report: dict[str, object] = {"status": "disabled"}
        artwork_policy = self._config.editorial.artwork
        if artwork_policy.generation_enabled:
            if self._artwork_generator is None:
                artwork_report = {
                    "status": "static_fallback",
                    "errorCode": "artwork_adapter_missing",
                }
            else:
                brief = build_artwork_brief(
                    lease=lease,
                    edition=edition,
                    events=events,
                    palette=palette,
                    policy=artwork_policy,
                )
                try:
                    generated = self._artwork_generator.generate(brief)
                except ArtworkGenerationFailed as exc:
                    artwork_report = {
                        "status": "static_fallback",
                        "errorCode": exc.reason_code,
                        "retriable": exc.retriable,
                        "promptVersion": artwork_policy.prompt_version,
                        "promptSha256": brief.prompt_sha256,
                    }
                else:
                    image = GazzettaImage(
                        src=generated.src,
                        alt=brief.alt,
                        caption=brief.caption,
                        credit=brief.credit,
                        focal_point=brief.focal_point,
                    )
                    edition = edition.model_copy(
                        update={
                            "lead_article": edition.lead_article.model_copy(
                                update={"image": image}
                            )
                        }
                    )
                    artwork_report = {
                        "status": "generated",
                        "model": generated.model,
                        "seed": generated.seed,
                        "width": generated.width,
                        "height": generated.height,
                        "cached": generated.cached,
                        "objectKey": generated.object_key,
                        "contentSha256": generated.content_sha256,
                        "promptVersion": artwork_policy.prompt_version,
                        "promptSha256": brief.prompt_sha256,
                    }
        if self._retrieval_adapter.active_release_id() != release_id:
            raise ReleaseMismatch("La release è cambiata durante la generazione dell'artwork")

        rate_limits: dict[str, str | int | float | None] = {}
        for call in calls:
            rate_limits.update(call.rate_limits)
        prompt_versions = {
            "planner": planner_prompt.version,
            "writer": writer_prompt.version,
            "verifier": verifier_prompt.version,
            "repair": repair_prompt.version,
        }
        prompt_hashes = {
            "planner": planner_prompt.content_sha256,
            "writer": writer_prompt.content_sha256,
            "verifier": verifier_prompt.content_sha256,
            "repair": repair_prompt.content_sha256,
        }
        events_payload = _event_payloads(events)
        return PreparedRun(
            phase="publishing",
            validation_status="passed",
            corpus_release_id=release_id,
            policy_hash=self._config.policy_hash,
            prompt_versions=prompt_versions,
            prompt_hashes=prompt_hashes,
            models={
                "planner": planner_model,
                "writer": writer_model,
                "verifier": verifier_model,
            },
            token_input=token_input,
            token_output=token_output,
            groq_requests=len(calls),
            rate_limits=rate_limits,
            validation_report={"passed": True, "issues": [], "artwork": artwork_report},
            snapshot=edition.model_dump(mode="json", by_alias=True),
            events=events_payload,
            storyline_updates=_storyline_updates(
                plan,
                events,
                state.storylines,
                issue_number=state.next_issue_number,
            ),
            entity_updates=_entity_updates(
                events,
                state.recurring_entities,
                edition,
                issue_number=state.next_issue_number,
                cooldown_issues=(
                    self._config.editorial.recurring_entities.default_cooldown_issues
                ),
            ),
            content_hash=_content_hash(edition),
            duration_ms=int((time.monotonic() - started) * 1000),
        )

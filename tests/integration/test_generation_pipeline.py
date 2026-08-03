from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from neveran_gazzetta.application.contracts import JobLease
from neveran_gazzetta.application.editorial_state import EditorialState
from neveran_gazzetta.artwork.models import ArtworkBrief, GeneratedArtwork
from neveran_gazzetta.config import load_config
from neveran_gazzetta.domain.errors import (
    ArtworkGenerationFailed,
    ConfigurationError,
    InvalidGeneration,
    ProviderQuota,
)
from neveran_gazzetta.domain.models import GazzettaEvent
from neveran_gazzetta.generation.models import GroqJsonResult, TokenUsage
from neveran_gazzetta.generation.pipeline import (
    GazzettaGenerationPipeline,
    _bounded_label,
    _minimum_source_reliability,
    _newsroom_bylines,
    _planner_policy_payload,
    _writer_event_payload,
    parse_rate_limit_reset,
)
from neveran_gazzetta.retrieval.palette import GazzettaLorePalette, PaletteEvidence
from neveran_gazzetta.retrieval.queries import EditorialQuery

ROOT = Path(__file__).resolve().parents[2]


def _words(count: int) -> str:
    return " ".join(f"parola{index}" for index in range(count))


def _article(importance: str, index: int) -> dict[str, object]:
    paragraphs = {
        "lead": [_words(28), _words(28), _words(28)],
        "major": [_words(22), _words(22)],
        "minor": [_words(25)],
        "brief": [_words(25)],
    }[importance]
    return {
        "id": f"{importance}-{index}",
        "category": "Cronaca",
        "byline": f"Cronista CCIN {index % 4 + 1}",
        "title": f"Titolo {index}",
        "summary": _words(10),
        "paragraphs": paragraphs,
        "importance": importance,
        "pullQuote": _words(8) if importance in {"lead", "major"} else None,
    }


def _edition(*, valid: bool = True) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "id": str(uuid4()),
        "slug": "edizione-di-prova",
        "issueNumber": 1,
        "publicationDate": datetime.now(UTC).isoformat(),
        "mastheadSubtitle": "Cronache quotidiane da Neveran",
        "locationLabel": "CCIN",
        "breakingNews": ["Uno", "Due", "Tre"],
        "leadArticle": _article("lead", 0),
        "articles": [
            _article("major", 1),
            _article("major", 2),
            _article("minor", 3),
            _article("minor", 4),
            _article("brief", 5),
        ],
        "editorialQuote": _words(10),
        "closingMotto": _words(5 if valid else 15),
    }


def _article_draft(importance: str, index: int) -> dict[str, object]:
    article = _article(importance, index)
    return {
        key: value
        for key, value in article.items()
        if key not in {"id", "importance", "byline"}
    }


def _edition_draft(*, valid: bool = True) -> dict[str, object]:
    lead_article = _article_draft("lead", 0)
    if not valid:
        lead_article["paragraphs"] = [_words(10), _words(28), _words(28)]
    return {
        "mastheadSubtitle": "Cronache quotidiane da Neveran",
        "locationLabel": "CCIN",
        "breakingNews": ["Uno", "Due", "Tre"],
        "leadArticle": lead_article,
        "majorArticles": [
            _article_draft("major", 1),
            _article_draft("major", 2),
        ],
        "minorArticles": [
            _article_draft("minor", 3),
            _article_draft("minor", 4),
        ],
        "briefArticle": _article_draft("brief", 5),
        "editorialQuote": _words(10),
        "closingMotto": _words(5 if valid else 15),
    }


class StateProvider:
    def get_editorial_state(self) -> EditorialState:
        return EditorialState(next_issue_number=1)


class RetrievalAdapter:
    def active_release_id(self) -> str:
        return "release-a"


class RetrievalService:
    def retrieve_palette(self, _plan, *, storylines, topic_hints):
        del storylines, topic_hints
        evidence = tuple(
            PaletteEvidence(
                chunk_id=f"chunk-{index}",
                document_id=f"lore.{index}",
                section_path=("Vita",),
                excerpt="Fatto pubblico.",
                score=0.8,
                approximate_tokens=4,
            )
            for index in range(4)
        )
        return GazzettaLorePalette(
            corpus_release_id="release-a",
            queries=(EditorialQuery(purpose="daily_life", text="vita quotidiana"),),
            evidence=evidence,
            constraints=("Non inventare divinità.",),
            terminology=("Loop è un materiale.",),
            possible_source_seeds=("lore.1",),
            gaps=(),
            approximate_tokens=16,
        )


class FakeGroq:
    def __init__(self, *, invalid_writer: bool = False, reject: bool = False) -> None:
        self.invalid_writer = invalid_writer
        self.reject = reject
        self.calls: list[str] = []

    def complete_json(self, **kwargs) -> GroqJsonResult:
        self.calls.append(kwargs["schema_name"])
        if kwargs["schema_name"] == "gazzetta_event_planner":
            slots = kwargs["user_payload"]["slotPlan"]["slots"]
            events = []
            for slot in slots:
                events.append(
                    {
                        "slot": slot["slot"],
                        "headlineSeed": f"Titolo locale {slot['slot']}",
                        "eventSummary": f"Un evento locale per {slot['slot']} è stato segnalato.",
                        "location": f"Distretto {slot['slot']}",
                        "entities": [],
                        "diegeticSources": [
                            {"name": "Testimone", "kind": "persona", "reliability": 0.8}
                        ],
                        "loreChunkIds": ["chunk-1"],
                    }
                )
            payload = {"events": events}
        elif kwargs["schema_name"] == "gazzetta_newspaper_writer":
            edition = _edition_draft(valid=True)
            if self.invalid_writer:
                edition["leadArticle"]["paragraphs"][0] = _words(10)
            payload = {"edition": edition}
        elif kwargs["schema_name"] == "gazzetta_repair":
            edition = _edition_draft(valid=True)
            payload = {"edition": edition}
        else:
            payload = (
                {
                    "outcome": "reject",
                    "issues": [
                        {
                            "code": "canon_conflict",
                            "message": "Conflitto",
                            "repairable": False,
                        }
                    ],
                }
                if self.reject
                else {"outcome": "pass", "issues": []}
            )
        return GroqJsonResult(
            payload=payload,
            usage=TokenUsage(input_tokens=100, output_tokens=50),
            rate_limits={"remaining": "ok"},
        )


class LowRemainingGroq(FakeGroq):
    def __init__(self) -> None:
        super().__init__()
        self.index = 0

    def complete_json(self, **kwargs) -> GroqJsonResult:
        result = super().complete_json(**kwargs)
        self.index += 1
        return result.model_copy(
            update={
                "rate_limits": {
                    "x-ratelimit-remaining-tokens": "1" if self.index == 1 else "8000",
                    "x-ratelimit-reset-tokens": "0s",
                }
            }
        )


class OnceRateLimitedGroq(FakeGroq):
    def __init__(self) -> None:
        super().__init__()
        self.rate_limited = False

    def complete_json(self, **kwargs) -> GroqJsonResult:
        if kwargs["schema_name"] == "gazzetta_newspaper_writer" and not self.rate_limited:
            self.rate_limited = True
            raise ProviderQuota("limite temporaneo", retry_after_seconds=0)
        return super().complete_json(**kwargs)


class FakeArtwork:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.briefs: list[ArtworkBrief] = []

    def generate(self, brief: ArtworkBrief) -> GeneratedArtwork:
        self.briefs.append(brief)
        if self.fail:
            raise ArtworkGenerationFailed(
                "outage di prova",
                reason_code="provider_unavailable",
                retriable=True,
            )
        object_key = (
            f"editions/issue-{brief.issue_number:06d}-{brief.job_id}"
            "-lead-deadbeefdeadbeefdead.png"
        )
        return GeneratedArtwork(
            src=(
                "https://neveran-test.supabase.co/storage/v1/object/public/"
                f"gazzetta-artwork/{object_key}"
            ),
            object_key=object_key,
            content_sha256="a" * 64,
            model="@cf/black-forest-labs/flux-2-klein-9b",
            seed=brief.seed,
            width=1536,
            height=896,
            cached=False,
        )


def _pipeline(
    groq: FakeGroq,
    artwork: FakeArtwork | None = None,
) -> GazzettaGenerationPipeline:
    return GazzettaGenerationPipeline(
        config=load_config(ROOT, environment={"ENVIRONMENT": "test"}),
        state_provider=StateProvider(),
        retrieval_adapter=RetrievalAdapter(),
        retrieval_service=RetrievalService(),
        groq=groq,
        prompts_root=ROOT / "prompts",
        artwork_generator=artwork,
    )


def _lease() -> JobLease:
    return JobLease(
        job_id=uuid4(),
        schedule_slot=datetime(2026, 8, 1, 4, 0, tzinfo=UTC),
        attempt_number=1,
        policy_version="gazzetta-editorial-v1",
    )


def test_pipeline_normale_usa_tre_chiamate_e_prepara_publish() -> None:
    groq = FakeGroq()

    run = _pipeline(groq).execute(_lease())

    assert run.validation_status == "passed"
    assert run.groq_requests == 3
    assert len(run.policy_hash) == 64
    assert set(run.prompt_hashes) == {"planner", "writer", "verifier", "repair"}
    assert all(len(value) == 64 for value in run.prompt_hashes.values())
    assert len(run.events) == 9
    assert len({item["id"] for item in run.events}) == 9
    assert len(run.entity_updates) == 3
    snapshot = run.snapshot
    assert snapshot is not None
    articles = [snapshot["leadArticle"], *snapshot["articles"]]
    assert {article["byline"] for article in articles} == {
        "Vaeris Cartis",
        "Oryn Neral",
        "Maev Velis",
    }
    assert all(item["kind"] == "journalist" for item in run.entity_updates)
    assert all(item["recurring"] is True for item in run.entity_updates)
    assert all(item["cooldownUntilIssue"] == 3 for item in run.entity_updates)
    assert run.content_hash and len(run.content_hash) == 64


def test_pipeline_genera_immagine_dal_lead_verificato() -> None:
    artwork = FakeArtwork()

    run = _pipeline(FakeGroq(), artwork).execute(_lease())

    assert len(artwork.briefs) == 1
    assert "Neveran" in artwork.briefs[0].prompt
    assert "Non inventare divinit" in artwork.briefs[0].prompt
    assert "Never depict a newspaper" in artwork.briefs[0].prompt
    assert len(artwork.briefs[0].prompt) <= 2200
    assert run.snapshot is not None
    assert run.snapshot["leadArticle"]["image"]["src"].startswith(
        "https://neveran-test.supabase.co/storage/v1/object/public/gazzetta-artwork/"
    )
    assert run.validation_report["artwork"]["status"] == "generated"


def test_pipeline_pubblica_col_fallback_statico_se_artwork_fallisce() -> None:
    run = _pipeline(FakeGroq(), FakeArtwork(fail=True)).execute(_lease())

    assert run.snapshot is not None
    assert run.snapshot["leadArticle"]["image"] is None
    assert run.validation_report["artwork"] == {
        "status": "static_fallback",
        "errorCode": "provider_unavailable",
        "retriable": True,
        "promptVersion": "neveran-lead-artwork-v3",
        "promptSha256": run.validation_report["artwork"]["promptSha256"],
    }


def test_payload_policy_planner_esclude_configurazione_di_altre_fasi() -> None:
    config = load_config(ROOT, environment={"ENVIRONMENT": "test"})

    payload = _planner_policy_payload(config)

    assert payload["language"] == "it"
    assert "truth_rules" in payload
    assert "invention_rules" in payload
    assert "loop_rule" in payload
    assert "slot_budgets" not in payload
    assert "reporting_mode_weights" not in payload
    assert "artwork" not in payload


def test_etichetta_tecnica_viene_accorciata_sul_confine_di_parola() -> None:
    assert _bounded_label(
        "registro portuale custodito dalla corporazione locale",
        max_characters=40,
    ) == "registro portuale custodito dalla"


def test_affidabilita_minima_fonti_deriva_dalla_policy_dello_slot() -> None:
    assert _minimum_source_reliability("lead", "reported_event") == 0.75
    assert _minimum_source_reliability("minor-1", "reported_event") == 0.55
    assert _minimum_source_reliability("brief", "intentional_fake") == 0.0


def test_payload_writer_omette_metadati_tecnici() -> None:
    groq = FakeGroq()
    run = _pipeline(groq).execute(_lease())
    event = run.events[0]

    payload = _writer_event_payload(GazzettaEvent.model_validate(event))

    assert "id" not in payload
    assert "occurredAt" not in payload
    assert "claims" not in payload
    assert "storylineId" not in payload
    assert payload["slot"] == event["slot"]


def test_redazione_neveran_ruota_senza_scomparire_tra_due_numeri() -> None:
    config = load_config(ROOT, environment={"ENVIRONMENT": "test"})
    first_issue = set(_newsroom_bylines(1, config))
    second_issue = set(_newsroom_bylines(2, config))

    assert len(first_issue) == 3
    assert len(second_issue) == 3
    assert len(first_issue & second_issue) == 1
    assert first_issue != second_issue


def test_pipeline_usa_una_sola_repair_prima_del_verifier() -> None:
    groq = FakeGroq(invalid_writer=True)

    run = _pipeline(groq).execute(_lease())

    assert run.groq_requests == 4
    assert groq.calls.count("gazzetta_repair") == 1
    assert groq.calls[-1] == "gazzetta_verifier"


def test_verifier_reject_impedisce_publish() -> None:
    with pytest.raises(InvalidGeneration, match="Verifier finale"):
        _pipeline(FakeGroq(reject=True)).execute(_lease())


def test_pipeline_rifiuta_job_con_policy_diversa() -> None:
    lease = _lease().model_copy(update={"policy_version": "policy-non-installata"})

    with pytest.raises(ConfigurationError, match="policy"):
        _pipeline(FakeGroq()).execute(lease)


def test_pipeline_attende_reset_breve_senza_ripetere_il_planner(monkeypatch) -> None:
    groq = LowRemainingGroq()
    waits: list[float] = []
    monkeypatch.setattr("neveran_gazzetta.generation.pipeline.time.sleep", waits.append)

    run = _pipeline(groq).execute(_lease())

    assert run.groq_requests == 3
    assert waits == [0.05]


def test_pipeline_riprova_una_sola_volta_dopo_429_breve(monkeypatch) -> None:
    groq = OnceRateLimitedGroq()
    waits: list[float] = []
    monkeypatch.setattr("neveran_gazzetta.generation.pipeline.time.sleep", waits.append)

    run = _pipeline(groq).execute(_lease())

    assert run.groq_requests == 3
    assert groq.rate_limited is True
    assert waits == [0.05]


@pytest.mark.parametrize(
    ("header", "seconds"),
    [("2m59.56s", 179.56), ("500ms", 0.5), ("1h2m3s", 3723.0), ("4.5", 4.5)],
)
def test_parser_reset_groq_supporta_formati_documentati(header: str, seconds: float) -> None:
    assert parse_rate_limit_reset(header) == pytest.approx(seconds)

"""Caricamento tipizzato della configurazione non sensibile e dei segreti runtime."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, model_validator

from neveran_gazzetta.domain.errors import ConfigurationError

PositiveInt = Annotated[int, Field(gt=0)]
NonNegativeInt = Annotated[int, Field(ge=0)]
Probability = Annotated[float, Field(ge=0, le=1)]


class StrictModel(BaseModel):
    """Base autorevole: campi inattesi sono sempre errori."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ApplicationConfig(StrictModel):
    name: str
    service_slug: str
    environment_env: str
    log_level_env: str


class ApiConfig(StrictModel):
    host: str
    port: Annotated[int, Field(ge=1, le=65535)]
    auth_mode: Literal["enforce"]
    service_token_env: str
    expose_player_content: Literal[False]


class SchedulerConfig(StrictModel):
    timezone: str
    cadence_days: PositiveInt
    publication_hour: Annotated[int, Field(ge=0, le=23)]
    publication_minute: Annotated[int, Field(ge=0, le=59)]
    tick_interval_seconds: PositiveInt
    catch_up_policy: Literal["latest_due_only"]
    publication_timestamp_policy: Literal["actual_publish_time"]
    issue_number_policy: Literal["increment_on_publish"]


class WorkerConfig(StrictModel):
    lease_seconds: PositiveInt
    heartbeat_seconds: PositiveInt
    poll_seconds: PositiveInt
    max_job_attempts: PositiveInt
    startup_tick: bool
    account_email_env: str
    account_password_env: str

    @model_validator(mode="after")
    def heartbeat_deve_stare_nel_lease(self) -> WorkerConfig:
        if self.heartbeat_seconds >= self.lease_seconds:
            raise ValueError("heartbeat_seconds deve essere minore di lease_seconds")
        return self


class RetrievalConfig(StrictModel):
    owner_package: str
    profile: str
    purpose: Literal["generation"]
    audience: Literal["public_assistant"]
    collection_env: str
    collection_default: str
    qdrant_url_env: str
    qdrant_api_key_env: str
    embedding_provider: Literal["jina"]
    embedding_model_env: str
    embedding_model_default: str
    embedding_dimension_env: str
    embedding_dimension_default: PositiveInt
    query_task_env: str
    query_task_default: Literal["retrieval.query"]
    max_queries: PositiveInt
    top_k_per_query: PositiveInt
    max_chunks: PositiveInt
    max_chunks_per_document: PositiveInt
    context_token_budget: PositiveInt
    allow_generation_without_evidence: Literal[False]
    distinguish_no_evidence_from_outage: Literal[True]
    require_release_alignment: Literal[True]
    release_manifest_path_env: str
    min_chunks_for_edition: PositiveInt
    min_documents_for_edition: PositiveInt
    min_average_score: Annotated[float, Field(ge=0, le=1)]

    @model_validator(mode="after")
    def limiti_chunk_coerenti(self) -> RetrievalConfig:
        if self.max_chunks_per_document > self.max_chunks:
            raise ValueError("max_chunks_per_document non può superare max_chunks")
        return self


class GenerationConfig(StrictModel):
    provider: Literal["cloudflare_workers_ai", "codex_cli"]
    api_key_env: str
    planner_model_env: str
    planner_model_default: str
    writer_model_env: str
    writer_model_default: str
    verifier_model_env: str
    verifier_model_default: str
    structured_planner_strict: Literal[True]
    structured_writer_strict: Literal[True]
    structured_verifier_strict: Literal[True]
    max_normal_calls: Annotated[int, Field(ge=1, le=3)]
    max_repair_calls: Annotated[int, Field(ge=0, le=1)]
    max_total_tokens_per_edition: PositiveInt
    max_storyline_context_tokens: PositiveInt
    max_edition_output_tokens: PositiveInt
    max_repair_output_tokens: PositiveInt
    max_rate_limit_wait_seconds: PositiveInt
    rate_limit_strategy: Literal["response_headers"]
    retry_on_invalid_content: Literal[False]
    # Solo per provider: codex_cli — nessun segreto qui (a differenza di ogni
    # altro provider in questo file): il login Codex CLI vive su disco in
    # ~/.codex/, mai in un env var. Vedi generation/codex_cli.py.
    codex_executable: str | None = None
    codex_sandbox: Literal["read-only"] | None = None
    codex_timeout_seconds: PositiveInt | None = None
    codex_auth_recheck_seconds: PositiveInt | None = None
    codex_quota_cooldown_seconds: PositiveInt | None = None
    codex_reasoning_effort: Literal["minimal", "low", "medium", "high", "xhigh"] | None = None

    @model_validator(mode="after")
    def campi_codex_coerenti_col_provider(self) -> GenerationConfig:
        codex_fields = (
            self.codex_executable, self.codex_sandbox, self.codex_timeout_seconds,
            self.codex_auth_recheck_seconds, self.codex_quota_cooldown_seconds,
            self.codex_reasoning_effort,
        )
        if self.provider == "codex_cli" and any(f is None for f in codex_fields):
            raise ValueError("provider codex_cli richiede tutti i campi codex_*")
        if self.provider == "cloudflare_workers_ai" and any(f is not None for f in codex_fields):
            raise ValueError("i campi codex_* si usano solo con provider codex_cli")
        return self


class ArtworkRuntimeConfig(StrictModel):
    provider: Literal["cloudflare_workers_ai"]
    endpoint_env: str
    token_env: str
    storage_bucket: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,62}$")
    max_stored_images: Annotated[int, Field(ge=10, le=250)]
    model: Literal["@cf/black-forest-labs/flux-2-klein-9b"]
    width: Annotated[int, Field(ge=256, le=1920)]
    height: Annotated[int, Field(ge=256, le=1920)]
    request_timeout_seconds: PositiveInt
    max_retries: Literal[1]


class PublicationConfig(StrictModel):
    storage: Literal["supabase"]
    supabase_url_env: str
    supabase_anon_key_env: str
    materialize_rpc: Literal["materialize_gazzetta_edition"]
    publish_rpc: Literal["publish_next_gazzetta_edition"]
    keep_last_valid_on_failure: Literal[True]
    player_reads_directly_from_supabase: Literal[True]
    player_calls_engine_api: Literal[False]


class RetentionConfig(StrictModel):
    published_editions_days: int | None
    withdrawn_editions_days: int | None
    compact_storylines: Literal[True]
    raw_provider_responses_days: PositiveInt
    detailed_run_logs_days: PositiveInt
    storyline_compaction_days: PositiveInt
    recurring_inactive_issues: PositiveInt
    nonrecurring_keep_issues: PositiveInt


class TelemetryConfig(StrictModel):
    enabled: bool
    monitor_url_env: str
    monitor_token_env: str
    fail_open: Literal[True]
    include_prompt_text: Literal[False]
    include_lore_text: Literal[False]
    include_raw_response: Literal[False]


class RuntimeConfig(StrictModel):
    schema_version: Literal[1]
    application: ApplicationConfig
    api: ApiConfig
    scheduler: SchedulerConfig
    worker: WorkerConfig
    retrieval: RetrievalConfig
    generation: GenerationConfig
    artwork: ArtworkRuntimeConfig
    publication: PublicationConfig
    retention: RetentionConfig
    telemetry: TelemetryConfig


class EditionPolicy(StrictModel):
    breaking_news_count: Literal[3]
    major_article_count: Literal[2]
    minor_article_count: Literal[2]
    brief_article_count: Literal[1]
    editorial_quote_count: Literal[1]
    closing_motto_count: Literal[1]
    regenerate_every_slot: Literal[True]
    max_intentional_fake_per_edition: Annotated[int, Field(ge=0, le=1)]
    require_intentional_fake: Literal[False]


class GenericBudget(StrictModel):
    max_characters: PositiveInt


class ArticleBudget(StrictModel):
    title_max_characters: PositiveInt
    summary_max_words: PositiveInt
    paragraph_count: PositiveInt
    paragraph_min_words: PositiveInt
    paragraph_max_words: PositiveInt
    pull_quote_max_words: PositiveInt | None = None

    @model_validator(mode="after")
    def intervallo_paragrafi_valido(self) -> ArticleBudget:
        if self.paragraph_min_words > self.paragraph_max_words:
            raise ValueError("paragraph_min_words deve essere <= paragraph_max_words")
        return self


class WordBudget(StrictModel):
    max_words: PositiveInt


class SlotBudgets(StrictModel):
    breaking: GenericBudget
    category: GenericBudget
    kicker: GenericBudget
    lead: ArticleBudget
    major: ArticleBudget
    minor: ArticleBudget
    brief: ArticleBudget
    editorial_quote: WordBudget
    closing_motto: WordBudget


class ReportingWeights(StrictModel):
    reported_event: Probability = 0
    credible_absurdity: Probability = 0
    unverified_rumor: Probability = 0
    satirical_report: Probability = 0
    intentional_fake: Probability = 0

    @model_validator(mode="after")
    def somma_uno(self) -> ReportingWeights:
        if abs(sum(self.model_dump().values()) - 1.0) > 1e-9:
            raise ValueError("i pesi di reporting devono sommare a 1")
        return self


class ReportingModeWeights(StrictModel):
    lead: ReportingWeights
    breaking: ReportingWeights
    major: ReportingWeights
    minor: ReportingWeights
    brief: ReportingWeights


class TruthRules(StrictModel):
    player_visible_labels: Literal[False]
    fake_allowed_slots: tuple[Literal["minor", "brief"], ...]
    forbidden_canon_relation: tuple[Literal["forbidden_conflict"], ...]
    deep_falsehood_requires_internal_fake_classification: Literal[True]
    weird_does_not_imply_false: Literal[True]


class InventionRules(StrictModel):
    allowed: tuple[str, ...]
    forbidden_as_real: tuple[str, ...]
    forbidden_items_may_appear_only_as_fake: Literal[True]


class LoopRule(StrictModel):
    canonical_meaning: str
    visual_tone_id: Literal["loop_material"]
    forbidden_meanings: tuple[str, ...]
    replacement_terms: tuple[str, ...]


class StorylinePolicy(StrictModel):
    max_appearances_including_first: Literal[4]
    max_epilogues: Literal[1]
    max_appearances_per_edition: Literal[1]
    allow_skipped_editions: Literal[True]
    allow_closed_storyline_only_for_epilogue: Literal[True]
    recap_max_words: PositiveInt
    prompt_context_max_tokens: PositiveInt
    continuation_probability: Probability
    epilogue_probability: Probability
    max_continuations_per_edition: Annotated[int, Field(ge=0, le=4)]
    new_storyline_probability: Probability
    max_new_storylines_per_edition: Annotated[int, Field(ge=0, le=2)]


class RecurringEntityPolicy(StrictModel):
    keep_recurring_editorial_core: Literal[True]
    avoid_same_byline_every_issue: Literal[True]
    journalist_core_per_edition: Annotated[int, Field(ge=2, le=5)]
    journalist_core_names: Annotated[tuple[str, ...], Field(min_length=6, max_length=12)]
    other_entities_per_edition: Annotated[int, Field(ge=0, le=5)]
    default_cooldown_issues: NonNegativeInt
    repeated_npc_penalty: Probability
    allow_npc_in_unrelated_future_storyline: Literal[True]


class ArtworkPolicy(StrictModel):
    generation_enabled: bool
    use_static_lead_artwork: Literal[True]
    failure_policy: Literal["static_fallback"]
    prompt_version: str


class EditorialPolicy(StrictModel):
    schema_version: Literal[1]
    policy_version: str
    language: Literal["it"]
    edition: EditionPolicy
    slot_budgets: SlotBudgets
    reporting_mode_weights: ReportingModeWeights
    truth_rules: TruthRules
    invention_rules: InventionRules
    loop_rule: LoopRule
    storylines: StorylinePolicy
    recurring_entities: RecurringEntityPolicy
    artwork: ArtworkPolicy


class SecretsConfig(StrictModel):
    environment: str
    log_level: str
    supabase_url: str | None = None
    supabase_anon_key: SecretStr | None = None
    worker_email: str | None = None
    worker_password: SecretStr | None = None
    cloudflare_account_id: str | None = None
    cloudflare_api_token: SecretStr | None = None
    planner_model: str | None = None
    writer_model: str | None = None
    verifier_model: str | None = None
    jina_api_key: SecretStr | None = None
    jina_embedding_model: str | None = None
    jina_query_task: str | None = None
    qdrant_url: str | None = None
    qdrant_api_key: SecretStr | None = None
    qdrant_collection: str | None = None
    embedding_dimension: int | None = None
    corpus_release_manifest_path: str | None = None
    knowledge_root: str | None = None
    monitor_url: str | None = None
    monitor_token: SecretStr | None = None
    api_token: SecretStr | None = None
    artwork_worker_url: str | None = None
    artwork_worker_token: SecretStr | None = None


class AppConfig(StrictModel):
    runtime: RuntimeConfig
    editorial: EditorialPolicy
    secrets: SecretsConfig
    policy_hash: str


REQUIRED_LIVE_ENV = (
    "SUPABASE_URL",
    "SUPABASE_ANON_KEY",
    "GAZZETTA_WORKER_EMAIL",
    "GAZZETTA_WORKER_PASSWORD",
    "CLOUDFLARE_ACCOUNT_ID",
    "CLOUDFLARE_API_TOKEN",
    "JINA_API_KEY",
    "QDRANT_URL",
    "QDRANT_API_KEY",
    "CORPUS_RELEASE_MANIFEST_PATH",
    "NEVERAN_MONITOR_URL",
    "NEVERAN_MONITOR_TOKEN",
    "GAZZETTA_API_TOKEN",
)

REQUIRED_ARTWORK_ENV = (
    "GAZZETTA_IMAGE_WORKER_URL",
    "GAZZETTA_IMAGE_WORKER_TOKEN",
)


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            payload = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"Impossibile leggere {path.name}") from exc
    if not isinstance(payload, dict):
        raise ConfigurationError(f"{path.name} deve contenere un oggetto YAML")
    return payload


def _policy_hash(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _optional(environment: Mapping[str, str], name: str) -> str | None:
    value = environment.get(name, "").strip()
    return value or None


def _optional_int(environment: Mapping[str, str], name: str) -> int | None:
    value = _optional(environment, name)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} deve essere un intero") from exc


def load_config(
    root: Path,
    *,
    environment: Mapping[str, str] | None = None,
    require_live_secrets: bool | None = None,
) -> AppConfig:
    """Carica e valida l'intera configurazione senza esporre i segreti."""

    env = os.environ if environment is None else environment
    runtime_payload = _load_yaml(root / "config" / "default.yaml")
    editorial_payload = _load_yaml(root / "config" / "editorial_policy.yaml")
    try:
        runtime = RuntimeConfig.model_validate(runtime_payload)
        editorial = EditorialPolicy.model_validate(editorial_payload)
    except ValidationError as exc:
        raise ConfigurationError("Configurazione YAML non valida") from exc

    environment_name = env.get("ENVIRONMENT", "development").strip() or "development"
    live_required = (
        environment_name not in {"development", "test"}
        if require_live_secrets is None
        else require_live_secrets
    )
    required = list(REQUIRED_LIVE_ENV)
    if editorial.artwork.generation_enabled:
        required.extend(REQUIRED_ARTWORK_ENV)
    missing = [name for name in required if not _optional(env, name)]
    if live_required and missing:
        raise ConfigurationError(
            "Segreti runtime mancanti: " + ", ".join(sorted(missing))
        )

    secrets = SecretsConfig(
        environment=environment_name,
        log_level=env.get("LOG_LEVEL", "INFO"),
        supabase_url=_optional(env, "SUPABASE_URL"),
        supabase_anon_key=_optional(env, "SUPABASE_ANON_KEY"),
        worker_email=_optional(env, "GAZZETTA_WORKER_EMAIL"),
        worker_password=_optional(env, "GAZZETTA_WORKER_PASSWORD"),
        cloudflare_account_id=_optional(env, "CLOUDFLARE_ACCOUNT_ID"),
        cloudflare_api_token=_optional(env, "CLOUDFLARE_API_TOKEN"),
        planner_model=_optional(env, "GAZZETTA_PLANNER_MODEL"),
        writer_model=_optional(env, "GAZZETTA_WRITER_MODEL"),
        verifier_model=_optional(env, "GAZZETTA_VERIFIER_MODEL"),
        jina_api_key=_optional(env, "JINA_API_KEY"),
        jina_embedding_model=_optional(env, "JINA_EMBED_MODEL"),
        jina_query_task=_optional(env, "JINA_TASK_QUERY"),
        qdrant_url=_optional(env, "QDRANT_URL"),
        qdrant_api_key=_optional(env, "QDRANT_API_KEY"),
        qdrant_collection=_optional(env, "QDRANT_COLLECTION"),
        embedding_dimension=_optional_int(env, "EMBED_DIM"),
        corpus_release_manifest_path=_optional(env, "CORPUS_RELEASE_MANIFEST_PATH"),
        knowledge_root=_optional(env, "NEVERAN_KNOWLEDGE_ROOT"),
        monitor_url=_optional(env, "NEVERAN_MONITOR_URL"),
        monitor_token=_optional(env, "NEVERAN_MONITOR_TOKEN"),
        api_token=_optional(env, "GAZZETTA_API_TOKEN"),
        artwork_worker_url=_optional(env, "GAZZETTA_IMAGE_WORKER_URL"),
        artwork_worker_token=_optional(env, "GAZZETTA_IMAGE_WORKER_TOKEN"),
    )
    return AppConfig(
        runtime=runtime,
        editorial=editorial,
        secrets=secrets,
        policy_hash=_policy_hash(editorial_payload),
    )
